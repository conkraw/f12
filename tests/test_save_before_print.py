"""6.57 confirmed saves before Print all, timestamp exports and BMI labels.

UI checks use instrumented callbacks, not a live browser or remote archive.
All handoffs and timestamps in these tests are synthetic.
"""
from copy import deepcopy
from datetime import datetime, timezone
import time
import pytest
import fitz

from test_callbacks import app, open_room
from test_ui_smoke import equip
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from exports import handoff_html, handoff_text, handoff_pdf, handoffs_pdf, handoffs_html, download_payload
from save_status import room_save_status, handoff_save_caption
from clinical_style import clinical_markup, clinical_runs

SAVED = '2026-11-10T14:15:30+00:00'
SAVED_TEXT = '11/10/2026 09:15:30 AM EST'
NEW = '2026-11-10T15:20:45+00:00'
NEW_TEXT = '11/10/2026 10:20:45 AM EST'
PRINTED = datetime(2026, 11, 10, 17, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self, error=None, before=None):
        self.calls = []
        self.error = error
        self.before = before

    def save(self, candidate, sha):
        if self.before:
            self.before()
        self.calls.append((deepcopy(candidate), sha))
        if self.error:
            raise self.error
        return 'confirmed-new-sha'


def seed(app, stamp=SAVED, room='P4102'):
    open_room(app, room)
    ss = app.st.session_state
    sheet = ss['drafts'][room]
    sheet['fields']['Diagnoses'] = 'Synthetic example'
    sheet['updated_at'] = stamp
    ss['vault']['rooms'][room] = deepcopy(sheet)
    ss['base_sheets'][room] = deepcopy(sheet)
    ss['vault_sha'] = 'old-sha'
    ss['page'] = ss['active_workspace'] = 'Handoff'
    return ss


def specimen(room='P4102', stamp=SAVED):
    sheet = new_sheet(room)
    sheet['fields']['Diagnoses'] = 'Synthetic example'
    sheet['updated_at'] = stamp
    return sheet


@pytest.mark.parametrize('section', ['Diagnoses', 'Neurologic', 'Respiratory', 'Cardiovascular', 'FEN / GI', 'Hematology', 'Infectious Disease'])
def test_navigation_captures_last_widget_edit_and_saves(app, monkeypatch, section):
    ss = seed(app)
    monkeypatch.setattr('models.utc_now', lambda: NEW)
    key = app.edit_key(ss['drafts']['P4102'], section)
    ss[key] = 'Most recent pending edit'
    ss['page'] = 'Print all'
    before_stamp = ss['vault']['rooms']['P4102']['updated_at']
    store = Store(before=lambda: _assert_stamp(ss, before_stamp))
    app.workspace_changed(store)
    assert ss['page'] == 'Print all'
    assert ss['active_workspace'] == 'Print all'
    assert len(store.calls) == 1
    assert store.calls[0][1] == 'old-sha'
    saved = ss['vault']['rooms']['P4102']
    assert saved['fields'][section] == 'Most recent pending edit'
    assert saved['updated_at'] == NEW
    assert ss['drafts']['P4102'] == saved == ss['base_sheets']['P4102']
    assert key not in ss
    assert ss['vault_sha'] == 'confirmed-new-sha'


def _assert_stamp(ss, stamp):
    assert ss['vault']['rooms']['P4102']['updated_at'] == stamp


@pytest.mark.parametrize('failure', [RuntimeError('network unavailable'), ValueError('save rejected')])
def test_save_failure_stays_in_handoff_and_keeps_pending_edit(app, failure):
    ss = seed(app)
    key = app.edit_key(ss['drafts']['P4102'], 'Neurologic')
    ss[key] = 'Unsaved latest text'
    before = deepcopy(ss['vault'])
    ss['page'] = 'Print all'
    app.workspace_changed(Store(error=failure))
    assert ss['page'] == 'Handoff'
    assert ss['vault'] == before
    assert ss['vault_sha'] == 'old-sha'
    assert ss[key] == 'Unsaved latest text'
    assert ss['notice'][0] == 'error'


