"""Text normalization, value parsing, and sales invoice field extraction. No Frappe imports.

Arabic text in PDFs is often stored in visual order, so a label may appear reversed. Labels are
searched in both orientations, and the value is read from the side that matches.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-z]")
BIDI_CONTROLS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u0640"), None)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

DATE_RE = re.compile(
	r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}\b|\b\d{1,2}[ \-/]?[A-Za-z]{3,9}[ \-/,]+\d{4}\b"
)
MONEY_RE = re.compile(r"(?<![\w/.\-])\d{1,3}(?:[,\s]\d{3})+(?:[.,]\d{1,4})?(?![\w/])|(?<![\w/.\-])\d+(?:[.,]\d{1,4})?(?![\w/])")
ID_RE = re.compile(r"(?<![\w])[A-Za-z0-9][A-Za-z0-9\-/_.]{1,39}(?![\w])")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TAX_ID_RE = re.compile(r"(?<!\d)\d{9,15}(?!\d)")
CURRENCY_CODE_RE = re.compile(r"\b(SAR|USD|EUR|AED|GBP|EGP|KWD|QAR|BHD|OMR)\b")
CURRENCY_AR = {"ر.س": "SAR", "ريال": "SAR", "ر س": "SAR"}


def normalize_text(value: str | None) -> str:
	if not value:
		return ""
	text = unicodedata.normalize("NFKC", value).translate(BIDI_CONTROLS).translate(ARABIC_DIGITS)
	text = text.replace("٫", ".").replace("٬", ",").replace("،", ",")
	return re.sub(r"[ \t\u00a0]+", " ", text).strip()


def has_arabic(text: str) -> bool:
	return bool(ARABIC_RE.search(text or ""))


def detect_language(text: str) -> str:
	arabic = len(ARABIC_RE.findall(text or ""))
	latin = len(LATIN_RE.findall(text or ""))
	if arabic and latin:
		return "mixed"
	if arabic:
		return "ar"
	if latin:
		return "en"
	return "unknown"


def parse_money(raw: str) -> str | None:
	value = raw.replace(" ", "").strip()
	if not value:
		return None
	if "," in value and "." in value:
		if value.rfind(",") > value.rfind("."):
			value = value.replace(".", "").replace(",", ".")
		else:
			value = value.replace(",", "")
	elif "," in value:
		head, _, tail = value.rpartition(",")
		value = value.replace(",", ".") if len(tail) <= 2 else value.replace(",", "")
	try:
		number = Decimal(value)
	except InvalidOperation:
		return None
	return f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


MONTH_NAMES = {
	name: index
	for index, name in enumerate(
		["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
	)
}


def parse_date(raw: str) -> tuple[str | None, bool]:
	"""Returns (ISO date, ambiguous). Day-first is assumed for dd/mm/yyyy; ambiguous when both parts <= 12."""
	value = raw.strip()
	named = re.fullmatch(r"(\d{1,2})[ \-/]?([A-Za-z]{3,9})[ \-/,]+(\d{4})", value)
	if named:
		month = MONTH_NAMES.get(named.group(2)[:3].lower())
		if not month:
			return None, False
		try:
			return date(int(named.group(3)), month, int(named.group(1))).isoformat(), False
		except ValueError:
			return None, False
	try:
		if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
			return date.fromisoformat(value).isoformat(), False
		parts = re.split(r"[/.\-]", value)
		day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
		parsed = date(year, month, day)
	except (ValueError, IndexError):
		return None, False
	ambiguous = day <= 12 and month <= 12 and day != month
	return parsed.isoformat(), ambiguous


@dataclass(frozen=True)
class FieldSpec:
	key: str
	label: str
	kind: str  # text | id | tax_id | date | money | name
	labels_en: tuple[str, ...]
	labels_ar: tuple[str, ...] = ()
	exclude: tuple[str, ...] = ()
	required: bool = False


SALES_INVOICE_FIELDS = (
	FieldSpec("invoice_number", "Invoice Number", "id",
		("Invoice No", "Invoice Number", "Invoice #", "Invoice No.", "Inv No", "Tax Invoice No"),
		("رقم الفاتورة", "فاتورة رقم", "رقم فاتورة", "رقم الفاتورة الضريبية"), required=True),
	FieldSpec("invoice_date", "Invoice Date", "date",
		("Invoice Date", "Issue Date", "Date"),
		("تاريخ الفاتورة", "تاريخ الإصدار", "التاريخ"), exclude=(r"\bdue\b", r"استحقاق"), required=True),
	FieldSpec("due_date", "Due Date", "date",
		("Due Date", "Payment Due"), ("تاريخ الاستحقاق", "تاريخ الاستحقاق")),
	FieldSpec("customer_name", "Customer Name", "name",
		("Bill To", "Customer Name", "Customer", "Client", "Sold To", "Name"),
		("اسم العميل", "العميل", "فاتورة إلى", "المشتري"),
		exclude=(r"\bvat\b", r"\btax\b", r"\btrn\b", r"الضريبي", r"company", r"officer", r"driver",
			r"collector", r"sales", r"financial", r"phone", r"email", r"الشركة"), required=True),
	FieldSpec("customer_tax_id", "Customer Tax ID", "tax_id",
		("Customer VAT", "VAT No", "VAT Number", "Tax ID", "TRN", "Tax Registration"),
		("الرقم الضريبي للعميل", "الرقم الضريبي", "رقم ضريبي")),
	FieldSpec("subtotal", "Subtotal", "money",
		("Sub Total", "Subtotal", "Net Amount", "Total Before VAT", "Total excl. VAT"),
		("المجموع الفرعي", "الإجمالي قبل الضريبة", "الإجمالي الفرعي")),
	FieldSpec("tax_amount", "VAT Amount", "money",
		("VAT Amount", "Tax Amount", "Total VAT", "VAT"),
		("ضريبة القيمة المضافة", "مبلغ الضريبة", "الضريبة"),
		exclude=(r"\bno\b", r"\bnumber\b", r"\bid\b", r"\btrn\b", r"registration", r"الرقم")),
	FieldSpec("grand_total", "Grand Total", "money",
		("Grand Total", "Total Amount Due", "Amount Due", "Total Due", "Total"),
		("المبلغ الإجمالي", "الإجمالي شامل الضريبة", "الإجمالي", "المجموع الكلي", "المجموع"),
		exclude=(r"\bvat\b", r"\btax\b", r"before", r"الفرعي", r"قبل الضريبة"), required=True),
)

REQUIRED_KEYS = tuple(spec.key for spec in SALES_INVOICE_FIELDS if spec.required)

# Common wording used by invoices that do not follow the mapped supplier's template. These
# are only tried for a field the mapping could not read, so a mapping always wins. Note the
# absence of a bare "Total": on most invoices that is the net total, not the grand total.
FALLBACK_FIELDS = {
	"posting_date": FieldSpec("posting_date", "Invoice Date", "date",
		("Invoice Date", "Date of Issue", "Issue Date", "Date"),
		("تاريخ الفاتورة", "تاريخ الإصدار", "التاريخ"), required=True),
	"due_date": FieldSpec("due_date", "Due Date", "date",
		("Due Date", "Payment Due"), ("تاريخ الاستحقاق",)),
	"customer": FieldSpec("customer", "Customer Name", "name",
		("Customer Name", "Bill To", "Sold To", "Client", "Customer"),
		("اسم العميل", "العميل", "فاتورة إلى", "المشتري", "الاسم"),
		exclude=(r"\bvat\b", r"\btax\b", r"\btrn\b", r"الضريبي", r"company", r"officer", r"driver",
			r"collector", r"sales", r"financial", r"phone", r"email", r"الشركة"), required=True),
	"tax_id": FieldSpec("tax_id", "Tax ID", "tax_id",
		("Customer VAT", "VAT No", "VAT Number", "Tax No", "Tax ID", "TRN", "Tax Registration"),
		("الرقم الضريبي للعميل", "الرقم الضريبي", "رقم ضريبي")),
	"currency": FieldSpec("currency", "Currency", "text", ("Currency",), ("العملة",)),
	"subtotal": FieldSpec("subtotal", "Subtotal", "money",
		("Total Before Vat", "Total Before VAT", "Total excluding tax", "Subtotal", "Net Total", "Net Amount"),
		("الإجمالي قبل الضريبة", "الاجمالي قبل الضريبة", "المجموع الفرعي")),
	"net_total": FieldSpec("net_total", "Net Total", "money",
		("Net Total", "Subtotal", "Total Before Vat", "Total excluding tax"),
		("الإجمالي قبل الضريبة", "المجموع الفرعي")),
	"tax_amount": FieldSpec("tax_amount", "VAT Amount", "money",
		("Total VAT", "VAT Amount", "Tax Amount", "VAT"),
		("اجمالي ضريبة القيمة المضافة", "ضريبة القيمة المضافة", "مبلغ الضريبة"),
		exclude=(r"\bbefore\b", r"\bafter\b", r"قبل", r"بعد", r"\bno\b", r"\bnumber\b", r"\bid\b", r"\btrn\b",
			r"registration", r"الرقم")),
	"grand_total": FieldSpec("grand_total", "Grand Total", "money",
		("Total after vat", "Total after VAT", "Total including VAT", "Grand Total", "Total Amount Due",
			"Amount Due", "Total Due"),
		("الإجمالي شامل الضريبة", "الإجمالي بعد الضريبة", "المبلغ الإجمالي", "المجموع الكلي"), required=True),
}

# Mapped field names that mean the same thing as a fallback field.
FALLBACK_ALIASES = {
	"grand_total": "grand_total",
	"base_grand_total": "grand_total",
	"total_taxes_and_charges": "tax_amount",
	"tax_amount": "tax_amount",
	"subtotal": "subtotal",
	"base_net_total": "subtotal",
	"net_total": "net_total",
	"posting_date": "posting_date",
	"due_date": "due_date",
	"customer": "customer",
	"customer_name": "customer",
	"party_name": "customer",
	"transaction_date": "posting_date",
	"tax_id": "tax_id",
	"customer_tax_id": "tax_id",
	"currency": "currency",
}


@dataclass(frozen=True)
class Line:
	page_no: int
	text: str


@dataclass
class FieldResult:
	key: str
	label: str
	value: str | None
	state: str
	confidence: float | None
	page_no: int | None
	source_text: str | None


def _locate(line: str, label: str):
	lowered = line.lower()
	needle = label.lower()
	if has_arabic(label):
		idx = line.find(label)
		if idx >= 0:
			return ("normal", idx, idx + len(label))
		idx = line.find(label[::-1])
		if idx >= 0:
			return ("reversed", idx, idx + len(label))
		return None
	match = re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", lowered)
	if match:
		return ("normal", match.start(), match.end())
	return None


def _candidates(kind: str, text: str) -> list[str]:
	if kind == "date":
		return DATE_RE.findall(text)
	if kind == "money":
		return MONEY_RE.findall(text)
	if kind == "email":
		return EMAIL_RE.findall(text)
	if kind == "tax_id":
		return TAX_ID_RE.findall(text)
	if kind == "id":
		return [c for c in ID_RE.findall(text) if re.search(r"\d", c)]
	return []


NAME_SEPARATORS = re.compile(r"[:©|•/\\{}\[\]<>]")
# A printed label that follows a value on the same OCR line: "Mo001 Maintain Stock: v".
# At least two capitalised English words, or two Arabic words, followed by a colon. The
# lookahead lets overlapping phrases be found so "Unit Allow Sales:" also yields "Allow Sales:".
NEXT_LABEL = re.compile(
	r"(?=((?:[A-Z][A-Za-z'&.\-]*(?:\s+[A-Z][A-Za-z'&.\-]*)+"
	r"|[\u0600-\u06FF]+(?:\s+[\u0600-\u06FF]+)+)\s*:))"
)
BIDI = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\u0640]")
NAME_STOP_WORDS = frozenset({"of", "for", "the", "and", "is", "to", "from", "by", "at", "in", "on", "with"})
NAME_FORBIDDEN = re.compile(
	r"(?i)\b(invoice|date|total|company|tax|vat|currency|due|sales|phone|email|address|name|cr)\b|الفاتورة|الشركة|رقم|التاريخ|الإجمالي|الاجمالي|الضريبي|السجل"
)

# Labels printed next to a name, often merged into the same OCR line. They are removed
# before the name is chosen, so "اسم المسؤول المالي شركة وسام الاتحاد التجارية" keeps the
# customer name and drops the role label in front of it.
NAME_LABEL_NOISE = re.compile(
	r"(?i)\b(?:name of financial officer|financial officer|customer name|customer|client|bill to|sold to|note|name)\b"
	r"|اسم المسؤول المالي|المسؤول المالي|اسم العميل|اسم المستلم|العميل|المشتري|فاتورة إلى|الاسم|اسم"
)


def clean_name(text: str) -> str | None:
	text = NAME_LABEL_NOISE.sub(" ", text)
	segments = [seg.strip(" -–—,") for seg in NAME_SEPARATORS.split(text)]
	letters = lambda seg: len(re.findall(r"[^\W\d_]", seg))
	candidates = sorted((seg for seg in segments if letters(seg) >= 3), key=letters, reverse=True)
	for best in candidates:
		# Keep only words that carry letters, so a trailing account number or a lone dash
		# ("مؤسسة دار الرابح للنقليات - 1003") is not left on the end of the name.
		words = [w for w in best.split() if re.search(r"[^\W\d_]", w)]
		if not words or words[0].lower() in NAME_STOP_WORDS:
			continue
		if "_" in best or re.search(r"[()\[\]]", best) or len(words) > 6:
			continue
		if NAME_FORBIDDEN.search(best):
			continue
		return " ".join(words)[:120]
	return None


def _label_starts(text: str) -> list[int]:
	return [match.start(1) for match in NEXT_LABEL.finditer(text)]


def _cut_before_label(text: str) -> str:
	"""Drops a following field that OCR put on the same line ("Mo001 Maintain Stock: v")."""
	starts = _label_starts(text)
	return text[: starts[-1]] if starts else text


def _after_last_label(text: str) -> str:
	"""The value after the previous field's label ("و Allow Purchase: منتجات")."""
	matches = list(NEXT_LABEL.finditer(text))
	return text[matches[-1].end(1) :] if matches else text


