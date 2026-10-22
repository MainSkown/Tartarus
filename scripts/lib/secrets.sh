# The secrets of .env, shared by scripts/gen-env.sh (which fills them) and scripts/preflight.sh (which
# judges them). Sourced, not executed.

SECRET_NAMES=(POSTGRES_PASSWORD CAPE_DB_PASSWORD CAPE_API_TOKEN GUEST_CONTROL_TOKEN)
TOKEN_NAMES=(CAPE_API_TOKEN GUEST_CONTROL_TOKEN)
# These two end up inside a database URL, so they are restricted to characters that need no escaping.
URL_SAFE_PASSWORD_PATTERN='^[A-Za-z0-9._-]+$'
KNOWN_PLACEHOLDERS=(change-me change-me-too)
MIN_TOKEN_LENGTH=32

in_list() {
    local wanted=$1 item
    shift
    for item in "$@"; do [ "$item" = "$wanted" ] && return 0; done
    return 1
}

is_token() { in_list "$1" "${TOKEN_NAMES[@]}"; }
