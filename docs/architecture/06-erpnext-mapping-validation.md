# 06. ERPNext Mapping, Matching, and Validation Strategy

## 1. Pipeline after extraction

```
Extracted (wrappers)
  -> Normalize      (types, dates, money as Decimal, currency, tax ID, UOM, text)
  -> Validate       (deterministic rules; produces Document Validation Result rows)
  -> Match          (supplier, items, PO; produces Document Match rows)
  -> Map            (reviewed values -> ERPNext payload; no writes)
  -> Dry-run check  (optional: ERPNext validation without saving, Phase 2 spike)
  -> Decide         (Pending Review or Ready to Create)
  -> Create         (only on explicit user action or Phase 3 policy)
```

Validation and matching run on the **effective values** (reviewed if present, otherwise extracted). Every Save Review re-runs them.

## 2. Validation engine

### 2.1 Rule contract

```python
@dataclass(frozen=True)
class RuleResult:
    rule_code: str
    status: Literal["passed", "failed", "skipped"]
    severity: Literal["block", "review", "warn", "info"]
    field_key: str | None
    line_no: int | None
    expected: str | None
    actual: str | None
    message_key: str            # translatable message id, not free text

Rule = Callable[[NormalizedDocument, RuleContext], Iterable[RuleResult]]
```

- Rules are pure functions over normalized data. `RuleContext` gives read-only access to ERPNext records through permission-aware lookups (see section 6).
- Rules are registered by code: `validation/registry.py` maps `rule_code` to function and default severity.
- A profile enables rules and may **raise** severity (`warn` to `review` to `block`). It may not lower a financial rule below `block`. The controller enforces this.

### 2.2 Supplier Invoice rule set (Phase 2)

| Code | Checks | Default severity | Notes |
|------|--------|------------------|-------|
| `REQ_FIELDS` | Required fields have a non-missing value | block | List from profile |
| `NO_CONFLICT` | No required field has state `conflict` | block | |
| `DATE_VALID` | Invoice date parses and is not in the future beyond 1 day | block | |
| `DATE_ORDER` | `invoice_date <= posting_date` (ERPNext rule, mirrored) | block | Posting date is a reviewer field |
| `DATE_AMBIGUOUS` | Date state is `uncertain` | review | |
| `CURRENCY_ENABLED` | Currency exists in ERPNext and is enabled | block | Lookup on Currency |
| `SUPPLIER_RESOLVED` | Exactly one confirmed supplier | block | |
| `SUPPLIER_ACTIVE` | Supplier `disabled = 0` | block | |
| `TAX_ID_MATCH` | If supplier has `tax_id` and document has one, they match (normalized) | block when profile requires, else review | |
| `DUP_INVOICE` | No intake with same (company, supplier, normalized bill_no, fiscal year) in Created, Pending Review, Ready to Create, Creating; no non-cancelled Purchase Invoice with same (supplier, bill_no) in the fiscal year | block | Always on. Independent of the ERPNext setting |
| `LINE_CALC` | `line_total == qty × unit_price − discount` within tolerance | block | Per line |
| `LINE_TAX` | `tax_amount == (line_total − discount) × tax_rate` within tolerance | block | Only when tax_rate present |
| `TAX_SUM` | Sum of tax rows equals `tax_total` | block | |
| `TOTAL_CALC` | `grand_total == subtotal − discount_total + tax_total` within tolerance | block | |
| `TOTAL_PRINTED` | Printed subtotal equals sum of lines | block | |
| `QTY_SIGN` | Negative qty | review | Credit-note-like |
| `UOM_KNOWN` | UOM maps to an ERPNext UOM | review | |
| `ITEM_CONFIRMED` | Each line has a confirmed item | review | Required before creation. Unresolved is a "required match", see 4.4 |
| `PO_REF_VALID` | PO reference exists, is submitted, belongs to same supplier and company, and is not closed | review | Phase 2 two-way |
| `PO_QTY` | Line qty ≤ PO line remaining qty (+ tolerance) | review | Overbilling |
| `PO_RATE` | Line rate ≈ PO line rate (+ tolerance) | review | Price difference |
| `KIND_INVOICE` | `document_kind == invoice` | review | Credit and debit notes go to review |

Financial rules marked `block` cannot be overridden by confidence or by AI.

### 2.3 Tolerances

Tolerances are resolved in this order (most specific wins):

1. Profile + company + supplier + item group + currency
2. Profile + company + currency
3. Profile default (`0.01` in document currency)

Tolerance rows are a child table in Phase 4. In Phase 2, the profile default and company currency tolerance are enough.

Numbers use `decimal.Decimal` with `ROUND_HALF_UP` at currency precision. Floats are never used for money comparisons.

## 3. Mapping engine

### 3.1 Declarative mapping

