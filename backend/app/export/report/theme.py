"""Colours both report outputs and the process-tree drawing share."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.db.models.analysis import Severity

# The design system's severity tokens (docs/design/design-system.md); the print variant keeps
# them so a severity reads the same on screen and on paper.
SEVERITY_COLOURS: Mapping[Severity, str] = MappingProxyType(
    {
        Severity.CRITICAL: "#ef4444",
        Severity.HIGH: "#f97316",
        Severity.MEDIUM: "#eab308",
        Severity.LOW: "#94a3b8",
        Severity.INFO: "#a3a3a3",
    }
)

# Fontconfig answers "sans-serif" and "system-ui" with a monospace face when only Liberation is
# installed, so the faces are named; DejaVu supplies glyphs Liberation lacks.
SANS_FONTS = "'Liberation Sans', Arial, Helvetica, 'DejaVu Sans', sans-serif"
MONO_FONTS = "'Liberation Mono', 'Courier New', Courier, 'DejaVu Sans Mono', monospace"


@dataclass(frozen=True)
class FontStacks:
    sans: str
    mono: str


# The HTML report keeps the design system's stacks (it opens on the analyst's own machine); the
# PDF is rendered in the image, where only Liberation and DejaVu exist.
SCREEN_FONTS = FontStacks(
    sans="system-ui, -apple-system, 'Segoe UI', 'Liberation Sans', Arial, sans-serif",
    mono="'Courier New', Courier, 'Liberation Mono', monospace",
)
PRINT_FONTS = FontStacks(sans=SANS_FONTS, mono=MONO_FONTS)
