"""Pure tests for grid table detection (no Frappe, no OCR)."""

from zero_touch.extraction.grid import grid_tables


def _table(top=100.0, left=50.0, right=400.0, header=20.0, rows=(20.0, 20.0)):
	"""Builds the thin border rectangles of a table with the given row heights."""
	boxes = []
	ys = [top]
	for height in (header, *rows):
		ys.append(ys[-1] + height)
	columns = [left + (right - left) * index / 4 for index in range(5)]
	for index in range(len(columns) - 1):
		boxes.append((columns[index], ys[0], columns[index + 1], ys[0] + 0.6))
		boxes.append((columns[index], ys[-1] - 0.6, columns[index + 1], ys[-1]))
	for y in ys[1:-1]:
		for index in range(len(columns) - 1):
			boxes.append((columns[index], y, columns[index + 1], y + 0.6))
	for x in columns:
		for lower, upper in zip(ys, ys[1:]):
			boxes.append((x, lower, x + 0.6, upper))
	return boxes


def test_finds_a_table_and_its_cell_boundaries():
	tables = grid_tables(_table())
	assert len(tables) == 1
	assert len(tables[0]["xs"]) == 5
	assert len(tables[0]["ys"]) == 4


def test_merges_consecutive_row_bands_into_one_table():
	tables = grid_tables(_table(rows=(20.0, 20.0, 20.0)))
	assert len(tables) == 1
	assert len(tables[0]["ys"]) == 5


def test_ignores_drawings_without_enough_columns():
	assert grid_tables([(10, 10, 300, 10.5), (10, 10, 10.5, 100), (300, 10, 300.5, 100)]) == []


def test_two_tables_stay_separate():
	boxes = _table(top=100.0) + _table(top=300.0)
	tables = grid_tables(boxes)
	assert len(tables) == 2
	assert tables[0]["ys"][0] < tables[1]["ys"][0]
