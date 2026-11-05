"""Named transforms available to field mappings. Config selects a name; it cannot add code. No Frappe imports."""

import re
from collections.abc import Callable

from zero_touch.extraction.parse import parse_date, parse_money


def _none(value: str) -> str:
	return value


def _strip(value: str) -> str:
	return value.strip()


def _upper(value: str) -> str:
	return value.strip().upper()


def _date_iso(value: str) -> str:
	iso, _ambiguous = parse_date(value)
	if iso is None:
		raise ValueError(f"not a date: {value}")
	return iso


def _money(value: str) -> str:
	amount = parse_money(value)
	if amount is None:
		raise ValueError(f"not an amount: {value}")
	return amount


def _digits_only(value: str) -> str:
	return re.sub(r"\D", "", value)


TRANSFORMS: dict[str, Callable[[str], str]] = {
	"none": _none,
	"strip": _strip,
	"upper": _upper,
	"date_iso": _date_iso,
	"money": _money,
	"digits_only": _digits_only,
}

TRANSFORM_NAMES = tuple(TRANSFORMS)


def apply_transform(name: str, value: str) -> str:
	try:
		transform = TRANSFORMS[name]
	except KeyError as exc:
		raise ValueError(f"unknown transform: {name}") from exc
	return transform(value)
