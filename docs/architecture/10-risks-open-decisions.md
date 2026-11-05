# 10. Technical Risks and Open Decisions

## 1. Open decisions (need your answer)

Recommended answers are in **bold**. Phase 1 can start once D-01 to D-02, D-05, D-08, D-11, and D-14 are answered. The rest can wait for the phase that needs them.

| ID | Question | Options | Recommendation | Needed by |
|----|----------|---------|----------------|-----------|
| D-01 | What does "Purchase" mean? | (a) Purchase Order (b) Purchase Order and Purchase Receipt (c) Purchase Request | **(a) Purchase Order in MVP** | Phase 2 |
| D-02 | What does "Invoice" mean? | (a) Supplier invoice to Purchase Invoice (b) Also customer invoice to Sales Invoice | **(a) Purchase Invoice in MVP.** Sales Invoice in Phase 4 | Phase 2 |
| D-03 | What does "Stock" mean? | (a) Purchase Receipt from supplier delivery note or GRN (b) Stock Entry (material receipt, transfer, issue) | **(a) Purchase Receipt**, because it matches to POs. Stock Entry later for internal moves | Phase 4 |
| D-04 | What does "Customer" mean? | (a) Create Customer master from a document (for example a registration form or tax certificate) (b) Create Sales Order from a customer PO (c) Both as separate profiles | **(c) Two profiles.** "Customer master" for registration documents. "Sales Order" for customer POs. Customer PO is already listed in the spec | Phase 4 |
| D-05 | Keep the status plus stage split (doc 03) instead of one long status list? | (a) Split (b) Single list as in the spec | **(a) Split.** Stages are checkpoints. Statuses drive UI and queues | Phase 1 |
| D-06 | Accuracy targets for MVP | Numbers in doc 09 | **Accept the proposed targets** and measure on our fixtures. Publish results, do not promise numbers to customers | Phase 2 |
| D-07 | `update_stock` on supplier invoices | (a) Off, receipt through Purchase Receipt (b) On, invoice updates stock | **(a) Off.** Matches ERPNext's standard flow with a separate receipt | Phase 2 |
| D-08 | Identity used by background stages | (a) Acting user (b) Dedicated system user with company-scoped read rights | **(a) Acting user** for create. **(b)** for extract and validate, read-only, company-scoped | Phase 1 |
| D-09 | Posting date for the Purchase Invoice | (a) Reviewer must enter it (b) Default to bill date, reviewer can change | **(b) Default to bill date, shown and editable in review** | Phase 2 |
| D-10 | Retention of original files | Days, or forever | **Default 0 (keep) until you set a policy.** Secure deletion available | Phase 1 |
| D-11 | Custom field `zero_touch_intake` on Purchase Invoice and Purchase Order | Yes or no | **Yes**, through app fixtures. It is the safety net for lost link writes | Phase 1 |
| D-12 | PDF rendering and licences | pypdfium2 (Apache-2.0/BSD) vs PyMuPDF (AGPL) vs poppler (GPL, CLI) | **pypdfium2**. PyMuPDF excluded | Phase 2 |
| D-13 | Multiple invoices in one file | Phase 2 support or review | **One invoice per file in MVP.** Multi-invoice split in Phase 4. Files with several invoices go to review | Phase 2 |
| D-14 | Can Zero Touch Admin read financial content? | Yes or no | **No**, unless also Manager or Reviewer for the company | Phase 1 |
| D-15 | Malware scanning | Off, optional ClamAV, required for external AI | **Optional ClamAV via socket**, off by default. Required when external AI is enabled | Phase 2 |
| D-16 | Legal hold | Yes or no | **Yes**, per company flag that blocks purge | Phase 5 |
| D-17 | Fair-share scheduling across companies | Now or later | **Later** (Phase 5). FIFO per queue in MVP | Phase 5 |
| D-18 | ZATCA support | Phase 4 module, or later | **Phase 4 as an optional validation module.** Phase 2 captures VAT tax ID only. Confirm the required e-invoicing scope with your compliance team before design | Phase 4 |
| D-19 | Test site | Dedicated `zt_test.local` with ERPNext, or reuse `zoma.local` | **Dedicated test site.** Do not run tests on `zoma.local` | Phase 1 |
| D-20 | AI provider for Phase 3 | Ollama local, OpenAI, Gemini, or several | **Ollama local first**, then one OpenAI-compatible cloud option behind the privacy mode | Phase 3 |
| D-21 | Company in upload | Required, or inferred from user | **Required, chosen in the upload dialog.** Filtered by the user's company permission | Phase 1 |
| D-22 | Duplicate override | Allowed with reason, or never | **Never in MVP.** Reviewer can cancel the duplicate intake and the original stays | Phase 1 |

