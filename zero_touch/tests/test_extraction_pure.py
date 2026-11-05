"""Extraction tests that need no Frappe site: text normalization, value parsing, label matching, and
a generated English sales invoice PDF read end-to-end with pdfplumber."""

import unittest

from zero_touch.extraction.parse import (
	FieldSpec,
	Line,
	detect_language,
	extract_sales_invoice,
	find_field,
	normalize_text,
	parse_date,
	parse_money,
)
from zero_touch.extraction.text_layer import read_pdf_text
from zero_touch.tests.pdf_fixture import make_text_pdf

ENGLISH_INVOICE = [
	["Tax Invoice", "Invoice No: INV-2026-0042", "Invoice Date: 28/10/2026", "Due Date: 27/11/2026"],
	["Bill To: Al Noor Trading Co.", "VAT No 300123456700003", "Currency: SAR"],
	["Description Qty Unit Price Amount", "Office chair 10 100.00 1,000.00"],
	["Sub Total 1,000.00", "VAT Amount 150.00", "Grand Total 1,150.00"],
]


class NormalizeTest(unittest.TestCase):
	def test_arabic_indic_digits_and_bidi_marks(self):
		self.assertEqual(normalize_text("رقم الفاتورة: ٧٧٣١\u200f"), "رقم الفاتورة: 7731")

	def test_arabic_decimal_separator(self):
		self.assertEqual(normalize_text("١٬١٥٠٫٥٠"), "1,150.50")

	def test_language_detection(self):
		self.assertEqual(detect_language("Invoice 123"), "en")
		self.assertEqual(detect_language("فاتورة ضريبية"), "ar")
		self.assertEqual(detect_language("فاتورة Invoice"), "mixed")
		self.assertEqual(detect_language("12345"), "unknown")


class ValueParsingTest(unittest.TestCase):
	def test_money_english_format(self):
		self.assertEqual(parse_money("1,150.00"), "1150.00")
		self.assertEqual(parse_money("150"), "150.00")
		self.assertEqual(parse_money("1,15"), "1.15")

	def test_money_european_format(self):
		self.assertEqual(parse_money("1.150,00"), "1150.00")

	def test_money_invalid(self):
		self.assertIsNone(parse_money(""))
		self.assertIsNone(parse_money("abc"))

	def test_date_day_first_and_iso(self):
		self.assertEqual(parse_date("28/10/2026"), ("2026-10-28", False))
		self.assertEqual(parse_date("2026-10-28"), ("2026-10-28", False))

	def test_date_ambiguous_flagged(self):
		self.assertEqual(parse_date("03/04/2026"), ("2026-04-03", True))

	def test_invalid_date(self):
		self.assertEqual(parse_date("31/02/2026"), (None, False))


