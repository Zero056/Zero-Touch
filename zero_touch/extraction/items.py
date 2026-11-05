"""Reads the line-item table of an invoice, from the text layer or from OCR word positions."""

import io
import re

from zero_touch.extraction.ocr import render_page_image, tsv_words
from zero_touch.extraction.tables import Word, build_rows, column_bounds, find_header, is_number, stop_top

DEFAULT_ITEM_LABELS = {
	"item_name": [
		"Service Type", "نوع الخدمة", "Description", "الوصف", "Item", "الصنف",
		"Name of Goods or Services", "Goods or Services", "Item Name", "Product Name", "Product",
		"اسم السلعة", "السلعة", "السلع والخدمات",
	],
	"qty": ["Quantity", "Qty", "العدد", "الكمية", "الكميه"],
	"rate": ["Price", "Rate", "Unit Price", "السعر", "سعر الوحدة"],
	"amount": ["Taxable Amount", "Amount", "المبلغ الخاضع للضريبة", "المبلغ الخاضع", "المبلغ"],
	"_subscription": ["Subscription", "نوع الاشتراك"],
	"_vat": ["VAT", "الضريبة", "ضريبة"],
	"_total": ["Total (SAR)", "Total", "الإجمالي", "الاجمالي"],
}
NUMERIC_FIELDS = {"qty", "rate", "amount"}
OCR_TABLE_SCALE = 2


def item_labels(mapped: dict[str, list[str]]) -> dict[str, list[str]]:
	labels = {key: list(values) for key, values in DEFAULT_ITEM_LABELS.items()}
	for field, extra in mapped.items():
		labels[field] = list(extra) + [label for label in labels.get(field, []) if label not in extra]
	return labels


