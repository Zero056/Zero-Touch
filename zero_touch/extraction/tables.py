"""Line-item reader: finds a table by its header words and assigns words to columns by position.

Pure logic, no Frappe imports. Coordinates can be PDF points or image pixels, as long as one page uses one unit.
"""

import re
import unicodedata
from dataclasses import dataclass
from statistics import median

NUMBER_RE = re.compile(r"^[\(\-]?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d+)?\)?$|^[\(\-]?\d+(?:[.,]\d+)?\)?$")
NOISE_TOKENS = frozenset({"#", "$", "₴", "£", "%", "-", "|", "/", "\\", "ر.س", "SAR"})
STOP_WORDS = ("المجموع", "الاجمالي", "الإجمالي", "اجمالي", "total", "subtotal", "vat", "الخصم", "discount")


@dataclass(frozen=True)
class Word:
	x0: float
	y0: float
	x1: float
	y1: float
	text: str

	@property
	def xc(self) -> float:
		return (self.x0 + self.x1) / 2

	@property
	def yc(self) -> float:
		return (self.y0 + self.y1) / 2

	@property
	def height(self) -> float:
		return self.y1 - self.y0


def norm(text: str) -> str:
	value = unicodedata.normalize("NFKC", text or "")
	value = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\u0640]", "", value)
	return value.strip(" :.,;()[]").casefold()


def _label_tokens(label: str) -> list[str]:
	tokens = [norm(t) for t in re.split(r"\s+", label.strip()) if norm(t)]
	# A printed label often carries a rate ("الضريبة 15%") that OCR mangles. The words
	# are the stable part; the number is not.
	words = [t for t in tokens if not re.fullmatch(r"[\d%.,/]+", t)]
	return words or tokens


def find_header(words: list[Word], labels_by_field: dict[str, list[str]]) -> tuple[float, float, dict[str, float]] | None:
	"""Returns (header top, header bottom, {field: header x centre}) for the row that matches the most columns."""
	if not words:
		return None
	by_line: list[list[Word]] = []
	for word in sorted(words, key=lambda w: w.yc):
		if by_line and abs(word.yc - by_line[-1][0].yc) <= max(word.height, 1) * 0.6:
			by_line[-1].append(word)
		else:
			by_line.append([word])

	best = None
	for line in by_line:
		line_words = sorted(line, key=lambda w: w.x0)
		anchors: dict[str, float] = {}
		for field, labels in labels_by_field.items():
			for label in labels:
				tokens = _label_tokens(label)
				if not tokens:
					continue
				match = _match_tokens(line_words, tokens)
				if match:
					anchors[field] = match
					break
		if anchors and (best is None or len(anchors) > len(best[2])):
			top = min(w.y0 for w in line)
			bottom = max(w.y1 for w in line)
			best = (top, bottom, anchors)
	return best


def _match_tokens(line_words: list[Word], tokens: list[str]) -> float | None:
	texts = [norm(w.text) for w in line_words]
	# Arabic headers are stored right-to-left, so the token order on the page is the
	# reverse of the order in the label. A header such as "المستحق عند التعاقد" can also
	# break after "عند", so a long label is also tried without its first/last word.
	candidates = [tokens]
	if len(tokens) > 2:
		candidates += [tokens[:-1], tokens[1:]]
	for wanted in candidates:
		for sequence in (wanted, list(reversed(wanted))):
			for start in range(len(texts)):
				end = start + len(sequence)
				if end > len(texts):
					break
				if texts[start:end] == sequence:
					span = line_words[start:end]
					return (min(w.x0 for w in span) + max(w.x1 for w in span)) / 2
	return None


def stop_top(words: list[Word], below_y: float) -> float | None:
	candidates = [
		w.y0
		for w in words
		if w.y0 > below_y and any(stop in norm(w.text) for stop in STOP_WORDS)
	]
	return min(candidates) if candidates else None


def column_bounds(anchors: dict[str, float], page_width: float) -> dict[str, tuple[float, float]]:
	ordered = sorted(anchors.items(), key=lambda item: item[1])
	bounds = {}
	for index, (field, centre) in enumerate(ordered):
		lo = 0.0 if index == 0 else (ordered[index - 1][1] + centre) / 2
		hi = page_width if index == len(ordered) - 1 else (centre + ordered[index + 1][1]) / 2
		bounds[field] = (lo, hi)
	return bounds


def is_number(text: str) -> bool:
	cleaned = text.replace("٫", ".").replace("٬", ",")
	return bool(NUMBER_RE.match(cleaned.strip())) and cleaned.strip() not in NOISE_TOKENS


def build_rows(
	words: list[Word],
	bounds: dict[str, tuple[float, float]],
	numeric_fields: set[str],
	region_top: float,
	region_bottom: float,
) -> list[dict]:
	"""Groups the table's words into rows. Each field's text is the words inside its column, in reading order."""
	inside = [w for w in words if region_top < w.yc < region_bottom and w.text.strip() not in NOISE_TOKENS]
	if not inside:
		return []
	height = median(w.height for w in inside) or 1.0

	def field_at(word: Word) -> str | None:
		for field, (lo, hi) in bounds.items():
			if lo <= word.xc < hi:
				return None if field.startswith("_") else field
		return None

	numeric = [w for w in inside if field_at(w) in numeric_fields and is_number(w.text)]
	if not numeric:
		return []

	centres: list[list[Word]] = []
	for word in sorted(numeric, key=lambda w: w.yc):
		if centres and abs(word.yc - sum(x.yc for x in centres[-1]) / len(centres[-1])) <= height * 0.8:
			centres[-1].append(word)
		else:
			centres.append([word])
	row_y = [sum(w.yc for w in group) / len(group) for group in centres]

	mapped = [field for field in bounds if not field.startswith("_")]
	rows = [{field: [] for field in mapped} for _ in row_y]
	for word in inside:
		field = field_at(word)
		if field is None:
			continue
		distances = [abs(word.yc - y) for y in row_y]
		index = min(range(len(row_y)), key=lambda i: distances[i])
		if distances[index] <= height * 2.2:
			rows[index][field].append(word)

	result = []
	for cells in rows:
		values = {}
		for field, cell_words in cells.items():
			ordered = sorted(cell_words, key=lambda w: (round(w.yc / max(height, 1)), w.x0))
			values[field] = " ".join(w.text.strip() for w in ordered if w.text.strip() not in NOISE_TOKENS).strip()
		if any(values.values()):
			result.append(values)
	return result
