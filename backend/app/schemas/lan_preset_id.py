from typing import Annotated

from pydantic import StringConstraints

# The control service's own slug rule (`SLUG` in cape/guest_engine/profile.py); whether a slug names
# a real preset is asked of the control service when an analysis is submitted.
type LanPresetId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,31}$")]
