from opensearchpy import AsyncOpenSearch


def create_opensearch_client(url: str) -> AsyncOpenSearch:
    return AsyncOpenSearch(hosts=[url])
