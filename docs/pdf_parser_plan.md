# PDF Statement Parser via Claude — Plan (DEFERRED)

> **Status: deferred.** Not built. The user does not yet have an Anthropic API
> key. `parsers/pdf_via_claude_api.py` exists as a registered stub whose
> `parse()` raises `NotImplementedError`. This document is the design to
> implement when a bank account arrives that provides **only** PDF statements.

## Why this exists

Every account in BSR_Recon is reconciled through a parser that turns a raw
statement export into a list of `NormalizedRecord` rows (see
`parsers/types.py`). Today every supported export is CSV or XLSX, so each
parser is deterministic table-reading code.

Some banks (and some account types) only hand out **PDF** statements — no
machine-readable export. PDFs have no stable column structure: layouts vary by
bank, pages wrap, columns drift, and `pdfplumber`-style extraction is brittle
across formats. Rather than hand-write and maintain a fragile per-bank PDF
scraper, we delegate the extraction to Claude: give it the PDF and the target
schema, and let it return structured JSON.

## The flow

1. **Trigger.** An account in `config/accounts.yaml` sets
   `statement_parser: pdf_via_claude_api`. The consolidator calls
   `get_parser("pdf_via_claude_api")` like any other parser and invokes
   `parse(path)` on each dropped `.pdf`.

2. **Read the key.** Load `claude_api_key` from `config/secrets.yaml`
   (git-ignored; template in `config/secrets.yaml.example`). If empty, raise a
   clear error telling the user to populate it — never fall back to a broken
   guess.

3. **Build the request.** Call the Anthropic **Messages API** with the PDF as a
   **document attachment** (base64-encoded `application/pdf` content block).
   Use the latest Claude model available at build time. Include a system/user
   prompt that:
   - states the task: extract every transaction row from the statement;
   - gives the exact `NormalizedRecord` field contract (see below);
   - pins conventions used everywhere else in this app: amounts are positive
     `Decimal`, the sign is carried by `direction` (`IN`/`OUT`); transaction IDs
     are strings (large IDs lose precision as floats); dates are full
     timestamps where available; money parsing strips thousands separators;
   - demands **JSON only** (an array of objects), no prose, so the response is
     machine-parseable. Prefer tool-use / structured output if available so the
     schema is enforced at the API layer rather than by string-parsing.

4. **Parse + validate the response.** Decode the JSON array. For each object,
   construct a `NormalizedRecord`, applying the same normalisation the other
   parsers use:
   - `amount` → `abs(Decimal(...))`;
   - `direction` ∈ {`IN`, `OUT`} (reject anything else);
   - `date` → parsed via `parsers/_dates.py` so unparseable dates flow through
     tagged `UNPARSEABLE_DATE` instead of crashing (consistent with the
     CSV/XLSX parsers);
   - `txn_id` → `str`;
   - keep the model's raw object in `NormalizedRecord.raw` for audit.
   Drop/flag rows that fail validation rather than trusting the model blindly.

5. **Return** `list[NormalizedRecord]` — indistinguishable downstream from a
   CSV/XLSX parser's output. The consolidator and reconciler need no changes.

## Target schema (the contract handed to the model)

```python
@dataclass
class NormalizedRecord:
    source_file: str   # the PDF filename
    date: datetime     # full timestamp where available
    txn_id: str        # statement-side ID; "" if N/A
    amount: Decimal    # always positive
    direction: str     # "IN" or "OUT" relative to the account
    counterparty: str  # payer/payee, free text
    txn_type: str      # e.g. "DEPOSIT", "TRANSFER", "Successful"
    raw: dict          # the model's original extracted object, for audit
```

## Reliability considerations (handle at implementation time)

- **Determinism / idempotency.** The consolidator dedupes on
  `(date, txn_id, amount, direction)` and re-runs every time. LLM extraction is
  not byte-deterministic, so two runs of the same PDF could yield slightly
  different `raw`/`counterparty` text and defeat dedup. Mitigations to decide
  then: cache the extracted JSON next to the PDF (keyed by file fingerprint) and
  reuse it on re-runs; and/or dedupe on the stable subset of fields only.
- **Cost / rate limits.** One API call per PDF (or per page batch for large
  statements). Cache results; don't re-call on every consolidation.
- **Multi-page / large statements.** Chunk by page range if a statement exceeds
  the document-size limit, then concatenate the extracted rows.
- **Verification.** Cross-check the extracted total against any
  printed statement total when present; surface a mismatch as an audit flag
  rather than silently trusting the model.
- **Failure mode.** On API error or empty key, raise a clear, actionable error.
  Never emit a partial/garbage record set that would poison reconciliation.

## What's already in place

- `parsers/pdf_via_claude_api.py` — registered stub, `parse()` raises
  `NotImplementedError` with a pointer to this doc.
- `parsers/__init__.py` — `pdf_via_claude_api` key in the registry.
- `config/secrets.yaml.example` — `claude_api_key: ""` placeholder;
  `config/secrets.yaml` is git-ignored.

## What's left (when un-deferred)

- Implement `parse()` per the flow above (Anthropic SDK call + JSON validation).
- Add `anthropic` to dependencies and the PyInstaller spec.
- Add tests with a small fixture PDF and a mocked API response.
- Document the new account in `config/accounts.yaml`.
