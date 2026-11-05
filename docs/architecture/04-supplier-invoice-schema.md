# 04. Supplier Invoice Extraction Schema

Schema id: `supplier_invoice_v1`. Used by the `supplier_invoice` profile (target Purchase Invoice).

Phase 2 scope: one invoice per file, Purchase Invoice only. Credit notes and debit notes are detected and sent to review, not mapped.

## 1. Principles

1. **Never invent.** A value that is not in the document is `null` with `state: "missing"`. No defaults are filled in by the extractor.
2. **Every value carries its source.** Value, original text, page, and bounding box when the provider supports it.
3. **Uncertainty is explicit.** Four states: `extracted`, `uncertain`, `missing`, `conflict`.
4. **Money is a decimal string.** No floats. Normalization happens in the Normalizer, not the extractor.
5. **Calculated values are not trusted.** The extractor reports what it sees (for example grand total). The validator recomputes.
6. **Company is not extracted.** It comes from the upload form. The document never chooses the company.

## 2. Envelope

Every provider returns this structure. Providers that cannot fill a section return the section with `null`s.

```json
{
  "schema": "supplier_invoice_v1",
  "document": {
    "language": "ar|en|mixed|unknown",
    "document_kind": "invoice|credit_note|debit_note|unknown",
    "pages": 2
  },
  "fields": { "...": "scalar field wrappers, see section 3" },
  "totals": { "...": "scalar field wrappers" },
  "taxes": [ { "...": "tax row" } ],
  "line_items": [ { "...": "line wrappers" } ],
  "additional": { "...": "payment terms, bank details, notes, references" },
  "meta": {
    "provider_code": "tesseract_local",
    "provider_version": "5.3.4",
    "model_name": null,
    "prompt_version": null,
    "processed_at": "2026-11-03T10:00:00Z"
  }
}
```

## 3. Scalar field wrapper

Every scalar is wrapped like this:

```json
"invoice_number": {
  "value": "INV-2026-0042",
  "state": "extracted",
  "confidence": 0.93,
  "source": {
    "page": 1,
    "bbox": [0.61, 0.08, 0.78, 0.11],
    "text": "Invoice No: INV-2026-0042"
  }
}
```

Missing value:

```json
"supplier_tax_id": { "value": null, "state": "missing", "confidence": null, "source": null }
```

Conflict (two places disagree):

```json
"grand_total": {
  "value": "1150.00",
  "state": "conflict",
  "confidence": 0.71,
  "alternatives": [ { "value": "1105.00", "page": 2, "text": "Total 1,105.00" } ],
  "source": { "page": 1, "bbox": [...], "text": "Grand Total 1,150.00" }
}
```

Bounding boxes are normalized `[x0, y0, x1, y1]` in the range 0 to 1, relative to the page image. Null when the provider cannot locate the value. Pixel coordinates are not stored, so the review UI works at any zoom.

## 4. Fields

### 4.1 Document fields (`fields`)

| Key | Type | Required for Purchase Invoice | Notes |
|-----|------|-------------------------------|-------|
| `invoice_number` | string | Yes | Maps to `bill_no`. Keep original characters. Arabic-Indic digits converted in normalization only |
| `invoice_date` | date | Yes | Maps to `bill_date`. ISO `YYYY-MM-DD` after normalization |
| `due_date` | date | No | Maps to `due_date`. Not computed from terms in MVP |
| `currency` | ISO 4217 | Yes | Maps to `currency`. Must match a currency enabled in ERPNext, or be the company currency |
| `supplier_name` | string | Yes | Resolved by the Matching Engine (doc 06) |
| `supplier_tax_id` | string | Conditional | Required when the profile policy says so. Used for exact matching |
| `supplier_address` | string | No | Used for the reviewer, not for creation |
| `purchase_order_reference` | string | No | Matched against Purchase Order names and the PO reference field |
| `document_kind` | enum | Yes | Must be `invoice` for this profile |

### 4.2 Totals (`totals`)

| Key | Type | Notes |
|-----|------|-------|
| `subtotal` | money | Before discount and tax |
| `discount_total` | money | Positive number, as printed |
| `tax_total` | money | |
| `grand_total` | money | Required. Maps to `grand_total` (validation recomputes) |
| `paid_amount` | money | Printed amount already paid. Not used for Purchase Invoice creation in MVP |
| `outstanding_amount` | money | Printed. Compared with recomputed value |

Money fields hold strings such as `"1150.00"`, with up to 4 decimals at extraction time. The Normalizer rounds to the currency precision during validation.

### 4.3 Taxes (`taxes`, array)

```json
{
  "tax_name": "VAT",
  "rate": "15.00",
  "base_amount": "1000.00",
  "tax_amount": "150.00",
  "account_hint": null,
  "state": "extracted",
  "confidence": 0.9,
  "source": { "page": 1, "bbox": [...], "text": "VAT 15% 150.00" }
}
```

