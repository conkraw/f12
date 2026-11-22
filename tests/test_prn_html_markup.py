"""Sanitized, HTML-only PRN refresh metadata and count placement."""
from copy import deepcopy
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import json

from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html
from infusions import render_body_blocks
from lab_windows import display_clock
from medications import format_medication
from prn_counts import event_time
from prn_html import PRN_PRINT_SCRIPT, mark_live_prn_counts
from test_prn_integration import NOW, auto_sheet


class CountSpans(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "span" and "data-prn-count" in attrs:
            self.current = {"payload": json.loads(attrs["data-prn-count"]), "text": ""}
            self.rows.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "span":
            self.current = None


def test_current_counts_have_only_sanitized_event_metadata():
    sheet = auto_sheet()
    before = deepcopy(sheet)
    html = handoff_html(sheet, NOW)
    spans = CountSpans(html).rows
    assert sorted(row["text"] for row in spans) == [" × 2", " × 3"]
    assert sheet["prn"]["reviewed"] == {}
    for row in spans:
        payload = row["payload"]
        assert set(payload) == {"version", "events"}
        assert payload["version"] == 2
        assert all(len(event) == 2 and isinstance(event[0], (int, float))
                   and type(event[1]) is int and event[1] > 0
                   for event in payload["events"])
        assert "medication" not in json.dumps(payload)
    vec = next(row for row in spans if row["text"] == " × 3")
    assert any(event[0] == event_time("2026-11-22T04:01:00-05:00").timestamp() * 1000
               for event in vec["payload"]["events"])
    assert any(event[0] == event_time("2026-11-22T07:01:00-05:00").timestamp() * 1000
               for event in vec["payload"]["events"])
    assert html.count(PRN_PRINT_SCRIPT) == 1
    assert sheet == before


def test_only_generated_suffix_is_wrapped_when_notes_have_identical_text():
    sheet = auto_sheet()
    row = dict(next(item for item in sheet["medications"] if "vecuronium" in item["name"].lower()),
               _prn_count=3)
    note = format_medication(row)
    blocks = [("notes", note), ("heading", "PRN"), ("medication", row)]
    body = render_body_blocks(blocks, True)
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, body, blocks)
    assert live.startswith(escape(note) + "\n<b>PRN</b>\n")
    assert len(CountSpans(live).rows) == 1
    assert live.count(" × 3") == 2


def test_custom_medication_text_and_escaping_survive_dynamic_suffix():
    sheet = auto_sheet()
    row = dict(next(item for item in sheet["medications"] if "vecuronium" in item["name"].lower()),
               custom_text="Vecuronium PRN × 3 as documented & <review>", _prn_count=3)
    blocks = [("medication", row)]
    body = render_body_blocks(blocks, True)
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, body, blocks)
    assert len(CountSpans(live).rows) == 1
    assert '</span> × 3 as documented &amp; &lt;review&gt;' in live
    assert "<review>" not in live
    row["custom_text"] = "Vecuronium instructions"
    body = render_body_blocks(blocks, True)
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, body, blocks)
    assert "Vecuronium instructions | PRN<span" in live


def test_stale_or_inconsistent_count_metadata_is_omitted():
    sheet = auto_sheet()
    row = dict(next(item for item in sheet["medications"] if "vecuronium" in item["name"].lower()),
               _prn_count=99)
    blocks = [("medication", row)]
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, render_body_blocks(blocks, True), blocks)
    assert " × 99" not in live and "data-prn-count" not in live


def test_analgesic_metadata_cannot_add_a_live_count():
    sheet = auto_sheet()
    row = dict(next(item for item in sheet["medications"] if "hydromorphone" in item["name"].lower()),
               _prn_count=12)
    blocks = [("medication", row)]
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, render_body_blocks(blocks, True), blocks)
    assert " × 12" not in live and "data-prn-count" not in live


def test_missing_af_data_does_not_receive_refresh_spans():
    sheet = auto_sheet()
    sheet["prn"] = None
    assert CountSpans(handoff_html(sheet, NOW)).rows == []


def test_invalid_source_metadata_removes_generated_suffix():
    sheet = auto_sheet()
    row = dict(next(item for item in sheet["medications"] if "vecuronium" in item["name"].lower()),
               _prn_count=3)
    blocks = [("medication", row)]
    sheet["prn"]["events"][0]["timestamp"] = "invalid"
    with display_clock(NOW):
        live = mark_live_prn_counts(sheet, render_body_blocks(blocks, True), blocks)
    assert " × 3" not in live and "data-prn-count" not in live


def test_plain_text_and_pdf_contain_counts_without_browser_payloads():
    sheet = auto_sheet()
    text = handoff_text(sheet, NOW)
    pdf = handoff_pdf(sheet, NOW)
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for value in (text, pdf_text):
        assert "PRN × 3" in value and "PRN × 2" in value
        assert value.count("PRN ×") == 2
        assert "data-prn-count" not in value and "window_start_ms" not in value


def test_batched_html_has_one_script_and_distinct_room_spans():
    html = handoffs_html([auto_sheet("P4102"), auto_sheet("P4104")], NOW)
    assert html.count(PRN_PRINT_SCRIPT) == 1
    assert len(CountSpans(html).rows) == 4
    assert html.count("<main>") == 2
