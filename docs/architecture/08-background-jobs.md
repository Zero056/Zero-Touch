# 08. Background Jobs, Retry, and Idempotency Design

## 1. Verified constraints (Frappe v15 source)

| Fact | Source | Consequence |
|------|--------|-------------|
| `frappe.enqueue(..., job_id=..., deduplicate=True)` exists. A duplicate queued job is not re-queued | `frappe/utils/background_jobs.py:enqueue` | Use deterministic job IDs |
| `is_job_enqueued(job_id)` and `get_job_status(job_id)` exist | same file | Useful for checks, but not a lock |
| Built-in queues: `short` (300 s), `default` (300 s), `long` (1500 s). Custom queues come from `common_site_config["workers"]` with a `timeout` per queue | same file, `get_queues_timeout` | Define `zt_ocr`, `zt_ai`, `zt_validate`, `zt_create` in site config |
| `execute_job` retries only on deadlock, lock-wait timeout, or `RetryBackgroundJobError`, up to 5 times | same file, `execute_job` | App-level retry with backoff is needed |
| `enqueue_after_commit=True` queues only after the DB commit | same file | Use it for every enqueue inside a transaction |
| `enqueue` raises when the queue has more than `MAX_QUEUED_JOBS` (500) jobs | same file, `_check_queue_size` | Backpressure is needed. Batch scheduler enqueues, do not flood |
| Each job runs in its own site context; the job's user is passed in | same file, `execute_job(..., user=...)` | Jobs run as the acting user |

Assumption A-1 (verify in spike): the `bench worker` command starts workers for custom queues listed in `workers`. Phase 1 spike checks this before queues are relied on. If not, the Procfile gets explicit worker entries.

## 2. Queues

| Queue | Stages | Timeout | Concurrency (default) | Why separate |
|-------|--------|---------|------------------------|--------------|
| `zt_validate` | Validation, matching, mapping, Save Review re-validation | 300 s | 2 workers | Fast, must not wait behind OCR |
| `zt_ocr` | Render, text layer, OCR | 1500 s | 1 worker, raise per CPU | Heavy, CPU bound |
| `zt_ai` | LLM extraction | 600 s | 2 workers (provider limits) | Network bound, rate limited |
| `zt_create` | ERPNext creation | 300 s | 1 worker | Financial writes. Low concurrency keeps them serial per site and reduces contention |
| `short` / `default` | Maintenance, notifications, retention purge | Frappe defaults | Frappe default | Non-processing |

Concurrency is set by the number of workers per queue in the bench configuration (Procfile). It is documented in the deployment guide (Phase 5).

Phase 1 uses `zt_validate` and `default` only. The other queues are added in Phase 2 with OCR.

## 3. Job model

Each stage is one job:

```
stage_job(intake_name, stage, extraction_name?, attempt, job_token)
```

- `stage` is one of: `classify`, `extract`, `validate`, `match`, `create`, `reconcile`, `purge`.
- `job_token` is a random value stored by the scheduler or the enqueuing action. It lets the job prove it is the owner of the lock.
- Jobs do not pass document content as arguments. They pass names and tokens, and read data from the database. Keeps Redis small and avoids stale data.

### 3.1 Job ID

```
job_id = f"zt:{site}:{intake_name}:{stage}:{checkpoint_version}"
```

`checkpoint_version` is the intake's current `stage` plus `attempt_count`. A new user action (Save Review) increments `attempt_count`, so it gets a new job ID. Two identical requests for the same checkpoint produce one job.

Enqueue call:

```python
frappe.enqueue(
    "zero_touch.pipeline.jobs.run_stage",
    queue="zt_validate",
    timeout=300,
    job_id=job_id,
    deduplicate=True,
    enqueue_after_commit=True,
    intake=intake_name,
    stage=stage,
    job_token=token,
)
```

## 4. Locks

Locks live on the intake row (`lock_token`, `lock_expires_at`) so they are visible to the UI and recoverable.

### 4.1 Acquire

```sql
UPDATE `tabDocument Intake`
SET lock_token = :token, lock_expires_at = :expires, status = 'Processing'
WHERE name = :intake
  AND status = 'Queued'
  AND (lock_token IS NULL OR lock_expires_at < NOW())
```