def _value_from(kind: str, text: str, reversed_order: bool) -> str | None:
	if kind == "text":
		text = _after_last_label(text) if reversed_order else _cut_before_label(text)
		segments = [seg.strip(" -–—,\t") for seg in NAME_SEPARATORS.split(text)]
		segments = [seg for seg in segments if seg and re.search(r"[^\W_]", seg)]
		if not segments:
			return None
		# Before a label, the value closest to that label is the last segment. The first
		# segment belonged to a previous label: on an Item print, "Is Bundle: v شرايح …
		# Item Name:" used to return "Is Bundle" as the item name.
		choice = segments[-1] if reversed_order else segments[0]
		choice = BIDI.sub("", choice).strip()
		# The previous field's checkbox value sits in the same segment ("v شرايح …").
		# Drop a standalone yes/no marker only when real text follows it.
		choice = re.sub(r"^\s*(?:[vx✓✔]|yes|no|y|n)\s+(?=\S)", "", choice, flags=re.IGNORECASE)
		return choice[:200] if choice else None
	if kind == "name":
		if not reversed_order:
			text = _cut_before_label(text)
		candidate = BIDI.sub("", clean_name(text) or "").strip()
		# A boolean value and the next label can precede the real value:
		# "و Allow Purchase: منتجات Item Group:". Take the part after that label.
		if candidate and re.match(r"^(?:و|[vx✓✔])\s+[A-Za-z]", candidate):
			alternate = BIDI.sub("", clean_name(_after_last_label(text)) or "").strip()
			if alternate:
				candidate = alternate
		return candidate
	found = _candidates(kind, text)
	if not found:
		return None
	if kind == "money":
		# Invoices often print the unrounded VAT and total (for example 72.3915), so accept
		# two or more decimals. parse_money rounds the value to the currency precision.
		with_decimals = [c for c in found if re.search(r"[.,]\d{1,4}$", c.strip())]
		if not with_decimals:
			return None
		choice = with_decimals[-1 if reversed_order else 0]
		return parse_money(choice)
	choice = found[-1] if reversed_order else found[0]
	if kind == "date":
		return choice
	return choice.strip()


