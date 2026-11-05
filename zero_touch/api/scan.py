import os

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from zero_touch.extraction.ocr import OcrError, recognize_png, render_page_for_ocr, tesseract_available
from zero_touch.extraction.service import image_to_pdf
from zero_touch.extraction.text_layer import PdfReadError, read_pdf_text

MB = 1024 * 1024
SUPPORTED = {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
AUDIO_SUPPORTED = {"mp3", "wav", "m4a", "mp4", "mpeg", "mpga", "webm", "ogg", "oga", "flac", "aac", "wma"}
_WHISPER_MODEL = None


def _extract(content: bytes, extension: str, max_pages: int) -> str:
	if extension != "pdf":
		content = image_to_pdf(content)
	pages = read_pdf_text(content, max_pages=max_pages)
	if not tesseract_available() and any(not page.text.strip() for page in pages):
		frappe.throw(_("Tesseract OCR is not installed on the server."))
	parts = []
	for page in pages:
		text = page.text.strip()
		if not text:
			text = recognize_png(render_page_for_ocr(content, page.page_no)).strip()
		if text:
			parts.append(text)
	if not parts:
		frappe.throw(_("No readable text was found. Try a clearer scan."))
	return "\n\n".join(parts)


def _patch_av_open():
	"""faster-whisper 1.2 calls av.open(metadata_errors=...), which older PyAV rejects.

	The option only controls how damaged metadata is handled; dropping it keeps the audio
	decoding and avoids a TypeError before transcription starts.
	"""
	import av

	if getattr(av.open, "_zt_metadata_compat", False):
		return
	original = av.open

	def open_compat(*args, **kwargs):
		kwargs.pop("metadata_errors", None)
		return original(*args, **kwargs)

	open_compat._zt_metadata_compat = True
	av.open = open_compat


def _transcribe(content: bytes, extension: str, language: str) -> str:
	global _WHISPER_MODEL
	import tempfile

	_patch_av_open()
	from faster_whisper import WhisperModel
	from faster_whisper.tokenizer import _LANGUAGE_CODES

	if language not in _LANGUAGE_CODES:
		frappe.throw(_("Choose a supported audio language."))
	if _WHISPER_MODEL is None:
		_WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
	with tempfile.NamedTemporaryFile(suffix=f".{extension}") as audio_file:
		audio_file.write(content)
		audio_file.flush()
		segments, _info = _WHISPER_MODEL.transcribe(audio_file.name, language=language, beam_size=5, vad_filter=True)
		text = " ".join(segment.text.strip() for segment in segments).strip()
	if not text:
		frappe.throw(_("No speech was recognized. Try a clearer recording."))
	return text


@frappe.whitelist()
def audio_languages():
	from faster_whisper.tokenizer import _LANGUAGE_CODES

	supported = set(_LANGUAGE_CODES)
	rows = frappe.get_all(
		"Language", filters={"enabled": 1}, fields=["language_code", "language_name"], order_by="language_name asc"
	)
	choices = {}
	for row in rows:
		code = (row.language_code or "").split("-", 1)[0].lower()
		if code not in supported:
			continue
		# Prefer the base language record (e.g. en) to locale variants (e.g. en-US).
		if code not in choices or row.language_code.lower() == code:
			choices[code] = row.language_name
	return [{"code": code, "label": label} for code, label in sorted(choices.items(), key=lambda item: item[1].casefold())]


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=20, seconds=3600)
def upload_scan(mode: str = "document", language: str | None = None):
	upload = frappe.request.files.get("file") if frappe.request else None
	if not upload:
		frappe.throw(_("Choose a file to upload."))
	filename = os.path.basename(upload.filename or "scan")
	extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
	if mode not in {"document", "audio"}:
		frappe.throw(_("Choose a valid upload type."))
	if mode == "document" and extension not in SUPPORTED:
		frappe.throw(_("Supported document types: PDF, PNG, JPG, TIFF, BMP, and WEBP."))
	if mode == "audio" and extension not in AUDIO_SUPPORTED:
		frappe.throw(_("Supported audio types: MP3, WAV, M4A, MP4, WEBM, OGG, FLAC, AAC, and WMA."))
	if mode == "audio" and not language:
		frappe.throw(_("Select the language spoken in the audio before uploading."))
	settings = frappe.get_single("Zero Touch Settings")
	content = upload.stream.read(int(settings.max_file_size_mb or 20) * MB + 1)
	if len(content) > int(settings.max_file_size_mb or 20) * MB:
		frappe.throw(_("The file exceeds the configured size limit."))
	try:
		text = (
			_transcribe(content, extension, language)
			if mode == "audio"
			else _extract(content, extension, int(settings.get("max_pages") or 50))
		)
	except PdfReadError as exc:
		frappe.throw(_(str(exc)))
	except OcrError as exc:
		frappe.throw(_("OCR failed: {0}").format(str(exc)))
	file_doc = frappe.get_doc({"doctype":"File", "file_name":filename, "content":content,
		"is_private":1}).insert(ignore_permissions=True)
	doc = frappe.get_doc({"doctype":"Document Scan", "original_filename":filename,
		"original_file":file_doc.file_url, "uploaded_by":frappe.session.user,
		"source_type":"Audio" if mode == "audio" else "Document",
		"audio_language":language if mode == "audio" else None, "extracted_text":text}).insert()
	frappe.db.set_value("File", file_doc.name, {
		"attached_to_doctype": "Document Scan", "attached_to_name": doc.name
	})
	return {"name":doc.name, "file_url":doc.original_file, "filename":filename,
		"text":text, "source_type":doc.source_type, "audio_language":doc.audio_language}