## 2. Confirmed findings (from source, see README)

- ERPNext duplicate supplier-invoice check is off by default. Our check is always on.
- Frappe retries only deadlocks. Our retry is required.
- Frappe File hash is MD5. We use SHA-256 for our fingerprint.
- `enqueue` with `deduplicate` exists. Queue names are configurable.

## 3. Assumptions (to verify in spikes)

| ID | Assumption | Spike | Fallback if wrong |
|----|-----------|-------|-------------------|
| A-1 | `bench worker` starts workers for custom queues from `workers` config | Phase 1, day 1 | Add explicit worker lines in Procfile |
| A-2 | `item_code` is mandatory on Purchase Invoice Item | Phase 2 spike | Validation rule `ITEM_CONFIRMED` already blocks it |
| A-3 | `frappe.get_doc(...).insert()` without commit inside a job is rolled back cleanly on exception | Phase 1 spike with a deliberate ERPNext validation failure | Use explicit savepoints |
| A-4 | Purchase Invoice Item `rate` and `discount_percentage` accept Decimal strings without precision loss | Phase 2 spike | Round to currency precision in the mapping |
| A-5 | Tesseract `ara` language data is present or installable on the target OS, and accuracy is acceptable for printed invoices | Phase 2 spike with 10 Arabic samples | Use cloud OCR as an optional provider behind privacy rules |
| A-6 | pdfplumber gives usable text for most digital invoices | Phase 2 spike | Fall back to OCR per page |
| A-7 | Supplier `tax_id` is populated in the customer data | Data review before go-live | Name-based matching with review |
| A-8 | Frappe v15 Desk supports a custom split-screen page with a PNG preview without a PDF viewer library | Phase 2 spike | Use Frappe's built-in file preview |
| A-9 | Frappe v16 compatibility can be kept by avoiding deprecated v15 APIs | Phase 5 review | Version pin per Frappe version |

## 4. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|-----------|
| R-01 | Arabic OCR accuracy too low for scanned invoices | High | High | Fixture-based measurement (D-06), text-layer first, clear review UI, optional cloud OCR |
| R-02 | Wrong supplier or item matched, creating a wrong draft | Medium | High | Deterministic auto-confirm only on exact keys. Fuzzy is suggestion only. Draft only. Review required in MVP |
| R-03 | Duplicate financial transaction through retry or race | Low (after design) | High | Creation key, unique index, lock, reconciliation tag, tests (doc 08) |
| R-04 | ERPNext upgrade changes Purchase Invoice behaviour | Medium | Medium | Use public APIs only. Integration tests on each ERPNext upgrade. Pin tested version |
| R-05 | Frappe v16 breaking changes in jobs, permissions, or File | Medium | Medium | Avoid private APIs. Phase 5 compatibility review |
| R-06 | Prompt injection in Phase 3 LLM output | Medium | High | No tools, schema validation, deterministic checks, value-in-source check, tests |
| R-07 | Worker crash leaves partial state | Medium | Medium | Checkpoints, locks with expiry, recovery job, chaos tests |
| R-08 | Queue starvation: large batch blocks other companies | Medium | Medium | Separate queues, batch rate limiting, fair-share later (D-17) |
| R-09 | File storage growth | High (at scale) | Medium | Retention, page-preview compression, raw JSON retention |
| R-10 | Sensitive data in logs or error reports | Medium | High | Redaction helper, log tests, generic user-facing errors |
| R-11 | Permission leak through list or report queries | Medium | High | Permission query hooks, per-role tests, no raw SQL for user data |
| R-12 | Malicious files (macros, zip bombs, script PDFs) | Medium | High | Upload checks, no macros, no script execution, pdfium with scripting disabled |
| R-13 | Misconfigured tax accounts block creation for all invoices | Medium | Medium | Profile tax account map validated before use. Clear error message |
| R-14 | Users over-trust AI or extracted values | High | High | Review by default, visible confidence, source highlight, no auto-create in MVP |
| R-15 | Scope creep (four target types plus channels) | High | High | Phase gates. Stock and Customer only after Phase 2 acceptance |
| R-16 | Licence contamination from OCR or PDF libraries | Low | High | Licence review of all dependencies before adding (decision D-12). Table in doc 05 |
| R-17 | Test data contains real customer documents | Medium | High | Synthetic fixtures only, reviewed before commit |
| R-18 | Tesseract and language packs differ across servers | Medium | Medium | Startup check, version recorded per extraction, documented install |
| R-19 | Currency conversion mismatch between extracted and ERPNext rate | Medium | Medium | Conversion rate required in review when currencies differ. ERPNext validation |
| R-20 | Save Review and Create race between two reviewers | Low | Medium | Optimistic concurrency on `modified`, lock on creation |

