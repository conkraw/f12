"""Team instructions and reusable Epic source text, never a patient handoff.

Published separately from the clinical vault. An empty source is intentional:
expanded sample results cannot reconstruct an institution's SmartLinks.
"""
from __future__ import annotations
from datetime import datetime, timezone
from html import escape
import re

MAX_TEMPLATE = 80000
MAX_INSTRUCTIONS = 32000
MAX_NOTES = 8000
DEFAULT_INSTRUCTIONS = """First use: In Epic, find SmartPhrase author Streamlit and subscribe to PICUHANDOFFSMARTPHRASE.

For each patient, select the correct room here. Open that patient's Epic note and enter .PICUHANDOFFSMARTPHRASE. Copy the populated text, including section dividers, into SmartPhrase text. Click Create / update handoff, then review the preview. Move to the next room to save automatically, or press Save handoff. Check the saved time before closing. Use Print all for the team's PDF."""


def handoff_instructions(value: dict) -> str:
    """Show the short workflow without silently rewriting a published guide.

    Legacy bundled instructions are replaced at display/edit time only. Actual
    administrator-authored instructions, source text and publication times stay
    intact until the administrator chooses to save a new publication.
    """
    text = value.get("instructions", "").strip()
    if not text or text.startswith("# Create a handoff you can check and trust"):
        return DEFAULT_INSTRUCTIONS
    return text



def default_guide() -> dict:
    return dict(schema=1, smartphrase_name="", smartphrase_text="", setup_notes="",
                instructions=DEFAULT_INSTRUCTIONS, updated_at=None)


def validate_guide(value: dict) -> None:
    expected = {"schema", "smartphrase_name", "smartphrase_text", "setup_notes", "instructions", "updated_at"}
    if not isinstance(value, dict) or set(value) != expected or type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("The saved user guide has an unsupported structure. Nothing was overwritten.")
    for key, limit in (("smartphrase_name", 120), ("smartphrase_text", MAX_TEMPLATE),
                       ("setup_notes", MAX_NOTES), ("instructions", MAX_INSTRUCTIONS)):
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
            raise ValueError("A user-guide field is invalid or too long.")
    if "\n" in value["smartphrase_name"] or "\r" in value["smartphrase_name"]:
        raise ValueError("The SmartPhrase name must fit on one line.")
    if not value["instructions"].strip():
        raise ValueError("Enter the user instructions before saving.")
    stamp = value["updated_at"]
    if stamp is not None:
        try:
            when = datetime.fromisoformat(stamp)
            if when.tzinfo is None or when.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("The user-guide timestamp is invalid.") from None


def publication(name: str, source: str, notes: str, instructions: str) -> dict:
    """Do not strip indentation/tabs in the reusable SmartPhrase source."""
    result = dict(schema=1, smartphrase_name=name.strip(), smartphrase_text=source,
                  setup_notes=notes, instructions=instructions,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    validate_guide(result)
    return result


def instructions_html(value: dict) -> str:
    """Portable learner guide. All administrator-supplied text is escaped."""
    validate_guide(value)
    sections = []
    for block in value["instructions"].split("\n\n"):
        block = block.strip()
        if not block:
            continue
        tag = "h2" if block.startswith("## ") else "h1" if block.startswith("# ") else "p"
        text = block[3:] if tag == "h2" else block[2:] if tag == "h1" else block
        sections.append(f"<{tag}>" + escape(text).replace("\n", "<br>") + f"</{tag}>")
    name = escape(value["smartphrase_name"]) or "Not yet published by the administrator"
    source = value["smartphrase_text"]
    phrase = '<h2>Team Epic SmartPhrase</h2><p>Name: <code>' + name + '</code></p>'
    if value["setup_notes"]:
        phrase += '<p>' + escape(value["setup_notes"]).replace("\n", "<br>") + '</p>'
    if source.strip():
        phrase += '<details><summary>Reusable source text</summary><pre>' + escape(source) + '</pre></details>'
    else:
        phrase += '<p>The source definition has not been published. Ask your app administrator. The guide does not reconstruct SmartLinks from sample patient results.</p>'
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PICU Handoff user guide</title><style>
body{font:16px/1.65 system-ui,Arial,sans-serif;color:#243749;background:#f3f6f8;margin:0;padding:28px}main{max-width:850px;margin:auto;background:white;padding:36px 42px;border:1px solid #d7e1e8;border-radius:10px}h1{font-size:29px;line-height:1.25;color:#123c53}h2{font-size:20px;line-height:1.35;margin-top:29px;color:#123c53}p{margin:12px 0}code{background:#edf2f5;padding:3px 6px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 monospace;background:#edf2f5;padding:16px}details{margin:14px 0}header{border-bottom:1px solid #d7e1e8;padding-bottom:18px;margin-bottom:24px}small{color:#566d7d}@media(max-width:600px){body{padding:8px}main{padding:20px}}@media print{body{background:white;padding:0}main{border:0;padding:0}h2{break-after:avoid}p{orphans:3;widows:3}}
</style></head><body><main><header><small>PICU HANDOFF / USER GUIDE</small>''' + phrase + '</header>' + ''.join(sections) + '</main></body></html>'