def test_conflict_keeps_original_timestamp_and_does_not_write(app):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Local draft'
    ss['vault']['rooms']['P4102']['fields']['Neurologic'] = 'Other session update'
    before = deepcopy(ss['vault'])
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == 'Handoff' and not store.calls
    assert ss['vault'] == before
    assert ss['drafts']['P4102']['fields']['Neurologic'] == 'Local draft'


def test_remote_conflict_keeps_open_draft(app):
    from github_store import StorageError
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Local draft'
    ss['page'] = 'Print all'
    store = Store(error=StorageError('Archive changed. Reload and compare.'))
    app.workspace_changed(store)
    assert ss['page'] == 'Handoff'
    assert ss['vault']['rooms']['P4102']['updated_at'] == SAVED
    assert ss['drafts']['P4102']['fields']['Neurologic'] == 'Local draft'


def test_invalid_pending_field_blocks_print_navigation(app):
    ss = seed(app)
    key = app.edit_key(ss['drafts']['P4102'], 'Neurologic')
    ss[key] = 'x' * (app.MAX_FIELD + 1)
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == 'Handoff' and not store.calls and key in ss
    assert ss['vault']['rooms']['P4102']['updated_at'] == SAVED


def test_pending_airway_choice_blocks_print_navigation(app):
    ss = seed(app)
    pending = {'room': 'P4102', 'example': 'unresolved'}
    ss['airway_update_pending'] = deepcopy(pending)
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == 'Handoff' and not store.calls
    assert ss['airway_update_pending'] == pending
    assert 'airway' in ss['notice'][1]


def test_clean_navigation_does_not_restamp_or_write(app):
    ss = seed(app)
    store = Store()
    ss['page'] = 'Print all'
    app.workspace_changed(store)
    assert not store.calls
    assert ss['vault']['rooms']['P4102']['updated_at'] == SAVED
    assert app.autosave_before_print_all(store)
    assert not store.calls


def test_other_dirty_drafts_are_saved_but_clean_rooms_keep_timestamp(app, monkeypatch):
    ss = seed(app)
    for room in ('P4104', 'P4301'):
        sheet = specimen(room)
        ss['vault']['rooms'][room] = deepcopy(sheet)
        ss['base_sheets'][room] = deepcopy(sheet)
        ss['drafts'][room] = deepcopy(sheet)
    ss['drafts']['P4301']['fields']['Neurologic'] = 'Custom room edit'
    monkeypatch.setattr('models.utc_now', lambda: NEW)
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert len(store.calls) == 1
    assert ss['vault']['rooms']['P4301']['updated_at'] == NEW
    assert ss['vault']['rooms']['P4102']['updated_at'] == SAVED
    assert ss['vault']['rooms']['P4104']['updated_at'] == SAVED


def test_invalid_other_draft_keeps_print_blocked(app):
    ss = seed(app)
    second = specimen('P4301')
    ss['drafts']['P4301'] = deepcopy(second)
    ss['base_sheets']['P4301'] = deepcopy(second)
    ss['vault']['rooms']['P4301'] = deepcopy(second)
    ss['drafts']['P4301']['fields']['Diagnoses'] = 'x' * (app.MAX_FIELD + 1)
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == 'Handoff' and not store.calls


def test_no_room_print_entry_does_not_create_empty_patient(app):
    ss = app.st.session_state
    ss['page'] = 'Print all'
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == 'Print all' and not store.calls
    assert ss['vault']['rooms'] == {}


def test_unapplied_paste_is_never_silently_imported_or_saved(app):
    ss = seed(app)
    ss['paste'] = 'RAW_NOT_APPLIED_OR_STORED'
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Reviewed edit'
    ss['page'] = 'Print all'
    app.workspace_changed(Store())
    assert 'RAW_NOT_APPLIED_OR_STORED' not in str(ss['vault'])
    assert ss['paste'] == 'RAW_NOT_APPLIED_OR_STORED'


