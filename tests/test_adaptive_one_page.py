"""Synthetic print-only compaction, content preservation and progress checks."""
from copy import deepcopy
from datetime import datetime, timezone

import fitz
import pytest

from devices import parse_devices
from difficult_airway import empty_airway
from exports import (handoff_pdf, handoff_pdf_body, handoff_text, handoff_html,
                     print_fit_report, _make_pdf_plan, _select_pdf_plan)
from models import new_sheet
from pdf_cache import SessionPdfCache, cached_handoffs_pdf


NOW = datetime(2026, 11, 20, 20, tzinfo=timezone.utc)


def goal_heavy_sheet():
    sheet = new_sheet('P4102')
    sheet['fields']['Diagnoses'] = 'CORE_DIAGNOSIS_SENTINEL'
    sheet['fields']['Goals / Follow-up'] = '\n'.join(
        f'GOAL_{index:03d} Synthetic follow-up detail.' for index in range(60))
    return sheet


def pdf_text(data):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return '\n'.join(page.get_text() for page in doc)


def test_already_fitting_sheet_keeps_goals_and_original_type():
    sheet = new_sheet('P4102')
    sheet['fields']['Goals / Follow-up'] = 'GOAL_KEEP_SENTINEL'
    report = print_fit_report(sheet)
    assert report['page_count'] == 1 and report['font_size'] == 8
    assert not report['goals_omitted'] and not report['compact_secondary']
    assert 'GOAL_KEEP_SENTINEL' in pdf_text(handoff_pdf(sheet, NOW))


def test_goal_omission_is_print_only_and_keeps_largest_core_type():
    sheet = goal_heavy_sheet()
    before = deepcopy(sheet)
    data, report = handoff_pdf_body(sheet, NOW)
    assert report['page_count'] == 1 and report['font_size'] == 8
    assert report['goals_omitted'] and report['compact_secondary']
    text = pdf_text(data)
    assert 'CORE_DIAGNOSIS_SENTINEL' in ''.join(text.split()) and 'GOAL_000' not in text
    assert 'Goals / Follow-up' not in text
    assert 'GOAL_000' in handoff_text(sheet, NOW)
    assert 'GOAL_059' in handoff_html(sheet, NOW)
    assert sheet == before


def test_explicit_two_page_target_keeps_goals_and_original_layout():
    sheet = goal_heavy_sheet()
    data, report = handoff_pdf_body(sheet, NOW, target_pages=2)
    assert report['page_count'] == 2 and report['font_size'] == 8
    assert not report['goals_omitted'] and not report['compact_secondary']
    text = pdf_text(data)
    for index in range(60):
        assert text.count(f'GOAL_{index:03d}') == 1


def test_secondary_compaction_keeps_all_orders_devices_and_airway_alert():
    sheet = new_sheet('P4102')
    sheet['fields']['Other Medications'] = '\n'.join(
        f'MED_TOKEN_{index:03d} recorded dose 1 mg oral daily' for index in range(60))
    sheet['fields']['Goals / Follow-up'] = 'GOAL_KEEP_SENTINEL'
    sheet['fields']['Access'] = 'ACCESS_SENTINEL'
    sheet['devices'] = parse_devices(
        'PICC 11/19/26 Right Arm-Site Assessment: Clean\n'
        'ETT 4 mm-Secured at (cm): 12 cm').data
    sheet['difficult_airway'] = dict(empty_airway(), enabled=True, issue='AIRWAY_SENTINEL')
    before = deepcopy(sheet)
    data, report = handoff_pdf_body(sheet, NOW)
    assert report['page_count'] == 1 and report['font_size'] == 8
    assert report['compact_secondary'] and report['secondary_font_size'] == 6
    assert not report['goals_omitted']
    with fitz.open(stream=data, filetype='pdf') as doc:
        text = ''.join(page.get_text() for page in doc)
        for index in range(60):
            assert text.count(f'MED_TOKEN_{index:03d}') == 1
        for value in ('PICC', 'Right Arm', '4 mm', '12 cm', 'GOAL_KEEP_SENTINEL',
                      'ACCESS_SENTINEL', 'AIRWAY_SENTINEL'):
            assert value in text
        spans = [span for page in doc for block in page.get_text('dict')['blocks']
                 for line in block.get('lines', []) for span in line['spans']]
        assert all(span['size'] == 6 for span in spans if 'MED_TOKEN_' in span['text'])
        assert all(span['size'] >= 8 for span in spans if 'AIRWAY_SENTINEL' in span['text'])
        for page in doc:
            for block in page.get_text('blocks'):
                assert 0 <= block[0] < block[2] <= 792.1
                assert 0 <= block[1] < block[3] <= 612.1
    assert sheet == before


