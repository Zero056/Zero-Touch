# 11. Document Scanner: Current Implementation

## Scope

The Document Scanner is a standalone Desk utility for extracting text from image/PDF files and audio. It creates a **Document Scan** record and private File; it does not use the financial Document Intake pipeline and does not create ERPNext transactions.

## User flow

1. Choose **Image or PDF** or **Audio file or recording** before upload.
2. For audio, choose the spoken language (required) and either choose an audio file or record through the browser microphone.
3. Upload and wait for extraction/transcription. The Desk page shows the private original beside editable source text.
4. Choose a translation target and translate. The translation appears below the source and is kept in a separate field.
5. The record stores the source file, filename, source type, uploader, extracted text, audio language, translation target, and translation.

Supported document extensions: PDF, PNG, JPG/JPEG, TIF/TIFF, BMP, WEBP. Supported audio extensions: MP3, WAV, M4A, MP4, MPEG/MPGA, WEBM, OGG/OGA, FLAC, AAC, WMA. The scanner checks extension and configured file-size limit. PDF extraction enforces `Zero Touch Settings.max_pages` (default 50).

## Components

| Component | Location | Behavior |
|-----------|----------|----------|
| Desk page | `zero_touch/zero_touch/page/zt_document_scanner/` | Input type, upload, browser recording, preview, editable text, copy and translation controls |
| Scanner endpoints | `zero_touch/api/scan.py` | `audio_languages`, `translation_languages`, `upload_scan`, and `translate` |
| Record | `zero_touch/zero_touch/doctype/document_scan/` | Private file metadata, owner, source and translation text |
| PDF text | `zero_touch/extraction/text_layer.py` | Read existing PDF text layer |
| OCR | `zero_touch/extraction/ocr.py` | Tesseract CLI using `eng+ara` |
| Audio | `faster-whisper` small model | CPU `int8` transcription, with caller-selected language and VAD |
| Translation | `argostranslate` model packages | Local translation, direct or through English |

### Language lists

Audio languages are enabled entries in Frappe's **Language** DocType, filtered to language codes supported by `faster_whisper.tokenizer._LANGUAGE_CODES`. Locale variants such as `en-US` map to Whisper's base code `en`; the base Language entry is preferred for its label. Labels use the DocType's `language_name` and may appear in the language's own script. Translation choices also start from enabled Language DocType entries and are filtered to targets in the available Argos package index. A language absent from either the DocType or the installed model's supported languages cannot be selected.

Translation languages are built from Argos Translate's available package index. The list includes English and Arabic and targets with an English source package. The Arabic source is translated directly to English, then through English to other selected targets. Argos packages are downloaded on first use and installed into the bench user's Argos data directory.

## Dependencies and installation

- `pdfplumber` is installed from `pyproject.toml` for PDF text and rendering.
- `tesseract-ocr`, `tesseract-ocr-eng`, and `tesseract-ocr-ara` are OS packages installed separately.
- `argostranslate` uses CPU PyTorch pinned by `constraints-translation.txt`; the CPU PyTorch index and constraint must be set while installing the app.
- `faster-whisper` and its Python dependencies are installed from `pyproject.toml`.
- The Whisper `small` model is approximately 460 MB and cached by Hugging Face under the bench service user's home directory.
- Arabic↔English Argos model packages are roughly 100 MB each on average. Other packages are downloaded when needed.

Follow [INSTALL.md](../INSTALL.md), including the model warm-up steps. Install and warm models as the Linux user running the Frappe web and worker processes so they can read the same caches.

## Runtime and boundaries

- OCR, transcription, language model downloads, and translation currently execute synchronously within a Desk API request. Long recordings or higher concurrency should be moved to background jobs with bounded workers and request-size/time limits.
- Browser microphone capture uses `getUserMedia` and `MediaRecorder`; the browser needs microphone permission and HTTPS or localhost.
- The source File is private and attached to Document Scan. API methods are rate limited; scans are owner-scoped for uploaders.
- The user-selected audio language is validated against Whisper's supported codes before transcription.
- The selected target language is validated by the available translation model. A translation model failure does not overwrite the source text.
- Audio transcription quality depends on microphone, accent, background noise, and model language support. Users can edit the transcript before translating.
- Models and the Argos package index need outbound internet on first download. After caches are populated, inference is local and source audio/text is not submitted to a hosted AI endpoint.