def test_page_has_save_guard_before_download(app, monkeypatch):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Updated note'
    equip(app, monkeypatch)
    downloads = []
    store = Store()
    def capture(label, data, *a, **kw):
        assert ss['drafts']['P4102'] == ss['vault']['rooms']['P4102']
        assert len(store.calls) == 1
        downloads.append(label)
    app.st.download_button = capture
    app.print_all_page(store)
    assert downloads == ['Download all selected handoffs (PDF)']


def test_page_never_offers_download_after_failed_save(app, monkeypatch):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Updated note'
    equip(app, monkeypatch)
    calls = []
    app.st.download_button = lambda *a, **k: calls.append(a)
    app.print_all_page(Store(error=RuntimeError('offline')))
    assert calls == []
    assert ss['vault']['rooms']['P4102']['updated_at'] == SAVED


def test_session_only_navigation_marks_session_save(app, monkeypatch):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Edited'
    monkeypatch.setattr('models.utc_now', lambda: NEW)
    ss['page'] = 'Print all'
    app.workspace_changed(None)
    status = app.display_room_save_status('P4102', None)
    text = handoff_save_caption(ss['drafts']['P4102'], status)
    assert text == 'Last session save: ' + NEW_TEXT
    assert 'shared' not in text.lower()


@pytest.mark.parametrize('page', ['Admin', 'Import errors'])
def test_nonprinting_workspace_preserves_widget_edit_without_save(app, page):
    ss = seed(app)
    ss[app.edit_key(ss['drafts']['P4102'], 'Neurologic')] = 'Pending note'
    ss['page'] = page
    store = Store()
    app.workspace_changed(store)
    assert ss['page'] == page and not store.calls
    assert ss['drafts']['P4102']['fields']['Neurologic'] == 'Pending note'


@pytest.mark.parametrize('stamp,expected', [
    (SAVED, SAVED_TEXT),
    ('2026-07-04T14:15:30+00:00', '07/04/2026 10:15:30 AM EDT'),
    ('2026-11-01T05:30:00+00:00', '11/01/2026 01:30:00 AM EDT'),
    ('2026-11-01T06:30:00+00:00', '11/01/2026 01:30:00 AM EST'),
    (None, 'Not saved yet'),
    ('invalid time', 'Save time unavailable'),
])
def test_save_label_uses_recorded_timestamp_only(stamp, expected):
    sheet = specimen(stamp=stamp)
    assert handoff_save_caption(sheet) == 'Last saved: ' + expected
    assert expected in handoff_html(sheet, PRINTED)
    assert expected in handoff_text(sheet, PRINTED)


def test_authoritative_save_status_overrides_draft_clock():
    saved = specimen()
    draft = deepcopy(saved)
    draft['updated_at'] = NEW
    draft['fields']['Neurologic'] = 'Unsaved'
    statuses = {'P4102': room_save_status('P4102', saved, draft)}
    html = handoff_html(draft, PRINTED, save_statuses=statuses)
    assert SAVED_TEXT in html and NEW_TEXT not in html
    assert 'Unsaved changes' in html


def test_new_patient_does_not_borrow_old_room_timestamp():
    saved = specimen()
    draft = specimen()
    status = room_save_status('P4102', saved, draft)
    html = handoff_html(draft, PRINTED, save_statuses={'P4102': status})
    assert 'Not saved yet' in html and SAVED_TEXT not in html


def test_wrong_room_status_is_rejected():
    with pytest.raises(ValueError, match='does not match'):
        handoff_save_caption(specimen(), room_save_status('P4301', specimen('P4301')))


def test_saved_timestamp_printed_in_pdf_and_distinct_from_print_time():
    sheet = specimen()
    before = deepcopy(sheet)
    doc = fitz.open(stream=handoff_pdf(sheet, PRINTED), filetype='pdf')
    text = doc[0].get_text()
    assert 'Last saved:' in text and SAVED_TEXT in text
    assert '11/10/2026 12:00:00 PM EST' in text
    assert sheet == before


