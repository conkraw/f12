"""Synthetic font-size, pagination and per-session preference regressions."""
from copy import deepcopy
from datetime import datetime, timezone
from threading import Event
import math
import time
import fitz
import pytest
from models import new_sheet, new_vault, save_sheet_in
from exports import (handoff_pdf, handoffs_pdf, handoff_html, handoffs_html,
                     print_fit_report, download_payload, handoff_text)
from print_options import (validated_font_size, font_candidates, preferences,
                           capture_preferences, PREFERENCES_KEY)
from lab_layout import laboratory_flowables, LabRow
from labs import parse_labs
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_compact_pn import sheet as compact_sheet

STAMP = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)


def dense(n=70, room='P4102'):
    s = new_sheet(room)
    s['fields']['Diagnoses'] = 'SYNTHETIC_FONT_TEST'
    s['fields']['Neurologic'] = '\n'.join(f'ITEM_{i:03d} Synthetic clinical detail.' for i in range(n))
    return s


@pytest.mark.parametrize('size', [6.5, 7.2, 8, 8.7, 9, 10, 12, 14])
def test_requested_font_exact_and_report_matches_pdf(size):
    s = dense()
    before = deepcopy(s)
    report = print_fit_report(s, font_size=size, auto_fit=False)
    document = fitz.open(stream=handoff_pdf(s, STAMP, font_size=size, auto_fit=False), filetype='pdf')
    assert report['page_count'] == len(document)
    assert report['font_size'] == float(size)
    assert report['target_met'] == (len(document) == 1)
    spans = [span for page in document for block in page.get_text('dict')['blocks'] if 'lines' in block
             for line in block['lines'] for span in line['spans']]
    token_spans = [span for span in spans if 'ITEM_' in span['text']]
    assert token_spans
    assert all(abs(span['size'] - size) < .02 for span in token_spans)
    text = ''.join(page.get_text() for page in document)
    for index in range(70):
        assert text.count(f'ITEM_{index:03d}') == 1
    for page in document:
        for block in page.get_text('blocks'):
            assert 0 <= block[0] < block[2] <= 792.1
            assert 0 <= block[1] < block[3] <= 612.1
    assert s == before


def test_fixed_size_may_exceed_target_without_shrinking():
    report = print_fit_report(dense(140), font_size=12, auto_fit=False)
    assert report['page_count'] > 2 and report['font_size'] == 12
    assert not report['target_met']


@pytest.mark.parametrize('target', [1, 2])
def test_opt_in_auto_fit_uses_no_larger_than_requested_and_keeps_everything(target):
    s = dense(45)
    report = print_fit_report(s, target, font_size=14, auto_fit=True)
    fixed = print_fit_report(s, target, font_size=14, auto_fit=False)
    document = fitz.open(stream=handoff_pdf(s, STAMP, target_pages=target, font_size=14, auto_fit=True), filetype='pdf')
    assert len(document) == report['page_count'] <= fixed['page_count']
    assert 6.5 <= report['font_size'] <= 14
    assert report['font_size'] < 14
    text = ''.join(page.get_text() for page in document)
    for index in range(45):
        assert text.count(f'ITEM_{index:03d}') == 1


@pytest.mark.parametrize('bad', [True, False, '9', '', [], {}, float('nan'), float('inf'), -1, 0, 6.49, 14.01, 100])
def test_invalid_size_is_rejected_before_rendering(bad):
    with pytest.raises(ValueError):
        handoff_pdf(new_sheet('P4102'), font_size=bad, auto_fit=False)
    with pytest.raises(ValueError):
        handoff_html(new_sheet('P4102'), font_size=bad)
    with pytest.raises(ValueError):
        download_payload([new_sheet('P4102')], 'pdf', font_size=bad)


@pytest.mark.parametrize('bad', [0, 1, 'true', None])
def test_invalid_auto_fit_is_rejected(bad):
    with pytest.raises(ValueError):
        handoff_pdf(new_sheet('P4102'), font_size=9, auto_fit=bad)


def test_legacy_callers_keep_existing_default_layout():
    s = new_sheet('P4102')
    report = print_fit_report(s)
    assert report['font_size'] == 7.2 and report['page_count'] == 1
    assert report['requested_font_size'] is None
    assert 'font-size:7.2pt' in handoff_html(s)


def test_font_candidates_obey_bounds_and_permission():
    assert font_candidates(9, False) == (9.,)
    assert font_candidates(6.5, True) == (6.5,)
    candidates = font_candidates(9.1, True)
    assert candidates[0] == 9.1 and candidates[-1] == 6.5
    assert all(a > b for a, b in zip(candidates, candidates[1:]))


@pytest.mark.parametrize('size', [8, 9, 10, 14])
def test_lab_values_are_resized_and_do_not_change(size):
    s = compact_sheet()
    before = deepcopy(s)
    document = fitz.open(stream=handoff_pdf(s, STAMP, font_size=size, auto_fit=False), filetype='pdf')
    spans = [span for page in document for block in page.get_text('dict')['blocks'] if 'lines' in block
             for line in block['lines'] for span in line['spans']]
    assert any(abs(span['size'] - size) < .02 and any(ch.isdigit() for ch in span['text']) for span in spans)
    text = ''.join(page.get_text() for page in document)
    for token in ('Hepatic', 'Coagulation', 'Pediatric 2-in-1 PN', 'And: fat emulsion', '[Held by provider]'):
        assert token in text
    assert s == before
    assert print_fit_report(s, font_size=size, auto_fit=False)['page_count'] == len(document)


