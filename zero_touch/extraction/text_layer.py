"""Reads the text layer and renders previews of digital PDFs with pdfplumber (MIT, pdfium renderer)."""

import io
from dataclasses import dataclass


class PdfReadError(Exception):
	pass


@dataclass(frozen=True)
class PageText:
	page_no: int
	width: float
	height: float
	text: str


def read_pdf_text(content: bytes, max_pages: int) -> list[PageText]:
	import pdfplumber

	try:
		with pdfplumber.open(io.BytesIO(content)) as pdf:
			if len(pdf.pages) > max_pages:
				raise PdfReadError(f"The document has {len(pdf.pages)} pages. The limit is {max_pages}.")
			pages = []
			for index, page in enumerate(pdf.pages, start=1):
				pages.append(
					PageText(
						page_no=index,
						width=float(page.width),
						height=float(page.height),
						text=page.extract_text() or "",
					)
				)
			return pages
	except PdfReadError:
		raise
	except Exception as exc:
		raise PdfReadError("The PDF could not be read. It may be encrypted or damaged.") from exc


def render_preview_png(content: bytes, page_no: int, resolution: int = 110) -> bytes:
	import pdfplumber

	with pdfplumber.open(io.BytesIO(content)) as pdf:
		image = pdf.pages[page_no - 1].to_image(resolution=resolution).original
		buffer = io.BytesIO()
		image.save(buffer, format="PNG")
		return buffer.getvalue()
