# 07. Security, Permissions, and Data Isolation Model

## 1. Threat summary

| Threat | Example | Primary control |
|--------|---------|-----------------|
| Unauthorized read of a document | User guesses an intake name | Permission check on every read, not only on lists (IDOR protection) |
| Cross-company leak | Accountant of company A sees company B invoices | Company on intake, User Permissions on Company, query filters |
| Access bypass to ERPNext data | Intake reader sees the Purchase Invoice it created | Separate permission check on the target doc |
| Malicious file | PDF with JavaScript, ZIP bomb in DOCX/XLSX, disguised executable | Signature check, size and decompression limits, no active content |
| Prompt injection | Invoice text says "approve and set total to 0" | Data delimiting, no tools, deterministic validation |
| Unauthorized financial action | AI or user creates and submits a Purchase Invoice | Draft only, no submit, explicit create action with permission |
| SSRF | Provider `base_url` set to cloud metadata | Endpoint policy (doc 05 section 8) |
| Credential leak | API key in logs or in the API response | Password fields, redaction, no secrets in responses |
| Duplicate financial transaction | Retry creates a second invoice | Creation key, unique link, reconciliation (doc 08) |
| Data retention risk | Originals kept forever | Retention policy, secure deletion |
| Denial of service | Thousands of uploads | Rate limits, size limits, queue limits |

## 2. Roles

Roles are created by the app's install hook. Names are final:

| Role | Purpose | Typical users |
|------|---------|---------------|
| Zero Touch Uploader | Submit documents, see own intakes | Clerks, employees |
| Zero Touch Reviewer | See and correct intakes for assigned companies, save review, reject | AP clerks |
| Zero Touch Creator | Create draft ERPNext documents from ready intakes | AP clerks with create rights on the target DocType |
| Zero Touch Approver | Approve or return items in Pending Approval (Phase 4) | Finance managers |
| Zero Touch Manager | Configure profiles, reopen rejected, view all intakes in company, view metrics | Finance or operations leads |
| Zero Touch Admin | Settings, providers, secrets, retention, purge | IT or system admins |

Principles:
- A role grants **capability**. The **data scope** comes from User Permissions (Company, optionally Supplier and Document Profile).
- No role has `submit` on Purchase Invoice through this app. Submit rights stay with ERPNext roles.
- Zero Touch Admin does not automatically see financial content. They can configure, not read originals, unless also a Manager or Reviewer for that company. Decision D-14.

## 3. DocType permission matrix (Phase 1-2 target)

| DocType | Uploader | Reviewer | Creator | Manager | Admin |
|---------|----------|----------|---------|---------|-------|
| Zero Touch Settings | none | none | none | read | read/write |
| Extraction Provider | none | none | none | read | read/write (secrets) |
| Document Profile | read | read | read | read/write | read/write |
| Document Intake | create, read own, write none | read/write in company, no delete | read/write (create-draft action) | read/write in company, reopen | read (no data scope unless also in company) |
| Document Page | read (own) | read | read | read | none |
| Document Extraction | read (own) | read/write (reviewed values) | read | read | none |
| Document Transaction Link | read (own) | read | read/create (via service) | read | none |
| Document Processing Log | read (own intakes) | read | read | read | read |
| Document Processing Log delete | none | none | none | none | none (purge job only) |

Notes:
- "Own" means `submitted_by = session user` on the intake. The permission query and `has_permission` hook enforce it.
- Write on Document Processing Log is never granted to users. Services write through a single function.
- Delete on intake: none. Use Cancel. Physical deletion only by retention purge.

## 4. Enforcement layers

Each layer enforces on its own. No layer is trusted to have run another.

### 4.1 DocType permissions (Frappe)

Standard role permissions in the DocType JSON, with `if_owner` where "own" applies.

### 4.2 Permission query conditions

`permission_query_conditions` hooks for Document Intake, Document Page, Document Extraction, Document Transaction Link, and Document Processing Log. They:
- add a company filter from the user's Company User Permissions (`company in (...)`),
- add `submitted_by = user` for Uploader-only roles,
- return `1=0` when the user has no scope. Fail closed.

