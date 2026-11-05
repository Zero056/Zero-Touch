"""Line-item table detection and column aliases. No Frappe site needed."""

import unittest

from zero_touch.mapping.line_fields import (
	AMOUNT_FIELDS,
	NAME_FIELDS,
	QTY_FIELDS,
	RATE_FIELDS,
	canonical,
	field_for,
	is_line_item,
)


class LineFieldsTest(unittest.TestCase):
	def test_standard_names(self):
		self.assertTrue(is_line_item({"item_name", "qty", "rate", "amount"}))
		self.assertEqual(canonical("qty"), "qty")
		self.assertEqual(canonical("rate"), "rate")

	def test_custom_child_table_aliases(self):
		names = {"description", "quantity", "unit_price", "line_total"}
		self.assertTrue(is_line_item(names))
		self.assertEqual(canonical("quantity"), "qty")
		self.assertEqual(canonical("unit_price"), "rate")
		self.assertEqual(canonical("line_total"), "amount")
		self.assertEqual(canonical("description"), "item_name")
		self.assertEqual(field_for(names, NAME_FIELDS), "description")
		self.assertEqual(field_for(names, QTY_FIELDS), "quantity")
		self.assertEqual(field_for(names, RATE_FIELDS), "unit_price")
		self.assertEqual(field_for(names, AMOUNT_FIELDS), "line_total")

	def test_not_a_line_table_without_a_quantity(self):
		self.assertFalse(is_line_item({"description", "price"}))
		self.assertFalse(is_line_item({"qty", "note"}))

	def test_rate_or_amount_is_enough(self):
		self.assertTrue(is_line_item({"qty", "amount"}))
		self.assertTrue(is_line_item({"quantity", "price"}))
