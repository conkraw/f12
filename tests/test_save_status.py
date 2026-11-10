"""v6.19 save timestamps: synthetic records, mocked storage and widget stubs."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from save_status import (saved_instant, saved_time_text, room_save_status,
                         latest_saved_time, most_recent_save_caption, save_status_table)
from models import new_vault, new_sheet, save_sheet_in, SCHEMA_VERSION
from github_store import StorageError, ConflictError
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip

STAMP = '2026-11-07T18:24:09+00:00'
DISPLAY = '11/07/2026 01:24:09 PM EST'
LATER = '2026-11-07T19:30:10+00:00'
LATER_DISPLAY = '11/07/2026 02:30:10 PM EST'


def saved_sheet(room='P4102', stamp=STAMP):
    sheet = new_sheet(room)
    sheet['fields']['Diagnoses'] = 'Synthetic example'
    sheet['updated_at'] = stamp
    return sheet


@pytest.mark.parametrize('value,expected', [
    (STAMP, DISPLAY),
    ('2026-11-07T18:24:09Z', DISPLAY),
    ('2026-11-07T13:24:09-05:00', DISPLAY),
    ('2026-07-04T18:24:09+00:00', '07/04/2026 02:24:09 PM EDT'),
    ('2026-11-01T05:30:00Z', '11/01/2026 01:30:00 AM EDT'),
    ('2026-11-01T06:30:00Z', '11/01/2026 01:30:00 AM EST'),
    ('2026-03-08T06:59:59Z', '03/08/2026 01:59:59 AM EST'),
    ('2026-03-08T07:00:00Z', '03/08/2026 03:00:00 AM EDT'),
    ('2026-01-01T02:00:00Z', '12/31/2025 09:00:00 PM EST'),
    (' 2026-11-07T18:24:09.100000+00:00 ', DISPLAY),
])
def test_explicit_eastern_date_and_time(value, expected):
    assert saved_time_text(value) == expected
    assert saved_instant(value).tzinfo is timezone.utc


@pytest.mark.parametrize('value', [None, '', ' ', 'not-a-time', '2026-02-30T10:00:00Z',
                                    '2026-11-07', '2026-11-07T18:24:09', 12, {}, True,
                                    '11/07/2026 1:00 PM', '<script>example</script>'])
def test_missing_or_invalid_time_never_defaults_to_now(value):
    assert saved_instant(value) is None
    assert saved_time_text(value) == 'Save time unavailable'


@pytest.mark.parametrize('room', ['P4102', 'P4201', 'P4301', 'OTHER 2', 'TEST-99'])
def test_saved_status_same_for_preset_and_custom_rooms(room):
    saved = saved_sheet(room)
    status = room_save_status(room, saved, deepcopy(saved))
    assert status.last_saved == DISPLAY
    assert status.status == 'Saved'
    assert not status.unsaved
    assert status.caption == 'Last saved to shared storage: ' + DISPLAY


def test_changed_draft_keeps_last_confirmed_time_not_draft_timestamp():
    saved = saved_sheet()
    draft = deepcopy(saved)
    draft['fields']['Respiratory'] = 'Edited but not saved'
    draft['updated_at'] = LATER
    state = room_save_status('P4102', saved, draft)
    assert state.unsaved and state.status == 'Unsaved changes'
    assert state.last_saved == DISPLAY


def test_unsaved_draft_does_not_borrow_created_time():
    draft = new_sheet('P4102')
    draft['updated_at'] = STAMP  # Not an acknowledged save in the vault.
    assert room_save_status('P4102', None, draft).last_saved == 'Not saved yet'


def test_no_record_no_draft():
    status = room_save_status('P4102', None)
    assert status.last_saved == 'Not saved yet' and status.status == 'No saved handoff'
    assert not status.unsaved


def test_saved_room_not_open_has_persistent_time():
    status = room_save_status('P4102', saved_sheet())
    assert status.last_saved == DISPLAY and not status.unsaved


def test_new_patient_does_not_show_old_patient_save_as_current():
    old = saved_sheet()
    draft = new_sheet('P4102')
    state = room_save_status('P4102', old, draft, base_sheet=old)
    assert state.last_saved == 'Not saved yet'
    assert state.different_handoff and state.unsaved
    assert 'previous saved sheet' in state.status


def test_legacy_missing_time_is_unavailable_not_never_saved():
    saved = saved_sheet(stamp=None)
    state = room_save_status('P4102', saved, deepcopy(saved))
    assert state.last_saved == 'Save time unavailable'
    assert state.status == 'Saved'


def test_loaded_conflict_status_keeps_new_archive_timestamp():
    old = saved_sheet()
    saved = deepcopy(old)
    saved['updated_at'] = LATER
    saved['fields']['Diagnoses'] = 'Other session edit'
    draft = deepcopy(old)
    draft['fields']['Diagnoses'] = 'Local edit'
    state = room_save_status('P4102', saved, draft, base_sheet=old)
    assert state.last_saved == LATER_DISPLAY
    assert 'reload and compare' in state.status and state.unsaved


def test_base_not_supplied_does_not_claim_conflict():
    saved = saved_sheet()
    draft = deepcopy(saved)
    draft['fields']['Diagnoses'] = 'New local value'
    assert room_save_status('P4102', saved, draft).status == 'Unsaved changes'


def test_session_only_label_does_not_claim_github():
    sheet = saved_sheet()
    status = room_save_status('P4102', sheet, sheet, session_only=True)
    assert 'session only' in status.caption and 'GitHub' not in status.caption
    assert status.status == 'Saved in this session only'
    html = save_status_table([status], session_only=True)
    assert 'Last session save (Eastern)' in html and 'GitHub' not in html


def test_summary_uses_chronology_not_iso_string_order():
    rooms = {'P4102': saved_sheet(stamp='2026-11-07T20:00:00+03:00'),
             'P4301': saved_sheet('P4301', STAMP),
             'P4104': saved_sheet('P4104', 'bad-time')}
    assert latest_saved_time(rooms) == DISPLAY
    assert most_recent_save_caption(rooms) == 'Most recent handoff save in loaded archive: ' + DISPLAY
    assert 'session-only' in most_recent_save_caption(rooms, session_only=True)


def test_empty_and_legacy_summary():
    assert latest_saved_time({}) is None
    assert most_recent_save_caption({}).endswith('No handoffs saved yet')
    assert most_recent_save_caption({'P4102': saved_sheet(stamp=None)}).endswith('Time unavailable')


def test_status_table_escape_and_input_immutability():
    saved = saved_sheet()
    draft = deepcopy(saved)
    before = deepcopy((saved, draft))
    statuses = [room_save_status('<script>x</script>', saved, draft)]
    html = save_status_table(statuses)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'Last saved (Eastern)' in html and DISPLAY in html
    assert (saved, draft) == before


class Store:
    def __init__(self, failure=None, inspect=None):
        self.calls = []
        self.failure = failure
        self.inspect = inspect

    def save(self, candidate, sha):
        if self.inspect:
            self.inspect()
        self.calls.append(deepcopy(candidate))
        if self.failure:
            raise self.failure
        return 'confirmed-save-sha'


def seed(app, room='P4102'):
    ss = app.st.session_state
    sheet = saved_sheet(room)
    ss['vault']['rooms'][room] = deepcopy(sheet)
    ss['base_sheets'][room] = deepcopy(sheet)
    ss['drafts'][room] = deepcopy(sheet)
    ss['current_room'] = ss['room_choice'] = room
    return ss


def test_explicit_save_time_changes_only_after_storage_acknowledges(app, monkeypatch):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Synthetic edit'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    def before_ack():
        assert app.display_room_save_status('P4102', object()).last_saved == DISPLAY
        assert app.display_room_save_status('P4102', object()).unsaved
    store = Store(inspect=before_ack)
    app.save_room(store)
    status = app.display_room_save_status('P4102', store)
    assert status.last_saved == LATER_DISPLAY and not status.unsaved
    assert LATER_DISPLAY in ss['notice'][1]
    assert ss['vault_sha'] == 'confirmed-save-sha'


@pytest.mark.parametrize('failure', [StorageError('Synthetic failure'), ConflictError('Synthetic conflict')])
def test_failed_explicit_save_keeps_previous_time(app, monkeypatch, failure):
    ss = seed(app)
    ss['drafts']['P4102']['fields']['Neurologic'] = 'Unsaved'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    old = deepcopy(ss['vault'])
    app.save_room(Store(failure))
    assert ss['vault'] == old
    state = app.display_room_save_status('P4102', object())
    assert state.last_saved == DISPLAY and state.unsaved
    assert ss['notice'][0] == 'error'


def test_first_save_failure_stays_not_saved(app, monkeypatch):
    open_room(app)
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    app.save_room(Store(StorageError('Failed')))
    assert app.display_room_save_status('P4102', object()).last_saved == 'Not saved yet'


def test_custom_room_autosave_records_correct_outgoing_room(app, monkeypatch):
    ss = seed(app, 'P4301')
    ss['drafts']['P4301']['fields']['Diagnoses'] = 'Synthetic custom room'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    ss['room_choice'] = 'P4104'
    store = Store()
    app.room_changed(store)
    assert ss['current_room'] == 'P4104'
    assert app.display_room_save_status('P4301', store).last_saved == LATER_DISPLAY
    assert app.display_room_save_status('P4104', store).last_saved == 'Not saved yet'
    assert LATER_DISPLAY in ss['notice'][1]


def test_failed_custom_autosave_time_not_advanced(app, monkeypatch):
    ss = seed(app, 'P4301')
    ss['drafts']['P4301']['fields']['Diagnoses'] = 'New edit'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    ss['room_choice'] = 'P4104'
    app.room_changed(Store(StorageError('Failed')))
    assert ss['current_room'] == 'P4301'
    assert app.display_room_save_status('P4301', object()).last_saved == DISPLAY


def test_unchanged_room_switch_does_not_claim_a_new_save(app, monkeypatch):
    ss = seed(app)
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    store = Store()
    ss['room_choice'] = 'P4104'
    app.room_changed(store)
    assert store.calls == []
    assert app.display_room_save_status('P4102', store).last_saved == DISPLAY


def test_save_all_each_room_and_untouched_closed_room(app, monkeypatch):
    ss = seed(app)
    seed(app, 'P4301')
    ss['vault']['rooms']['P4106'] = saved_sheet('P4106')
    ss['drafts']['P4301']['fields']['Diagnoses'] = 'Changed custom room'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    store = Store()
    app.save_all_rooms(store)
    assert len(store.calls) == 1
    for room in ['P4102', 'P4301']:
        assert app.display_room_save_status(room, store).last_saved == LATER_DISPLAY
        assert not app.display_room_save_status(room, store).unsaved
    assert app.display_room_save_status('P4106', store).last_saved == DISPLAY


def test_failed_save_all_does_not_update_any_timestamp(app, monkeypatch):
    ss = seed(app)
    seed(app, 'P4301')
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    before = deepcopy(ss['vault'])
    app.save_all_rooms(Store(StorageError('Failed')))
    assert ss['vault'] == before
    for room in ['P4102', 'P4301']:
        assert app.display_room_save_status(room, object()).last_saved == DISPLAY


def test_new_patient_not_saved_until_replaces_previous(app, monkeypatch):
    ss = seed(app)
    app.start_new_patient()
    assert app.display_room_save_status('P4102', object()).last_saved == 'Not saved yet'
    monkeypatch.setattr('models.utc_now', lambda: LATER)
    app.save_room(Store())
    assert app.display_room_save_status('P4102', object()).last_saved == LATER_DISPLAY


def test_admin_only_write_does_not_change_room_save_time(app):
    ss = seed(app)
    candidate = deepcopy(ss['vault'])
    candidate['settings']['rooms'].append('P4301')
    app.commit(candidate, Store())
    assert app.display_room_save_status('P4102', object()).last_saved == DISPLAY
    assert latest_saved_time(ss['vault']['rooms']) == DISPLAY


def test_reload_archive_changes_time_only_from_loaded_record(app):
    ss = seed(app)
    fresh = deepcopy(ss['vault'])
    fresh['rooms']['P4102']['updated_at'] = LATER
    fresh['rooms']['P4102']['fields']['Diagnoses'] = 'Changed in other session'
    class LoadedStore:
        def load(self):
            return fresh, 'fresh-sha'
    app.reload_archive(LoadedStore())
    state = app.display_room_save_status('P4102', object())
    assert state.last_saved == LATER_DISPLAY
    assert 'reload and compare' in state.status


def capture_page(app, monkeypatch):
    equip(app, monkeypatch)
    events = []
    for name in ['caption', 'markdown', 'warning', 'info', 'text', 'subheader']:
        setattr(app.st, name, lambda *args, _name=name, **kwargs: events.append((_name, str(args[0]) if args else '')))
    app.st.download_button = lambda label, *args, **kwargs: events.append(('download', label))
    return events


def test_room_page_places_timestamp_next_to_room_heading_and_in_all_room_list(app, monkeypatch):
    seed(app, 'P4301')
    events = capture_page(app, monkeypatch)
    app.handoff_page(Store())
    assert ('subheader', 'Handoff') in events
    # The room selector now replaces the repeated heading. Save metadata stays
    # visible in one compact status line, not three separate captions.
    assert any(kind == 'caption' and 'Age: -- | Sex: --' in text and
               'Last saved to shared storage: ' + DISPLAY in text and
               text.endswith(' | Saved') for kind, text in events)
    tables = [text for kind, text in events if kind == 'markdown' and 'Handoff save status' in text]
    assert len(tables) == 1 and 'P4301' in tables[0] and 'P4102' in tables[0]


def test_print_table_precedes_download_buttons_and_lists_custom_room(app, monkeypatch):
    ss = seed(app)
    seed(app, 'P4301')
    ss['drafts']['P4301']['fields']['Neurologic'] = 'Still unsaved'
    events = capture_page(app, monkeypatch)
    before = deepcopy(ss['vault'])
    store = Store()
    app.print_all_page(store)
    table_index = next(i for i, (kind, text) in enumerate(events) if kind == 'markdown' and 'Handoff save status' in text)
    download_index = next(i for i, (kind, text) in enumerate(events) if kind == 'download')
    assert table_index < download_index
    table = events[table_index][1]
    assert 'P4102' in table and 'P4301' in table and table.count(DISPLAY) == 2
    assert 'Unsaved changes' in table
    assert any(kind == 'warning' and 'Downloading alone does not save' in text for kind, text in events)
    assert any(kind == 'caption' and 'Most recent handoff save' in text and DISPLAY in text for kind, text in events)
    assert ss['vault'] == before and not store.calls


def test_print_selection_timestamp_list_does_not_include_deselected_rooms(app, monkeypatch):
    ss = seed(app)
    seed(app, 'P4301')
    ss.update(print_room_options=['P4102', 'P4301'], print_rooms=['P4301'])
    events = capture_page(app, monkeypatch)
    app.print_all_page(Store())
    table = next(text for kind, text in events if kind == 'markdown' and 'Handoff save status' in text)
    assert 'P4301' in table and 'P4102' not in table


def test_session_testing_screen_never_claims_github_save(app, monkeypatch):
    seed(app)
    events = capture_page(app, monkeypatch)
    app.print_all_page(None)
    table = next(text for kind, text in events if kind == 'markdown' and 'Handoff save status' in text)
    assert 'Last session save (Eastern)' in table
    assert any('Most recent session-only handoff save' in text for kind, text in events)


def test_create_and_edit_do_not_change_last_confirmed_time(app):
    seed(app)
    app.st.session_state['paste'] = 'aaaaaaaa\nDiagnoses:\n1. Synthetic new value\naaaaaaaa'
    app.create_handoff()
    state = app.display_room_save_status('P4102', object())
    assert state.last_saved == DISPLAY and state.unsaved


def test_export_never_advances_save_timestamp_or_storage(app):
    from exports import handoff_html, handoff_text, handoff_pdf
    ss = seed(app)
    original = deepcopy(ss['vault'])
    sheet = ss['drafts']['P4102']
    for renderer in [handoff_html, handoff_text, handoff_pdf]:
        assert renderer(sheet)
    assert ss['vault'] == original
    assert app.display_room_save_status('P4102', object()).last_saved == DISPLAY


def test_same_schema_roundtrip_preserves_all_times_and_custom_rooms():
    vault = new_vault()
    vault['rooms'] = {'P4102': saved_sheet(), 'P4301': saved_sheet('P4301', LATER)}
    before = deepcopy(vault)
    key = generate_key()
    restored = open_vault(seal_vault(vault, key), key)
    assert restored == before and SCHEMA_VERSION ==33
    assert room_save_status('P4301', restored['rooms']['P4301']).last_saved == LATER_DISPLAY
