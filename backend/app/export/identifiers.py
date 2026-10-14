import uuid

# A fixed namespace makes every id a pure function of what it names, so exporting the same
# analysis twice gives the same ids and a consumer can tell it is the same record.
NAMESPACE = uuid.UUID("6f1d3b52-8a4e-5c07-9b2d-4e7a1c9f0d38")


def stable_uuid(*parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, "\x1f".join(str(part) for part in parts)))
