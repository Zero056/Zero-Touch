# Zero Touch

Zero Touch is an app for Frappe and ERPNext v15 that helps you create ERPNext documents from existing business documents without entering all the information manually.

Upload an invoice, quotation, employee form, scanned document, or another supported file. Zero Touch extracts the available information and matches it with fields in the DocType you have configured.

You can review the extracted data, correct mistakes, and choose the right ERPNext records before creating anything.

The app only creates draft documents. It never submits them or completes transactions automatically. The final decision always stays with the user.

## Features

### Document extraction

Zero Touch supports several document formats:

- PDF files, including PDFs with selectable text and scanned pages.
- Images: JPG, JPEG, PNG, TIFF, BMP, and WEBP.
- Audio recordings, with speech-to-text transcription.
- Arabic and English documents, including forms that contain both languages.

For scanned documents, Tesseract is used to extract text. Audio transcription is handled by faster-whisper.

### Field mapping

The extraction process is based on configuration rather than hardcoded DocType names.

Each Document Type is a `Document Field Mapping` record. It defines the target DocType and the fields that should be extracted from the uploaded document.

You can use standard ERPNext DocTypes or your own custom DocTypes. Field information is loaded from Frappe metadata, including fields inside child tables.

Arabic label matching also handles common spelling differences, such as Alef variations, Ta Marbuta, diacritics, and extra spaces.

### Review before creation

Extracted information is not inserted directly into ERPNext.

The reviewer can open the Review Center, preview the original document, check extracted values, and correct anything that was not read properly.

Each extracted field includes its confidence level and the source text used to identify its value.

The review page supports both document fields and child-table rows.

### ERPNext record matching

Link fields are matched against existing ERPNext records.

This includes Customer, Supplier, Item, Item Group, UOM, Warehouse, and other Link fields.

When a matching record cannot be found, the reviewer can handle the issue before creating the document. Creating missing records from the uploaded document is currently limited to Customer and Supplier.

### Child tables and item rows

Zero Touch identifies child tables from the target DocType metadata.

It can recognize common item-table field names, even when they differ from the standard ERPNext naming conventions.

For example, quantity can be stored in `qty` or `quantity`, while the item price can be stored in `rate` or `unit_price`.

### Local processing

The default setup processes documents locally on your server.

- Tesseract handles OCR.
- faster-whisper handles audio transcription.
- Argos Translate handles translation.

Document content is not sent to an external AI service unless you configure an external provider.

## How it works

The process starts when a user uploads a document and selects the Document Type to use.

```text
Upload document
      |
      v
Document Intake
      |
      v
Extraction
  - Read PDF text or run OCR
  - Extract mapped header fields
  - Read line items
  - Match Link fields
      |
      v
Review Center
  - Preview original document
  - Correct extracted values
  - Select ERPNext records
  - Save review
      |
      v
Create Draft
      |
      v
ERPNext Document (docstatus = 0)
```

Document processing runs in the background. Once a document is uploaded, a background job handles the extraction. The reviewer can follow its progress through the Document Inbox.

A scheduled job also checks for stalled processing jobs and handles retries when needed.

## Main screens

| Screen | Description |
|---|---|
| Document Inbox | Upload documents, select a Document Type, and follow processing status. |
| Review Center | Preview documents, review extracted fields, correct values, and create drafts. |
| Processing Monitor | Check processing status, queue counts, and recently uploaded documents. |
| Document Scanner | Extract text from images and PDFs, transcribe audio, and translate text. |
| Document Types | Configure target DocTypes and field mappings. |

## Installation

For production installation, upgrades, model downloads, permissions, and troubleshooting, see [docs/INSTALL.md](docs/INSTALL.md).

### Requirements

| Component | Requirement |
|---|---|
| Frappe / ERPNext | v15 |
| Python | 3.10–3.12 (bench virtualenv) |
| Tesseract OCR | 4.1+ with `eng` and `ara` language data |
| MariaDB / Redis | Same requirements as your Frappe bench |
| Background workers | `bench worker` |
| Scheduler | `bench schedule` |
| HTTPS | Required for browser microphone recording |

The Python dependencies are declared in `pyproject.toml`:

