"""Name normalisation shared by the data sources so players can be joined."""

from __future__ import annotations

import unicodedata

# Letters that decomposition cannot take apart. Without these, "Đorđe Petrović"
# became "ore petrovic" and never met Transfermarkt's "Djordje Petrovic", and
# "Ødegaard" lost its first letter.
_TRANSLITERATE = str.maketrans(
    {
        "Đ": "Dj", "đ": "dj", "Ø": "O", "ø": "o", "Ł": "L", "ł": "l", "ß": "ss",
        "Æ": "Ae", "æ": "ae", "Œ": "Oe", "œ": "oe", "Þ": "Th", "þ": "th",
        "Ð": "D", "ð": "d", "ı": "i",
    }
)


def normalize_name(name: str) -> str:
    """Accent-/case-insensitive key so 'Jérémy Doku' joins 'Jeremy Doku'."""
    decomposed = unicodedata.normalize("NFKD", name.translate(_TRANSLITERATE))
    ascii_name = decomposed.encode("ascii", "ignore").decode()
    return " ".join(ascii_name.lower().split())
