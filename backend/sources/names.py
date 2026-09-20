"""Name normalisation shared by the data sources so players can be joined."""

from __future__ import annotations

import unicodedata


def normalize_name(name: str) -> str:
    """Accent-/case-insensitive key so 'Jérémy Doku' joins 'Jeremy Doku'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(ascii_name.lower().split())