- `pdfplumber`
- `argostranslate`
- `faster-whisper`

### Quick installation

First, install Tesseract and its English and Arabic language packages:

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara
```

Go to your bench directory:

```bash
cd /path/to/frappe-bench
```

Install the app. The CPU PyTorch constraint is used for the Argos Translate dependencies:

```bash
PIP_CONSTRAINT=apps/zero_touch/constraints-translation.txt \
PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
bench get-app zero_touch <git-url> --branch main
```

Install it on your site:

```bash
bench --site your-site.example install-app zero_touch
bench --site your-site.example migrate
bench build --app zero_touch
bench --site your-site.example clear-cache
```

Make sure the background worker and scheduler are running:

```bash
bench worker
bench schedule
```

The first audio transcription downloads the Whisper `small` model. The first translation also downloads the required Argos language pair.

For production environments, I recommend downloading these models before allowing users to process documents. The warm-up commands are available in [docs/INSTALL.md](docs/INSTALL.md#31-download-local-models-before-first-use-recommended).

### Verify the installation

1. Open Zero Touch and go to Zero Touch Settings.
2. Enable document processing.
3. Open Document Inbox and upload a document.
4. Select a configured Document Type.
5. Check that the document moves through Queued, Processing, and Pending Review.
6. Open the Review Center, check the extracted information, and click the appropriate Create button.

## Configuration

### Zero Touch Settings

The settings page controls the main processing options:

- Enable or disable document processing.
- Set the maximum allowed file size.
- Configure allowed file extensions.
- Set the maximum number of automatic attempts and retry limits.
- Configure the VAT/tax account used when a Quotation or Sales Order needs the tax information extracted from the document.

### Document Types and field mapping

Document Types are stored as `Document Field Mapping` records. There is no separate profile DocType.

Each mapping record contains the following information:

| Field | Description |
|---|---|
| Label | Name displayed in the upload screen, such as Quotation or Employee. |
| Target DocType | The ERPNext or custom DocType that will be created. |
| Company | Optional company restriction. Leave empty to make the mapping available to all companies. |
| Enabled | Controls whether the mapping appears in the upload screen. |
| Field Mapping | Defines the document labels and target fields. |

Each field mapping row has a Source option.

**From document**

The value is extracted from the uploaded document using the English or Arabic label configured in the mapping.

**ERPNext fills automatically**

The value is not extracted from the document. Instead, the review page shows the value that ERPNext is expected to use when creating the document, such as Item Group or UOM defaults.

The available target fields are loaded directly from DocType metadata. This includes custom fields and fields belonging to child tables.

You can use the Fill Required Fields button to add mandatory fields from the target DocType. After that, configure the labels as they appear on your actual documents.

### Link fields

Link fields are matched against existing records using the linked DocType's own name field.

Common examples include:

- Customer
- Supplier
- Item
- Item Group
- UOM
- Warehouse

Arabic text normalization helps with common OCR differences, including Alef variations, Ta Marbuta, diacritics, and spacing.

When a record cannot be matched, creating a new record is currently supported for Customer and Supplier only.

### Line-item tables

Zero Touch looks at the target DocType's child tables to identify possible item tables.

A child table is considered an item table when it contains a quantity field and a rate or amount field.

The following field names are supported:

| Document value | Supported child-table fields |
|---|---|
| Item name | `item_name`, `description`, `product_name`, `particulars`, `service` |
| Quantity | `qty`, `quantity`, `qty_in` |
| Rate | `rate`, `price`, `unit_price`, `selling_price`, `valuation_rate` |
| Amount | `amount`, `total`, `line_total`, `net_amount` |

Only the first detected item table is added to the default mapping rows. Other child tables are still available for selection from the field dropdown.

## Document Scanner

The Document Scanner is separate from the normal Document Intake and Review Center workflow.

It allows users to extract, edit, and translate text without creating an ERPNext business document.

The result is saved as a `Document Scan` record.

Available operations:

**Image and PDF scanning**

Upload an image or PDF and extract its text using Tesseract OCR. The extracted text remains editable.

**Audio transcription**

Upload an audio file or record audio directly from the browser. Select the spoken language and transcribe it using faster-whisper.

**Translation**

Choose a target language and translate the extracted or edited text using Argos Translate.

Browser recording requires microphone permission and HTTPS, or localhost.

## Roles and permissions

Zero Touch uses separate roles for uploading, reviewing, configuring, and managing documents.

| Role | Permissions |
|---|---|
| Zero Touch Uploader | Upload documents and view their own uploads. |
| Zero Touch Reviewer | Review documents and save extracted values for accessible companies. |
| Zero Touch Manager | Configure mappings and reprocess documents. |
| Zero Touch Admin | Manage settings and extraction providers. |
| Zero Touch Creator / Approver | Reserved for future approval workflows. |

Company User Permissions are also applied. Users without access to a company will not see documents belonging to that company.

## Project structure

The app is organized into separate modules for extraction, mapping, processing, document creation, and security.

```text
zero_touch/
├── api/                 Whitelisted endpoints
├── audit/               Event logging and redaction
├── creation/            Payload building and draft creation
├── extraction/          Text extraction, OCR, tables, items, and totals
├── intake/              Upload validation and intake creation
├── mapping/             Field mapping and compatibility
├── patches/             Installation and data migrations
├── pipeline/            Processing states, jobs, and retries
├── providers/           Extraction provider abstraction
├── security/            Permission checks and endpoint policies
├── tests/               Unit and site-level tests
├── public/js/           Document Intake scripts
└── zero_touch/
    ├── doctype/          DocTypes
    ├── page/             Review Center, Processing Monitor, Scanner
    └── workspace/       Zero Touch workspace