def test_each_room_keeps_its_own_save_time():
    sheets = [specimen('P4102'), specimen('P4301', NEW)]
    doc = fitz.open(stream=handoffs_pdf(sheets, PRINTED), filetype='pdf')
    assert len(doc) == 2
    assert SAVED_TEXT in doc[0].get_text() and NEW_TEXT not in doc[0].get_text()
    assert NEW_TEXT in doc[1].get_text() and SAVED_TEXT not in doc[1].get_text()
    html = handoffs_html(sheets, PRINTED)
    assert html.count('class="save-meta"') == 2
    assert SAVED_TEXT in html and NEW_TEXT in html


def test_continuation_pages_repeat_same_saved_timestamp():
    sheet = specimen()
    sheet['fields']['Neurologic'] = ('Synthetic long note\n' * 100)
    doc = fitz.open(stream=handoff_pdf(sheet, PRINTED), filetype='pdf')
    assert len(doc) > 1
    assert all(SAVED_TEXT in page.get_text() for page in doc)


@pytest.mark.parametrize('kind', ['pdf', 'html', 'text'])
def test_download_captures_confirmed_status_and_does_not_mutate_sheet(kind):
    saved = specimen()
    statuses = {'P4102': room_save_status('P4102', saved, saved)}
    before = deepcopy(saved)
    generate = download_payload([saved], kind, save_statuses=statuses)
    statuses['P4102'] = room_save_status('P4102', None, saved)
    saved['updated_at'] = NEW
    payload = generate()
    text = ''.join(p.get_text() for p in fitz.open(stream=payload, filetype='pdf')) if kind == 'pdf' else payload.decode()
    assert SAVED_TEXT in text and NEW_TEXT not in text
    assert saved['updated_at'] == NEW
    assert before['updated_at'] == SAVED


def test_html_print_event_never_rewrites_last_saved():
    html = handoff_html(specimen(), PRINTED)
    save_node = html.split('<div class="save-meta">', 1)[1].split('</div>', 1)[0]
    assert 'data-print-time' not in save_node
    assert 'data-print-label' not in save_node
    assert '<b>Last saved:</b>' in save_node


@pytest.mark.parametrize('label', ['BMI:', 'bmi:', 'BMI: 17.14 kg/m²', 'BMI: 18.2 kg/m² (75th percentile)'])
def test_bmi_label_only_is_bold(label):
    markup = clinical_markup(label)
    assert markup.startswith('<b>' + label.split(':', 1)[0] + ':</b>')
    assert markup.count('<b>') == 1
    runs = clinical_runs(label)
    assert runs[0][1] is True
    assert all(not bold for _, bold, _ in runs[1:])


def test_bmi_value_unchanged_in_patient_output():
    from anthropometrics import empty_anthropometrics, clean_field
    sheet = specimen()
    sheet['anthropometrics'] = empty_anthropometrics()
    sheet['anthropometrics'].update({k: clean_field(k, v) for k, v in {'age': '6 years', 'sex': 'Female', 'bmi': '17.14'}.items()})
    validate_sheet(sheet)
    html = handoff_html(sheet, PRINTED)
    assert '<b>BMI:</b>' in html and '17.14' in html
    doc = fitz.open(stream=handoff_pdf(sheet, PRINTED), filetype='pdf')
    spans = [span for block in doc[0].get_text('dict')['blocks'] if 'lines' in block
             for line in block['lines'] for span in line['spans']]
    label = next(span for span in spans if 'BMI:' in span['text'])
    assert 'Bold' in label['font']


def test_bmi_still_hidden_under_two():
    from anthropometrics import empty_anthropometrics, clean_field
    sheet = specimen()
    sheet['anthropometrics'] = empty_anthropometrics()
    sheet['anthropometrics'].update({k: clean_field(k, v) for k, v in {'age': '18 months', 'sex': 'Female', 'bmi': '17.14'}.items()})
    assert '<b>BMI:</b>' not in handoff_html(sheet, PRINTED)