def rows_from_text_layer(page, labels: dict[str, list[str]]) -> list[dict]:
	words = [
		Word(float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"]), w["text"])
		for w in page.extract_words(keep_blank_chars=False, use_text_flow=True)
	]
	return _read(words, labels, float(page.width), float(page.height))


def rows_from_ocr(content: bytes, page_no: int, labels: dict[str, list[str]]) -> list[dict]:
	from zero_touch.extraction.ocr import recognize_png  # noqa: F811

	page_image = render_page_image(content, page_no, resolution=300)
	png = _png(page_image)
	words = [Word(*box[:4], box[4]) for box in tsv_words(png, psm="4")]
	width, height = page_image.size
	found = find_header(words, labels)
	if not found:
		return []
	top, bottom, anchors = found
	region_bottom = stop_top(words, below_y=bottom) or height * 0.92
	bounds = column_bounds(anchors, page_width=width)

	box = (0, int(bottom), width, int(region_bottom))
	if box[3] <= box[1]:
		return []
	crop = page_image.crop(box).resize(((box[2] - box[0]) * OCR_TABLE_SCALE, (box[3] - box[1]) * OCR_TABLE_SCALE))
	table_words = [
		Word(
			x0 / OCR_TABLE_SCALE + box[0],
			y0 / OCR_TABLE_SCALE + box[1],
			x1 / OCR_TABLE_SCALE + box[0],
			y1 / OCR_TABLE_SCALE + box[1],
			text,
		)
		for x0, y0, x1, y1, text in tsv_words(_png(crop), psm="6")
	]
	return clean_rows(build_rows(table_words, bounds, NUMERIC_FIELDS, bottom, region_bottom))


TOTAL_WORDS = ("total", "discount", "subtotal", "vat", "المجموع", "الخصم", "الاجمالي", "الإجمالي", "اجمالي", "ضريبة")
LETTER = re.compile(r"[^\W\d_]")


LEADING_JUNK = re.compile(r"[:;,.\)\]\(\[\|\-•]")


def tidy_name(name: str) -> str:
	"""Drops leading label debris such as "4: )" but keeps model numbers like "160*70*30"."""
	name = re.sub(r"\s*=\s*", " - ", name or "")
	tokens = name.split()
	while tokens and not LETTER.search(tokens[0]) and LEADING_JUNK.search(tokens[0]):
		tokens.pop(0)
	while tokens and not LETTER.search(tokens[-1]) and not re.search(r"\d", tokens[-1]):
		tokens.pop()
	return " ".join(tokens)


def amount_from(qty, rate) -> str | None:
	"""Quantity × rate, rounded to the currency precision, or None when either is not a number."""
	from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

	try:
		quantity = Decimal(str(qty).replace(",", "").strip())
		price = Decimal(str(rate).replace(",", "").strip())
	except (InvalidOperation, ValueError):
		return None
	return f"{(quantity * price).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def clean_rows(rows: list[dict]) -> list[dict]:
	"""Keeps item rows only: a name and at least one number. Stops at the first totals row."""
	from zero_touch.extraction.tables import norm

	kept = []
	for row in rows:
		row["item_name"] = tidy_name(row.get("item_name") or "")
		# A cell may read as "150.00 ء شريحة" when a stray word lands in a numeric column.
		# Keep the money token; leave values without a 2-decimal amount for the reviewer,
		# because guessing between "5" and "7" in "5-7" would post a wrong price.
		for field in ("qty", "rate", "amount"):
			value = str(row.get(field) or "")
			match = re.search(r"\d[\d,]*(?:\.\d{2})\b", value) if value else None
			if match:
				row[field] = match.group(0).replace(",", "")
		name = norm(row["item_name"])
		if any(word in name for word in TOTAL_WORDS):
			break
		if not row["item_name"]:
			continue
		if not row.get("amount") and row.get("qty") and row.get("rate"):
			row["amount"] = amount_from(row["qty"], row["rate"])
		if not (row.get("qty") or row.get("amount")):
			continue
		kept.append(row)
	return kept


def _prefer(direct: list[dict], rows: list[dict]) -> list[dict]:
	"""Keeps the reading that produced more item rows."""
	return rows if len(rows) >= len(direct) else direct


def _read(words, labels, width, height):
	found = find_header(words, labels)
	if not found:
		return []
	top, bottom, anchors = found
	region_bottom = stop_top(words, below_y=bottom) or height * 0.92
	bounds = column_bounds(anchors, page_width=width)
	return clean_rows(build_rows(words, bounds, NUMERIC_FIELDS, bottom, region_bottom))


def _png(image) -> bytes:
	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	return buffer.getvalue()


GRID_DPI = 400
# Numbers read more reliably at 300 dpi (a 5 is often mistaken for a 9 at 400), while
# Arabic item names need 400. The table reader uses one resolution for each.
GRID_NUMBER_DPI = 300
GRID_NAME_DPI = 400
# Do not shrink the cell: a 2pt inset clips the tops of Arabic letters and turns
# "المدرسة الامريكية العالمية الرياض" into unreadable fragments.
GRID_INSET = 0.0
GRID_TEXT_SCALE = 2
GRID_NUMBER_SCALE = 3


def _cell_text(image, left, top, right, bottom, scale, psm, lang, inset=None, text_scale=None) -> str:
	import os
	import subprocess
	import tempfile

	margin = GRID_INSET if inset is None else inset
	box = (
		int((left + margin) * scale),
		int((top + margin) * scale),
		int((right - margin) * scale),
		int((bottom - margin) * scale),
	)
	if box[2] <= box[0] or box[3] <= box[1]:
		return ""
	crop = image.crop(box)

	def read(factor: int) -> str:
		scaled = crop.resize((max(crop.width * factor, 1), max(crop.height * factor, 1)))
		with tempfile.TemporaryDirectory() as folder:
			path = os.path.join(folder, "cell.png")
			scaled.save(path)
			completed = subprocess.run(
				["tesseract", path, "stdout", "--psm", psm, "-l", lang],
				capture_output=True,
				text=True,
				timeout=60,
				check=False,
			)
		return completed.stdout.strip()

	# Upscaling helps faint scans but can make a small cell (for example a lone "1")
	# unreadable, so fall back to the original size when the enlarged read is empty.
	factor = text_scale or (GRID_NUMBER_SCALE if psm == "7" else GRID_TEXT_SCALE)
	text = read(factor)
	if not text and factor != 1:
		text = read(1)
	return text


def _grid_columns(image, xs, top, bottom, labels, scale, text_scale=None) -> dict[str, int]:
	"""Maps each item field to the column whose header matches one of its labels."""
	from zero_touch.extraction.tables import norm

	texts = [
		_cell_text(image, xs[index], top, xs[index + 1], bottom, scale, "6", "eng+ara", text_scale=text_scale)
		for index in range(len(xs) - 1)
	]
	reads = [norm(text) for text in texts]
	columns: dict[str, int] = {}
	for field, names in labels.items():
		# A header that equals the label wins over one that merely contains it. Without
		# this, "Discount Amount" is taken for "Amount" and "Item" for "Description".
		for name in names:
			wanted = norm(name)
			if not wanted:
				continue
			index = next((i for i, read in enumerate(reads) if read == wanted), None)
			if index is not None:
				columns[field] = index
				break
		if field in columns:
			continue
		for name in names:
			wanted = norm(name)
			if not wanted:
				continue
			index = next(
				(i for i, read in enumerate(reads) if read and (wanted in read or read in wanted)),
				None,
			)
			if index is not None:
				columns[field] = index
				break
	return columns


def _numbers_in(text: str) -> list[str]:
	return [number.replace(",", "") for number in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")]


def _best_number(text: str) -> str:
	"""The money amount in a cell, ignoring noise numbers such as a stray "01" or "2"."""
	values = _numbers_in(text)
	if not values:
		return ""
	decimals = [value for value in values if re.search(r"\.\d{2}$", value)]
	return (decimals or values)[-1]


def _row_consistent(row: dict) -> bool:
	from decimal import Decimal, InvalidOperation

	try:
		qty = Decimal(str(row["qty"]))
		rate = Decimal(str(row["rate"]))
		amount = Decimal(str(row["amount"]))
	except (KeyError, InvalidOperation):
		return False
	return abs(qty * rate - amount) <= Decimal("0.05")


def _grid_number(image, xs, column, top, bottom, scale) -> str:
	# psm 6 reads a sparse cell (one number in a tall row) better than psm 7, which often
	# returns nothing when the cell is mostly empty.
	text = _cell_text(image, xs[column], top, xs[column + 1], bottom, scale, "6", "eng+ara")
	numbers = _numbers_in(text.replace("#", " "))
	if not numbers:
		return ""
	return numbers[0]


def _rows_from_pdf_tables(
	content: bytes,
	page_no: int,
	width: float,
	tables,
	labels: dict[str, list[str]],
	text_scale=None,
) -> list[dict]:
	"""Reads the tables pdfplumber can outline, using one OCR call per cell.

	pdfplumber sees the real cell borders even when a merged header or a totals block
	prevents the line clustering in grid_tables from finding every column. Numbers are read
	at 300 dpi (where 5 and 9 are not confused) and item names at 400 dpi.
	"""
	from zero_touch.extraction.tables import norm

	header_image = render_page_image(content, page_no, resolution=GRID_NUMBER_DPI)
	header_scale = header_image.width / width
	words = [Word(*box[:4], box[4]) for box in tsv_words(_png(header_image), psm="4")]
	found = find_header(words, labels)
	if not found:
		return []
	top, bottom, anchors = found
	header_mid = (((top + bottom) / 2) / header_scale)
	table = next(
		(t for t in tables if float(t.bbox[1]) - 4 <= header_mid <= float(t.bbox[3]) + 4),
		max(tables, key=lambda t: len(t.rows)),
	)
	base = max(table.rows, key=lambda row: sum(cell is not None for cell in row.cells))
	base_cells = [cell for cell in base.cells if cell is not None]
	if len(base_cells) < 3:
		return []

	name_image = render_page_image(content, page_no, resolution=GRID_NAME_DPI)
	name_scale = name_image.width / width
	number_image = header_image
	number_scale = header_scale
	xs = [float(base_cells[0][0])] + [float(cell[2]) for cell in base_cells]
	columns: dict[str, int] = {}
	for field, centre in anchors.items():
		centre /= header_scale
		for index in range(len(xs) - 1):
			if xs[index] <= centre <= xs[index + 1]:
				columns[field] = index
				break
	if "item_name" not in columns:
		return []

	rows = []
	started = False
	description = columns["item_name"] - 1
	for row in table.rows:
		cells = [cell for cell in row.cells if cell is not None]
		if len(cells) < len(base_cells):
			# The header is often one merged cell above the first full row; the totals block
			# is merged the same way below the items.
			if started:
				break
			continue
		values: dict[str, str] = {}
		for field, index in columns.items():
			cell = cells[index]
			if field == "item_name":
				text = _cell_text(name_image, *cell, name_scale, "6", "eng+ara", text_scale=2)
			else:
				text = _cell_text(number_image, *cell, number_scale, "6", "eng", inset=2)
				if not _best_number(text):
					alternate = _cell_text(number_image, *cell, number_scale, "7", "eng", inset=2)
					if _best_number(alternate):
						text = alternate
			values[field] = (text or "").strip()
		name = values.get("item_name") or ""
		if any(label and norm(label) in norm(name) for label in labels.get("item_name", [])):
			continue
		started = True
		if any(word in norm(name) for word in TOTAL_WORDS):
			break
		if description >= 0 and len(LETTER.findall(name)) < 3 and description < len(cells):
			cell = cells[description]
			alternate = _cell_text(name_image, *cell, name_scale, "6", "eng+ara", text_scale=2)
			if len(LETTER.findall(alternate)) > len(LETTER.findall(name)):
				name = alternate
		row_data = {"item_name": name}
		for field in NUMERIC_FIELDS:
			number = _best_number(values.get(field) or "")
			if number:
				row_data[field] = number
		if not row_data.get("qty") and row_data.get("rate") and row_data.get("amount") == row_data.get("rate"):
			row_data["qty"] = "1"
		if name.strip() and any(row_data.get(field) for field in NUMERIC_FIELDS):
			rows.append(row_data)
	return clean_rows(rows)


def rows_from_grid(content: bytes, page_no: int, labels: dict[str, list[str]], text_scale=None) -> list[dict]:
	"""Reads a table drawn with vector lines, one OCR call per cell."""
	import io

	import pdfplumber

	from zero_touch.extraction.grid import grid_tables
	from zero_touch.extraction.tables import norm

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		if page_no > len(pdf.pages):
			return []
		page = pdf.pages[page_no - 1]
		boxes = [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in page.rects]
		boxes += [(line["x0"], line["top"], line["x1"], line["bottom"]) for line in page.lines]
		width = float(page.width)
		try:
			tables = page.find_tables()
		except Exception:
			tables = []
	if tables:
		try:
			rows = _rows_from_pdf_tables(content, page_no, width, tables, labels, text_scale)
		except Exception:
			rows = []
		if rows:
			return rows
	image = render_page_image(content, page_no, resolution=GRID_DPI)
	scale = image.width / width
	if not boxes:
		# A photo or a scan has the table borders only as pixels.
		from zero_touch.extraction.grid import raster_boxes

		boxes = raster_boxes(image, scale)
	tables = grid_tables(boxes)
	if not tables:
		return []
	found: list[dict] = []
	for table in tables:
		xs, ys = table["xs"], table["ys"]
		if len(ys) < 3:
			continue
		columns = _grid_columns(image, xs, ys[0], ys[1], labels, scale, text_scale=text_scale)
		if "item_name" not in columns:
			continue
		rows = []
		for top, bottom in zip(ys[1:], ys[2:]):
			cells = {}
			for field in ("item_name", *NUMERIC_FIELDS):
				column = columns.get(field)
				if column is None:
					continue
				text = _cell_text(
					image, xs[column], top, xs[column + 1], bottom, scale, "6", "eng+ara", text_scale=text_scale
				)
				if field in NUMERIC_FIELDS and not _numbers_in(text):
					# A digit sitting on the border can be lost when the whole cell is used;
					# shrinking the crop slightly reads it again.
					alt = _cell_text(
						image,
						xs[column],
						top,
						xs[column + 1],
						bottom,
						scale,
						"6",
						"eng+ara",
						inset=2.0,
						text_scale=text_scale,
					)
					if _numbers_in(alt):
						text = alt
				cells[field] = text
			if not (cells.get("item_name") or "").strip() and "item_name" in columns:
				# Some cells come back empty with psm 6 but readable with psm 7.
				cells["item_name"] = _cell_text(
					image,
					xs[columns["item_name"]],
					top,
					xs[columns["item_name"] + 1],
					bottom,
					scale,
					"7",
					"eng+ara",
					text_scale=text_scale,
				)
			name_lines = [line.strip() for line in (cells.get("item_name") or "").splitlines() if line.strip()]
			numbers = {
				field: [_numbers_in(line) for line in (cells.get(field) or "").splitlines()] for field in NUMERIC_FIELDS
			}
			# A table with a line between its rows has one band per item; the description may
			# wrap over several lines inside that band, so keep them together. A table with a
			# single body band has no row lines, and the text lines inside it are the rows.
			if len(ys) > 3:
				name = " ".join(" ".join(line.split()) for line in name_lines)
				if not name:
					continue
				if any(word in norm(name) for word in TOTAL_WORDS):
					break
				row = {"item_name": name}
				for field in NUMERIC_FIELDS:
					number = _best_number(cells.get(field) or "")
					if number:
						row[field] = number
				# If qty × rate does not match the printed amount, the cell crop misread a
				# digit. Read those three cells again at the unscaled size and keep that
				# reading only when it adds up.
				if not _row_consistent(row) and all(row.get(field) for field in ("qty", "rate", "amount")):
					alternate = {}
					for field in NUMERIC_FIELDS:
						column = columns.get(field)
						if column is None:
							continue
						text = _cell_text(
							image,
							xs[column],
							top,
							xs[column + 1],
							bottom,
							scale,
							"6",
							"eng+ara",
							text_scale=2 if text_scale == 1 else 1,
						)
						number = _best_number(text)
						if number:
							alternate[field] = number
					if _row_consistent(alternate):
						row.update(alternate)
				if any(row.get(field) for field in NUMERIC_FIELDS):
					rows.append(row)
				continue
			# Rows without drawn separators put every item in the same cell, one text line per
			# item. The line count of the numbers tells how many rows the band holds.
			height = max(
				(sum(1 for line in values if line) for values in numbers.values()),
				default=1,
			)
			height = max(1, min(height, 50))
			for index in range(height):
				name = name_lines[index] if index < len(name_lines) else (name_lines[-1] if name_lines else "")
				name = " ".join(name.split())
				if not name:
					continue
				if any(word in norm(name) for word in TOTAL_WORDS):
					break
				row = {"item_name": name}
				for field in NUMERIC_FIELDS:
					values = [number for line in numbers.get(field, []) for number in line]
					if values:
						row[field] = values[index] if index < len(values) else values[-1]
				if not any(row.get(field) for field in NUMERIC_FIELDS):
					continue
				rows.append(row)
		for row in rows:
			if not row.get("qty") and row.get("rate") and row.get("amount") == row.get("rate"):
				row["qty"] = "1"
		found.extend(clean_rows(rows))
	return found


CELL_MARGIN = 12
CELL_SCALE = 3


def _ocr_cell(image, box) -> str:
	import os
	import subprocess
	import tempfile

	crop = image.crop(tuple(int(v) for v in box))
	crop = crop.resize((crop.width * CELL_SCALE, crop.height * CELL_SCALE))
	with tempfile.TemporaryDirectory() as folder:
		path = os.path.join(folder, "cell.png")
		crop.save(path)
		completed = subprocess.run(
			["tesseract", path, "stdout", "--psm", "7"],
			capture_output=True,
			text=True,
			timeout=60,
			check=False,
		)
	return completed.stdout.strip()


def _raster_bands(image, top: float, bottom: float) -> list[tuple[int, int]]:
	"""Row bands between the long dark horizontal lines of a scanned or photographed table."""
	import numpy as np

	gray = np.asarray(image.convert("L")) < 160
	_height, width = gray.shape
	lines = sorted(
		{
			int(y)
			for y in np.flatnonzero(gray.sum(axis=1) > width * 0.5)
			if top - 2 <= y <= bottom + 2
		}
	)
	return [(a, b) for a, b in zip(lines, lines[1:]) if b - a > 5]


def rows_from_ocr_cells(content: bytes, page_no: int, labels: dict[str, list[str]]) -> list[dict]:
	"""Reads each item row by its name position, then reads each cell on its own at high resolution."""
	from zero_touch.extraction.tables import Word, find_header, norm, stop_top

	page_image = render_page_image(content, page_no, resolution=300)
	width, height = page_image.size
	words = [Word(*box[:4], box[4]) for box in tsv_words(_png(page_image), psm="6")]
	found = find_header(words, labels)
	if not found:
		return []
	# The full-page read keeps rows together better than the per-cell passes on some
	# Arabic scans. Only pay for the second OCR when the item header was actually found.
	direct = []
	words4 = [Word(*box[:4], box[4]) for box in tsv_words(_png(page_image), psm="4")]
	found4 = find_header(words4, labels)
	if found4:
		top4, bottom4, anchors4 = found4
		direct = clean_rows(
			build_rows(
				words4,
				column_bounds(anchors4, page_width=width),
				NUMERIC_FIELDS,
				bottom4,
				stop_top(words4, below_y=bottom4) or height * 0.92,
			)
		)
	top, bottom, anchors = found
	region_bottom = stop_top(words, below_y=bottom) or height * 0.92
	bounds = column_bounds(anchors, page_width=width)
	if "item_name" not in bounds:
		# The item name header was not recognised (common on Arabic invoices). It is the
		# wide left-most column; everything left of the first numeric column belongs to it.
		first = min(anchors, key=anchors.get)
		start = max(anchors[first] - 40, 0)
		bounds["item_name"] = (0.0, start)
		_lo, hi = bounds[first]
		bounds[first] = (start, hi)
	name_lo, name_hi = bounds.get("item_name", (0, width))

	# A scan or photo has no vector lines, but its table borders are visible as long dark
	# rows. Those lines give exact row bands, and the header anchors give the columns.
	bands = _raster_bands(page_image, bottom, region_bottom)
	if bands:
		rows = []
		for band_top, band_bottom in bands:
			name = " ".join(
				w.text
				for w in sorted(
					(w for w in words if band_top <= w.yc < band_bottom and name_lo <= w.xc < name_hi),
					key=lambda w: (round(w.yc / max(w.height, 1)), w.x0),
				)
			)
			name = " ".join(name.split())
			if not name:
				continue
			if any(word in norm(name) for word in TOTAL_WORDS):
				break
			row = {"item_name": name}
			for field in NUMERIC_FIELDS:
				centre = anchors.get(field)
				if centre is None:
					continue
				candidates = [
					w
					for w in words
					if band_top <= w.yc < band_bottom
					and abs(w.xc - centre) <= 45
					and re.search(r"\d", w.text)
				]
				if candidates:
					nearest = min(candidates, key=lambda w: abs(w.xc - centre))
					number = _best_number(nearest.text)
					if number:
						row[field] = number
			if any(row.get(field) for field in NUMERIC_FIELDS):
				rows.append(row)
		return _prefer(direct, clean_rows(rows))

	name_words = sorted(
		(w for w in words if bottom < w.yc < region_bottom and name_lo <= w.xc < name_hi and not w.text.strip() == ""),
		key=lambda w: w.y0,
	)
	if not name_words:
		return []
	starts: list[list[Word]] = []
	gap = max(w.height for w in name_words) * 0.3
	for word in name_words:
		if starts and word.y0 - starts[-1][-1].y1 <= gap:
			starts[-1].append(word)
		else:
			starts.append([word])

	rows = []
	for index, group in enumerate(starts):
		band_top = group[0].y0 - 12
		row_height = max(w.height for w in group)
		group_bottom = max(w.y1 for w in group)
		band_bottom = min(group_bottom + row_height * 1.2, region_bottom)
		if index + 1 < len(starts):
			band_bottom = min(band_bottom, starts[index + 1][0].y0 - 12)
		row = {}
		for field, (lo, hi) in bounds.items():
			if field.startswith("_"):
				continue
			if field == "item_name":
				name_bottom = group_bottom + row_height * 0.6
				row[field] = " ".join(w.text for w in sorted(
					(w for w in words if band_top <= w.yc < name_bottom and lo <= w.xc < hi and not w.text.strip() == ""),
					key=lambda w: (round(w.yc / max(w.height, 1)), w.x0),
				)).strip()
				continue
			cell = _ocr_cell(page_image, (lo + CELL_MARGIN if lo else 0, band_top, hi - CELL_MARGIN, band_bottom))
			if not is_number(cell.replace(" ", "")) and field in NUMERIC_FIELDS:
				wide = [
					w
					for w in words_from_band(page_image, band_top, band_bottom)
					if lo <= w.xc < hi and is_number(w.text)
				]
				cell = " ".join(w.text for w in wide)
			numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", cell.replace("#", " "))
			if field in NUMERIC_FIELDS and numbers:
				cell = numbers[0]
			row[field] = cell.replace("#", "").strip()
		if any(v for k, v in row.items() if k != "item_name"):
			rows.append(row)
	return _prefer(direct, clean_rows(rows))


def words_from_band(image, band_top: float, band_bottom: float) -> list[Word]:
	box = (0, int(band_top), image.size[0], int(band_bottom))
	if box[3] <= box[1]:
		return []
	crop = image.crop(box).resize(((box[2] - box[0]) * CELL_SCALE, (box[3] - box[1]) * CELL_SCALE))
	return [
		Word(x0 / CELL_SCALE, y0 / CELL_SCALE + box[1], x1 / CELL_SCALE, y1 / CELL_SCALE + box[1], text)
		for x0, y0, x1, y1, text in tsv_words(_png(crop), psm="6")
	]