# Tax and VAT are deliberately not excluded here: a customer block often reads
# "Tax No : 123 ... Customer Name" on one line, and that line still carries the name.
# clean_name() rejects a candidate that is only a tax label.
NAME_LINE_EXCLUDE = (
	r"company|الشركة|الضريبي|السجل التجاري|\bcr\b"
	r"|phone|telephone|mobile|fax|email|address|driver|signature"
	r"|هاتف|الهاتف|بريد|البريد|العنوان|السائق|توقيع"
)


def _excluded(spec: FieldSpec, line: str) -> bool:
	if spec.kind == "name" and re.search(NAME_LINE_EXCLUDE, line, re.IGNORECASE):
		return True
	return any(re.search(pattern, line, re.IGNORECASE) for pattern in spec.exclude)


def _result_for_value(spec: FieldSpec, value: str, line: Line, confidence: float) -> FieldResult:
	state = "extracted"
	if spec.kind == "date":
		iso, ambiguous = parse_date(value)
		if iso is None:
			return FieldResult(spec.key, spec.label, value, "uncertain", 0.4, line.page_no, line.text)
		if ambiguous:
			state = "uncertain"
			confidence = min(confidence, 0.6)
		value = iso
	return FieldResult(spec.key, spec.label, value, state, confidence, line.page_no, line.text)


