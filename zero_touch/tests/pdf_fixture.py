"""Builds a small digital PDF with Helvetica text (Latin-1 only). Used by tests; no Frappe imports."""


def _escape(text: str) -> str:
	return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_text_pdf(pages: list[list[str]]) -> bytes:
	objects: list[bytes] = []
	page_ids = [4 + i * 2 for i in range(len(pages))]
	objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
	kids = " ".join(f"{pid} 0 R" for pid in page_ids)
	objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
	objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

	for index, lines in enumerate(pages):
		content_id = 5 + index * 2
		body = ["BT /F1 11 Tf 40 780 Td 14 TL"]
		for line in lines:
			body.append(f"({_escape(line)}) Tj T*")
		body.append("ET")
		stream = "\n".join(body).encode("latin-1")
		page = (
			f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
			f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
		).encode()
		objects.append(page)
		objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")

	out = bytearray(b"%PDF-1.4\n")
	offsets = []
	for number, body in enumerate(objects, start=1):
		offsets.append(len(out))
		out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
	xref_at = len(out)
	out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
	for offset in offsets:
		out += f"{offset:010d} 00000 n \n".encode()
	out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
	return bytes(out)
