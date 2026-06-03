"""Deferred: PDF statement parser via the Anthropic Messages API.

STUB — not yet implemented. See `docs/pdf_parser_plan.md` for the design.

When a future bank account provides statements only as PDF (no CSV/XLSX export),
this parser will send the PDF to Claude as a document attachment and ask it to
extract every transaction into the `NormalizedRecord` schema as JSON, then
validate and return the rows like any other parser.

It is registered in the parser registry under `pdf_via_claude_api` so the
plumbing is discoverable, but it is inert: `parse()` raises
`NotImplementedError`. Deferred until the user has an Anthropic API key
(`config/secrets.yaml`, see `config/secrets.yaml.example`).
"""

from __future__ import annotations

from pathlib import Path

from parsers.types import NormalizedRecord


def parse(path: Path) -> list[NormalizedRecord]:
    """Not implemented yet — see docs/pdf_parser_plan.md."""
    raise NotImplementedError(
        "PDF parsing via Anthropic API is not yet implemented. "
        "See docs/pdf_parser_plan.md for the plan."
    )
