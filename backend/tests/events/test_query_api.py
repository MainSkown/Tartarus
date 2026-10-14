import httpx


async def validate(client: httpx.AsyncClient, query: str) -> dict[str, object]:
    response = await client.post("/api/query/validate", json={"query": query})
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


async def test_a_valid_query_is_ok(client: httpx.AsyncClient) -> None:
    assert await validate(client, "process.name:cmd.exe AND lane:file") == {
        "ok": True,
        "errors": [],
    }


async def test_an_empty_query_is_ok(client: httpx.AsyncClient) -> None:
    assert await validate(client, "") == {"ok": True, "errors": []}
    assert await validate(client, "   ") == {"ok": True, "errors": []}


async def test_an_unknown_field_is_an_error_with_a_span_and_a_suggestion(
    client: httpx.AsyncClient,
) -> None:
    assert await validate(client, "procss.name:x") == {
        "ok": False,
        "errors": [
            {
                "start": 0,
                "end": 11,
                "message": "unknown field 'procss.name'; did you mean 'process.name'?",
                "suggestion": "process.name",
            }
        ],
    }


async def test_a_syntax_error_is_an_error_with_a_span_and_no_suggestion(
    client: httpx.AsyncClient,
) -> None:
    result = await validate(client, "lane:(")

    assert result["ok"] is False
    (error,) = result["errors"]  # type: ignore[misc]
    assert error["suggestion"] is None
    assert 0 <= error["start"] <= error["end"] <= len("lane:(")


async def test_validating_never_needs_an_analysis(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/query/validate", json={})

    assert response.status_code == 422


async def test_the_field_catalog_lists_every_field_with_what_the_bar_shows(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/query/fields")

    assert response.status_code == 200
    fields = {field["name"]: field for field in response.json()}
    process_name = fields["process.name"]
    assert process_name["type"] == "keyword"
    assert process_name["aliases"] == ["process", "proc"]
    assert process_name["example"] == "cmd.exe"
    assert process_name["description"]
    assert process_name["searchable"] is True
    assert process_name["members"] == []
    assert fields["api.name"]["lane"] == "api"
    assert fields["tartarus.raw"]["searchable"] is False
    assert fields["domain"]["members"] == ["dns.question.name", "destination.domain"]


async def test_a_prefix_narrows_the_catalog_to_searchable_matches_best_first(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/query/fields", params={"prefix": "proc"})

    names = [field["name"] for field in response.json()]
    assert names
    assert names[0].startswith("process.")
    assert "tartarus.raw" not in names
    assert all(field["searchable"] for field in response.json())


async def test_an_alias_prefix_finds_its_field(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/query/fields", params={"prefix": "cmdl"})

    assert [field["name"] for field in response.json()] == ["process.command_line"]


async def test_a_prefix_that_matches_nothing_gives_an_empty_list(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/query/fields", params={"prefix": "zzzzzz"})

    assert response.json() == []