## 5. Known limitations (MVP, stated to users)

- One invoice per file.
- No handwritten invoices.
- No automatic creation. Every document is reviewed and saved.
- Credit notes and debit notes go to review, not to automatic mapping.
- No item creation. Unknown items block creation until matched.
- Hijri dates are not converted.
- ZATCA QR is not read in MVP.
- Accuracy depends on scan quality. Poor scans go to review.

## 6. Dependency and licence notes

| Dependency | Licence | Phase | Note |
|------------|---------|-------|------|
| pdfplumber (and pdfminer.six) | MIT | Current | Python dependency for PDF text and rendering |
| Tesseract OCR | Apache-2.0 | Current system package | CLI binary; install `eng` and `ara` data packages |
| Pillow | MIT-CMU (HPND) | Current transitive dependency | Image conversion for scanner input |
| Argos Translate | MIT | Current | Local text translation; Argos model packages are separate downloads |
| PyTorch CPU | BSD-style | Current constrained dependency | `torch==2.8.0+cpu`; install with the PyTorch CPU package index |
| faster-whisper | MIT | Current | Local speech recognition wrapper |
| CTranslate2 | MIT | Current transitive dependency | faster-whisper inference engine |
| PyAV | BSD-3-Clause | Current transitive dependency | Audio decoding; wheels include FFmpeg libraries |
| Babel | BSD-3-Clause | Current Frappe dependency | Display names for Whisper language codes |
| pypdfium2 | Apache-2.0 or BSD-3 | Planned | Renderer. Chosen over PyMuPDF (AGPL) |
| pytesseract (wrapper) | MIT | Not used by current scanner | Current code invokes the Tesseract CLI directly |
| openpyxl | MIT | Planned | XLSX reading |
| python-docx | MIT | Planned | DOCX reading |
| jsonschema | MIT | Planned | Output validation |
| ClamAV (optional) | GPL-2.0 (external daemon, not linked) | 2 optional | Used via socket only. Not bundled |

The app Python dependencies are declared in `pyproject.toml`; OS packages and model weights are documented separately in [INSTALL.md](../INSTALL.md). Verify current upstream licence terms when changing dependency versions.

## 7. Approval checklist

Please confirm:

1. Target types: D-01 to D-04 (Invoice, Purchase, Stock, Customer).
2. Architecture: D-05 (status and stage split), doc 01 layering.
3. DocType set (doc 02), including merges and deferrals. Approve or amend.
4. State machine (doc 03), including the Save Review path.
5. Creation rules: D-07, D-08, D-09, D-11, D-22 (no duplicate override).
6. Security model (doc 07), including D-14 and D-21.
7. Test site: D-19.
8. Phase 1 scope (doc 09 section 2).

Once approved, Phase 1 starts with the test-site setup and the A-1 queue spike.
