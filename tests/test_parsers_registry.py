"""Smoke test the parser registry."""

from __future__ import annotations

import pytest

from parsers import available_parsers, get_parser


def test_registry_lists_expected_parsers():
    assert set(available_parsers()) == {
        "karibu_ledger_csv",
        "mtn_merchant_csv",
        "airtel_merchant_csv",
        "momo_agent_xlsx",
        "pdf_via_claude_api",
    }


def test_get_parser_returns_callable():
    fn = get_parser("momo_agent_xlsx")
    assert callable(fn)


def test_pdf_via_claude_api_stub_raises_not_implemented():
    """The deferred PDF parser is registered but inert (Phase 6)."""
    from pathlib import Path

    fn = get_parser("pdf_via_claude_api")
    with pytest.raises(NotImplementedError) as excinfo:
        fn(Path("dummy.pdf"))
    assert str(excinfo.value) == (
        "PDF parsing via Anthropic API is not yet implemented. "
        "See docs/pdf_parser_plan.md for the plan."
    )


def test_unknown_parser_raises_key_error_with_hint():
    with pytest.raises(KeyError) as excinfo:
        get_parser("nope")
    assert "nope" in str(excinfo.value)
    assert "known parsers" in str(excinfo.value)
