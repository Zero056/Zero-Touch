# 09. MVP Scope and Implementation Roadmap

> This roadmap describes planned financial-document intake phases. The standalone Document Scanner for image/PDF extraction, audio transcription, and local translation is implemented separately; see [Document Scanner architecture](11-document-scanner.md). It does not imply that the planned invoice pipeline milestones are complete.

## 1. Scope decision

Your request names four target types: **Invoice, Purchase, Stock, Customer**. The spec puts Supplier Invoice and Purchase Order first. This plan follows that order:

| Target choice | Target DocType | Phase | Status |
|---------------|----------------|-------|--------|
| Invoice | Purchase Invoice | 2 (MVP) | Designed in detail |
| Purchase | Purchase Order | 2 (MVP) | Designed in detail (decision D-01) |
| Stock | Purchase Receipt | 4 | Profile pattern is ready. Needs decision D-03 |
| Customer | Customer (master) | 4 | Needs decision D-04 |

Stock and Customer are not built in MVP. The architecture supports them without core changes. Stock and Customer have different matching needs (receipts match to POs; customers have no supplier-style duplicate key), so they need their own rule sets.

## 2. Phase 1: Foundation

**Goal:** A reliable intake and processing framework with no extraction.

Build:
- App scaffold (done), module layout (doc 01 section 5), install hook that creates roles and default records.
- DocTypes: Zero Touch Settings, Extraction Provider, Document Profile (+ child tables), Document Intake, Document Processing Log.
- Upload service: channel `upload`, file type and signature checks, size and page limits, SHA-256, exact duplicate detection.
- Original file storage as private file, with a permission-checked download method.
- State machine module with the transition table (doc 03), CAS updates, transition logging.
- Job framework: `run_stage`, job IDs, locks, backoff, scheduler jobs for stale locks and retries, queue backpressure handling.
- Provider abstraction: base protocols, registry, `NullProvider` and `TextLayerProvider` stub (no OCR yet).
- Profile registry with the `supplier_invoice` profile skeleton (no mapping yet).
- Permission hooks and queries for intake and log, with unit tests per role.
- Redaction helper and log writer.
- Minimal Desk UI: Document Intake list and form, an upload dialog with type and company choice, status indicator.

Not in Phase 1: OCR, AI, extraction, mapping, ERPNext creation, review UI.

Phase 1 acceptance:
1. Upload of a valid PDF stores the original as a private file, creates an intake in Queued, and runs the stage job.
2. Invalid files (wrong signature, too large, too many pages, bad ZIP) are rejected with no intake created. The rejection is logged.
3. The same file uploaded twice in the same company gives Duplicate with `duplicate_of`. A different company gets its own intake.
4. Concurrent lock test: exactly one job processes an intake.
5. A forced exception after partial writes leaves no half state, and retry resumes.
6. Expired locks are recovered and retried with backoff.
7. Users without scope cannot read another company's intake by name or in lists (IDOR and cross-company tests pass).
8. Transition table: every invalid transition is refused and logged as an attempt.
9. Logs contain no raw text and no secrets (test searches the log).
10. `bench build --app zero_touch` and the test suite pass on the test site.

## 3. Phase 2: Supplier Invoice and Purchase Order MVP

This phase delivers your core flow for Invoice and Purchase.

