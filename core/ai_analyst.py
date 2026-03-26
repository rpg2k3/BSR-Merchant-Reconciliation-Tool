"""Module 3b — Optional Claude AI Analysis.

Only loaded/used if a Claude API key is configured.
Sends flagged anomaly summary to Claude for narrative analysis.
"""

import json


def run_ai_analysis(flagged_rows: list[dict], channel: str, api_key: str) -> str:
    """Send flagged rows to Claude for audit narrative analysis.

    Returns plain text narrative string.
    """
    if not api_key:
        return ""

    try:
        import anthropic
    except ImportError:
        return "Error: anthropic package not installed. Run: pip install anthropic"

    if not flagged_rows:
        return "No anomalies flagged — no AI analysis needed."

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = (
        "You are an internal auditor for Bunyonyi Safaris Resort (BSR), a hospitality business in Uganda. "
        "You are reviewing a reconciliation between the resort's mobile money merchant statements "
        f"({channel} channel) and the Karibu HMS (hotel management system) ledger reports. "
        "Analyze the flagged anomalies and provide:\n"
        "1. A plain-English summary of the most significant anomalies\n"
        "2. Any patterns suggesting systematic errors vs one-off discrepancies\n"
        "3. A prioritized list of items needing immediate investigation\n"
        "Be specific about amounts, dates, and transaction IDs. Use UGX currency."
    )

    user_msg = (
        f"Here are the flagged anomalies from the {channel} reconciliation:\n\n"
        f"```json\n{json.dumps(flagged_rows, indent=2)}\n```\n\n"
        "Please provide your audit analysis."
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        return response.content[0].text
    except Exception as e:
        return f"AI analysis error: {e}"


def save_narrative(narrative: str, recon_path, channel: str):
    """Save AI narrative to a text file alongside the reconciliation output."""
    from pathlib import Path
    out_dir = Path(recon_path).parent
    txt_path = out_dir / f"BSR_{channel}_Audit_Narrative.txt"
    with open(txt_path, "w") as f:
        f.write(f"BSR {channel} Reconciliation — AI Audit Narrative\n")
        f.write("=" * 60 + "\n\n")
        f.write(narrative)
    return str(txt_path)