```

## Development

Go to the app directory:

```bash
cd apps/zero_touch
```

Install the pre-commit hooks:

```bash
pre-commit install
```

Run the pure Python tests:

```bash
../../env/bin/python -m unittest discover \
  -s zero_touch/tests \
  -p 'test_*pure*.py'
```

To run the app tests on a test site:

```bash
bench --site test-site.example run-tests --app zero_touch
```

After changing Python code, restart the background worker so it loads the updated code.

After changing JavaScript, rebuild the assets and clear the site cache:

```bash
bench build --app zero_touch
bench --site your-site.example clear-cache
```

## Troubleshooting

| Problem | What to check |
|---|---|
| Document stays in Queued | Make sure `bench worker` is running. |
| Scanned document has no extracted text | Check that Tesseract and both `eng` and `ara` language packages are installed. Then use Re-run Extraction. |
| Audio language list is empty | Check `logs/<site>.log`, rebuild assets, and hard-refresh the browser. |
| Microphone button is unavailable | Check browser microphone permissions and make sure the site uses HTTPS or localhost. |
| First audio transcription takes a long time | Whisper is probably downloading its model. Run the warm-up command as the bench user. |
| Translation languages are missing | Check server connectivity and the Argos package index. Review the server logs for errors. |
| Re-run Extraction is not available | It is currently available only for Pending Review and Ready to Create documents. |

See [docs/INSTALL.md](docs/INSTALL.md#11-troubleshooting) for additional troubleshooting information and log locations.

## Design notes

A few implementation decisions are worth mentioning:

- A Document Type is a `Document Field Mapping` record. There is no additional profile record.
- Extraction depends on labels configured in the mapping. Fields without printed labels can still be filled manually in the Review Center or populated through ERPNext defaults.
- Before inserting a document, Zero Touch checks whether all required fields can be populated. If something is missing, the user gets a clear message instead of an incomplete insert.
- If the target DocType contains a `grand_total` field, the extracted totals are checked before creation. A mismatch blocks the operation.
- Documents are always inserted with `docstatus = 0`.
- The user who clicks Create is the user who creates the ERPNext document.
- Zero Touch does not submit documents automatically.

More information about the internal design is available in [docs/architecture](docs/architecture).

## Contributing

Contributions and bug reports are welcome.

If you want to work on the project:

1. Create a separate branch for your changes.
2. Keep each commit focused on one logical change.
3. Run the pure tests and pre-commit checks before committing.
4. Add tests when fixing extraction, field mapping, or document creation issues.

## License

Zero Touch is released under the MIT License. See [license.txt](license.txt).
