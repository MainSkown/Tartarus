import re
from typing import Annotated

from fastapi import Path

# Both rules are the control service's own (cape/bin/guest-control GUEST_NAME and BUILD_ID): a value
# that fails them is refused here so that nothing a client sends can alter a control-service URL.
GUEST_NAME = re.compile(r"[a-z][a-z0-9-]{1,31}")
BUILD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Pydantic searches a `pattern` instead of matching all of the value, hence the anchors.
GuestNamePath = Annotated[str, Path(pattern=f"^{GUEST_NAME.pattern}$")]
BuildIdPath = Annotated[str, Path(pattern=f"^{BUILD_ID.pattern}$")]
