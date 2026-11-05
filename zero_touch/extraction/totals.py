"""Reads totals (grand total, tax, subtotal) from the amount printed on the same line as its label."""

import re

from zero_touch.extraction.parse import parse_money
from zero_touch.extraction.tables import Word, norm

AMOUNT_RE = re.compile(r"^[+\-]?\d{1,3}(?:[,\s]\d{3})*[.,]\d{1,4}$|^[+\-]?\d+[.,]\d{1,4}$")


def amount_words(words: list[Word]) -> list[Word]:
	found = []
	for word in words:
		text = word.text.replace("\u200f", "").replace("\u200e", "").strip().lstrip("+-")
		if AMOUNT_RE.match(text.replace("+", "").strip()):
			found.append(word)
	return found


def label_anchors(words: list[Word], label: str) -> list[Word]:
	tokens = [norm(t) for t in label.split() if norm(t)]
	if not tokens:
		return []
	first = tokens[0]
	return [w for w in words if norm(w.text) == first]


def positional_amount(
	words: list[Word],
	labels: list[str],
	band_words,
	page_height: float,
) -> tuple[str, str] | None:
	"""Returns (amount, the band text used) for the lowest label that has an amount on its line."""
	anchors = []
	for label in labels:
		tokens = [norm(t) for t in label.split() if norm(t)]
		anchors.extend((anchor, label, len(tokens)) for anchor in label_anchors(words, label))
	# Bottom of the page first. On the same row, try the most specific label first, so
	# "Total including VAT" wins over a generic "Total" that also starts the same row.
	for anchor, label, token_count in sorted(anchors, key=lambda item: (-item[0].yc, -item[2])):
		height = max(anchor.height, 1)
		band = band_words(anchor.yc - height * 1.1, anchor.yc + height * 1.1)
		needed = [norm(t) for t in label.split() if norm(t)]
		present = {norm(w.text) for w in band}
		band_text = norm(" ".join(w.text for w in band))
		if len(needed) > 1 and not (
			norm(label) in band_text or all(token in present for token in needed)
		):
			continue
		candidates = [w for w in amount_words(band) if abs(w.yc - anchor.yc) <= height * 1.1]
		candidates = [w for w in candidates if w.x0 > anchor.x1 or w.x1 < anchor.x0]
		if not candidates:
			continue
		nearest = min(candidates, key=lambda w: abs(w.xc - anchor.xc))
		amount = parse_money(nearest.text.replace("\u200f", "").replace("+", "").strip())
		if amount is None:
			continue
		text = " ".join(w.text for w in sorted(band, key=lambda w: w.x0) if w.text.strip())
		return amount, text[:200]
	return None
