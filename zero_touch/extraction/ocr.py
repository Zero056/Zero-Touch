"""OCR with the Tesseract command-line tool. Arguments are passed as a list; no shell is used."""

import io
import os
import shutil
import subprocess
import tempfile

OCR_LANGUAGES = "eng+ara"
OCR_TIMEOUT_SECONDS = 120


class OcrError(Exception):
	pass


def tesseract_available() -> bool:
	return shutil.which("tesseract") is not None


def render_page_for_ocr(content: bytes, page_no: int, resolution: int = 200) -> bytes:
	import pdfplumber

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		image = pdf.pages[page_no - 1].to_image(resolution=resolution).original.convert("L")
		buffer = io.BytesIO()
		image.save(buffer, format="PNG")
		return buffer.getvalue()


def recognize_png(png: bytes, languages: str = OCR_LANGUAGES) -> str:
	with tempfile.TemporaryDirectory() as folder:
		path = os.path.join(folder, "page.png")
		with open(path, "wb") as handle:
			handle.write(png)
		try:
			completed = subprocess.run(
				["tesseract", path, "stdout", "-l", languages, "--psm", "6"],
				capture_output=True,
				text=True,
				timeout=OCR_TIMEOUT_SECONDS,
				check=False,
			)
		except subprocess.TimeoutExpired as exc:
			raise OcrError("OCR timed out") from exc
	if completed.returncode != 0:
		raise OcrError("OCR failed on this page")
	return completed.stdout


def render_page_image(content: bytes, page_no: int, resolution: int = 300):
	import pdfplumber

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		return pdf.pages[page_no - 1].to_image(resolution=resolution).original.convert("L")


def tsv_words(png: bytes, languages: str = OCR_LANGUAGES, psm: str = "6") -> list[tuple[float, float, float, float, str]]:
	"""Word boxes in image pixels, from Tesseract's TSV output."""
	from zero_touch.extraction.tables import Word  # noqa: F401  (kept for type parity)

	with tempfile.TemporaryDirectory() as folder:
		path = os.path.join(folder, "page.png")
		with open(path, "wb") as handle:
			handle.write(png)
		try:
			completed = subprocess.run(
				["tesseract", path, "stdout", "-l", languages, "--psm", psm, "tsv"],
				capture_output=True,
				text=True,
				timeout=OCR_TIMEOUT_SECONDS,
				check=False,
			)
		except subprocess.TimeoutExpired as exc:
			raise OcrError("OCR timed out") from exc
	if completed.returncode != 0:
		raise OcrError("OCR failed on this page")

	words = []
	for line in completed.stdout.splitlines()[1:]:
		parts = line.split("\t")
		if len(parts) != 12 or not parts[11].strip():
			continue
		left, top, width, height = (float(parts[i]) for i in (6, 7, 8, 9))
		words.append((left, top, left + width, top + height, parts[11]))
	return words