def _label_variants(label: str):
	"""The printed label, then safe variants when OCR drops or adds words."""
	yield label
	core = re.sub(r"\d+(?:[.,]\d+)?\s*%?", " ", label)
	core = re.sub(r"\s+", " ", core).strip(" -–—:,.")
	if core and core != label and len(core) >= 2:
		yield core
	# "Default Unit of Measure" is printed across two form columns and OCR often keeps only
	# "Default Unit of". Try the leading words, never a single generic word.
	words = label.split()
	if len(words) >= 3 and not has_arabic(label):
		for count in range(len(words) - 1, 1, -1):
			shorter = " ".join(words[:count]).strip(" -–—:,.")
			if len(shorter) >= 8 and shorter != label:
				yield shorter


def find_field(lines: list[Line], spec: FieldSpec) -> FieldResult:
	labels = sorted(spec.labels_en + spec.labels_ar, key=len, reverse=True)
	for label in labels:
		for candidate in _label_variants(label):
			for index, line in enumerate(lines):
				if _excluded(spec, line.text):
					continue
				hit = _locate(line.text, candidate)
				if not hit:
					continue
				orientation, _start, end = hit
				if orientation == "normal":
					remainder = line.text[end:]
				else:
					remainder = line.text[:_start]
				reversed_order = orientation == "reversed"
				if spec.kind == "name" and orientation == "normal" and has_arabic(candidate):
					before = _value_from(spec.kind, line.text[:_start], False)
					if before:
						return _result_for_value(spec, before, line, 0.7)
				if spec.kind == "name" and orientation == "normal" and remainder.count(":") >= 2:
					# Several labels are printed on one row ("Customer Name: … Posting Date: …
					# Note: …"); the name is on the line below, not in this remainder.
					value = None
				else:
					value = _value_from(spec.kind, remainder, reversed_order)
				if not value and not reversed_order and has_arabic(candidate):
					# Arabic labels are often printed after their value, for example
					# "429.75 ... / اجمالي ضريبة القيمة المضافة". Read the number before the label
					# instead of borrowing the next line, which may be a different total.
					value = _value_from(spec.kind, line.text[:_start], True)
				if not value:
					# The same is common with English labels in exported tables, where the value
					# sits in the cell to the left: "2026-08-03 :Date".
					value = _value_from(spec.kind, line.text[:_start], True)
				if value:
					confidence = 0.6 if reversed_order else 0.85
					return _result_for_value(spec, value, line, confidence)
				if (
					not reversed_order
					and index + 1 < len(lines)
					and lines[index + 1].page_no == line.page_no
					and not _excluded(spec, lines[index + 1].text)
					# For a name, text already sitting before the label is the value's place;
					# never borrow the next line and turn an address or a heading into a customer.
					and not (spec.kind == "name" and re.search(r"[^\W\d_]", line.text[:_start]))
				):
					next_line = lines[index + 1]
					value = _value_from(spec.kind, next_line.text, False)
					if value:
						return _result_for_value(spec, value, next_line, 0.7)
				if (
					spec.kind != "name"
					and index > 0
					and lines[index - 1].page_no == line.page_no
					and not _excluded(spec, lines[index - 1].text)
				):
					previous_line = lines[index - 1]
					value = _value_from(spec.kind, previous_line.text, True)
					if value:
						return _result_for_value(spec, value, previous_line, 0.65)
	return FieldResult(spec.key, spec.label, None, "missing", None, None, None)


