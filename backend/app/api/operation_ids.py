from fastapi.routing import APIRoute


def generate_operation_id(route: APIRoute) -> str:
    """`<tag>_<route name>`, e.g. `system_health`; the generated client is named after it."""
    if not route.tags:
        raise ValueError(f"Route {route.name!r} ({route.path}) needs a tag to get an operation id")
    return f"{route.tags[0]}_{route.name}"
