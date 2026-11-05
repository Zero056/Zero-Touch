from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

import frappe

from zero_touch.extraction.ocr import OcrError, recognize_png, render_page_for_ocr, tesseract_available
from zero_touch.extraction.parse import extract_fields, normalize_text
from zero_touch.audit.log import write_event
from zero_touch.extraction.cells import cell_lines
from zero_touch.extraction.items import item_labels, rows_from_grid, rows_from_ocr_cells, rows_from_text_layer
from zero_touch.extraction.specs import fallback_specs, field_specs, has_item_rows, item_label_map, link_rules, load_mapping
from zero_touch.extraction.text_layer import PageText, PdfReadError, read_pdf_text, render_preview_png

ENGINE = "pdf_text_layer"
OCR_ENGINE = "tesseract"
IMAGE_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"})
MIN_TEXT_CHARS = 20
DEFAULT_MAX_PAGES = 50
OCR_CONFIDENCE_FACTOR = 0.85


@dataclass(frozen=True)
class ExtractionOutcome:
	ok: bool
	reason: str
	extraction: str | None = None
	field_count: int = 0
	permanent: bool = False
	transient: bool = False


def _attach_preview(page_doc_name: str, png: bytes, page_no: int) -> str:
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"preview-page-{page_no}.png",
			"content": png,
			"is_private": 1,
			"attached_to_doctype": "Document Page",
			"attached_to_name": page_doc_name,
			"attached_to_field": "preview_file",
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc.file_url