class SalesInvoiceParsingTest(unittest.TestCase):
	def _fields(self, pages):
		result = extract_sales_invoice(pages)
		return result, {f.key: f for f in result["fields"]}

	def test_english_invoice_text(self):
		result, fields = self._fields([(1, "\n".join(sum(ENGLISH_INVOICE, [])))])
		self.assertEqual(fields["invoice_number"].value, "INV-2026-0042")
		self.assertEqual(fields["invoice_date"].value, "2026-10-28")
		self.assertEqual(fields["due_date"].value, "2026-11-27")
		self.assertEqual(fields["customer_name"].value, "Al Noor Trading Co.")
		self.assertEqual(fields["customer_tax_id"].value, "300123456700003")
		self.assertEqual(fields["subtotal"].value, "1000.00")
		self.assertEqual(fields["tax_amount"].value, "150.00")
		self.assertEqual(fields["grand_total"].value, "1150.00")
		self.assertEqual(fields["currency"].value, "SAR")
		self.assertTrue(result["checks"]["totals_consistent"])
		self.assertEqual(result["missing_required"], [])

	def test_due_date_is_not_taken_as_invoice_date(self):
		_, fields = self._fields([(1, "Due Date: 27/11/2026\nInvoice Date: 28/10/2026")])
		self.assertEqual(fields["invoice_date"].value, "2026-10-28")

	def test_vat_number_line_is_not_taken_as_tax_amount(self):
		_, fields = self._fields([(1, "VAT No 300123456700003\nGrand Total 115.00")])
		self.assertIsNone(fields["tax_amount"].value)
		self.assertEqual(fields["customer_tax_id"].value, "300123456700003")

	def test_arabic_reversed_label_read_from_visual_order(self):
		# Visual order of "رقم الفاتورة: 7731" as pdfplumber returns it for this font.
		visual = "7731 :ةروتافلا مقر"
		_, fields = self._fields([(1, visual)])
		self.assertEqual(fields["invoice_number"].value, "7731")
		self.assertEqual(fields["invoice_number"].confidence, 0.6)

	def test_arabic_logical_order_labels(self):
		text = "رقم الفاتورة: INV-88\nالإجمالي: 1,150.00"
		_, fields = self._fields([(1, text)])
		self.assertEqual(fields["invoice_number"].value, "INV-88")
		self.assertEqual(fields["grand_total"].value, "1150.00")

	def test_missing_required_reported(self):
		result, _ = self._fields([(1, "Nothing useful here")])
		self.assertIn("invoice_number", result["missing_required"])
		self.assertIn("grand_total", result["missing_required"])

	def test_wrong_totals_flagged(self):
		result, _ = self._fields([(1, "Sub Total 1,000.00\nVAT Amount 150.00\nGrand Total 1,100.00")])
		self.assertFalse(result["checks"]["totals_consistent"])

	def test_text_value_before_two_labels_is_the_segment_next_to_it(self):
		# An Item print puts two fields on one OCR line: "Is Bundle: v <item name> Item Name:".
		# The value next to Item Name is the item name, not the first label on the line.
		spec = FieldSpec("item_name", "Item Name", "text", ("Item Name",), (), required=False)
		result = find_field(
			[Line(1, "Is Bundle: v شرايح موبايلي 10 ميغا تتبع Item Name:")], spec
		)
		self.assertEqual(result.value, "شرايح موبايلي 10 ميغا تتبع")

	def test_mapped_label_with_percentage_matches_bare_label(self):
		# "الضريبة 15%" is on the mapping, but OCR prints the tax row without the rate.
		spec = FieldSpec(
			"total_taxes_and_charges", "VAT", "money", (), ("الضريبة 15%",), required=True
		)
		result = find_field([Line(1, "429.75 © -Seventy Five Halala only 9/15 الضريبة")], spec)
		self.assertEqual(result.value, "429.75")


class GeneratedPdfTest(unittest.TestCase):
	def test_read_and_extract_generated_invoice(self):
		content = make_text_pdf(ENGLISH_INVOICE)
		pages = read_pdf_text(content, max_pages=50)
		self.assertEqual(len(pages), len(ENGLISH_INVOICE))
		result = extract_sales_invoice([(p.page_no, p.text) for p in pages])
		fields = {f.key: f.value for f in result["fields"]}
		self.assertEqual(fields["invoice_number"], "INV-2026-0042")
		self.assertEqual(fields["grand_total"], "1150.00")
		self.assertEqual(fields["currency"], "SAR")

	def test_page_limit_enforced(self):
		from zero_touch.extraction.text_layer import PdfReadError

		content = make_text_pdf([["a"], ["b"], ["c"]])
		with self.assertRaises(PdfReadError):
			read_pdf_text(content, max_pages=2)

	def test_damaged_pdf_rejected(self):
		from zero_touch.extraction.text_layer import PdfReadError

		with self.assertRaises(PdfReadError):
			read_pdf_text(b"%PDF-1.4\ngarbage", max_pages=5)


if __name__ == "__main__":
	unittest.main()
