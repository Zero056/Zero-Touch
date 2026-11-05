"""Line-item reader tests on word positions taken from sales 2.pdf (page 1, 300 dpi, pixel coordinates)."""

import unittest

from zero_touch.extraction.tables import Word, build_rows, column_bounds, find_header, stop_top

LABELS = {
	"item_name": ["Service Type", "نوع الخدمة"],
	"qty": ["Quantity", "العدد"],
	"rate": ["Price", "السعر"],
	"amount": ["Taxable Amount", "المبلغ الخاضع للضريبة"],
	"_subscription": ["Subscription"],
	"_vat": ["VAT"],
	"_total": ["Total (SAR)", "Total"],
}


def w(x0, y0, x1, y1, text):
	return Word(float(x0), float(y0), float(x1), float(y1), text)


HEADER = [
	w(327, 1917, 422, 1950, "Service"), w(431, 1918, 490, 1943, "Type"),
	w(633, 1913, 796, 1948, "Subscription"),
	w(898, 1913, 1018, 1948, "Quantity"),
	w(1188, 1914, 1261, 1948, "Price"),
	w(1432, 1917, 1529, 1936, "Taxable"), w(1537, 1918, 1639, 1937, "Amount"),
	w(1756, 1893, 1835, 1948, "VAT."),
	w(2005, 1917, 2066, 1936, "Total"),
]
ROW = [
	w(262, 1982, 378, 2031, "Teltonika"), w(390, 1986, 470, 2005, "GPS"), w(453, 1987, 544, 2006, "Tracker"),
	w(262, 2010, 360, 2030, "Basic"), w(365, 2010, 440, 2030, "FMC920"),
	w(950, 2000, 980, 2020, "1"),
	w(1200, 2000, 1300, 2020, "230.00"),
	w(1480, 2000, 1580, 2020, "230.00"),
	w(1760, 2000, 1840, 2020, "34.50"),
	w(1990, 2000, 2090, 2020, "264.50"),
]
FOOTER = [w(1500, 2200, 1700, 2230, "المجموع"), w(1500, 2200, 1700, 2230, "/")]


class TableReaderTest(unittest.TestCase):
	def test_header_anchors_found_for_mapped_and_unmapped_columns(self):
		top, bottom, anchors = find_header(HEADER, LABELS)
		self.assertEqual(set(anchors), {"item_name", "qty", "rate", "amount", "_subscription", "_vat", "_total"})
		self.assertLess(anchors["item_name"], anchors["qty"])
		self.assertLess(anchors["qty"], anchors["rate"])

	def test_row_read_into_mapped_columns(self):
		_, bottom, anchors = find_header(HEADER, LABELS)
		bounds = column_bounds(anchors, page_width=2481)
		rows = build_rows(
			HEADER + ROW,
			bounds,
			numeric_fields={"qty", "rate", "amount"},
			region_top=bottom,
			region_bottom=2180,
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["item_name"], "Teltonika GPS Tracker Basic FMC920")
		self.assertEqual(row["qty"], "1")
		self.assertEqual(row["rate"], "230.00")
		self.assertEqual(row["amount"], "230.00")

	def test_vat_and_total_columns_do_not_leak_into_amount(self):
		_, bottom, anchors = find_header(HEADER, LABELS)
		bounds = column_bounds(anchors, page_width=2481)
		row = build_rows(HEADER + ROW, bounds, {"qty", "rate", "amount"}, bottom, 2180)[0]
		self.assertNotIn("34.50", row["amount"])
		self.assertNotIn("264.50", row["amount"])

	def test_totals_line_is_a_stop(self):
		self.assertEqual(stop_top(ROW + FOOTER, below_y=1950), 2200)

	def test_no_header_means_no_table(self):
		self.assertIsNone(find_header(ROW, LABELS))

	def test_rows_outside_region_are_ignored(self):
		_, bottom, anchors = find_header(HEADER, LABELS)
		bounds = column_bounds(anchors, page_width=2481)
		self.assertEqual(build_rows(HEADER + ROW, bounds, {"qty", "rate", "amount"}, bottom, 1990), [])

	def test_arabic_rtl_header_and_wrapped_label(self):
		# Words as OCR returns them on the page: x ascending, i.e. right-to-left Arabic.
		header = [
			w(2105, 684, 2184, 736, "البند"),
			w(1516, 674, 1635, 744, "البيان"),
			w(1101, 678, 1201, 723, "تكلفة"),
			w(953, 684, 1081, 736, "الوحدة"),
			w(790, 695, 859, 723, "عدد"),
			w(618, 677, 767, 738, "الأجهزة"),
			w(302, 684, 479, 740, "المستحق"),
			w(214, 687, 279, 723, "عند"),
			w(288, 770, 405, 816, "التعاقد"),
		]
		labels = {
			"item_name": ["البند"],
			"qty": ["عدد الأجهزة"],
			"rate": ["تكلفة الوحدة"],
			"amount": ["المستحق عند التعاقد"],
		}
		top, _bottom, anchors = find_header(header, labels)
		self.assertEqual(set(anchors), {"item_name", "qty", "rate", "amount"})
		self.assertLess(anchors["amount"], anchors["qty"])
		self.assertLess(anchors["qty"], anchors["rate"])
		self.assertLess(anchors["rate"], anchors["item_name"])


if __name__ == "__main__":
	unittest.main()
