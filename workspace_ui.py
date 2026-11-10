"""Compact interface helpers, with no storage writes or shared patient cache.

Clinical and save validation do not depend on which tab is visible. These
helpers only organize existing messages and choose interface presentation.
"""
from __future__ import annotations

from copy import deepcopy
from html import escape
from import_review import diagnostic_text
from user_guide import DEFAULT_INSTRUCTIONS, handoff_instructions

WORKSPACE_TABS = (
    "Preview / print", "Medications", "Labs / Vitals", "Cultures", "Labs/Imaging",
    "Problems", "Difficult airway", "Alerts", "Edit handoff",
)

# This styles the application shell only. Printable handoffs use their own
# document/iframe stylesheet and are deliberately unaffected.
COMPACT_STYLES = """<style>
[data-testid="stMainBlockContainer"], .main .block-container {
    padding-top: 4rem; padding-bottom: 1rem;
}
[data-testid="stMain"] [data-testid="stVerticalBlock"] { gap: .45rem; }
[data-testid="stMain"] h2, [data-testid="stMain"] h3 { padding-top: .25rem; padding-bottom: .25rem; }
.handoff-alert-lines { font-size: .75rem; line-height: 1.4; margin: .1rem 0; }
.handoff-alert-line { padding: .13rem 0; overflow-wrap: anywhere; }
.handoff-alert-error { color: #9c2222; font-weight: 600; }
.handoff-alert-warning { color: #704700; }
.handoff-alert-info, .handoff-alert-success { color: #334155; }
</style>"""


def compact_help(guide: dict) -> str:
    """Shorten bundled guidance, not administrator-authored instructions."""
    text = handoff_instructions(guide)
    if text == DEFAULT_INSTRUCTIONS:
        return ("Epic: SmartPhrase author Streamlit, subscribe to PICUHANDOFFSMARTPHRASE. "
                "Open the patient note, enter .PICUHANDOFFSMARTPHRASE, then copy the result. "
                "Select room, paste, create, review. Change rooms to save, or press Save handoff.")
    return text


def _scope(sheet: dict | None) -> str:
    return sheet.get("id", "workspace") if sheet else "workspace"


def remember_notice(session, kind: str, text: str) -> None:
    """Keep the last action per handoff in session memory, never in the vault."""
    room = session.get("current_room")
    sheet = session.get("drafts", {}).get(room)
    if session.get("room_choice") in ("Choose a room", "Other room"):
        sheet = None
    key = _scope(sheet)
    messages = session.setdefault("workspace_notices", {})
    messages[key] = (kind if kind in ("error", "warning", "success", "info") else "info", str(text))
    # Bounded to the open census, not an indefinite session history.
    if len(messages) > 100:
        for old in list(messages)[:-100]:
            del messages[old]


def remember_import(session, sheet: dict, result: dict) -> None:
    """Retain only import diagnostics/summary across tab and room changes."""
    remembered = session.setdefault("workspace_imports", {})
    remembered[sheet["id"]] = deepcopy({
        key: result.get(key, [] if key != "room" else sheet["room"])
        for key in ("room", "errors", "notices", "imported")
    })
    if len(remembered) > 100:
        for old in list(remembered)[:-100]:
            del remembered[old]


def current_import(sheet: dict, session) -> dict:
    current = session.get("import_result", {})
    if current.get("room") == sheet.get("room"):
        return current
    return session.get("workspace_imports", {}).get(sheet.get("id"), {})


def alert_rows(sheet: dict | None, session) -> list[tuple[str, str]]:
    """Collect existing alerts for this room, retaining order and severity."""
    result = []
    seen = set()

    def add(kind, text):
        text = str(text or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        result.append((kind, text))

    notice = session.get("workspace_notices", {}).get(_scope(sheet))
    if notice:
        add(*notice)
    if sheet:
        room = sheet.get("room")
        if session.get("base_sheets", {}).get(room) != session.get("vault", {}).get("rooms", {}).get(room):
            add("error", "A newer saved handoff exists. Reload the archive and compare before saving. Your draft is kept.")
        for section, entries in sheet.get("import_warnings", {}).items():
            for entry in entries:
                add("warning", diagnostic_text(entry))
        imported = current_import(sheet, session)
        if imported.get("room") == sheet.get("room"):
            for text in imported.get("errors", []):
                add("warning", text)
            for text in imported.get("notices", []):
                add("info", text)
            if imported.get("imported"):
                add("info", "Updated: " + ", ".join(imported["imported"]))
            if session.get("last_error_reference"):
                add("info", "Technical report: " + str(session["last_error_reference"])[:12] + ". See Import errors.")
        for med in sheet.get("medications", []):
            for text in med.get("warnings", []):
                add("info", text)
        for device in sheet.get("noninvasive", []):
            if device.get("pressure_inferred"):
                add("warning", "BiPAP was inferred from pressure entries. Check that these are current settings.")
            if device.get("flow_inferred"):
                add("warning", "HFNC was inferred from a mask-plus-flow entry. Check the current delivery device.")
    add("warning", session.get("guide_load_error"))
    add("warning", session.get("error_log_notice"))
    if session.get("pending_error_events") and not session.get("error_log_notice"):
        add("warning", "Technical reports have not been saved. Retry from Import errors before closing.")
    return result


def alert_lines_html(rows: list[tuple[str, str]]) -> str:
    """Escaped text, no large colored cards, 12-pixel-equivalent readable type."""
    if not rows:
        rows = [("info", "No alerts.")]
    pieces = ['<div class="handoff-alert-lines" role="status">']
    for kind, text in rows:
        severity = kind if kind in ("error", "warning", "success", "info") else "info"
        pieces.append('<div class="handoff-alert-line handoff-alert-' + severity + '">' +
                      escape(str(text)).replace("\n", "<br>") + '</div>')
    return "".join(pieces) + '</div>'


def workspace_attention(sheet: dict | None, session) -> str:
    """An unsuccessful action must not be mistaken for a completed save/import."""
    notice = session.get("workspace_notices", {}).get(_scope(sheet))
    if notice and notice[0] == "error":
        return "Action not completed. See Alerts." if sheet else str(notice[1])
    if sheet:
        room = sheet.get("room")
        if session.get("base_sheets", {}).get(room) != session.get("vault", {}).get("rooms", {}).get(room):
            return "Saved record changed. Reload before saving. See Alerts."
        imported = current_import(sheet, session)
        if imported.get("room") == room and imported.get("errors") and not imported.get("imported"):
            return "Import not completed. See Alerts."
    return ""