def find_currency(lines: list[Line]) -> FieldResult:
	for line in lines:
		match = CURRENCY_CODE_RE.search(line.text)
		if match:
			return FieldResult("currency", "Currency", match.group(1), "extracted", 0.75, line.page_no, line.text)
		for token, code in CURRENCY_AR.items():
			if token in line.text:
				return FieldResult("currency", "Currency", code, "extracted", 0.7, line.page_no, line.text)
	return FieldResult("currency", "Currency", None, "missing", None, None, None)


def totals_consistent(values: dict[str, str | None]) -> bool | None:
	subtotal, tax, total = values.get("subtotal"), values.get("tax_amount"), values.get("grand_total")
	if not (subtotal and tax and total):
		return None
	return abs(Decimal(subtotal) + Decimal(tax) - Decimal(total)) <= Decimal("0.01")


def extract_sales_invoice(pages: list[tuple[int, str]]) -> dict:
	return extract_fields(pages, SALES_INVOICE_FIELDS)


def extract_fields(pages: list[tuple[int, str]], specs, fallbacks=()) -> dict:
	lines = []
	for page_no, text in pages:
		for raw in normalize_text(text).splitlines():
			clean = raw.strip()
			if clean:
				lines.append(Line(page_no, clean))

	specs = tuple(specs)
	results = [find_field(lines, spec) for spec in specs]
	# A different supplier writes different labels. Whatever the mapping could not read is
	# retried once with the common wording for that field.
	by_key = {result.key: result for result in results}
	for fallback in fallbacks:
		result = by_key.get(fallback.key)
		if result is None or result.value:
			continue
		alt = find_field(lines, fallback)
		if alt.value:
			result.value = alt.value
			result.state = alt.state
			result.confidence = alt.confidence
			result.page_no = alt.page_no
			result.source_text = alt.source_text
	if not any(spec.key == "currency" for spec in specs):
		results.append(find_currency(lines))
	values = {r.key: r.value for r in results}
	full_text = "\n".join(line.text for line in lines)
	return {
		"language": detect_language(full_text),
		"fields": results,
		"checks": {"totals_consistent": totals_consistent(values)},
		"missing_required": [spec.key for spec in specs if spec.required and not values.get(spec.key)],
		"required_keys": [spec.key for spec in specs if spec.required],
	}
