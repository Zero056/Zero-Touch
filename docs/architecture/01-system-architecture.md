# 01. System Architecture and Component Design

## 1. Principles

1. **Deterministic core.** Validation, matching, and ERPNext writes never depend on AI. AI and OCR only propose values.
2. **Human-in-the-loop is the default.** The user flow is: upload with a chosen type, review extracted fields, save, then explicitly create. Automation is a policy that can be enabled later.
3. **Stages are independent and checkpointed.** Each stage writes its output before the next stage runs. A failure never repeats earlier stages.
4. **ERPNext is the system of record.** We create standard documents through the normal document API as the acting user. We never bypass validation and never submit.
5. **Frappe-native first.** Use Frappe permissions, File, Comments, Version, background jobs, and Password fields. Avoid parallel infrastructure.
6. **No arbitrary code or SQL from configuration.** Mappings use a fixed transform registry.

## 2. Current user flows

### 2.1 ERP document intake and review

```
Upload (choose target type + company)
  -> Intake created (status: Received -> Queued)
  -> Background: classify-check, extract, validate, match
  -> Review screen: original page on the left, fields on the right
       each field: value, confidence, source highlight, validation status, match suggestions
  -> User edits fields as needed
  -> Save Review   (re-validates; no ERPNext write)
       blocking failures remain -> stays Pending Review
       no blocking failures    -> Ready to Create
  -> Create Draft  (explicit click; enqueued; runs as the user)
       -> Draft Purchase Invoice / Purchase Order / ... created
       -> Transaction link stored; intake Created
```

"Classify-check" means: the selected profile is compared with the content (for example, a Purchase Order uploaded as Invoice). A mismatch is a warning and forces review. The user's choice is never silently overridden.

### 2.2 Standalone Document Scanner

The scanner is a separate utility flow. It stores a private source file and extracted text in **Document Scan**; it does not create a Document Intake or an ERPNext transaction.

```
Choose image/PDF or audio
  -> image/PDF: read PDF text layer, then OCR pages that have no text
  -> audio: require a Whisper-supported language; transcribe with local faster-whisper
  -> show private source beside editable text
  -> optional local Argos translation into a separately displayed result
  -> save source, owner, source type, language, edited source text and translation
```

Audio can be uploaded or recorded through the browser microphone. Both language lists start from enabled records in Frappe's **Language** DocType, then keep only codes supported by the relevant speech or translation model.

## 3. Layered architecture

```
+--------------------------------------------------------------+
| Presentation  Desk pages: Inbox, Review Center, Monitor,      |
|               Mapping/Provider config, Dashboard              |
+--------------------------------------------------------------+
| API           Whitelisted methods (permission-checked)         |
+--------------------------------------------------------------+
| Application   Intake service | Pipeline/State service |         |
|               Review service | Creation service               |
+--------------------------------------------------------------+
| Domain engines (pure Python, no Frappe imports where possible)|
|  Normalization | Validation | Matching | Mapping | Decision   |
+--------------------------------------------------------------+
| Providers     Text-layer | Tesseract OCR | faster-whisper | Argos | LLM (optional) |
+--------------------------------------------------------------+
| Infrastructure  Frappe ORM, File, Redis queues, Scheduler,   |
|                 Password, Logs                               |
+--------------------------------------------------------------+
| ERPNext       Supplier, Item, PO, PR, Purchase Invoice ...   |
+--------------------------------------------------------------+
```

Domain engines should not depend on Frappe request context. That makes them testable with plain unit tests and reusable for later channels.

## 4. Components

