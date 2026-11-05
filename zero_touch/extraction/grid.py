"""Finds table grids drawn with vector lines (rectangles), so each cell can be read on its own.

Invoices are often exported with no text layer but with the table borders drawn as vector
rectangles. The cell borders give exact row and column positions, which is far more reliable
than grouping words by their guessed table structure.
"""

from collections.abc import Iterable

# Borders are often drawn as filled strips about 1.6pt thick, so the "thin" limit must
# allow them while still rejecting solid blocks of content.
THIN = 2.0
MIN_SEGMENT = 6.0
Y_TOLERANCE = 1.2
X_TOLERANCE = 2.0
MIN_COLUMNS = 3


def _cluster(values: Iterable[float], tolerance: float) -> list[float]:
	groups: list[list[float]] = []
	for value in sorted(values):
		if groups and value - groups[-1][-1] <= tolerance:
			groups[-1].append(value)
		else:
			groups.append([value])
	return [sum(group) / len(group) for group in groups]


def _edges(boxes: Iterable[tuple[float, float, float, float]]) -> tuple[list, list]:
	"""Splits thin boxes into horizontal and vertical border segments."""
	horizontal = []
	vertical = []
	for x0, top, x1, bottom in boxes:
		width = x1 - x0
		height = bottom - top
		if height <= THIN and width >= MIN_SEGMENT:
			horizontal.append((top, x0, x1))
		elif width <= THIN and height >= MIN_SEGMENT:
			vertical.append((x0, top, bottom))
	return horizontal, vertical


def _runs(mask) -> list[tuple[int, int]]:
	"""Start/end of every run of True values in a 1-D boolean array."""
	import numpy as np

	index = np.flatnonzero(mask)
	if not len(index):
		return []
	breaks = np.where(np.diff(index) > 1)[0]
	starts = np.r_[index[0], index[breaks + 1]]
	ends = np.r_[index[breaks], index[-1]]
	return list(zip(starts.tolist(), ends.tolist()))


def raster_boxes(image, scale: float, min_horizontal_ratio: float = 0.35, min_vertical: int = 40):
	"""Finds table borders in a page image (photos and scans have no vector lines).

	Only long horizontal runs (most of the table width) and tall vertical runs are kept,
	so ordinary text strokes are not mistaken for table borders.
	"""
	import numpy as np

	dark = np.asarray(image.convert("L")) < 160
	_height, width = dark.shape
	min_horizontal = int(width * min_horizontal_ratio)
	boxes: list[tuple[float, float, float, float]] = []
	for y in np.flatnonzero(dark.sum(axis=1) > min_horizontal):
		for x0, x1 in _runs(dark[y]):
			if x1 - x0 >= min_horizontal:
				boxes.append((x0 / scale, y / scale, (x1 + 1) / scale, (y + 1) / scale))
	for x in np.flatnonzero(dark.sum(axis=0) > min_vertical):
		for y0, y1 in _runs(dark[:, x]):
			if y1 - y0 >= min_vertical:
				boxes.append((x / scale, y0 / scale, (x + 1) / scale, (y1 + 1) / scale))
	return boxes


def grid_tables(boxes: Iterable[tuple[float, float, float, float]]) -> list[dict]:
	"""Returns the line-drawn tables as {'xs': [...], 'ys': [...]} with sorted cell boundaries.

	Consecutive row bands that share the same column positions are merged into one table.
	Tables without at least three columns are ignored.
	"""
	horizontal, vertical = _edges(boxes)
	if len(vertical) < MIN_COLUMNS:
		return []
	rows = _cluster((h[0] for h in horizontal), Y_TOLERANCE)

	bands: list[dict] = []
	for top, bottom in zip(rows, rows[1:]):
		if bottom - top < 4:
			continue
		# A border is often drawn as one short strip per cell, so it does not span the whole
		# row band. Any vertical strip inside the band marks a column boundary.
		spanning = [v for v in vertical if v[2] > top + Y_TOLERANCE and v[1] < bottom - Y_TOLERANCE]
		if len(spanning) < MIN_COLUMNS:
			continue
		xs = _cluster((v[0] for v in spanning), X_TOLERANCE)
		if len(xs) < MIN_COLUMNS:
			continue
		last = bands[-1] if bands else None
		if (
			last
			and abs(last["ys"][-1] - top) <= Y_TOLERANCE
			and len(last["xs"]) == len(xs)
			and all(abs(a - b) <= X_TOLERANCE for a, b in zip(last["xs"], xs))
		):
			last["ys"].append(bottom)
		else:
			bands.append({"xs": xs, "ys": [top, bottom]})
	return bands
