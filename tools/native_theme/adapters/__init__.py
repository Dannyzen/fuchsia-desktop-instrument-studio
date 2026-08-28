"""Public, parser-bounded NativeTheme adapter API."""

from .base16_base24 import adapt_base16, adapt_base24
from .common import AdapterDiagnostic, AdapterError, AdapterProvenance
from .dtcg_2025_10 import adapt_dtcg_2025_10
from .omarchy_palette import adapt_omarchy_palette

__all__ = (
    "AdapterDiagnostic",
    "AdapterError",
    "AdapterProvenance",
    "adapt_base16",
    "adapt_base24",
    "adapt_dtcg_2025_10",
    "adapt_omarchy_palette",
)