Each row needs `rate` (percent) and `tax_amount`. A tax row is never invented from the grand total. Missing rate means `state: missing` on that row.

### 4.4 Line items (`line_items`, array)

| Key | Type | Required | Notes |
|-----|------|----------|-------|
| `line_no` | int | Yes | Printed number or sequence |
| `description` | text | Yes | Original language kept |
| `supplier_part_no` | string | No | Used for item matching |
| `item_code_hint` | string | No | Only if printed as an item code |
| `qty` | decimal string | Yes | Signed |
| `uom` | string | No | Raw text. Normalized in Normalizer |
| `unit_price` | money | Yes | Net price per UOM as printed |
| `discount_amount` | money | No | Per line, absolute |
| `tax_rate` | percent | No | |
| `tax_amount` | money | No | |
| `line_total` | money | Yes | As printed. Validation recomputes |
| `po_reference` | string | No | PO line reference if printed |

## 5. Confidence model

- Field confidence comes from the provider. For OCR, it is derived from the word-level confidence of the source text. For text-layer PDFs, the text is exact, so confidence is 1.0 for the characters, but the **field-to-text mapping** still carries a mapping confidence.
- For LLM providers, the self-reported score is **not** used as-is. It is capped at 0.85 and combined with the mapping check (is the value literally present in the source text?). A value that is not present in the source is marked `uncertain`, regardless of its score.
- **Document confidence** is not an average. It is:
  - `min` over required fields,
  - and `review` if any required field is below the threshold.
- Every decision in doc 03 uses per-field and rule outcomes, not the average.

## 6. Normalization rules (applied after extraction)

| Input | Rule |
|-------|------|
| Dates | Accept `DD/MM/YYYY`, `MM/DD/YYYY` (ambiguous, see below), `YYYY-MM-DD`, `D MMM YYYY`, Arabic month names, Hijri dates are **not** converted (flagged `uncertain`) |
| Ambiguous dates | If day and month are both `<= 12`, state becomes `uncertain` unless the profile sets a date order for the company |
| Decimals | Remove thousands separators by locale rule. `1,150.00` and `1.150,00` are both recognised. Arabic-Indic digits (`٠-٩`) and Eastern Arabic decimal separator (`٫`) are converted |
| Currency | Symbol to ISO code only when unambiguous (`SAR`, `USD`, `EUR`). `ر.س` maps to `SAR`. Bare `$` is `uncertain` |
| Tax ID | Remove spaces and dashes. Keep as string. Never numeric |
| Invoice number | Keep the original characters. Normalize only whitespace. Used for duplicate checks in a normalized form (uppercase, no spaces) |
| UOM | Map through a configured table (`Nos` -> `Nos`, `pcs` -> `Nos`). Unknown stays raw and is flagged |
| Text | Trim, collapse whitespace, keep RTL characters, do not transliterate |

Normalization never changes a value that cannot be parsed. It sets `state: uncertain` and keeps the original text.

## 7. Example (text-layer invoice, English)

