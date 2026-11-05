# Zero Touch: Architecture and Implementation Notes

Status: **Mixed design and implementation documentation.** The financial intake documents include planned phases; the Document Scanner is implemented as a separate utility flow. Section labels identify plans and current behavior.

## Document index

| # | Document | Purpose |
|---|----------|---------|
| 01 | [System Architecture](01-system-architecture.md) | Components, layers, module layout, user flow |
| 02 | [DocType Design](02-doctype-design.md) | Final DocTypes, fields, relationships, indexes |
| 03 | [State Machine](03-state-machine.md) | Intake statuses, stage checkpoints, transitions |
| 04 | [Supplier Invoice Schema](04-supplier-invoice-schema.md) | Extraction schema, uncertainty states, examples |
| 05 | [Provider Abstraction](05-provider-abstraction.md) | OCR, text-layer, and AI provider contracts |
| 06 | [ERPNext Mapping and Validation](06-erpnext-mapping-validation.md) | Mapping, transform registry, rules, matching |
| 07 | [Security Model](07-security-model.md) | Roles, permissions, file safety, isolation, retention |
| 08 | [Background Jobs](08-background-jobs.md) | Queues, locks, retries, idempotency, reconciliation |
| 09 | [MVP Scope and Roadmap](09-mvp-roadmap.md) | Scope per phase, acceptance criteria, test plan |
| 10 | [Risks and Open Decisions](10-risks-open-decisions.md) | Risks, decisions needing your approval |
| 11 | [Document Scanner](11-document-scanner.md) | Implemented document/audio scanner, language sources, models, API and operational boundaries |

## Verified findings (Phase 0 inspection)

Environment: Frappe `version-15` (15.121.1), ERPNext `erpnext-v15.87.2` (15.87.2), HRMS 15.64.2, bench 5.31.0, site `zoma.local` (MariaDB).

Each finding was checked against the source in `apps/frappe` and `apps/erpnext`.

| Finding | Source | Impact on design |
|---------|--------|------------------|
| `frappe.enqueue` supports `job_id` and `deduplicate=True`, and `is_job_enqueued()` exists | `frappe/utils/background_jobs.py` | Use deterministic job IDs for dedup |
| Custom queues are allowed through `common_site_config["workers"]`; built-in queues are `short`, `default`, `long` | `background_jobs.py:get_queues_timeout` | Create `zt_ocr`, `zt_ai`, `zt_validate`, `zt_create` queues |
| Frappe retries only deadlock and timeout errors (up to 5 times). Nothing else | `background_jobs.py:execute_job` | App needs its own retry with backoff, stored on the intake |
| ERPNext duplicate supplier-invoice check (`bill_no`) runs only when `Accounts Settings.check_supplier_invoice_uniqueness` is on. Default is `0` | `purchase_invoice.py:validate_supplier_invoice`, `accounts_settings.json` | `zero_touch` must run its own duplicate check, always |
| Frappe `File.content_hash` is MD5 (`hashlib.md5(..., usedforsecurity=False)`) | `frappe/utils/file_manager.py:get_content_hash` | Use SHA-256 for our fingerprint. MD5 is not collision-resistant |
| Max upload size defaults to 10 MB, configurable with `max_file_size` in site config | `file_manager.py:get_max_file_size` | Our limit is configurable and enforced before storage |
| Purchase Invoice has `bill_no`, `bill_date`, `supplier`, `currency`, `items`, `taxes` (Purchase Taxes and Charges), `grand_total`, `outstanding_amount` | `purchase_invoice.json` | Direct mapping target |
| Purchase Invoice Item has `item_code`, `qty`, `uom`, `rate`, `discount_percentage`, `purchase_order`, `po_detail`, `purchase_receipt`, `pr_detail` | `purchase_invoice_item.json` | PO and PR linkage available on the item row |
| Supplier-part-number lookup exists in `Item Supplier` child table (`supplier_part_no`) | `stock/doctype/item_supplier/item_supplier.json` | Item matching by supplier part number is native |
| Supplier has `tax_id`, `disabled`, `supplier_name`; Customer has `tax_id`, `disabled`, `customer_name` | `supplier.json`, `customer.json` | Party matching and disabled checks |
| Purchase Order `items` table with `item_code`, `qty`, `rate`, `received_qty`, `uom`; Purchase Receipt Item has `purchase_order`, `purchase_invoice_item` | `purchase_order_item.json`, `purchase_receipt_item.json` | Two-way and three-way matching targets |
| Stock Entry and Customer exist as standard DocTypes | `stock_entry.json`, `customer.json` | Targets for the Stock and Customer profiles (later) |
| `frappe.get_decrypted_password` and `set_encrypted_password` exist; encryption key comes from site config | `frappe/utils/password.py` | Provider API keys stored as Password fields |
| `frappe.rate_limiter.rate_limit` decorator exists | `frappe/rate_limiter.py` | Upload and API rate limits |

Known gap: `bench build --app zero_touch` now passes. It needed the `business_radar` editable install, which is a bench-level fix and does not touch `zero_touch` or `business_radar` source.

## Document-type scope (from your latest request)

You choose the target type at upload. The system then extracts, shows fields, lets you save or edit, and creates the matching ERPNext document.

| Your choice | Proposed target | Phase |
|-------------|-----------------|-------|
| Invoice | Purchase Invoice (supplier invoice) | MVP (Phase 2) |
| Purchase | Purchase Order | MVP (Phase 2) |
| Stock | Purchase Receipt (goods received or delivery note). Alternative: Stock Entry | Phase 4 (decision D-03) |
| Customer | Customer master, or Sales Invoice (decision D-02/D-04) | Phase 4 (decision D-04) |

The design treats each choice as a **Document Profile**, so new types don't need core changes.

## Labels

- **Verified**: checked in the installed source.
- **Assumption**: believed true, must be checked in a Phase 1 or 2 spike.
- **Recommendation**: a proposed choice for approval.
- **Open decision**: needs your answer. See document 10.
