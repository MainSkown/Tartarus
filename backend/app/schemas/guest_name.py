from typing import Annotated

from pydantic import StringConstraints

# The control service holds the full rules (decision 3); this is the shape every name shares, so
# an analysis option or a setting can be checked without asking it.
type GuestName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,31}$")]
