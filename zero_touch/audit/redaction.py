"""Masks sensitive values before anything is written to logs. No Frappe imports."""

import re

MAX_MESSAGE_LENGTH = 500

_PATTERNS = (
	("SECRET", re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)\b\s*[:=]\s*\S+")),
	("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}\s?[A-Z0-9]{1,4}\b")),
	("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
	("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
	("PHONE", re.compile(r"(?<![\w])\+?\d[\d\s()-]{7,}\d(?![\w])")),
)


def redact(text: str | None, max_length: int = MAX_MESSAGE_LENGTH) -> str:
	if not text:
		return ""
	value = str(text)
	for label, pattern in _PATTERNS:
		value = pattern.sub(f"[{label}]", value)
	if len(value) > max_length:
		value = value[: max_length - 3] + "..."
	return value