| Component | Responsibility | Key rule |
|-----------|----------------|----------|
| Intake Service | Accepts files from configured intake channels. Checks type, size, signature, and page limits. Computes SHA-256. Creates the intake and checks exact duplicates. | Main intake extraction runs in the pipeline worker. |
| Scanner API | Accepts standalone image, PDF, and audio uploads; extracts/transcribes, stores a private File and Document Scan. | Enforces extension, size, language, ownership and rate limits. |
| Translation | Local Argos Translate package models, direct or English pivot. | No document text sent to a hosted translation API. |
| Pipeline Service | Runs stage jobs, takes locks, records checkpoints, schedules retries. | Only place that changes status (through the state machine). |
| Profile Registry | Maps a profile code (for example `supplier_invoice`) to schema, mapping, rules, and target DocType. | Adding a type = register a profile. No core edits. |
| Provider Registry | Holds text-layer, OCR, classifier, and LLM providers behind one interface. | Provider output is untrusted until validated. |
| Normalizer | Dates, money (Decimal), currency codes, tax IDs, UOM, Arabic/English digits, RTL text. | Pure functions, unit-tested. |
| Validation Engine | Deterministic rules: totals, tax, required fields, dates, duplicates, policies. | Runs after every save and every stage. Cannot be overridden by AI. |
| Matching Engine | Supplier, item, PO, and PR matching with deterministic methods first. AI suggestions are labelled and need confirmation. | AI matches are never authoritative. |
| Mapping Engine | Converts reviewed fields into an ERPNext payload using declarative mappings and the transform registry. | No eval, no SQL, no Python from config. |
| Decision Engine | Phase 1-2: always "Pending Review" unless the user saves. Phase 3+: policy-based automation. | Financial blockers always win over confidence. |
| Creation Service | Creates draft ERPNext documents as the acting user, stores the transaction link, reconciles retries. | Insert only. Never submit. |
| Review Service | Loads a review, applies user edits, logs corrections, and re-runs validation. | Every change is logged. |
| Audit Log | Append-only Document Processing Log with actor, stage, transition, and redacted payload. | No raw document text in logs. |
| Settings and Config | Zero Touch Settings (Single), Document Profile, Extraction Provider. | Secrets use Password fields. |

## 5. Module layout (proposed)

Inside `apps/zero_touch/zero_touch/`:

```
zero_touch/
  intake/            # channels, file validation, fingerprint, storage
  pipeline/          # stage runner, locks, state machine, retry policy
  providers/         # base protocols, registry, text_layer/, ocr/, llm/, classifier/
  profiles/          # profile registry, profile definitions (supplier_invoice/)
  extraction/        # normalization, schema validation, confidence helpers
  validation/        # rule registry, rules/ (supplier_invoice rules)
  matching/          # strategies: supplier, item, purchase_order
  mapping/           # mapping engine, transform registry
  decision/          # policy evaluation (Phase 3+)
  execution/         # ERPNext creation, reconciliation
  review/            # review service, correction logging
  audit/             # processing log writer, redaction
  security/          # file guards, SSRF guard, rate limits, retention
  api/               # whitelisted methods (thin layer)
  zero_touch/doctype/  # DocType JSON + controllers (thin)
  zero_touch/page/   # Review Center, Monitor, Document Scanner Desk pages
  public/js/         # Inbox and DocType scripts
  tests/             # unit, integration, security (see doc 09)
```

Controllers stay thin. Business logic lives in the packages above so that a new document type adds a profile module, not edits to the core.

## 6. Extension points

| Extension | Interface | Registration |
|-----------|-----------|--------------|
| New document type | `DocumentProfile` (schema, mapping, rules, matching policy, target DocType) | `profiles/registry.py` plus a Document Profile record |
| New text or OCR provider | `TextExtractor` or `OCRProvider` protocol | `providers/registry.py` plus an Extraction Provider record |
| New LLM provider | `StructuredExtractor` protocol | Same, `provider_type = llm` |
| New validation rule | `Rule` (pure function on normalized data) | `validation/registry.py` with a code |
| New matching strategy | `MatchStrategy` | `matching/registry.py` |
| New transform | `Transform` function | `mapping/transforms.py` |
| New channel | `IntakeChannel` (adapter producing a file plus metadata) | `intake/channels.py` |
| New workflow action | `Action` (guarded transition) | `pipeline/actions.py` |

Each extension point has a documented contract and an example in the Phase 2 developer guide.

## 7. Phase 1 boundary (for approval)

Phase 1 builds the foundation only:
- App scaffold, settings, roles, and permissions
- Document Intake with file validation, fingerprint, and duplicate detection
- State machine and transitions
- Background job framework with locks, retries, and job IDs
- Processing log
- Provider abstraction with a `NullProvider` and a `TextLayerProvider` stub
- Profile registry with one empty `supplier_invoice` profile

Phase 1 does not include OCR, AI, extraction, mapping, or ERPNext creation.

## 8. Deployment topology

- Web: existing gunicorn workers.
- Workers: existing `bench worker`, plus dedicated queues (`zt_ocr`, `zt_ai`, `zt_validate`, `zt_create`) with separate concurrency.
- Storage: private Frappe files for originals and page previews (`is_private=1`).
- Redis: existing `redis_queue` and `redis_cache`.
- OCR and LLM: local (Tesseract, Ollama) or external, depending on the privacy mode.
- Standalone scanner OCR, speech transcription and translation currently run synchronously in the web request. Install/warm their language models as the bench service user; use upload-size limits and a web-worker timeout appropriate to the model. Moving long audio jobs to a queue is a production scaling improvement.
