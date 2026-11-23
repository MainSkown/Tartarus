import sys
from pathlib import Path

# lan_session.py is the one file shared with the control service; the image copies it next to the
# package, and the tests put its source directory on the path instead.
SHARED = Path(__file__).resolve().parents[2] / "cape" / "guest_engine"
sys.path.insert(0, str(SHARED))