A Document Field Mapping row has this shape:

| Column | Example | Meaning |
|--------|---------|---------|
| `source_key` | `invoice_number` | Key in reviewed values |
| `target_field` | `bill_no` | Field on the target DocType |
| `target_table` | (blank) or `items` | Child table, if any |
| `transform` | `strip`, `upper_no_space`, `to_date_iso` | Named transform from the registry |
| `default_value` | `USD` | Used only when `source_key` is missing and the default is explicitly configured |
| `required` | Yes | Mapping fails if the value is absent after transform |
| `when` | `supplier_tax_id != ""` | Restricted expression (see 3.3) |

For child table rows, `source_key` is `line_items.<field>` and the mapping runs once per row.

### 3.2 Transform registry

`mapping/transforms.py` holds a closed set of named functions. Each has a signature and tests. Examples:

| Name | Input -> output |
|------|-----------------|
| `strip` | string -> string |
| `upper_no_space` | string -> string |
| `to_date_iso` | string or date -> `YYYY-MM-DD` |
| `to_decimal_str` | normalized money -> Decimal string at currency precision |
| `to_float_qty` | decimal string -> float (quantities only) |
| `lookup_supplier` | tax ID or name -> Supplier name (confirmed match only) |
| `lookup_item` | confirmed item match -> item_code |
| `lookup_uom` | raw UOM -> ERPNext UOM |
| `lookup_currency` | ISO code -> currency code (enabled) |
| `company_default` | company -> default value from the company record |

Rules:
- A transform cannot call the network or the database directly. Lookups receive results from the Matching stage, not raw queries.
- Transforms are referenced by name. Config cannot add new ones.
- Unknown transform names fail the profile validation when saved.

### 3.3 Conditional mappings

The `when` column uses a restricted grammar:

```
expr   := term (("and" | "or") term)*
term   := "not"? (field op value | field "is" ("set" | "missing"))
op     := "==" | "!=" | "in"
```

Field names must be keys of the extraction schema. Values are literals (strings, numbers, booleans, lists). No function calls, no attribute access, no eval. The parser is about 80 lines and is unit-tested with hostile inputs.

### 3.4 Supplier Invoice mapping (Purchase Invoice, Phase 2)

| Source (reviewed value) | Target | Transform |
|-------------------------|--------|-----------|
| (company from intake) | `company` | |
| (resolved supplier) | `supplier` | confirmed match |
| `invoice_number` | `bill_no` | strip |
| `invoice_date` | `bill_date` | to_date_iso |
| (reviewer posting date) | `posting_date` | to_date_iso. Required in review (decision D-09) |
| `due_date` | `due_date` | to_date_iso, optional |
| `currency` | `currency` | lookup_currency |
| (exchange rate, if currency differs from company currency) | `conversion_rate` | reviewer input. Otherwise ERPNext fetches it |
| `line_items[].item_code` | `items[].item_code` | lookup_item (confirmed) |
| `line_items[].description` | `items[].description` | strip |
| `line_items[].qty` | `items[].qty` | to_float_qty |
| `line_items[].uom` | `items[].uom` | lookup_uom |
| `line_items[].unit_price` | `items[].rate` | to_decimal_str |
| `line_items[].discount_amount` | `items[].discount_amount` (or `discount_percentage` per settings) | to_decimal_str |
| `line_items[].po_reference` + matched PO row | `items[].purchase_order`, `items[].po_detail` | confirmed match |
| `taxes[]` | `taxes[]` (Purchase Taxes and Charges): `charge_type`, `account_head`, `rate`, `description` | `account_head` comes from the profile's tax account map, never from the document |
| `purchase_order_reference` | (validation only) | |
| `supplier_name` | (not mapped, for reference) | |

Notes:
- `account_head` for taxes is **not** extracted. The profile maps tax names (for example VAT) to ERPNext accounts per company. Missing mapping blocks creation.
- `expense_account` and `cost_center` for items come from ERPNext defaults or the profile. The document never sets accounts.
- `update_stock` is **0** for the supplier invoice profile. Stock is received through Purchase Receipt (Phase 4). Decision D-07.
- Currency fields with different company currency require `conversion_rate`. The review form asks for it if ERPNext cannot fetch it.

### 3.5 Creating the payload

- The payload is built as a dict and passed to `frappe.get_doc(payload)`, then `.insert()`.
- `docstatus` stays 0. The app never calls `.submit()`.
- The acting user is set with `frappe.set_user()` for the job. No `ignore_permissions`. No `ignore_mandatory`. No `ignore_validate`.
- `zero_touch_intake` (custom field) is set to the intake name for traceability (decision D-11).
- ERPNext's own validations run. Any exception rolls back the transaction and returns the intake to Pending Review.

## 4. Matching engine

### 4.1 Strategy interface