def test_blank_footer_rows_removed_only_for_compact_plan():
    sheet = new_sheet('P4102')
    ordinary = _make_pdf_plan(sheet, 792, 8)
    compact = _make_pdf_plan(sheet, 792, 8, tight=True, compact_secondary=True)
    assert any(label == 'Other Medications' for label, _ in ordinary['bands'])
    assert ordinary['access']
    assert all(label != 'Other Medications' for label, _ in compact['bands'])
    assert compact['access'] == []


def test_continuation_preserves_every_core_note_and_still_omits_optional_goals():
    sheet = new_sheet('P4102')
    sheet['fields']['Neurologic'] = '\n'.join(
        f'CORE_{index:03d} Synthetic clinical detail' for index in range(100))
    sheet['fields']['Goals / Follow-up'] = 'GOAL_OMIT_SENTINEL'
    before = deepcopy(sheet)
    data, report = handoff_pdf_body(sheet, NOW)
    assert report['page_count'] > 1 and not report['target_met']
    assert report['goals_omitted'] and report['font_size'] >= 6.5
    text = pdf_text(data)
    for index in range(100):
        assert text.count(f'CORE_{index:03d}') == 1
    assert 'GOAL_OMIT_SENTINEL' not in text and sheet == before


@pytest.mark.parametrize('target', [1, 2])
def test_cached_fit_report_and_pdf_match_direct_output(target):
    sheet = goal_heavy_sheet()
    cache = SessionPdfCache()
    try:
        prepared = cache.prepare(sheet, NOW, target_pages=target)
        assert prepared.report == print_fit_report(sheet, target)
        direct = handoff_pdf(sheet, NOW, target_pages=target)
        cached = cached_handoffs_pdf([sheet], cache, NOW, target_pages=target)
        with fitz.open(stream=direct, filetype='pdf') as a, fitz.open(stream=cached, filetype='pdf') as b:
            assert len(a) == len(b) == prepared.page_count
            for first, second in zip(a, b):
                assert first.get_pixmap().samples == second.get_pixmap().samples
    finally:
        cache.close()


def test_packet_progress_and_reports_are_ordered_anonymous_and_reusable():
    sheets = [goal_heavy_sheet(), new_sheet('P4104')]
    cache = SessionPdfCache()
    events, reports = [], []
    try:
        for _ in range(2):
            events.clear()
            reports.clear()
            data = cached_handoffs_pdf(sheets, cache, NOW,
                on_progress=lambda *event: events.append(event), on_report=reports.append)
            assert data.startswith(b'%PDF-')
            assert events == [(0, 2, 'preparing'), (1, 2, 'preparing'),
                              (2, 2, 'preparing'), (2, 2, 'assembling'), (2, 2, 'complete')]
            assert len(reports) == 2 and reports[0]['goals_omitted']
            assert all('room' not in report and 'id' not in report for report in reports)
        assert cache.stats['builds'] == 2
    finally:
        cache.close()


def test_failed_packet_never_reports_complete(monkeypatch):
    cache = SessionPdfCache()
    events, reports = [], []
    prepare = cache.prepare
    def fail_second(sheet, *args, **kwargs):
        if sheet['room'] == 'P4104':
            raise ValueError('Synthetic render failure')
        return prepare(sheet, *args, **kwargs)
    monkeypatch.setattr(cache, 'prepare', fail_second)
    try:
        with pytest.raises(ValueError, match='Synthetic render failure'):
            cached_handoffs_pdf([new_sheet('P4102'), new_sheet('P4104')], cache, NOW,
                on_progress=lambda *event: events.append(event), on_report=reports.append)
        assert events == [(0, 2, 'preparing'), (1, 2, 'preparing')]
        assert len(reports) == 1
    finally:
        cache.close()


def test_display_callback_failure_does_not_change_pdf():
    cache = SessionPdfCache()
    sheet = new_sheet('P4102')
    def broken_display(*args):
        raise RuntimeError('Synthetic unavailable UI')
    try:
        data = cached_handoffs_pdf([sheet], cache, NOW,
                                  on_progress=broken_display, on_report=broken_display)
        assert 'Room: P4102' in pdf_text(data)
    finally:
        cache.close()