```json
{
  "schema": "supplier_invoice_v1",
  "document": { "language": "en", "document_kind": "invoice", "pages": 1 },
  "fields": {
    "invoice_number": { "value": "INV-2026-0042", "state": "extracted", "confidence": 1.0,
      "source": { "page": 1, "bbox": [0.61, 0.08, 0.78, 0.11], "text": "Invoice No: INV-2026-0042" } },
    "invoice_date": { "value": "2026-10-28", "state": "extracted", "confidence": 1.0,
      "source": { "page": 1, "bbox": [0.61, 0.12, 0.78, 0.15], "text": "Date: 28/10/2026" } },
    "due_date": { "value": null, "state": "missing", "confidence": null, "source": null },
    "currency": { "value": "SAR", "state": "extracted", "confidence": 0.95,
      "source": { "page": 1, "bbox": [0.7, 0.45, 0.9, 0.48], "text": "SAR" } },
    "supplier_name": { "value": "Al Noor Trading Co.", "state": "extracted", "confidence": 0.98,
      "source": { "page": 1, "bbox": [0.05, 0.05, 0.4, 0.09], "text": "Al Noor Trading Co." } },
    "supplier_tax_id": { "value": "300123456700003", "state": "extracted", "confidence": 0.97,
      "source": { "page": 1, "bbox": [0.05, 0.1, 0.3, 0.12], "text": "VAT No 300123456700003" } },
    "purchase_order_reference": { "value": "PO-00127", "state": "extracted", "confidence": 0.9,
      "source": { "page": 1, "bbox": [0.61, 0.16, 0.8, 0.18], "text": "PO: PO-00127" } }
  },
  "totals": {
    "subtotal": { "value": "1000.00", "state": "extracted", "confidence": 0.98, "source": { "page": 1, "bbox": [0.7, 0.7, 0.9, 0.72], "text": "1,000.00" } },
    "discount_total": { "value": "0.00", "state": "extracted", "confidence": 0.9, "source": null },
    "tax_total": { "value": "150.00", "state": "extracted", "confidence": 0.98, "source": { "page": 1, "bbox": [0.7, 0.74, 0.9, 0.76], "text": "150.00" } },
    "grand_total": { "value": "1150.00", "state": "extracted", "confidence": 0.98, "source": { "page": 1, "bbox": [0.7, 0.78, 0.9, 0.8], "text": "1,150.00" } },
    "paid_amount": { "value": null, "state": "missing", "confidence": null, "source": null },
    "outstanding_amount": { "value": null, "state": "missing", "confidence": null, "source": null }
  },
  "taxes": [
    { "tax_name": "VAT", "rate": "15.00", "base_amount": "1000.00", "tax_amount": "150.00",
      "account_hint": null, "state": "extracted", "confidence": 0.95,
      "source": { "page": 1, "bbox": [0.5, 0.74, 0.9, 0.76], "text": "VAT 15% 150.00" } }
  ],
  "line_items": [
    { "line_no": 1, "description": "Office chair, ergonomic", "supplier_part_no": "OC-200",
      "qty": "10", "uom": "Nos", "unit_price": "100.00", "discount_amount": "0.00",
      "tax_rate": "15.00", "tax_amount": "150.00", "line_total": "1000.00", "po_reference": "PO-00127",
      "state": "extracted", "confidence": 0.95, "source": { "page": 1, "bbox": [0.05, 0.35, 0.95, 0.38], "text": "OC-200 Office chair, ergonomic 10 Nos 100.00 1,000.00" } }
  ],
  "additional": {
    "payment_terms": { "value": "Net 30", "state": "extracted", "confidence": 0.9, "source": null },
    "bank": { "iban": null, "bank_name": null, "state": "missing" },
    "notes": { "value": null, "state": "missing" },
    "references": []
  },
  "meta": { "provider_code": "text_layer_pdf", "provider_version": "pdfplumber-0.11", "model_name": null, "prompt_version": null, "processed_at": "2026-11-03T10:00:00Z" }
}
```

## 8. Example (scanned Arabic and English, mixed)

Key points from this example:
- `invoice_number` is extracted from Arabic-Indic digits in OCR text and normalized to Western digits, with `source.text` kept as printed.
- `invoice_date` is `uncertain` because `03/04/2026` could be 3 April or 4 March. The reviewer picks.
- `currency` is `SAR` from `ر.س`, state `extracted`.
- `grand_total` is `conflict`: the footer shows `1,150.00` and a stamp on page 2 shows `1,105.00`. Creation is blocked until the reviewer resolves it.

Shape only:

```json
{
  "fields": {
    "invoice_number": { "value": "7731", "state": "extracted", "confidence": 0.82,
      "source": { "page": 1, "bbox": [0.6, 0.1, 0.8, 0.13], "text": "رقم الفاتورة: ٧٧٣١" } },
    "invoice_date": { "value": "2026-04-03", "state": "uncertain", "confidence": 0.6,
      "source": { "page": 1, "bbox": [0.6, 0.14, 0.8, 0.17], "text": "03/04/2026" },
      "alternatives": [ { "value": "2026-03-04", "text": "03/04/2026 (MM/DD reading)" } ] }
  },
  "totals": {
    "grand_total": { "value": "1150.00", "state": "conflict", "confidence": 0.71,
      "alternatives": [ { "value": "1105.00", "page": 2, "text": "١,١٠٥.٠٠" } ],
      "source": { "page": 1, "bbox": [0.7, 0.78, 0.9, 0.8], "text": "1,150.00" } }
  }
}
```

## 9. Validation contract (summary; full rules in doc 06)

Each rule reads normalized values and returns `passed | failed | skipped`. For this schema:

| Rule | Severity | Failure example |
|------|----------|-----------------|
| Required fields present | block | `invoice_number` missing |
| Dates valid and not in the future beyond tolerance | block | Invoice date after today |
| Date order (invoice date before posting date) | block | Posting date earlier than bill date |
| Currency supported | block | `XYZ` not enabled |
| Line totals equal qty × unit price − discount (± tolerance) | block | Line total 1,000 vs 999 |
| Line tax equals rate × net (± tolerance) | block | Tax 150 vs 149.9 |
| Tax total equals sum of tax rows | block | |
| Grand total equals subtotal − discount + tax (± tolerance) | block | 1,150 vs 1,100 |
| Printed grand total equals computed total | block | |
| No `conflict` state on a required field | block | Two totals |
| Supplier resolved and enabled | block | Supplier disabled |
| Duplicate invoice (supplier + bill_no + company + fiscal year, normalized) | block | Already in ERPNext or intake |
| Negative quantity | review | Credit note in disguise |
| Ambiguous date | review | `uncertain` date |
| PO reference found and open | review | PO closed or missing |
| Item not matched | review | Line has no confirmed item |

Tolerance defaults: 0.01 in company currency, configurable per profile.
