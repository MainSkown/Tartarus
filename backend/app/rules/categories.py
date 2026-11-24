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
        "lan_authentication",
        "lan_share_access",
        "lan_file_write",
        "lan_service_request",
        "lan_sweep",
        "lan_fan_out",
        "lan_credential_spray",
    }
)
SUPPORTED_PRODUCT = "windows"

# docs/specs/data-model.md, "Sigma field mapping". Only a started remote thread is Sysmon's
# CreateRemoteThread; a memory write, section map or APC is not one and must not feed those rules.
# `lan-aggregate` has no category: it stands for events the daemon stopped logging, so no rule
# can say what it did.
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
    "lan-login-attempt": "lan_authentication",
    "lan-share-access": "lan_share_access",
    "lan-file-write": "lan_file_write",
    "lan-service-request": "lan_service_request",
    "lan-sweep": "lan_sweep",
    "lan-fan-out": "lan_fan_out",
    "lan-credential-spray": "lan_credential_spray",
}


def category_of(action: object) -> str | None:
    """The Sigma logsource category of an `event.action`, or `None` when no rule can apply."""
    if not isinstance(action, str):
        return None
    return ACTION_CATEGORIES.get(action)
