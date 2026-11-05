# Zero Touch

**Turn business documents into reviewed ERPNext drafts — without retyping them.**

Zero Touch is a Frappe/ERPNext v15 app that reads invoices, quotations, item prints, employee forms, and other business documents (Arabic or English), lets a reviewer correct what was read, and creates a **draft** record in the DocType you choose.

Nothing is posted automatically. The app never submits a document; a person always reviews and creates the draft.

---

## What it does

- **Reads PDFs, scans, photos, and audio** — text-layer PDFs, scanned/vector PDFs, JPG/PNG/TIFF/BMP/WEBP images, and audio recordings.
- **Arabic and English** — label matching handles right-to-left Arabic headers, Alef/Ta Marbuta spelling differences, and mixed-language forms.
- **Mapping-driven** — a **Document Type** (Document Field Mapping) decides the target DocType and every field read from the document. There is no per-DocType code list.
- **Any normal DocType** — including custom DocTypes. Child tables are discovered from the target's metadata; line-item tables are supported even when their columns are named `quantity`/`unit_price` instead of `qty`/`rate`.
- **Review before creation** — the Review Center shows the source page, the extracted value, confidence, and the exact text it came from. Only Pending Review / Ready to Create documents are editable.
- **Draft only** — records are created with `docstatus = 0` as the user who clicked. Zero Touch never submits them.
- **Local processing by default** — Tesseract OCR, faster-whisper speech-to-text, and Argos Translate run on your server. No document text is sent to a cloud AI service unless you explicitly configure a provider.

---

## How it works

```text
Upload
  │
  ▼
Document Intake ──► Extraction (text layer or OCR)
  │                     │
  │                     ├─ header fields from mapped labels
  │                     ├─ line items from the item table
  │                     └─ link fields matched to ERPNext records
  ▼
Review Center
  │  correct values, pick customers/items, save review
  ▼
Create draft
  │  build payload from the mapping, insert as the clicking user
  ▼
ERPNext document (Draft)
```

The pipeline is asynchronous: an upload is queued, a worker extracts it, and the reviewer is notified through the Document Inbox. A schedule job recovers stalled jobs and retries failures.

---

## Main screens

| Screen | Purpose |
|---|---|
| **Document Inbox** | Upload a document, choose its Document Type, follow its status. |
| **Review Center** | Preview pages, correct extracted fields and item rows, then create the draft. |
| **Processing Monitor** | See queue/status counts and recent documents. |
| **Document Scanner** | OCR an image/PDF, transcribe audio, and translate the text. Saves a **Document Scan**. |
| **Document Types** (`Document Field Mapping`) | Configure the target DocType, company scope, and field mapping. |

---

## Installation

See the full [installation and upgrade guide](docs/INSTALL.md) for production setup, model warm-up, permissions, and troubleshooting.

### Requirements

| Component | Requirement |
|---|---|
| Frappe / ERPNext | v15 |
| Python | 3.10–3.12 (bench virtualenv) |
| Tesseract OCR | 4.1+, with `eng` and `ara` language data |
| MariaDB / Redis | Same as your bench |
| Worker + scheduler | `bench worker` and `bench schedule` must run |
| HTTPS | Required for browser microphone recording |

Python dependencies are declared in `pyproject.toml`: `pdfplumber`, `argostranslate`, and `faster-whisper`.

### Quick install

```bash
# On the server, once:
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara

cd /path/to/frappe-bench

# Use the CPU PyTorch constraint for Argos Translate:
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
  bench get-app zero_touch <git-url> --branch main

bench --site your-site.example install-app zero_touch
bench --site your-site.example migrate
bench build --app zero_touch
bench --site your-site.example clear-cache
```

Then start the background services:

```bash
bench worker          # or: bench worker --queue default
bench schedule
```

