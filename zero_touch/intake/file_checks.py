"""Upload checks that run before anything is stored. No Frappe imports."""

import hashlib
import io
import os
import re
import zipfile
from dataclasses import dataclass

MAX_ARCHIVE_MEMBERS = 1000
MAX_ARCHIVE_UNCOMPRESSED = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 50
RATIO_CHECK_MIN_BYTES = 1024 * 1024
TEXT_SNIFF_BYTES = 64 * 1024

OOXML_REQUIRED_MEMBER = {
	"docx": "word/document.xml",
	"xlsx": "xl/workbook.xml",
}
MACRO_MARKERS = ("vbaproject.bin",)
NESTED_ARCHIVE_SUFFIXES = (".zip", ".docx", ".xlsx", ".xlsm", ".docm", ".jar", ".rar", ".7z")

SUPPORTED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "png", "tif", "tiff", "csv", "xlsx", "docx"})

MIME_BY_KIND = {
	"pdf": "application/pdf",
	"jpeg": "image/jpeg",
	"png": "image/png",
	"tiff": "image/tiff",
	"csv": "text/csv",
	"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
	"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class UploadCheck:
	ok: bool
	reason: str | None
	extension: str
	kind: str | None
	size: int
	sha256: str


def sanitize_filename(name: str, max_length: int = 140) -> str:
	base = os.path.basename((name or "").replace("\\", "/")).strip()
	base = re.sub(r"[\x00-\x1f\x7f]", "", base)
	base = re.sub(r"[^\w.\- ()\u0600-\u06FF]", "_", base)
	if not base or base in (".", ".."):
		return "document"
	if len(base) > max_length:
		stem, dot, ext = base.rpartition(".")
		ext = ext[:10] if dot else ""
		keep = max_length - (len(ext) + 1 if ext else 0)
		base = stem[:keep] + (("." + ext) if ext else "")
	return base


def extension_of(name: str) -> str:
	_, dot, ext = (name or "").rpartition(".")
	return ext.lower() if dot else ""


def _signature_kind(extension: str, content: bytes) -> str | None:
	head = content[:1024]
	if extension == "pdf":
		return "pdf" if b"%PDF-" in head else None
	if extension in ("jpg", "jpeg"):
		return "jpeg" if content[:3] == b"\xff\xd8\xff" else None
	if extension == "png":
		return "png" if content[:8] == b"\x89PNG\r\n\x1a\n" else None
	if extension in ("tif", "tiff"):
		return "tiff" if content[:4] in (b"II*\x00", b"MM\x00*") else None
	if extension in ("docx", "xlsx"):
		return extension if content[:4] == b"PK\x03\x04" else None
	if extension == "csv":
		return "csv" if b"\x00" not in content[:TEXT_SNIFF_BYTES] else None
	return None


def _check_archive(extension: str, content: bytes) -> str | None:
	try:
		archive = zipfile.ZipFile(io.BytesIO(content))
	except zipfile.BadZipFile:
		return "ARCHIVE_INVALID"
	with archive:
		infos = archive.infolist()
		if len(infos) > MAX_ARCHIVE_MEMBERS:
			return "ARCHIVE_TOO_MANY_MEMBERS"
		names = [info.filename.replace("\\", "/") for info in infos]
		for name in names:
			if name.startswith("/") or ".." in name.split("/"):
				return "ARCHIVE_INVALID"
		lowered = [n.lower() for n in names]
		if any(n.endswith(NESTED_ARCHIVE_SUFFIXES) for n in lowered):
			return "ARCHIVE_NESTED"
		if any(n.endswith(MACRO_MARKERS) for n in lowered):
			return "ARCHIVE_MACRO"
		if "[content_types].xml" not in lowered or OOXML_REQUIRED_MEMBER[extension] not in lowered:
			return "SIGNATURE_MISMATCH"
		uncompressed = sum(info.file_size for info in infos)
		compressed = sum(info.compress_size for info in infos)
		if uncompressed > MAX_ARCHIVE_UNCOMPRESSED:
			return "ARCHIVE_TOO_LARGE"
		if uncompressed > RATIO_CHECK_MIN_BYTES and uncompressed > MAX_COMPRESSION_RATIO * max(compressed, 1):
			return "ARCHIVE_TOO_LARGE"
	return None


def check_upload(
	filename: str,
	content: bytes,
	allowed_extensions: list[str] | tuple[str, ...],
	max_bytes: int,
) -> UploadCheck:
	extension = extension_of(filename)
	size = len(content or b"")
	sha256 = hashlib.sha256(content or b"").hexdigest()

	def fail(reason: str, kind: str | None = None) -> UploadCheck:
		return UploadCheck(False, reason, extension, kind, size, sha256)

	if size == 0:
		return fail("EMPTY_FILE")
	if extension not in {e.lower() for e in allowed_extensions}:
		return fail("EXTENSION_NOT_ALLOWED")
	if size > max_bytes:
		return fail("FILE_TOO_LARGE")

	kind = _signature_kind(extension, content)
	if kind is None:
		return fail("SIGNATURE_MISMATCH")

	if extension in OOXML_REQUIRED_MEMBER:
		archive_problem = _check_archive(extension, content)
		if archive_problem:
			return fail(archive_problem, kind)

	return UploadCheck(True, None, extension, kind, size, sha256)
