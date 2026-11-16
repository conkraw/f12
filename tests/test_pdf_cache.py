"""6.79 synthetic cache, PDF parity, freshness and integration regressions.

No real patient information, browser, or live shared archive is used here.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
import time

import fitz
import pytest

import exports
from census_guard import guard_download, saved_room_version
from devices import parse_devices
from importing import import_replacement
from lab_windows import display_clock
from labs import parse_labs
from models import new_sheet, new_vault, save_sheet_in, SYSTEMS
from pdf_cache import SessionPdfCache, cached_handoffs_pdf
from save_status import room_save_status
from test_callbacks import app, open_room
from test_compact_pn import sheet as compact_sheet
from test_print_fit_reset import long_column
from test_room_replacement import Store, NEW

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def specimen(room='P4102', text='SYNTHETIC CURRENT HANDOFF'):
    sheet = new_sheet(room)
    sheet['fields']['Diagnoses'] = text
    return sheet


def pdf_text(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(page.get_text() for page in doc)


def lab_sheet(component, value='12.4', date='11/15/2026 07:00'):
    sheet = specimen()
    parsed = parse_labs('LABS:\nComponent\tValue\tDate\n' + '\t'.join((component, value, date)))
    assert not parsed.error
    sheet['labs'] = parsed.data
    return sheet


@pytest.mark.parametrize('target', [1, 2])
@pytest.mark.parametrize('kind', ['simple', 'compact', 'dense', 'overflow'])
def test_cached_packet_is_pixel_identical_to_existing_renderer(target, kind):
    sheet = {'simple': specimen, 'compact': compact_sheet,
             'dense': lambda: long_column(36), 'overflow': lambda: long_column(140)}[kind]()
    cache = SessionPdfCache()
    before = deepcopy(sheet)
    regular = exports.handoffs_pdf([sheet], NOW, target_pages=target)
    reused = cached_handoffs_pdf([sheet], cache, NOW, target_pages=target)
    with fitz.open(stream=regular, filetype='pdf') as old, fitz.open(stream=reused, filetype='pdf') as new:
        assert len(old) == len(new) == cache.prepare(sheet, NOW, target_pages=target).page_count
        for a, b in zip(old, new):
            assert a.rect == b.rect
            assert a.get_pixmap(matrix=fitz.Matrix(1, 1)).samples == b.get_pixmap(matrix=fitz.Matrix(1, 1)).samples
    assert sheet == before


def test_import_preparation_is_reused_for_single_and_all_and_repeat():
    cache = SessionPdfCache()
    sheets = [specimen(), specimen('P4104')]
    for sheet in sheets:
        cache.prepare(sheet, NOW)
    assert cache.stats['builds'] == 2
    cached_handoffs_pdf(sheets[:1], cache, NOW + timedelta(minutes=1))
    cached_handoffs_pdf(sheets, cache, NOW + timedelta(minutes=2))
    cached_handoffs_pdf(sheets, cache, NOW + timedelta(minutes=3))
    assert cache.stats['builds'] == 2 and cache.stats['hits'] == 5


@pytest.mark.parametrize('section', SYSTEMS)
def test_edit_regenerates_only_the_changed_room(section):
    cache = SessionPdfCache()
    sheets = [specimen(), specimen('P4104')]
    for sheet in sheets:
        cache.prepare(sheet, NOW)
    sheets[0]['fields'][section] = 'NEW_SYNTHETIC_FIELD_CONTENT'
    result = cached_handoffs_pdf(sheets, cache, NOW)
    assert cache.stats['builds'] == 3
    # Labs is a legacy mapping field, not a printable free-text column.
    if section != 'Labs':
        assert 'NEW_SYNTHETIC_FIELD_CONTENT' in ''.join(pdf_text(result).split())


def test_room_replacement_never_uses_previous_pdf():
    cache = SessionPdfCache()
    old, other = specimen(text='OLD_PATIENT_SENTINEL'), specimen('P4104', 'OTHER_PATIENT_SENTINEL')
    cached_handoffs_pdf([old, other], cache, NOW)
    replacement = specimen(text='NEW_PATIENT_SENTINEL')
    result = cached_handoffs_pdf([replacement, other], cache, NOW)
    text = ''.join(pdf_text(result).split())
    assert 'NEW_PATIENT_SENTINEL' in text and 'OTHER_PATIENT_SENTINEL' in text
    assert 'OLD_PATIENT_SENTINEL' not in text and old['id'][:8] not in text
    assert cache.stats['builds'] == 3


def test_save_timestamp_and_status_change_only_metadata():
    cache = SessionPdfCache()
    sheet = specimen()
    body = cache.prepare(sheet, NOW)
    assert 'Print prepared:' not in pdf_text(body.data) and 'Last saved:' not in pdf_text(body.data)
    sheet['updated_at'] = '2026-11-16T12:01:00+00:00'
    status = room_save_status('P4102', sheet, sheet, session_only=True)
    data = cached_handoffs_pdf([sheet], cache, NOW + timedelta(minutes=2),
                              save_statuses={'P4102': status})
    text = pdf_text(data)
    assert cache.stats['builds'] == 1
    assert 'Last session save: 11/16/2026 07:01:00 AM EST' in text
    assert 'Print prepared: 11/16/2026 07:02:00 AM EST' in text
    assert '07:00:00 AM EST' not in text


def test_page_target_keeps_two_separate_variants_without_rebuilding():
    cache = SessionPdfCache()
    sheet = long_column(40)
    for target in (1, 2, 1, 2):
        cached_handoffs_pdf([sheet], cache, NOW, target_pages=target)
    assert cache.stats['builds'] == 2 and cache.stats['entries'] == 2


def test_order_selection_and_packet_numbers_refresh_without_rebuilding():
    cache = SessionPdfCache()
    a, b = specimen(), specimen('P4104')
    cached_handoffs_pdf([a, b], cache, NOW)
    data = cached_handoffs_pdf([b, a], cache, NOW + timedelta(minutes=1))
    with fitz.open(stream=data, filetype='pdf') as doc:
        assert 'Room P4104' in doc[0].get_text() and 'Sheet 1/2' in doc[0].get_text()
        assert 'Room P4102' in doc[1].get_text() and 'Sheet 2/2' in doc[1].get_text()
    text = pdf_text(cached_handoffs_pdf([b], cache, NOW))
    assert 'Sheet 1/1' in text and 'Room P4102' not in text
    assert cache.stats['builds'] == 2


@pytest.mark.parametrize('component,value', [('VANCOTROUGH', '12.4'), ('THEOPH', '8.2'),
                         ('CK', '100'), ('METHB', '1.2'), ('O2SATV', '75'), ('LACTATE', '2.3')])
def test_exact_24_hour_boundary_rebuilds_without_waiting_for_ttl(component, value):
    sheet = lab_sheet(component, value)
    cache = SessionPdfCache()
    at_boundary = cache.prepare(sheet, NOW)
    # At exactly 24 hours, the included source remains valid.
    cache.prepare(sheet, NOW - timedelta(microseconds=1))
    assert cache.stats['builds'] == 1
    expired = cache.prepare(sheet, NOW + timedelta(microseconds=1))
    assert at_boundary.signature != expired.signature and cache.stats['builds'] == 2
    assert sheet['labs']['rows'][0]['value'] == value


def test_line_days_rebuild_at_eastern_midnight():
    sheet = specimen()
    parsed = parse_devices('PICC 11/15/26 Right Arm-Site Assessment: Clean')
    assert not parsed.error
    sheet['devices'] = parsed.data
    before = datetime(2026, 11, 16, 4, 59, tzinfo=timezone.utc)
    after = before + timedelta(minutes=2)
    cache = SessionPdfCache()
    a = cache.prepare(sheet, before)
    b = cache.prepare(sheet, after)
    assert a.signature != b.signature and cache.stats['builds'] == 2
    assert 'Day 1' in pdf_text(a.data) and 'Day 2' in pdf_text(b.data)


def test_heplmw_midnight_relocation_refreshes_pdf():
    sheet = lab_sheet('HEPLMW', '0.56', '11/15/2026 12:00')
    cache = SessionPdfCache()
    before = datetime(2026, 11, 16, 4, 59, tzinfo=timezone.utc)
    a = cache.prepare(sheet, before)
    b = cache.prepare(sheet, before + timedelta(minutes=2))
    assert a.signature != b.signature and cache.stats['builds'] == 2


def test_future_mrsa_becomes_eligible_without_source_edit():
    sheet = lab_sheet('MRSADNA', 'Positive', '11/16/2026 07:01')
    cache = SessionPdfCache()
    a = cache.prepare(sheet, NOW)
    b = cache.prepare(sheet, NOW + timedelta(minutes=2))
    assert a.signature != b.signature
    assert 'MRSA Screen:' not in pdf_text(a.data)
    assert 'MRSA Screen: Positive' in pdf_text(b.data)


def test_future_lab_value_change_rebuilds_even_when_date_is_unchanged():
    sheet = lab_sheet('NTPROBNP', '999', '11/16/2026 07:01')
    cache = SessionPdfCache()
    a = cache.prepare(sheet, NOW)
    b = cache.prepare(sheet, NOW + timedelta(minutes=2))
    assert a.signature != b.signature
    assert 'NT-proBNP: 999' not in pdf_text(a.data)
    assert 'NT-proBNP: 999' in pdf_text(b.data)


def test_no_same_patient_fallback_when_new_render_fails(monkeypatch):
    sheet = specimen()
    cache = SessionPdfCache()
    cache.prepare(sheet, NOW)
    sheet['fields']['Neurologic'] = 'NEW NOTE'
    def fail(*args, **kwargs):
        raise RuntimeError('SYNTHETIC_FAILURE')
    monkeypatch.setattr(exports, 'handoff_pdf_body', fail)
    with pytest.raises(RuntimeError):
        cache.prepare(sheet, NOW)
    assert cache.stats['entries'] == 0 and cache.stats['bytes'] == 0


def test_renderer_version_change_invalidates_cached_pdf(monkeypatch):
    sheet, cache = specimen(), SessionPdfCache()
    cache.prepare(sheet, NOW)
    original = exports.pdf_content_signature
    monkeypatch.setattr(exports, 'pdf_content_signature', lambda *a, **kw: 'new-renderer:' + original(*a, **kw))
    cache.prepare(sheet, NOW)
    assert cache.stats['builds'] == 2


def test_threaded_simultaneous_downloads_build_each_room_only_once():
    cache, sheet = SessionPdfCache(), specimen()
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: cached_handoffs_pdf([sheet], cache, NOW), range(4)))
    assert all('SYNTHETICCURRENTHANDOFF' in ''.join(pdf_text(data).split()) for data in outputs)
    assert cache.stats['builds'] == 1


def test_caches_are_private_per_instance_and_never_shared():
    a, b, sheet = SessionPdfCache(), SessionPdfCache(), specimen()
    a.prepare(sheet, NOW)
    assert b.stats['entries'] == 0
    b.prepare(sheet, NOW)
    assert a.stats['builds'] == b.stats['builds'] == 1
    a.close()
    assert a.stats['bytes'] == 0 and b.stats['bytes'] > 0
    with pytest.raises(ValueError, match='cleared'):
        a.prepare(sheet, NOW)


def test_lru_entry_limits_evict_and_regenerate_only_when_needed():
    cache = SessionPdfCache(max_entries=1)
    a, b = specimen(), specimen('P4104')
    cache.prepare(a, NOW)
    cache.prepare(b, NOW)
    assert cache.stats['entries'] == 1
    cache.prepare(a, NOW)
    assert cache.stats['builds'] == 3


def test_oversize_pdf_can_print_without_violating_memory_bound():
    cache = SessionPdfCache(max_bytes=1)
    result = cached_handoffs_pdf([specimen()], cache, NOW)
    assert result.startswith(b'%PDF-') and cache.stats['entries'] == cache.stats['bytes'] == 0


@pytest.mark.parametrize('target', [0, 3, True, None, '1'])
def test_invalid_page_target_fails_closed(target):
    with pytest.raises(ValueError):
        cached_handoffs_pdf([specimen()], SessionPdfCache(), NOW, target_pages=target)


@pytest.mark.parametrize('kind', ['empty', 'duplicate', 'overlimit'])
def test_invalid_packet_rejected(kind):
    sheet = specimen()
    sheets = {'empty': [], 'duplicate': [sheet, deepcopy(sheet)], 'overlimit': [sheet] * 101}[kind]
    with pytest.raises(ValueError):
        cached_handoffs_pdf(sheets, SessionPdfCache(), NOW)


def test_status_for_wrong_room_cannot_be_stamped():
    sheet = specimen()
    wrong = room_save_status('P4104', specimen('P4104'))
    with pytest.raises(ValueError, match='does not match'):
        cached_handoffs_pdf([sheet], SessionPdfCache(), NOW, save_statuses={'P4102': wrong})


def test_download_worker_captures_private_snapshot_and_refreshes_timestamp():
    sheet, cache = specimen(), SessionPdfCache()
    with display_clock(NOW):
        cache.prepare(sheet)
        generate = exports.download_payload([sheet], 'pdf', pdf_cache=cache)
    sheet['fields']['Diagnoses'] = 'AFTER_SNAPSHOT_MUTATION'
    with display_clock(NOW + timedelta(minutes=1)):
        data = generate()
    assert cache.stats['builds'] == 1
    assert 'AFTER_SNAPSHOT_MUTATION' not in pdf_text(data)
    assert 'Print prepared: 11/16/2026 07:01:00 AM EST' in pdf_text(data)


@pytest.mark.parametrize('mode', ['expired', 'revoked'])
def test_cached_download_cannot_bypass_session_expiry_or_revocation(mode):
    cache, sheet, cancelled = SessionPdfCache(), specimen(), Event()
    cache.prepare(sheet, NOW)
    deadline = time.monotonic() - 1 if mode == 'expired' else None
    generate = exports.download_payload([sheet], 'pdf', deadline, cancelled=cancelled, pdf_cache=cache)
    if mode == 'revoked':
        cancelled.set()
    with pytest.raises(ValueError):
        generate()


@pytest.mark.parametrize('when', ['before', 'during'])
def test_shared_same_id_same_timestamp_edit_rejected(when):
    vault = save_sheet_in(new_vault(), specimen())
    store = Store(vault)
    original = deepcopy(vault['rooms']['P4102'])
    expected = {'P4102': saved_room_version(original)}
    def change():
        # Keep both id and updated_at unchanged to exercise a content-level guard.
        store.vault['rooms']['P4102']['fields']['Neurologic'] = 'CHANGED_ELSEWHERE'
    calls = []
    def generate():
        calls.append(True)
        if when == 'during':
            change()
        return b'OLD_BYTES'
    guarded = guard_download(generate, store, vault['reset_generation'], expected_versions=expected)
    if when == 'before':
        change()
    with pytest.raises(ValueError, match='patient list changed'):
        guarded()
    assert bool(calls) == (when == 'during')


def test_shared_unrelated_room_edit_does_not_block_selected_room():
    vault = save_sheet_in(save_sheet_in(new_vault(), specimen()), specimen('P4104'))
    store = Store(vault)
    expected = {'P4102': saved_room_version(vault['rooms']['P4102'])}
    store.vault['rooms']['P4104']['fields']['Other'] = 'UNRELATED_CHANGE'
    assert guard_download(lambda: b'OK', store, vault['reset_generation'], expected_versions=expected)() == b'OK'


def test_app_import_prepares_pdf_and_print_all_reuses(app):
    open_room(app)
    app.st.session_state['paste'] = NEW
    app.create_handoff()
    cache = app.session_pdf_cache()
    assert cache.stats['builds'] == 1
    sheet = app.st.session_state['drafts']['P4102']
    assert app.handoff_download([sheet], None)().startswith(b'%PDF-')
    assert cache.stats['builds'] == 1


def test_app_saved_edit_revokes_old_download_and_warms_new_pdf(app):
    open_room(app)
    app.st.session_state['paste'] = NEW
    app.create_handoff()
    ss = app.st.session_state
    old = app.handoff_download([ss['drafts']['P4102']], None)
    ss['drafts']['P4102']['fields']['Other'] = 'LATEST_EDIT'
    app.save_room(None)
    with pytest.raises(ValueError, match='cleared'):
        old()
    assert app.session_pdf_cache().stats['builds'] == 2
    data = app.handoff_download([ss['drafts']['P4102']], None)()
    assert 'LATEST_EDIT' in pdf_text(data)
    assert app.session_pdf_cache().stats['builds'] == 2


@pytest.mark.parametrize('operation', ['logout', 'reset'])
def test_app_reset_logout_discards_cache_and_blocks_captured_workers(app, operation):
    open_room(app)
    app.st.session_state['paste'] = NEW
    app.create_handoff()
    cache = app.session_pdf_cache()
    generate = app.handoff_download([app.st.session_state['drafts']['P4102']], None)
    if operation == 'logout':
        app.clear_session()
    else:
        app.clear_all_handoffs(None)
    assert cache.closed and cache.stats['bytes'] == 0
    assert 'handoff_pdf_cache' not in app.st.session_state
    with pytest.raises(ValueError):
        generate()


def test_app_warm_failure_does_not_undo_successful_import(app, monkeypatch):
    open_room(app)
    app.st.session_state['paste'] = NEW
    def fail(*args, **kwargs):
        raise RuntimeError('DO_NOT_EXPOSE_THIS')
    monkeypatch.setattr(exports, 'handoff_pdf_body', fail)
    app.create_handoff()
    assert 'NEW_SYNTHETIC_PATIENT' in app.st.session_state['vault']['rooms']['P4102']['fields']['Diagnoses']
    assert 'DO_NOT_EXPOSE_THIS' not in str(app.st.session_state.get('notice'))
    assert 'retry' in app.st.session_state['notice'][1]
    with pytest.raises(ValueError, match='could not be generated'):
        app.handoff_download([app.st.session_state['drafts']['P4102']], None)()