Build:
- Renderer (pypdfium2) and page previews.
- Text-layer extraction for digital PDFs (pdfplumber). Excel and CSV text readers.
- Tesseract OCR provider for scanned pages (`eng`, `ara`). Language packs checked at startup.
- Rule-based classifier with the profile mismatch warning.
- Normalizer (dates, Decimal money, currency, tax ID, Arabic digits, UOM).
- `supplier_invoice_v1` schema, extraction output, field-level confidence, bounding boxes when supported.
- Validation engine with the Supplier Invoice rule set (doc 06 section 2.2).
- Matching: supplier (exact tax ID, exact name), item (supplier part number, item code), Purchase Order (two-way).
- Mapping engine with the transform registry and the restricted `when` grammar.
- Purchase Order profile: extraction schema `purchase_order_v1` (header, lines, supplier, totals), validation (supplier, items, totals), mapping to Purchase Order, and creation.
- Review Center: split screen (original page left, fields right), field confidence colours, source highlight on click, validation panel, match panel with confirm/reject, correction log, Save Review, Create Draft, Reject with reason, Comments.
- Creation service for Purchase Invoice and Purchase Order (insert only, acting user, `zero_touch_intake` custom field, creation key, reconciliation job).
- Processing Monitor (list of intakes by status and stage, retry button for Failed).
- Duplicate checks at three layers (doc 06 section 5).

