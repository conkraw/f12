"""Whole-room replacement regressions. Synthetic source and storage only."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
from threading import Event

import pytest

from test_callbacks import app, open_room
from models import new_sheet, new_vault, save_sheet_in, validate_sheet
from importing import import_replacement, import_sections
from difficult_airway import empty_airway
from import_review import diagnostic_text, review_summary
from medications import upsert_rule
from exports import handoff_text, handoff_html
from batching import available_handoffs
from security import seal_vault, open_vault, generate_key
from github_store import ConflictError, StorageError
from census_guard import guard_download
from user_guide import LEGACY_DEFAULT_INSTRUCTIONS, DEFAULT_INSTRUCTIONS, handoff_instructions, default_guide
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
NEW = 'aaaaaaaa\nDiagnoses:\n1. NEW_SYNTHETIC_PATIENT\naaaaaaaa'


def rich_old():
    sheet = new_sheet('P4102')
    for name in ('synthetic_smartphrase.txt', 'synthetic_cbc_smartphrase.txt',
                 'synthetic_cultures_ads.txt', 'synthetic_viral_positive.txt',
                 'synthetic_feeds.txt', 'synthetic_devices_smartphrase.txt',
                 'synthetic_pacemaker.txt', 'synthetic_dietary_orders.txt',
                 'synthetic_mrsa_epidural_sodium_line_days.txt'):
        parsed = import_sections(sheet, (ROOT/'examples'/name).read_text(), new_vault()['settings'])
        if parsed.sheet is not None:
            sheet = parsed.sheet
    for key in sheet['fields']:
        sheet['fields'][key] = 'OLD_SYNTHETIC_' + key
    sheet['difficult_airway'] = dict(empty_airway(), enabled=True, issue='OLD_AIRWAY_SENTINEL')
    validate_sheet(sheet)
    return sheet


class Store:
    def __init__(self, vault, failure=None, lost_ack=False):
        self.vault = deepcopy(vault)
        self.sha = 'old-sha'
        self.calls = []
        self.failure = failure
        self.lost_ack = lost_ack

    def save(self, candidate, sha):
        self.calls.append((deepcopy(candidate), sha))
        if self.failure:
            raise self.failure
        if sha != self.sha:
            raise ConflictError('Synthetic concurrent change')
        self.vault = deepcopy(candidate)
        self.sha = 'next-sha'
        if self.lost_ack:
            raise StorageError('Sensitive error detail must not be shown')
        return self.sha

    def load(self):
        return deepcopy(self.vault), self.sha


def setup(app):
    ss = app.st.session_state
    ss['vault'] = save_sheet_in(new_vault(), rich_old())
    other = new_sheet('P4104')
    other['fields']['Diagnoses'] = 'OTHER_ROOM_UNCHANGED'
    ss['vault'] = save_sheet_in(ss['vault'], other)
    ss['vault']['settings']['medication_mappings'] = upsert_rule([], 'acetaminophen', 'Neurologic')
    ss['vault_sha'] = 'old-sha'
    open_room(app)
    ss['paste'] = NEW
    return ss


def clinical_only(sheet):
    return {k: deepcopy(v) for k, v in sheet.items() if k not in ('id', 'created_at', 'updated_at')}


def test_application_has_no_section_merge_import_entrypoint(app):
    assert not hasattr(app, 'import_sections')
    source = inspect.getsource(app.create_handoff)
    assert 'import_replacement(room,' in source
    assert 'editor_snapshot(room)' not in source


@pytest.mark.parametrize('store_enabled', [True, False])
def test_whole_record_replaced_and_saved_with_no_old_fields(app, store_enabled):
    ss = setup(app)
    before = deepcopy(ss['vault'])
    old_id = ss['drafts']['P4102']['id']
    store = Store(before) if store_enabled else None
    app.create_handoff(store)
    replacement = ss['drafts']['P4102']
    expected = import_replacement('P4102', NEW, before['settings']).sheet
    assert replacement['id'] != old_id
    assert clinical_only(replacement) == clinical_only(expected)
    assert ss['vault']['rooms']['P4102'] == replacement == ss['base_sheets']['P4102']
    assert replacement['updated_at']
    assert ss['vault']['rooms']['P4104'] == before['rooms']['P4104']
    assert ss['vault']['settings'] == before['settings']
    assert ss['vault']['reset_generation'] == before['reset_generation']
    assert 'OLD_SYNTHETIC_' not in json.dumps(replacement)
    assert 'OLD_AIRWAY_SENTINEL' not in json.dumps(replacement)
    assert ss['paste'] == ''
    if store:
        assert len(store.calls) == 1
        assert store.vault == ss['vault']
        assert 'shared storage' in ss['notice'][1]
    else:
        assert 'session only' in ss['notice'][1]


def test_stale_widgets_diagnostics_and_print_callbacks_cannot_restore_old_patient(app):
    ss = setup(app)
    old_id = ss['drafts']['P4102']['id']
    stale_key = app.edit_key(ss['drafts']['P4102'], 'Neurologic')
    ss[stale_key] = 'OLD_LAST_SECOND_EDIT'
    ss['dairway_' + old_id + '_issue'] = 'OLD_AIRWAY_WIDGET'
    ss['workspace_imports'] = {old_id: {'notices': ['OLD_IMPORT_MESSAGE']}}
    ss['workspace_notices'] = {old_id: ('info', 'OLD_ACTION_MESSAGE')}
    old_download = app.download_revocation()
    app.create_handoff(Store(ss['vault']))
    assert stale_key not in ss
    assert not any(k.startswith('dairway_' + old_id) for k in ss)
    assert old_id not in ss['workspace_imports'] and old_id not in ss['workspace_notices']
    assert old_download.is_set() and not app.download_revocation().is_set()
    # Even an old callback delivered after replacement has no old widget value.
    app.update_field('P4102', 'Neurologic', stale_key)
    assert 'OLD_' not in json.dumps(app.editor_snapshot('P4102'))
    app.save_all_rooms(None)
    assert 'OLD_' not in json.dumps(ss['vault']['rooms']['P4102'])


@pytest.mark.parametrize('kind', ['text', 'html', 'batch', 'encrypted'])
def test_only_new_record_reaches_output_and_reloaded_archive(app, kind):
    ss = setup(app)
    app.create_handoff(Store(ss['vault']))
    if kind == 'text':
        output = handoff_text(ss['drafts']['P4102'])
    elif kind == 'html':
        output = handoff_html(ss['drafts']['P4102'])
    elif kind == 'batch':
        output = json.dumps(available_handoffs(ss['vault'], ss['drafts'])['P4102'])
    else:
        key = generate_key()
        restored = open_vault(seal_vault(ss['vault'], key), key)
        output = json.dumps(restored['rooms']['P4102'])
    assert 'NEW_SYNTHETIC_PATIENT' in output
    assert 'OLD_' not in output


@pytest.mark.parametrize('source', ['', 'unsupported source', 'aaaaaaaa\nDiagnoses:\n1. Unclosed',
                                   NEW+'\n'+NEW,
                                   'bbbbbbbb\nMedications:\nMALFORMED\nbbbbbbbb'])
def test_unusable_paste_never_deletes_or_merges_previous_record(app, source):
    ss = setup(app)
    ss['paste'] = source
    before = {k: deepcopy(ss[k]) for k in ('vault', 'drafts', 'base_sheets')}
    store = Store(ss['vault'])
    app.create_handoff(store)
    assert not store.calls
    assert all(ss[k] == value for k, value in before.items())
    assert ss['paste'] == source
    assert 'NOT replaced' in ss['notice'][1]
    assert ss['notice'][0] == 'error'


@pytest.mark.parametrize('failure', [StorageError('SECRET_SOURCE_DETAIL'), ConflictError('SECRET_SOURCE_DETAIL'), RuntimeError('SECRET_SOURCE_DETAIL')])
def test_failed_save_keeps_old_record_and_new_paste_without_claiming_success(app, failure):
    ss = setup(app)
    before = {k: deepcopy(ss[k]) for k in ('vault', 'drafts', 'base_sheets')}
    store = Store(ss['vault'], failure=failure)
    revoked = app.download_revocation()
    app.create_handoff(store)
    assert len(store.calls) == 1
    assert all(ss[k] == value for k, value in before.items())
    assert ss['paste'] == NEW and not revoked.is_set()
    assert 'NOT confirmed' in ss['notice'][1]
    assert 'SECRET_SOURCE_DETAIL' not in str(ss['notice'])
    assert not ss['import_result']['imported']


def test_lost_ack_cannot_restore_old_record_by_retry_or_save(app):
    ss = setup(app)
    old = deepcopy(ss['vault'])
    store = Store(old, lost_ack=True)
    app.create_handoff(store)
    assert store.vault['rooms']['P4102']['fields']['Diagnoses'] == 'NEW_SYNTHETIC_PATIENT'
    assert ss['vault'] == old
    store.lost_ack = False
    app.save_room(store)
    assert store.vault['rooms']['P4102']['fields']['Diagnoses'] == 'NEW_SYNTHETIC_PATIENT'
    assert ss['notice'][0] == 'error'


def test_stale_local_base_cannot_replace_newer_saved_room(app):
    ss = setup(app)
    newer = new_sheet('P4102')
    newer['fields']['Diagnoses'] = 'NEWER_SHARED_PATIENT'
    ss['vault'] = save_sheet_in(ss['vault'], newer)
    store = Store(ss['vault'])
    app.create_handoff(store)
    assert not store.calls
    assert 'saved room changed' in ss['notice'][1]
    assert ss['paste'] == NEW


def test_partial_new_phrase_omits_failed_section_without_old_values(app):
    ss = setup(app)
    ss['paste'] = NEW + '\nbbbbbbbb\nMedications:\nMALFORMED\nbbbbbbbb'
    app.create_handoff(Store(ss['vault']))
    sheet = ss['drafts']['P4102']
    assert sheet['fields']['Diagnoses'] == 'NEW_SYNTHETIC_PATIENT'
    assert sheet['medications'] == [] and sheet['ventilation'] is None
    assert ss['import_result']['errors'] and ss['notice'][0] == 'warning'
    assert 'OLD_' not in json.dumps(sheet)
    warnings = sheet['import_warnings']['b']
    assert all(item['action'] == 'not_imported' for item in warnings)
    assert 'No previous patient information was carried over' in diagnostic_text(warnings[0])
    assert 'no prior data retained' in review_summary(sheet)
    assert 'verify retained values' not in handoff_text(sheet)


def test_same_phrase_imported_again_also_clears_manual_edits(app):
    ss = setup(app)
    app.create_handoff(None)
    first_id = ss['drafts']['P4102']['id']
    ss['drafts']['P4102']['fields']['Goals / Follow-up'] = 'OLD_MANUAL_PLAN'
    ss['paste'] = NEW
    app.create_handoff(None)
    assert ss['drafts']['P4102']['id'] != first_id
    assert ss['drafts']['P4102']['fields']['Goals / Follow-up'] == ''


def test_no_patient_identity_comparison_or_extra_prompt_required(app):
    ss = setup(app)
    app.create_handoff(None)
    assert not ss.get('airway_update_pending')
    assert ss['drafts']['P4102']['fields']['Diagnoses'] == 'NEW_SYNTHETIC_PATIENT'


@pytest.mark.parametrize('stage', ['before', 'during'])
def test_download_rejects_room_replaced_in_another_session(stage):
    vault = save_sheet_in(new_vault(), rich_old())
    expected = {'P4102': vault['rooms']['P4102']['id']}
    store = Store(vault)
    called = []
    def replace():
        store.vault = save_sheet_in(store.vault, import_replacement('P4102', NEW, store.vault['settings']).sheet)
    def generate():
        called.append(True)
        if stage == 'during':
            replace()
        return b'OLD_PDF_BYTES'
    pending = guard_download(generate, store, vault['reset_generation'], expected_rooms=expected)
    if stage == 'before':
        replace()
    with pytest.raises(ValueError, match='patient list changed'):
        pending()
    assert bool(called) == (stage == 'during')


def test_other_room_replacement_does_not_invalidate_this_room_download():
    vault = save_sheet_in(new_vault(), rich_old())
    store = Store(vault)
    expected = {'P4102': vault['rooms']['P4102']['id']}
    pending = guard_download(lambda: b'CURRENT_ROOM_BYTES', store, vault['reset_generation'], expected_rooms=expected)
    store.vault = save_sheet_in(store.vault, new_sheet('P4104'))
    assert pending() == b'CURRENT_ROOM_BYTES'


def test_expected_room_snapshot_cannot_mutate_after_preparing_download():
    store = Store(save_sheet_in(new_vault(), rich_old()))
    expected = {'P4102': store.vault['rooms']['P4102']['id']}
    pending = guard_download(lambda: b'old', store, '', expected_rooms=expected)
    store.vault = save_sheet_in(store.vault, new_sheet('P4102'))
    expected['P4102'] = store.vault['rooms']['P4102']['id']
    with pytest.raises(ValueError):
        pending()


def test_local_stale_draft_cannot_prepare_pdf_after_archive_reload(app):
    ss = setup(app)
    ss['vault'] = save_sheet_in(ss['vault'], new_sheet('P4102'))
    with pytest.raises(ValueError, match='saved room changed'):
        app.handoff_download([ss['drafts']['P4102']], None)


def test_missing_saved_room_invalidates_prepared_download():
    store = Store(save_sheet_in(new_vault(), rich_old()))
    expected = {'P4102': store.vault['rooms']['P4102']['id']}
    pending = guard_download(lambda: b'old', store, '', expected_rooms=expected)
    store.vault['rooms'].pop('P4102')
    with pytest.raises(ValueError):
        pending()


def test_legacy_default_instructions_update_but_custom_text_does_not():
    guide = default_guide()
    guide['instructions'] = LEGACY_DEFAULT_INSTRUCTIONS
    assert handoff_instructions(guide) == DEFAULT_INSTRUCTIONS
    guide['instructions'] = 'My institution-specific instructions.'
    assert handoff_instructions(guide) == guide['instructions']


def test_user_sees_explicit_replacement_button_and_room_only_warning(app, monkeypatch):
    open_room(app)
    equip(app, monkeypatch)
    buttons, captions = [], []
    app.st.form_submit_button = lambda text, **kw: buttons.append(text) or False
    app.st.caption = lambda text, **kw: captions.append(str(text))
    app.handoff_page(None)
    assert 'Replace room handoff' in buttons
    assert any('Every import replaces and saves this room only' in text for text in captions)


@pytest.mark.parametrize('source', sorted((ROOT/'examples').glob('synthetic_*.txt')), ids=lambda p: p.stem)
def test_replacement_parser_preserves_new_source_parsing(source, monkeypatch):
    text = source.read_text()
    settings = new_vault()['settings']
    import uuid
    import sbs
    from datetime import datetime, timezone
    fixed = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
    real_clock = sbs.clock
    monkeypatch.setattr(sbs, 'clock', lambda at=None: real_clock(at) if at is not None else fixed)
    from itertools import count
    ids = count(1)
    monkeypatch.setattr(uuid, 'uuid4', lambda: uuid.UUID(int=next(ids)))
    low = import_sections(new_sheet('P4102'), text, settings)
    ids = count(1)
    replacement = import_replacement('P4102', text, settings)
    if low.sheet is None or not low.imported:
        assert replacement.sheet is None
    else:
        assert replacement.sheet is not None
        a, b = clinical_only(low.sheet), clinical_only(replacement.sheet)
        # Only warning wording/actions change, never newly parsed clinical data.
        a.pop('import_warnings', None)
        b.pop('import_warnings', None)
        assert a == b