def test_large_lab_trees_use_wider_cards_instead_of_clipped_values():
    data = parse_labs('Lab Results\nComponent\tValue\tDate\nNA\t140\t11/08/2026\nK\t4.1\t11/08/2026\nCL\t103\t11/08/2026\nCO2\t24\t11/08/2026\nBUN\t12\t11/08/2026\nCREATININE\t0.123456789\t11/08/2026\nGLUCOSE\t100\t11/08/2026').data
    items = laboratory_flowables(data, 750, 14, tree_font_size=14)
    trees = [item for item in items if isinstance(item, LabRow)]
    assert trees and trees[0].cell_width >= 375
    value_sizes = [item[4] for tree in trees for _, plan in tree.plans for item in plan if item[0] == 'text' and item[3] == '140']
    assert value_sizes == [14.0]


def test_combined_pdf_count_is_sum_of_individuals_and_room_starts_are_separate():
    a, b = dense(45), dense(80, 'P4104')
    expected_a = print_fit_report(a, font_size=10, auto_fit=False)['page_count']
    expected_b = print_fit_report(b, font_size=10, auto_fit=False)['page_count']
    doc = fitz.open(stream=handoffs_pdf([a, b], STAMP, font_size=10, auto_fit=False), filetype='pdf')
    assert len(doc) == expected_a + expected_b
    assert 'Room P4102' in doc[0].get_text()
    assert 'Room P4104' in doc[expected_a].get_text()


def test_download_captures_font_and_content_without_mutating_original():
    s = dense(15)
    payload = download_payload([s], 'pdf', font_size=10, auto_fit=False)
    s['fields']['Neurologic'] = 'CHANGED_AFTER_PREPARING'
    doc = fitz.open(stream=payload(), filetype='pdf')
    text = ''.join(page.get_text() for page in doc)
    assert 'ITEM_014' in text and 'CHANGED_AFTER_PREPARING' not in text
    sizes = [span['size'] for page in doc for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines'] for span in line['spans'] if 'ITEM_' in span['text']]
    assert sizes and all(abs(size - 10) < .02 for size in sizes)


def test_sized_downloads_remain_revocable_and_expire():
    event = Event()
    payload = download_payload([dense(1)], 'pdf', font_size=10, auto_fit=False, cancelled=event)
    event.set()
    with pytest.raises(ValueError, match='cleared'):
        payload()
    payload = download_payload([dense(1)], 'pdf', expires_at=time.monotonic()-1, font_size=10)
    with pytest.raises(ValueError, match='expired'):
        payload()


def test_html_uses_requested_size_even_when_pdf_auto_fits():
    s = dense()
    assert 'font-size:10pt' in handoff_html(s, STAMP, font_size=10)
    assert 'font-size:10pt' in handoffs_html([s], STAMP, font_size=10)
    assert b'font-size:10pt' in download_payload([s], 'html', font_size=10, auto_fit=True)()


def test_print_preferences_defaults_corruption_and_session_isolation():
    first, second = {}, {}
    assert preferences(first) == dict(font_size=7.2, auto_fit=False, target_pages=1)
    first.update(room_print_font_size=10., room_print_auto_fit=True, room_print_target_pages=2)
    capture_preferences(first, 'room_print')
    assert preferences(first) == dict(font_size=10., auto_fit=True, target_pages=2)
    assert preferences(second) == dict(font_size=7.2, auto_fit=False, target_pages=1)
    first[PREFERENCES_KEY] = dict(font_size='bad', auto_fit='bad', target_pages=100)
    assert preferences(first) == preferences(second)


def test_controls_follow_room_and_print_all_without_touching_archive(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    before = deepcopy(ss['vault']), deepcopy(ss['drafts'])
    equip(app, monkeypatch)
    app.print_size_controls('room_print')
    ss['room_print_font_size'] = 10.
    ss['room_print_auto_fit'] = False
    ss['room_print_target_pages'] = 2
    app.update_print_preferences('room_print')
    # Simulate widget cleanup when switching workspaces.
    for key in list(ss):
        if key.startswith('room_print_'):
            del ss[key]
    options = app.print_size_controls('all_print')
    assert options == dict(font_size=10., auto_fit=False, target_pages=2)
    assert (ss['vault'], ss['drafts']) == before


def test_print_controls_rehydrate_after_widget_cleanup(app, monkeypatch):
    open_room(app)
    ss = app.st.session_state
    ss[PREFERENCES_KEY] = dict(font_size=8.5, auto_fit=True, target_pages=2)
    equip(app, monkeypatch)
    options = app.print_size_controls('room_print')
    assert options == dict(font_size=8.5, auto_fit=True, target_pages=2)
    app.clear_session()
    assert preferences(ss) == dict(font_size=7.2, auto_fit=False, target_pages=1)


def test_fixed_size_ui_warns_and_displays_actual_size(app, monkeypatch):
    equip(app, monkeypatch)
    warnings, markup = [], []
    app.st.warning = warnings.append
    app.st.markdown = lambda value, **kwargs: markup.append(value)
    app.render_print_fit([dense(140)], 1, font_size=12, auto_fit=False)
    assert warnings and 'Your chosen size is kept' in warnings[0]
    assert any('12.0 pt' in value for value in markup)