def _download_translation_pair(from_code: str, to_code: str) -> None:
	import argostranslate.package
	import argostranslate.translate

	installed = argostranslate.translate.get_installed_languages()
	from_lang = next((lang for lang in installed if lang.code == from_code), None)
	if from_lang and any(translation.to_lang.code == to_code for translation in from_lang.translations_from):
		return
	available = argostranslate.package.get_available_packages()
	pkg = next((p for p in available if p.from_code == from_code and p.to_code == to_code), None)
	if not pkg:
		frappe.throw(_("Offline translation model {0} → {1} is not available.").format(from_code, to_code))
	path = pkg.download()
	argostranslate.package.install_from_path(path)


@frappe.whitelist()
def translation_languages():
	import argostranslate.package

	packages = argostranslate.package.get_available_packages()
	model_languages = {"en": "English", "ar": "Arabic"}
	for package in packages:
		# The scanner detects Arabic and English. Every selectable target must have a
		# direct model from English so either detected source can pivot through English.
		if package.from_code == "en":
			model_languages[package.to_code] = package.to_name
	rows = frappe.get_all("Language", filters={"enabled": 1}, fields=["language_code", "language_name"])
	frappe_languages = {row.language_code.lower(): row.language_name for row in rows}
	choices = [
		{"code": code, "label": frappe_languages[code]}
		for code in model_languages
		if code in frappe_languages
	]
	return sorted(choices, key=lambda item: item["label"].casefold())


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=3600)
def translate(scan: str, language: str, edited_text: str | None = None):
	doc = frappe.get_doc("Document Scan", scan)
	doc.check_permission("read")
	if doc.uploaded_by != frappe.session.user and not frappe.has_permission("Document Scan", "write"):
		frappe.throw(_("You cannot edit this scan."), frappe.PermissionError)
	if not language.strip() or len(language) > 5:
		frappe.throw(_("Choose a valid target language."))
	text = edited_text if edited_text is not None else doc.extracted_text
	if not text or len(text) > 200_000:
		frappe.throw(_("Text is empty or too long to translate (maximum 200,000 characters)."))
	from_code = "ar" if sum("\u0600" <= char <= "\u06ff" for char in text) > sum(char.isalpha() for char in text) / 3 else "en"
	to_code = language.strip().lower()
	if from_code != to_code:
		try:
			if to_code == "en":
				_download_translation_pair(from_code, to_code)
			elif from_code == "en":
				_download_translation_pair(from_code, to_code)
			else:
				_download_translation_pair(from_code, "en")
				_download_translation_pair("en", to_code)
			import argostranslate.translate
			translated = argostranslate.translate.translate(text, from_code, to_code)
		except frappe.ValidationError:
			raise
		except Exception as exc:
			frappe.log_error(title="Document Scan translation failed", message=frappe.get_traceback())
			frappe.throw(_("Could not download or run the offline translation model: {0}").format(str(exc)))
	else:
		translated = text
	doc.extracted_text = text
	doc.translation_language = language.strip()
	doc.translated_text = translated
	doc.save(ignore_permissions=True)
	return {"text":translated, "language":language.strip()}
