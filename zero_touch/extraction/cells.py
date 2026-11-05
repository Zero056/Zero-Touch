"""Reads every cell of a line-drawn table as its own text.

Invoices often draw their header blocks and totals as small tables. Reading each cell
separately keeps a label and its value together ("Invoice No: ACC-SINV-2026-00155"),
instead of relying on the order in which the page's text happens to come out.
"""

import io

from zero_touch.extraction.grid import grid_tables
from zero_touch.extraction.items import GRID_DPI, GRID_NUMBER_DPI, _cell_text
from zero_touch.extraction.tables import norm

ITEM_FIELDS = ("item_name", "qty", "rate", "amount")


def is_item_table(texts, labels: dict[str, list[str]]) -> bool:
	"""True when the header cells look like the line-item table, which is read separately."""
	hits = 0
	for field in ITEM_FIELDS:
		names = labels.get(field) or []
		for text in texts:
			read = norm(text)
			if read and any(name and (norm(name) in read or read in norm(name)) for name in names):
				hits += 1
				break
	return hits >= 2


def cell_lines(content: bytes, page_no: int, labels: dict[str, list[str]]) -> list[str]:
	"""Every non-item-table cell on the page, one line per text line inside the cell."""
	import pdfplumber

	from zero_touch.extraction.ocr import render_page_image

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		if page_no > len(pdf.pages):
			return []
		page = pdf.pages[page_no - 1]
		boxes = [(r["x0"], r["top"], r["x1"], r["bottom"]) for r in page.rects]
		boxes += [(line["x0"], line["top"], line["x1"], line["bottom"]) for line in page.lines]
		width = float(page.width)
		try:
			pdf_tables = page.find_tables()
		except Exception:
			pdf_tables = []

	# pdfplumber finds key/value blocks that have only two columns and rows merged across the
	# full width (a label and its value in one cell). grid_tables requires three columns and
	# used to drop those blocks, which is where Customer Name and Date usually live.
	if pdf_tables:
		image = render_page_image(content, page_no, resolution=GRID_NUMBER_DPI)
		scale = image.width / width
		texts: list[str] = []
		for table in pdf_tables:
			rows = table.rows
			if not rows:
				continue
			header = [
				_cell_text(image, *cell, scale, "6", "eng+ara")
				for cell in rows[0].cells
				if cell is not None
			]
			if is_item_table(header, labels):
				continue
			for row in rows:
				row_lines: list[str] = []
				for cell in row.cells:
					if cell is None:
						continue
					text = _cell_text(image, *cell, scale, "6", "eng+ara")
					for line in text.splitlines():
						line = " ".join(line.split()).strip("\u200e\u200f ")
						if line:
							row_lines.append(line)
				joined = " | ".join(row_lines)
				if joined:
					texts.append(joined)
		return texts

	image = render_page_image(content, page_no, resolution=GRID_DPI)
	scale = image.width / width
	if not boxes:
		# A photo or a scan has the table borders only as pixels.
		from zero_touch.extraction.grid import raster_boxes

		boxes = raster_boxes(image, scale)
	tables = grid_tables(boxes)
	if not tables:
		return []
	texts: list[str] = []
	for table in tables:
		xs, ys = table["xs"], table["ys"]
		if len(xs) < 3 or len(ys) < 2:
			continue
		header = [
			_cell_text(image, xs[index], ys[0], xs[index + 1], ys[1], scale, "6", "eng+ara")
			for index in range(len(xs) - 1)
		]
		if is_item_table(header, labels):
			continue
		row_lines: list[str] = []
		cell_lines_out: list[str] = []
		for top, bottom in zip(ys, ys[1:]):
			row_cells: list[str] = []
			for index in range(len(xs) - 1):
				cell = _cell_text(image, xs[index], top, xs[index + 1], bottom, scale, "6", "eng+ara")
				row_cells.append(" ".join(cell.split()))
				for line in cell.splitlines():
					line = " ".join(line.split()).strip("\u200e\u200f ")
					if line:
						cell_lines_out.append(line)
			# The label and its value are often in side-by-side cells. Keeping the whole row
			# on one line lets the reader take the value from the left of the label, which is
			# how most exported invoices print it.
			joined = " | ".join(cell for cell in row_cells if cell)
			if joined:
				row_lines.append(joined.strip(" |"))
		texts.extend(row_lines)
		texts.extend(cell_lines_out)
	return texts