```python
class MatchStrategy(Protocol):
    match_type: str
    def candidates(self, key: MatchKey, ctx: RuleContext) -> list[Candidate]: ...
```

Each candidate has `method`, `score`, and `candidate_name`. Only the methods listed as deterministic can auto-confirm.

### 4.2 Supplier matching

Order:
1. **exact_tax_id**: normalized `supplier_tax_id` equals `Supplier.tax_id` (normalized). Auto-confirm when exactly one active supplier matches.
2. **exact_name**: normalized name equals `supplier_name` or `Supplier.supplier_name`. Auto-confirm only when no tax ID exists on either side and exactly one match.
3. **fuzzy_name**: token similarity (Arabic and English normalized). Always `suggested`.

If multiple candidates remain, the intake goes to Pending Review. Supplier is never picked by score.

### 4.3 Item matching

Order:
1. **supplier_part_no**: `Item Supplier` child rows with `supplier` = matched supplier and `supplier_part_no` = line value. Auto-confirm when exactly one active item.
2. **item_code_text**: line `item_code_hint` equals an existing `Item.item_code`. Auto-confirm when exactly one.
3. **fuzzy_name**: description similarity. Always `suggested`. May be shown to the reviewer.
4. **ai_suggested** (Phase 3): from the LLM, labelled. Always `suggested` and requires a click.

A line with no confirmed item blocks creation (`ITEM_CONFIRMED`). The reviewer can create a new Item only through a separate, permission-checked action. Creating Items is out of scope for MVP.

### 4.4 Purchase Order matching (two-way)

Order:
1. **po_reference**: `purchase_order_reference` equals a submitted Purchase Order name for the matched supplier and company. Auto-confirm when exactly one.
2. **line-level**: for each line with `po_reference` or matched item, find PO item rows with the same `item_code`, and compare `qty` and `rate` with remaining quantity. Sets `po_detail` only when the match is unique.

Discrepancies create validation results: `PO_QTY`, `PO_RATE`, and `PO_REF_VALID`.

Without a PO reference, the invoice is **unmatched**. In MVP, unmatched is allowed when the profile's `matching_policy` is `none`. For `two_way`, it goes to Pending Review.

Three-way matching (Purchase Receipt) is Phase 4. The design is the same strategy interface with a PR candidate source.

### 4.5 Required and optional matches

A match is **required** for creation when the profile says so. The matching result is shown in the review panel with its method, score, and status. A user can confirm a suggested match from the review, which records `confirmed_by`.

## 5. Duplicate detection

Three layers, from cheapest to most thorough:

| Layer | Key | When | Result |
|-------|-----|------|--------|
| File | `file_sha256` | At upload | Intake status Duplicate (exact same file, same company) |
| Intake | (company, supplier, normalized bill_no, fiscal year) | After extraction | Validation `DUP_INVOICE` blocks. Shows link to the earlier intake |
| ERPNext | (supplier, bill_no) on Purchase Invoice in fiscal year, docstatus < 2 | After extraction and again at creation | Blocks and links to the existing Purchase Invoice |

Normalized bill number: uppercase, remove spaces and punctuation other than `-` and `/`, convert Arabic-Indic digits.

The creation step checks the ERPNext layer again inside the transaction, to close the race.

Fiscal year is resolved with ERPNext's `get_fiscal_year` for the posting date. If the posting date is not set, the bill date is used for the check.

## 6. Permission-aware reads for rules and matches

- All lookups in rules and matches use `frappe.get_list` or `frappe.get_doc` with the **acting user** context. They never use raw SQL to bypass permissions.
- Where a lookup needs data the user cannot see (for example a supplier of another company), the result is "not found" from the user's viewpoint. The job still runs as the uploader or the approver, so it sees what they see.
- Background stage jobs (extraction, validation) run as the intake's `submitted_by` user, or as a system user with read-only, company-scoped rights. Decision D-08.

## 7. Dry-run (spike, Phase 2)

Before a Create step, the app can ask ERPNext to validate the payload without saving. Frappe has no native dry-run for insert, so the Phase 2 spike will test wrapping `insert()` in a savepoint and rolling back, versus building the doc and calling `validate()` only. The result decides how we show "ERPNext would reject this" before the user clicks Create. Not in the critical path.

## 8. Testing focus for this area

- Each rule: pass, fail, and skipped cases, plus rounding edge cases (0.005, half cents, large totals).
- Each transform: valid, invalid, Arabic-Indic digits, empty.
- Expression parser: valid, invalid, injection attempts (`__import__`, attribute access, long input).
- Matching: exact, ambiguous (two suppliers with the same name), disabled supplier, cross-company supplier.
- Mapping: a creation test that inserts a draft Purchase Invoice against a test company, checks `docstatus == 0`, and checks the link.