Phase 2 acceptance (maps to the spec's MVP criteria 1-18):

| # | Criterion | How tested |
|---|-----------|------------|
| 1 | User uploads supplier invoice PDF | Integration test, UI smoke test |
| 2 | Original preserved | Hash of stored file equals hash of upload |
| 3 | Identified as supplier invoice | Classifier test on fixtures (English and Arabic). Mismatch warning test |
| 4 | Supplier, number, dates, currency, totals, taxes, lines extracted | Golden-file tests on 20 fixtures with expected JSON |
| 5 | Field-level source traceability | Each extracted field has page and text (bbox when OCR or PDF coordinates available) |
| 6 | Supplier matched against ERPNext | Matching tests: exact tax ID, name, ambiguous, disabled |
| 7 | Items and PO matching attempted | Matching tests with fixtures |
| 8 | Calculations and business rules validated | Rule tests, rounding edge cases |
| 9 | Duplicate invoices detected | Intake layer and ERPNext layer tests |
| 10 | Automatic-processing eligibility determined | Phase 2 always Pending Review. Test that the reason is shown |
| 11 | Uncertain documents enter review | Test: low confidence and conflicts reach Pending Review |
| 12 | Authorized users correct information | Review save test, permission test |
| 13 | Draft Purchase Invoice created via ERPNext validation | Integration test: docstatus 0, ERPNext validation error propagates |
| 14 | Original remains linked | Transaction link and `zero_touch_intake` field test |
| 15 | Processing history available | Log entries for every transition and stage |
| 16 | Failed processing retried safely | Retry test with injected failure |
| 17 | Reprocessing creates no duplicate transactions | Creation key test, reconciliation test |
| 18 | Arabic and English supported within limits | Fixture set with stated accuracy (decision D-06) |

Accuracy target: stated per fixture set and reported in the test output. We do not promise a number until the fixture set is measured. Proposed initial targets (decision D-06): required field extraction at or above 90% on clean digital PDFs; at or above 75% on scanned Tesseract output; zero false automatic creations (Phase 3 only).

## 4. Phase 3: AI and Zero-Touch Automation

- LLM provider (Ollama local first, then OpenAI-compatible), privacy modes, redaction before external calls.
- Structured output validation (`jsonschema`), prompt versions, token logging.
- AI-assisted matching (suggestions only, labelled).
- Decision engine: policy per profile and company (auto-eligible rule set), using per-field confidence and rule outcomes.
- `auto_create_enabled` switch. Creation still makes **drafts only**.
- Human fallback for every automated decision, with the reason shown.
- Correction feedback export (corrections as a dataset, not used to train anything automatically).
- Arabic and English improvements (normalization tables, OCR tuning, mixed-language tests).

Phase 3 acceptance: no auto-created document without a passed rule set, prompt-injection tests pass, AI-off mode works identically to Phase 2 with the same fixtures.

## 5. Phase 4: Advanced automation

- Stock profile (Purchase Receipt) and three-way matching (decision D-03).
- Customer profile (decision D-04).
- Email ingestion (dedicated mailbox, sender policy, attachment checks).
- REST API (token auth, idempotency keys, per-key scope).
- Webhooks (HMAC, replay protection).
- External storage connectors (outbound allowlist).
- Approval policies: Approval Policy and Document Approval DocTypes, thresholds by amount, company, supplier (segregation of duties).
- Matching tolerance table (company, supplier, item group, currency).
- More OCR providers (PaddleOCR as an option, cloud OCR behind the same protocol).
- Advanced analytics (dashboard and reports in section 9 of the spec).
- ZATCA-related fields (QR parsing) as a configurable validation module (decision D-18).

## 6. Phase 5: Production readiness

- Performance: load test with thousands of documents per day, index review, query plan checks, no N+1 (tests with query counters).
- Security hardening: penetration test on the API and file endpoints, dependency audit.
- Documentation: user guide (English and Arabic), admin guide, developer guide with the examples for a new document type and a new provider.
- Upgrade and migration tests: install on a fresh site, migrate from each prior version, patches are idempotent.
- CI/CD: GitHub Actions for lint, unit tests, integration tests against a test bench. Frappe's own CI pattern.
- Monitoring: queue length, stage durations, failure rates, lock recoveries, provider health.
- Deployment guide: worker configuration per queue, Tesseract language packs, storage encryption, backup and restore including private files.
- Demo environment: a seeded site with sample invoices and a fixture company.
- Production acceptance tests: the full Phase 2 criteria plus a 1,000-document batch run.

## 7. Test strategy (by phase)

| Level | Tooling | Phase 1 | Phase 2 | Phase 3+ |
|-------|---------|---------|---------|----------|
| Unit | pytest-style tests inside Frappe's test runner (`FrappeTestCase`) | State machine, file checks, hashing, redaction, backoff, lock logic | Normalizer, rules, transforms, expression parser, matching | Decision engine, prompt contract |
| Integration | Frappe test runner on a dedicated test site | Upload, jobs, retries, permissions | OCR, matching against ERPNext fixtures, PI and PO creation | AI provider (recorded), decision flows |
| Security | Dedicated security test module | IDOR, cross-company, malicious files, log redaction | Invoice creation without rights, file access | Prompt injection, API bypass, SSRF |
| Golden files | Fixture PDFs with expected JSON, versioned | | 20 invoices, 10 POs, Arabic and English | Growing set |
| Performance | Locust or a script against the test site | Queue throughput | Single-document latency | Batch and concurrency tests |
| Chaos | Kill workers mid-stage, mock provider outages | Lock recovery | Retry and reconciliation | Provider outage |

Test site: create a **dedicated test site** (for example `zt_test.local`) with ERPNext installed and a fixture company. Tests must not run on `zoma.local`, because they create and delete data. Setup is a Phase 1 task after approval.

Edge-case fixtures (from spec section 13): Arabic invoice, mixed language, several currencies, multiple tax rates, missing fields, duplicate invoice number, two invoices in one PDF (expected to be sent to review in MVP), credit note, negative quantity, different UOMs, incorrect totals, poor OCR quality.

Each fixture is a file plus an expected JSON, committed to the app under `tests/fixtures/` with a README stating its origin and licence. Real customer documents are not committed. Synthetic fixtures are generated.

## 8. Definition of done (every phase)

- Code follows the layer boundaries in doc 01.
- New DocTypes have permission matrix tests.
- Every new state transition is in the table and tested.
- Every new external call goes through the provider or endpoint policy.
- No `ignore_permissions` or `ignore_validate` in code paths reachable by users.
- Lint and type check clean. `bench build --app zero_touch` passes.
- Documentation updated, including the changelog.

## 9. Work breakdown estimate (relative)

| Phase | Relative size | Main risk |
|-------|---------------|-----------|
| 1 | Medium | Background job correctness |
| 2 | Large | OCR accuracy on Arabic, the review UI |
| 3 | Medium | Prompt safety, decision explainability |
| 4 | Large | Scope creep across four target types |
| 5 | Medium | Operational readiness |

Time estimates are not given here because they depend on your review cycle and whether we use paid or local providers. We can estimate after Phase 0 approval.