- One row updated: lock acquired. Zero rows: someone else has it, or the status changed. The job exits without side effects and logs `lock_skipped` at debug level.
- Using a single conditional `UPDATE` avoids the read-then-write race.

### 4.2 Heartbeat

Long stages extend `lock_expires_at` at checkpoints (after each page, each batch). The default lock lengths: 5 minutes for validate and match, 15 minutes for OCR, 10 minutes for AI, 5 minutes for create.

### 4.3 Release

Released in the same DB transaction as the stage checkpoint, using the token: `WHERE lock_token = :token`. A stage that loses its lock must not write its results (it re-reads the lock before writing).

### 4.4 Recovery

A scheduler job (every 5 minutes, `cron`) finds intakes in Processing with an expired lock:
- logs `lock_recovered`,
- sets status to Failed with `status_reason = "worker interrupted"`,
- sets `next_retry_at` according to backoff,
- the retry scheduler enqueues them later.

Recovery never deletes partial results. It keeps every extraction attempt.

## 5. Checkpoints

Each stage writes its output before it finishes, in one transaction:

| Stage | Writes | Checkpoint (`stage`) |
|-------|--------|----------------------|
| classify | Classifier result on extraction, profile match warning | `classified` |
| extract | Document Pages (text, OCR), Document Extraction (fields, lines, raw file) | `extracted` |
| validate | Validation results (replaced for the extraction) | `validated` |
| match | Match rows (replaced for the extraction, confirmed rows kept) | `matched` |
| create | Document Transaction Link, intake status Created | (status change, `stage` stays `matched`) |

Retry resumes at the first stage after the last checkpoint. Re-running a completed stage is allowed and idempotent (it replaces its own rows, not others). A new extraction attempt creates a new Document Extraction and never overwrites the old one.

Save Review never runs extract. It runs validate and match only, against the reviewed values.

## 6. Retry policy

### 6.1 Error classes

| Class | Examples | Retry |
|-------|----------|-------|
| Transient | Timeout, rate limit, DB deadlock, Redis hiccup, provider `UNAVAILABLE` | Yes, with backoff |
| Permanent (input) | Corrupt file, encrypted PDF, too many pages | No. Failed with reason. Reviewer or uploader action needed |
| Permanent (config) | Missing provider, invalid profile, unknown mapping transform | No. Failed. Admin action needed |
| Business | ERPNext validation, permission denied, duplicate | No retry. Status Pending Review (creation) |
| Lock lost | Lock expired mid-stage | Yes, once the new job takes over |

### 6.2 Backoff

- `delay = min(base × 2^(attempt − 1), max_delay)` with full jitter: `delay = random(0, delay)`.
- Defaults: base 60 s, max 3600 s, `max_attempts` from Settings (default 5).
- After `max_attempts`, status Failed. Retry is then manual (Failed to Queued).
- `retry_count` and `next_retry_at` are on the intake. The scheduler (every 5 minutes) enqueues due retries.

### 6.3 Within a job

- Provider HTTP calls: up to 2 immediate retries for `TIMEOUT` and `RATE_LIMITED` with short jitter, then the error is recorded and the backoff above applies to the stage.
- DB deadlocks: Frappe's built-in retry handles up to 5 times. Don't add a second layer.

## 7. Idempotency

| Operation | Key | Guarantee |
|-----------|-----|-----------|
| Upload | `file_sha256` + company | Same file in same company gives one intake (Duplicate for the second) |
| Stage enqueue | `job_id` (checkpoint version) | Deduplicated by Frappe while queued |
| Stage execution | Lock token + checkpoint | Two runs of the same stage don't both write. The second sees the lock or the checkpoint and exits |
| Save Review | `attempt_count` on intake + client-sent `review_version` | Stale saves are rejected (optimistic concurrency) |
| ERPNext creation | `creation_key` = SHA-256(intake, extraction, target_doctype, profile_version) | Unique index on Document Transaction Link. Second call returns the existing link |
| Creation with ERPNext-side tag | `zero_touch_intake` custom field | Reconciliation finds the document if the link write was lost |
| Purge | Intake `original_purged` flag | Purge is idempotent. Skips purged rows |

