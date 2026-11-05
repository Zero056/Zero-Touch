"""Pure tests for cell-level table reading decisions (no OCR)."""

import unittest

from zero_touch.extraction.cells import is_item_table

LABELS = {
	"item_name": ["Service Type", "نوع الخدمة"],
	"qty": ["Quantity", "العدد"],
	"rate": ["Price", "السعر"],
	"amount": ["Taxable Amount"],
}


class CellTest(unittest.TestCase):
	def test_item_header_is_recognised(self):
		header = ["/ نوع الخدمة\nService Type", "/ العدد\nQuantity", "/ السعر\nPrice"]
		self.assertTrue(is_item_table(header, LABELS))

	def test_totals_block_is_not_an_item_table(self):
		header = ["المجموع / Total: 2,865.00", "الخصم / Invoice Discount: 0.00"]
		self.assertFalse(is_item_table(header, LABELS))

	def test_empty_labels_never_match(self):
		self.assertFalse(is_item_table(["Service Type", "Quantity", "Price"], {}))


if __name__ == "__main__":
	unittest.main()