def _apply_positional_totals(content: bytes, pages: list[PageText], text_source: str, result: dict, specs) -> None:
	from zero_touch.extraction.ocr import render_page_image, tsv_words
	from zero_touch.extraction.items import _png, words_from_band
	from zero_touch.extraction.parse import SALES_INVOICE_FIELDS
	from zero_touch.extraction.tables import Word
	from zero_touch.extraction.totals import positional_amount

	fields = {field.key: field for field in result["fields"]}
	builtin = {spec.key: spec for spec in SALES_INVOICE_FIELDS}
	targets = []
	for spec in specs:
		field = fields.get(spec.key)
		if spec.kind != "money" or field is None or field.value:
			continue
		labels = list(spec.labels_en) + list(spec.labels_ar)
		if not labels and spec.key in builtin:
			# Built-in labels are only a fallback. When the mapping names the label, use it
			# alone: generic words such as "Total" must not override a specific
			# "Total including VAT", or the net total is read as the grand total.
			labels += list(builtin[spec.key].labels_en) + list(builtin[spec.key].labels_ar)
		if labels:
			targets.append((spec.key, labels))
	if not targets:
		return

	for page in pages:
		if text_source == "text_layer":
			import io

			import pdfplumber

			with pdfplumber.open(io.BytesIO(content)) as pdf:
				pdf_page = pdf.pages[page.page_no - 1]
				words = [
					Word(float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"]), w["text"])
					for w in pdf_page.extract_words()
				]
			band = lambda y0, y1, words=words: [w for w in words if y0 <= w.yc <= y1]
		else:
			image = render_page_image(content, page.page_no, resolution=300)
			words = [Word(*box[:4], box[4]) for box in tsv_words(_png(image), psm="4")]
			band = lambda y0, y1, image=image: words_from_band(image, y0, y1)

		for key, labels in list(targets):
			found = positional_amount(words, labels, band, page.height)
			if not found:
				continue
			amount, source = found
			field = fields[key]
			field.value = amount
			field.state = "uncertain"
			field.confidence = 0.6
			field.page_no = page.page_no
			field.source_text = f"read from the line of the label: {source}"
			targets.remove((key, labels))
		if not targets:
			break

	result["missing_required"] = [spec.key for spec in specs if spec.required and not fields[spec.key].value]


def _refine_money_values(content: bytes, pages: list[PageText], result, specs) -> None:
	"""Re-reads an amount token on its own, away from the table border.

	A bold total sitting under a ruled line is often read as "49.40" instead of "19.10"
	when the whole line is OCR'd. Cropping just the number reads it correctly.
	"""
	import io
	import os
	import subprocess
	import tempfile

	from PIL import Image

	from zero_touch.extraction.ocr import render_page_for_ocr, tsv_words
	from zero_touch.extraction.parse import parse_money

	# Only the grand total: it is the value the create guard compares, and a total printed
	# just under a ruled line is the one most often read with an extra stroke. Re-reading
	# small values such as VAT can introduce a new error instead of removing one.
	targets = [field for field in result["fields"] if field.key == "grand_total" and field.value]
	if not targets:
		return
	for page in pages:
		png = render_page_for_ocr(content, page.page_no, resolution=300)
		image = Image.open(io.BytesIO(png))
		width, height = image.size
		words = tsv_words(png, psm="6")
		for field in targets:
			wanted = parse_money(field.value)
			if wanted is None:
				continue
			for word in words:
				x0, y0, x1, y1, text = word
				if parse_money(text.replace(" ", "")) != wanted:
					continue
				pad = 4
				crop = image.crop(
					(max(0, int(x0) - pad), max(0, int(y0) - pad), min(width, int(x1) + pad), min(height, int(y1) + pad))
				)
				crop = crop.resize((crop.width * 3, crop.height * 3))
				with tempfile.TemporaryDirectory() as folder:
					path = os.path.join(folder, "amount.png")
					crop.save(path)
					completed = subprocess.run(
						["tesseract", path, "stdout", "--psm", "7", "-l", "eng"],
						capture_output=True,
						text=True,
						timeout=60,
						check=False,
					)
				read = parse_money(completed.stdout.strip())
				if read is not None and read != wanted:
					field.value = read
					field.state = "uncertain"
					field.confidence = 0.6
					field.source_text = f"amount re-read near the printed border: {read}"
				break


def _read_lines(
	content: bytes, pages: list[PageText], text_source: str, labels: dict, text_scale=None
) -> list[tuple[int, dict]]:
	found = []
	if text_source == "text_layer":
		import io

		import pdfplumber

		with pdfplumber.open(io.BytesIO(content)) as pdf:
			for index, page in enumerate(pdf.pages, start=1):
				found.extend((index, row) for row in rows_from_text_layer(page, labels))
	if found:
		return found
	# Tables drawn with vector lines can be read cell by cell, which is exact about which
	# number belongs to which column. Scanned invoices often have no text layer but do have
	# these lines.
	for page in pages:
		try:
			rows = rows_from_grid(content, page.page_no, labels, text_scale=text_scale)
		except Exception:
			rows = []
		found.extend((page.page_no, row) for row in rows)
	if found:
		return found
	if text_source != "text_layer":
		for page in pages:
			found.extend((page.page_no, row) for row in rows_from_ocr_cells(content, page.page_no, labels))
	return found


def _expected_items_total(result) -> Decimal | None:
	"""What the item amounts should add up to: the grand total less the tax."""
	values = {field.key: field.value for field in result["fields"]}
	grand = values.get("grand_total")
	if not grand:
		return None
	tax = values.get("total_taxes_and_charges") or values.get("tax_amount") or "0"
	try:
		return Decimal(str(grand)) - Decimal(str(tax))
	except (InvalidOperation, ValueError):
		return None


def _lines_total(lines) -> Decimal:
	total = Decimal("0")
	for _page, row in lines:
		amount = row.get("amount")
		if not amount:
			continue
		try:
			total += Decimal(str(amount))
		except (InvalidOperation, ValueError):
			continue
	return total


def image_to_pdf(content: bytes) -> bytes:
	"""Turns an uploaded photo or scan into a one-page PDF so it uses the same OCR pipeline."""
	import io

	from PIL import Image, ImageOps

	image = Image.open(io.BytesIO(content))
	image = ImageOps.exif_transpose(image)
	if image.mode not in ("RGB", "L"):
		image = image.convert("RGB")
	# Make the PDF page A4-wide whatever the image size. The OCR step renders the page at
	# 200 dpi; if a small image became a small page, the text would be downsampled and
	# unreadable (a 768px photo produced a 184pt page and only 317 characters).
	dpi = max(image.width, 1) * 72.0 / 595.0
	buffer = io.BytesIO()
	image.save(buffer, format="PDF", resolution=max(dpi, 24.0))
	return buffer.getvalue()


def _read_pages(content: bytes, max_pages: int) -> tuple[list[PageText], str]:
	pages = read_pdf_text(content, max_pages=max_pages)
	if sum(len(p.text.strip()) for p in pages) >= MIN_TEXT_CHARS:
		return pages, "text_layer"
	if not tesseract_available():
		raise _NoText(
			"No readable text was found, and OCR is not installed on this server. Install Tesseract, then retry."
		)
	recognised = []
	for page in pages:
		text = recognize_png(render_page_for_ocr(content, page.page_no))
		recognised.append(PageText(page.page_no, page.width, page.height, text))
	if sum(len(p.text.strip()) for p in recognised) < MIN_TEXT_CHARS:
		raise _NoText("OCR could not read any text from this document.")
	return recognised, "ocr"


class _NoText(Exception):
	pass


def run_pdf_extraction(intake: str, content: bytes, profile: str) -> ExtractionOutcome:
	settings = frappe.get_single("Zero Touch Settings")
	max_pages = int(settings.get("max_pages") or DEFAULT_MAX_PAGES)

	try:
		pages, text_source = _read_pages(content, max_pages)
	except PdfReadError as exc:
		return ExtractionOutcome(ok=False, reason=str(exc), permanent=True)
	except _NoText as exc:
		return ExtractionOutcome(ok=False, reason=str(exc), permanent=True)
	except OcrError as exc:
		return ExtractionOutcome(ok=False, reason=f"{exc}. It will be tried again.", transient=True)

	intake_row = frappe.db.get_value(
		"Document Intake", intake, ["company", "target_doctype"], as_dict=True
	)
	company = intake_row.company
	mapping = load_mapping(profile, company)
	specs = field_specs(mapping, intake_row.target_doctype)
	links = link_rules(mapping)
	labels = item_labels(item_label_map(mapping))
	if text_source == "ocr":
		# Read the header and totals blocks cell by cell. This keeps each label next to its
		# value, which OCR text order alone often loses. The item table is read separately.
		enriched = []
		for page in pages:
			try:
				extra = cell_lines(content, page.page_no, labels)
			except Exception as exc:
				extra = []
				write_event("stage_fail", intake=intake, stage="extract", message=f"cells not read: {exc}")
			enriched.append(replace(page, text="\n".join([*extra, page.text])) if extra else page)
		pages = enriched
	result = extract_fields([(p.page_no, p.text) for p in pages], specs, fallback_specs(specs))
	try:
		_apply_positional_totals(content, pages, text_source, result, specs)
	except Exception as exc:
		write_event("stage_fail", intake=intake, stage="extract", message=f"totals not read by position: {exc}")
	try:
		_refine_money_values(content, pages, result, specs)
	except Exception as exc:
		write_event("stage_fail", intake=intake, stage="extract", message=f"amounts not re-read: {exc}")
	if intake_row.target_doctype and not frappe.get_meta(intake_row.target_doctype).has_field("currency"):
		result["fields"] = [field for field in result["fields"] if field.key != "currency"]
	required_keys = set(result["required_keys"])
	spec_kind = {spec.key: spec.kind for spec in specs}
	engine = ENGINE if text_source == "text_layer" else OCR_ENGINE
	factor = 1.0 if text_source == "text_layer" else OCR_CONFIDENCE_FACTOR
	attempt_no = (frappe.db.count("Document Extraction", {"intake": intake}) or 0) + 1
	extraction = frappe.get_doc(
		{
			"doctype": "Document Extraction",
			"intake": intake,
			"document_profile": profile,
			"attempt_no": attempt_no,
			"status": "succeeded",
			"engine": engine,
			"text_source": text_source,
			"language": result["language"],
			"page_count": len(pages),
			"checks_totals": "Yes" if result["checks"]["totals_consistent"] else (
				"No" if result["checks"]["totals_consistent"] is False else "Not checked"
			),
			"missing_required": ", ".join(result["missing_required"]),
		}
	)
	for field in result["fields"]:
		extraction.append(
			"fields",
			{
				"field_key": field.key,
				"label": field.label,
				"value_type": spec_kind.get(field.key, "text"),
				"value": field.value,
				"state": field.state,
				"confidence": round((field.confidence or 0) * factor * 100, 1)
				if field.confidence is not None
				else None,
				"page_no": field.page_no,
				"source_text": (field.source_text or "")[:500],
				"required": 1 if field.key in required_keys else 0,
				"link_doctype": links.get(field.key, {}).get("doctype"),
				"link_create": 1 if links.get(field.key, {}).get("create") else 0,
				"link_status": "not_found" if field.key in links and field.value else "",
			},
		)
	if has_item_rows(mapping):
		try:
			lines = _read_lines(content, pages, text_source, labels)
		except Exception as exc:
			lines = []
			write_event("stage_fail", intake=intake, stage="extract", message=f"line items not read: {exc}")
		# A misread digit (52,012.50 read as 92,012.50) still satisfies qty × rate. If the
		# item amounts do not add up to the printed net total, read the table again at the
		# other scale and keep the reading that matches the document.
		expected = _expected_items_total(result)
		if text_source != "text_layer" and expected is not None and lines:
			if abs(_lines_total(lines) - expected) > Decimal("0.05"):
				try:
					alternate = _read_lines(content, pages, text_source, labels, text_scale=1)
				except Exception:
					alternate = []
				if alternate and abs(_lines_total(alternate) - expected) < abs(
					_lines_total(lines) - expected
				):
					lines = alternate
		for number, (page_no, row) in enumerate(lines, start=1):
			extraction.append(
				"lines",
				{
					"line_no": number,
					"item_name": normalize_text(row.get("item_name")),
					"qty": row.get("qty") or "",
					"rate": row.get("rate") or "",
					"amount": row.get("amount") or "",
					"page_no": page_no,
					"state": "extracted",
				},
			)
	extraction.insert(ignore_permissions=True)

	for page in pages:
		page_doc = frappe.get_doc(
			{
				"doctype": "Document Page",
				"intake": intake,
				"extraction": extraction.name,
				"page_no": page.page_no,
				"width": page.width,
				"height": page.height,
				"text_layer": page.text,
			}
		)
		page_doc.insert(ignore_permissions=True)
		png = render_preview_png(content, page.page_no)
		file_url = _attach_preview(page_doc.name, png, page.page_no)
		frappe.db.set_value("Document Page", page_doc.name, "preview_file", file_url, update_modified=False)

	found = len([f for f in result["fields"] if f.value])
	return ExtractionOutcome(ok=True, reason="", extraction=extraction.name, field_count=found)
