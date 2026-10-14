SUPPORTED_CATEGORIES = frozenset(
    {
        "process_creation",
        "file_event",
        "registry_set",
        "registry_add",
        "registry_delete",
        "network_connection",
        "dns_query",
        "create_remote_thread",
    }
)
SUPPORTED_PRODUCT = "windows"

# docs/specs/data-model.md, "Sigma field mapping". Only a started remote thread is Sysmon's
# CreateRemoteThread; a memory write, section map or APC is not one and must not feed those rules.
ACTION_CATEGORIES = {
    "process-created": "process_creation",
    "file-created": "file_event",
    "reg-value-set": "registry_set",
    "reg-key-created": "registry_add",
    "reg-value-deleted": "registry_delete",
    "reg-key-deleted": "registry_delete",
    "network-connection": "network_connection",
    "dns-query": "dns_query",
    "create-remote-thread": "create_remote_thread",
    "inject-thread": "create_remote_thread",
}


def category_of(action: object) -> str | None:
    """The Sigma logsource category of an `event.action`, or `None` when no rule can apply."""
    if not isinstance(action, str):
        return None
    return ACTION_CATEGORIES.get(action)
