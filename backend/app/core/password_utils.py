import re
from typing import Optional

_ZERO_WIDTH_TRANSLATION = {
    ord("\u200b"): None,  # zero width space
    ord("\u200c"): None,  # zero width non-joiner
    ord("\u200d"): None,  # zero width joiner
    ord("\ufeff"): None,  # bom / zero width no-break space
    ord("\u2060"): None,  # word joiner
}

_RJCODE_PATTERN = re.compile(r"([RVB]J)\s*[-_.]?\s*(\d{6}|\d{8})(?!\d)", re.IGNORECASE)


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_password_value(value: Optional[str]) -> str:
    normalized = str(value or "")
    normalized = normalized.translate(_ZERO_WIDTH_TRANSLATION)
    normalized = normalized.strip()
    return normalized


def normalize_rjcode_value(value: Optional[str]) -> Optional[str]:
    normalized = normalize_optional_text(value)
    if not normalized:
        return None
    match = _RJCODE_PATTERN.search(normalized)
    if match:
        return f"RJ{match.group(2)}"
    return normalized.upper()


def normalize_filename_value(value: Optional[str]) -> Optional[str]:
    return normalize_optional_text(value)