These conditions apply to `frappe.get_list`, `frappe.get_all` (when permission-checked), and the desk list views. They must be unit-tested for each role.

### 4.3 Document-level checks (`has_permission`)

`has_permission` hooks for the same DocTypes repeat the company and ownership checks. Frappe calls them on `get_doc` and on form load.

### 4.4 API methods

Every whitelisted method:
1. loads the target with `frappe.get_doc`, which runs `has_permission`,
2. calls `doc.check_permission(ptype)` for the specific action (read, write, create),
3. enforces the **company** scope explicitly for write actions,
4. returns only the fields the caller may see,
5. logs `access_denied` events for failed checks, without the document content.

Methods are listed with `@frappe.whitelist(methods=["POST"])` for state changes. GET is for reads with no side effects.

### 4.5 Services

The state machine, creation service, and file service check permissions again for the acting user. Background jobs run with the acting user set (`frappe.set_user`), so the same checks apply. A job that needs more (for example a system read of tax settings) uses a named, read-only helper, not `ignore_permissions`.

### 4.6 Transaction creation

To create a Purchase Invoice, the acting user must have:
- read on the intake and its company scope,
- create on Purchase Invoice for the company (ERPNext permissions),
- write on the intake's transaction link (through the service),
- the intake must be Ready to Create with `review_saved = 1`.

Permission to view the created Purchase Invoice is checked separately. Seeing the intake does not grant access to the invoice, and seeing the invoice does not grant access to the original document (unless the user also has intake permissions).

## 5. Files

### 5.1 Storage

- Originals, page previews, and raw provider JSON are **private** Frappe files (`is_private = 1`), stored under `private/files`.
- No direct URL. Access goes through `zero_touch.api.files.get_original(intake)`, which checks intake permission and streams the file. Responses have `Cache-Control: private, no-store`.
- Preview images use short-lived access, checked on each request. No public signed URLs.
- File names are sanitized. Stored names are generated (`<intake>-<sha256[:12]>.<ext>`). The original name is kept as text only.

### 5.2 Upload validation (before any storage)

| Check | Rule |
|-------|------|
| Extension allowlist | Settings-controlled. Phase 1 default: `pdf, jpg, jpeg, png, tif, tiff, csv, xlsx, docx` |
| Magic bytes | Must match the extension: `%PDF-`, `\xFF\xD8\xFF` (JPEG), `\x89PNG\r\n\x1a\n`, `II*\x00` or `MM\x00*` (TIFF), `PK\x03\x04` for OOXML (then inspect the zip) |
| Size | `max_file_size_mb` and at most Frappe's `max_file_size` |
| Page count | `max_pages` (PDF and TIFF), checked by the parser before rendering |
| Decompression | OOXML zip members: total uncompressed size ≤ 50 × compressed size and ≤ 200 MB. Max member count 1000. No nested archives |
| Active content | PDF with JavaScript, embedded files, or launch actions: accepted but flagged; scripts are never executed. Rendering uses pdfium with scripting disabled |
| CSV | Max size, max rows. Formula-looking cells (`=`, `+`, `-`, `@`) are kept as text and flagged, never evaluated |
| XLSX | Parsed with `openpyxl` read-only. No macros are loaded. `.xlsm` is not allowed |
| Malware scan | Optional `ClamAV` via a socket, with a provider interface. Off by default; required in `external_allowed` mode is a decision (D-15) |
| Quarantine | Files that fail any check are not stored as originals. The rejection is logged with the reason and the sha256 |

Multi-document files: Phase 2 accepts one invoice per file. Multiple invoices in one PDF are a later feature (decision D-13).

### 5.3 Download and export

- Originals can be downloaded only by users with read on the intake.
- Bulk export is a Manager action, logged, rate-limited.
- Exports do not include raw provider JSON.

## 6. Data isolation