Optimistic concurrency detail: every review save sends `modified` (the intake's modified timestamp). If it changed, the server returns a conflict and the UI reloads. This prevents two reviewers overwriting each other.

## 8. Creation: atomic write and reconciliation

Creation is the most sensitive stage. The flow in `zt_create`:

1. Acquire the lock (status Ready to Create to Creating).
2. Check `creation_key` link: if present, mark intake Created and stop (idempotent success).
3. Check ERPNext for an existing document tagged with this intake (`zero_touch_intake = intake`) or with the same (supplier, bill_no) in the fiscal year. If found and it's ours, link it. If found and not ours, Pending Review (duplicate).
4. Build payload from reviewed values (doc 06).
5. `frappe.get_doc(payload).insert()` as the acting user.
6. Insert the Document Transaction Link with `creation_key`.
7. Update intake to Created and release the lock, in the same DB transaction as step 5 and 6.
8. Commit once at the end of the job.

Failure handling:
- ERPNext exception (validation, permission, mandatory): the transaction rolls back. The intake goes to Pending Review. The message is stored (redacted). No retry.
- Deadlock during commit: Frappe retries the job. Step 2 then short-circuits if the first attempt committed.
- Crash after commit but before the job reports success: the next run hits step 2 or 3 and reconciles. The `zero_touch_intake` tag is what makes this safe.
- Crash before commit: nothing was written. Retry is safe.

Reconciliation job (`reconcile`, hourly): lists intakes in Creating older than the lock timeout, looks up the tag in ERPNext, and either links the document and marks Created, or moves to Failed. Logs every case.

## 9. Scheduler jobs

| Job | Frequency | Action |
|-----|-----------|--------|
| `recover_stale_locks` | Every 5 min | Expired locks to Failed (retryable) |
| `enqueue_due_retries` | Every 5 min | `next_retry_at <= now` and status Failed with `retry_count < max` to Queued |
| `reconcile_creating` | Hourly | Creating older than 15 min: reconcile (section 8) |
| `purge_expired` | Daily | Retention actions. Batched, idempotent (doc 07) |
| `refresh_metrics` | Hourly | Dashboard aggregates (Phase 4). No per-document work |
| `check_providers` | Every 15 min | Health check, circuit breaker state (cache only) |

Scheduler jobs use `frappe.enqueue` with `job_id` and `deduplicate=True`, so an overlapping run is skipped.

Batching: each scheduler job processes at most `N` intakes per run (default 200). Remaining items wait for the next run. This bounds memory and DB locks.

## 10. Queue backpressure and fairness

- `enqueue` refuses beyond `MAX_QUEUED_JOBS` (500 per queue). The upload path catches this and stores the intake in Received with `next_retry_at`, instead of failing the user. The scheduler enqueues it later. The user sees "queued, waiting for capacity".
- Batch uploads are enqueued at a controlled rate (for example 50 per minute), so one large batch can't block other companies. Phase 5.
- Priority is by queue, not by company. A company-level fair-share scheduler is a Phase 5 option (decision D-17).

## 11. Timeouts and cancellation

- Each job has a Frappe timeout (above) and an internal deadline checked between pages. A timed-out job leaves its checkpoint at the last completed stage.
- Cancel (user action) sets a flag. Running jobs check it at checkpoints and stop. Queued jobs check on start and exit. A cancelled intake never gets a Created status.

## 12. Metrics

Each stage writes a Processing Log entry with `duration_ms`, `stage`, `provider_code`, and the result summary. Daily aggregates feed the dashboard (Phase 4).

Queue metrics: queue length and worker count from Redis RQ (read-only). Shown on the Processing Monitor page.

Metrics that matter:
- Time from Received to Pending Review (p50, p95).
- Stage failure rate by provider.
- Retry count distribution.
- Lock recovery count (should be near zero).
- Creation failure reasons (business vs system).

## 13. Testing plan for jobs

- Two jobs with the same `job_id`: one enqueued.
- Two concurrent lock acquisitions: exactly one wins (real DB, two threads or processes).
- Worker crash mid-stage (simulated exception after partial writes): checkpoint and lock recovery, no partial state visible.
- Retry after transient error: resumes at the right stage, no duplicated extraction rows.
- Creation: ERPNext exception rolls back everything. Deadlock retry does not duplicate. Crash after commit is reconciled.
- Queue full: upload succeeds, intake waits, later enqueued.
- Provider outage: circuit breaker opens, skipped, document goes to Pending Review with the reason.
- Cancel during processing: no Created status, no ERPNext document.