> The first audio transcription downloads the Whisper `small` model. The first translation downloads the required Argos language pair. Run the warm-up commands in the [install guide](docs/INSTALL.md#31-download-local-models-before-first-use-recommended) as the bench user.

### Verify

1. Open **Zero Touch → Zero Touch Settings** and enable processing.
2. Upload a document from **Document Inbox** and choose a Document Type.
3. Watch it move from Queued → Processing → Pending Review.
4. Open **Review Center**, correct anything, and click **Create …**.

---

## Configuration

### Zero Touch Settings

- Enable/disable processing.
- Maximum file size and allowed extensions.
- Maximum automatic attempts and retry limits.
- VAT/tax account used when a Quotation or Sales Order needs the tax read from the document.

### Document Types

A **Document Type** is one `Document Field Mapping` record:

| Field | Meaning |
|---|---|
| Label | Name shown in the upload screen, e.g. *Quotation* or *Employee*. |
| Target DocType | Any normal DocType, including a custom one. |
| Company | Optional company scope. Empty means every company. |
| Enabled | Only enabled types appear in the upload picker. |
| Field Mapping rows | The labels to read and the target fields to fill. |

Each row has a **Source**:

- **From document** — the value is read using the English/Arabic label you enter.
- **ERPNext fills automatically** — Zero Touch does not read it; the review page shows what ERPNext will use on creation (for example Item Group or UOM defaults).

The target field list and child-table fields are loaded from the target DocType's metadata, so custom fields and custom child tables appear automatically. Click **Fill Required Fields** to add the target's mandatory fields, then set the labels printed on your document.

### Link fields

Customer, Supplier, Item, Item Group, UOM, Warehouse, and other Link fields are matched against existing ERPNext records using the linked DocType's own name field. Arabic spelling variants (Alef, Ta Marbuta, diacritics, spacing) and near-identical OCR text are handled. Creating missing records from the document is intentionally limited to **Customer** and **Supplier**.

### Line-item tables

A child table is treated as the document's item grid when it has a quantity plus a rate or amount. Common alternative names are supported:

| Document column | Accepted child fields |
|---|---|
| Item name | `item_name`, `description`, `product_name`, `particulars`, `service` |
| Quantity | `qty`, `quantity`, `qty_in` |
| Rate | `rate`, `price`, `unit_price`, `selling_price`, `valuation_rate` |
| Amount | `amount`, `total`, `line_total`, `net_amount` |

Only the first line-item table is added to the default mapping rows; every child table remains selectable in the field dropdown.

---

## Document Scanner

The scanner is separate from the intake/review pipeline and saves a **Document Scan** record.

- **Image or PDF** — OCR with Tesseract, preserving an editable text area.
- **Audio file or recording** — select the spoken language, upload or record, and transcribe locally with faster-whisper.
- **Translate** — translate the edited text locally with Argos Translate.

Microphone recording requires HTTPS (or localhost) and browser microphone permission.

---

## Roles

| Role | Can |
|---|---|
| Zero Touch Uploader | Upload documents; sees their own uploads. |
| Zero Touch Reviewer | Review and save values for companies they can access. |
| Zero Touch Manager | Configure mappings, reprocess documents. |
| Zero Touch Admin | Configure settings and providers. |
| Zero Touch Creator / Approver | Reserved for later approval flows. |

Access is further limited by **Company** User Permissions. A user with no company permission sees no documents, by design.

---

## Project structure

```text
zero_touch/
├─ api/                 Whitelisted endpoints (upload, extraction, creation, mapping, scan, monitor)
├─ audit/               Event logging and redaction
├─ creation/            Payload builder and draft creation
├─ extraction/          Text layer, OCR, tables, line items, links, totals
├─ intake/              Upload validation and intake creation
├─ mapping/             Field compatibility, transforms, line-field aliases
├─ patches/             Installation and data migrations
├─ pipeline/            State machine, jobs, retries
├─ providers/           Extraction provider abstraction
├─ security/            Permission queries and endpoint policy
├─ tests/               Pure and site-level tests
├─ public/js/           Document Intake form/list scripts
└─ zero_touch/
   ├─ doctype/          DocTypes (Intake, Extraction, Mapping, Scan, …)
   ├─ page/             Review Center, Processing Monitor, Document Scanner
   └─ workspace/        Zero Touch workspace
```

---

## Development

```bash
cd apps/zero_touch

# Formatting/linting
pre-commit install

# Pure tests (no site required)
../../env/bin/python -m unittest discover -s zero_touch/tests -p 'test_*pure*.py'

# Site tests on a test site
bench --site test-site.example run-tests --app zero_touch
```

After changing Python code, restart the worker so it loads the new code. After changing JavaScript, run:

```bash
bench build --app zero_touch
bench --site your-site.example clear-cache
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Document stays **Queued** | Start `bench worker`. |
| Scanned document has no text | Install Tesseract with `eng` and `ara`, then click **Re-run Extraction**. |
| Audio language list is empty | Check `logs/<site>.log`, rebuild assets, hard-refresh. |
| Microphone button unavailable | Allow microphone access and use HTTPS or localhost. |
| First audio transcription is slow | The Whisper model is downloading; run the warm-up command as the bench user. |
| Translation choices missing | Check internet access and the server log; the Argos package index may be unreachable. |
| Re-run Extraction is missing | It is available in **Pending Review** and **Ready to Create**. |

More detail and log locations: [docs/INSTALL.md](docs/INSTALL.md#11-troubleshooting).

---

## Design notes

- The **Document Type is the mapping** (`Document Field Mapping`); there is no separate profile record.
- Extraction is label-driven. A field with no printed label can be filled on the Review Center or left to an ERPNext default.
- Required fields that neither the mapping nor ERPNext can fill produce a clear blocker before an insert is attempted.
- Totals are checked for any target with a `grand_total`; a mismatch blocks creation.
- Drafts are created as the clicking user with `docstatus = 0`.

More design detail: [docs/architecture](docs/architecture).

---

## Contributing

1. Create a small branch.
2. Keep changes focused; one logical change per commit.
3. Run the pure tests and pre-commit before committing.
4. Add a test when fixing an extraction or mapping bug.

---

## License

MIT. See [license.txt](license.txt).