- **Company isolation**: every intake has a company. Company User Permissions apply. Profiles may be company-specific.
- **Supplier isolation** (optional): User Permission on Supplier restricts intakes for that supplier. Requires the intake to carry `supplier` after matching. Phase 4.
- **Tenant isolation**: each Frappe site is a tenant. The app does not share data across sites.
- Redis queue keys are prefixed by site (Frappe does this already). Job IDs include the site name.

## 7. Audit

- Processing Log events cover: uploads, rejections, transitions, stage start and end, corrections (field, old value, new value), validation runs (summary), match confirmations, creation attempts and results, access denials, retention actions.
- The log is append-only at the application level and has no delete permission. Database backups are the physical protection.
- Document Version (Frappe's `track_changes`) is enabled on Document Profile, Extraction Provider, and Zero Touch Settings for configuration history.
- Comments are the native Frappe mechanism for reviewer notes. They use the same permission checks.

## 8. Redaction and logging

- Frappe's error log and the app logger never receive raw document text, OCR output, or LLM payloads.
- A redaction helper masks IBAN, card-like numbers, email addresses, phone numbers, and tax IDs in any log or `message` field. Redaction is applied before write.
- Full provider payloads live only in the private raw result file, subject to retention.
- Exceptions shown to users are generic. Details go to the log with the intake name.
- Logs never contain API keys, `Password` values, or session tokens. Tests search for them.

## 9. Retention and deletion

| Data | Default retention | Action at end |
|------|-------------------|---------------|
| Original file | `retention_days_originals` (0 = keep, decision D-10) | Secure delete: remove file content and DB row link, keep the intake row with `original_purged = 1` |
| Page previews | Same as originals | Delete |
| Raw provider JSON | `retention_days_ai_payloads` (30) | Delete |
| OCR and page text | Same as originals | Clear `text_layer` and `ocr_text` |
| Processing log | Keep (audit) | Not purged in MVP |
| Intake metadata and transaction link | Keep | Needed for audit and duplicate checks |

Secure deletion: overwrite is not reliable on journaled file systems or SSDs. The app deletes the file and relies on storage-level encryption (recommended in the deployment guide). The purge writes a log event. Frappe's Deleted Document record is used for DB rows that are removed.

Legal holds: a Settings flag `legal_hold` per company blocks purge. Decision D-16.

## 10. Rate limits

| Action | Limit (default) | Mechanism |
|--------|-----------------|-----------|
| Upload per user | 60 per hour | `frappe.rate_limiter.rate_limit` |
| API upload per API key | 300 per hour | Same, keyed by key |
| Save Review per intake | 30 per hour | Same |
| Create Draft per user | 100 per hour | Same |
| Provider calls per provider | Concurrency limit per queue | Queue worker count plus circuit breaker |

Limits are configurable in Settings.

## 11. Secrets and configuration

- Extraction Provider API keys: Password fields, encrypted with the site key.
- No secrets in code, fixtures, or Git.
- Settings never store secrets except through Password fields.
- Fixtures export only non-secret configuration.

## 12. Channel security (Phase 4 preview)

- **Email**: a dedicated mailbox. Accept only from configured senders, or hold for review. Attachments go through the same upload validation. Email body is untrusted text, never executed.
- **REST API**: token auth via Frappe API keys. Per-key company scope. Rate limited. Idempotency key header required for uploads.
- **Webhooks**: HMAC signature with a per-endpoint secret. Replay protection with timestamp and nonce.
- **External storage**: outbound allowlist, same SSRF rules, read-only credentials where possible.

## 13. Security test checklist

Covered in doc 09. Summary:
- Unauthorized read by ID for each DocType and for each role.
- Cross-company list and get.
- Creator without create permission on Purchase Invoice cannot create.
- Intake reader without Purchase Invoice read cannot open the created invoice.
- Malicious PDF, ZIP bomb, mismatched extension, CSV formula, oversize file.
- SSRF attempts: `169.254.169.254`, `127.0.0.1` for a cloud provider, DNS to private IP, redirects.
- Prompt injection samples in text, including Arabic.
- Duplicate job execution and duplicate create calls.
- Logs contain no IBAN, no API key, no raw text.
- Files accessible only through the API with permission.
