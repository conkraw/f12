from style_assert_helpers import without_style_tags
"""Display-only coagulation placement with preserved source rows and ID markers."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from pypdf import PdfReader

from exports import handoff_html, handoff_pdf, handoff_text, handoffs_pdf, handoffs_html
from importing import import_sections
from lab_layout import laboratory_html, laboratory_flowables, horizontal_card_markup
from labs import (parse_labs, result_cards, labs_text, id_labs_text,
                  display_component, canonical)
from models import new_vault, new_sheet, fields_with_medications, save_sheet_in, SCHEMA_VERSION
from security import generate_key, seal_vault, open_vault

ROOT = Path(__file__).parents[1]


def sample():
    result = import_sections(new_sheet('P4102'),
        (ROOT / 'examples' / 'synthetic_demographics_labs.txt').read_text(),
        new_vault()['settings'])
    assert not result.errors
    return result.sheet


def test_cards_keep_coagulation_immediately_after_hepatic():
    s = sample()
    titles = [c['title'] for c in result_cards(s['labs'], include_id_panels=False)]
    h = titles.index('Hepatic | latest')
    assert titles[h+1] == 'Coagulation | latest'
    assert not any(t.startswith('Inflammatory') for t in titles)


def test_card_preview_option_still_supports_all_laboratory_groups():
    titles = [c['title'] for c in result_cards(sample()['labs'], include_id_panels=True)]
    assert titles.count('Hepatic | latest') == 1
    assert titles.count('Coagulation | latest') == 1
    assert titles.count('Inflammatory | latest') == 1


def test_id_keeps_temperature_markers_cultures_and_notes_in_order():
    s = sample()
    s['fields']['Infectious Disease'] = 'ID note sentinel'
    f = fields_with_medications(s)
    text = f['Infectious Disease']
    assert text.index('Temp:') < text.index('Inflammatory markers') < text.index('Cultures') < text.index('ID note sentinel')
    for label in ['CRP:', 'PROCAL:']:
        assert label in text and label not in f['Lab Results / Trends']
    for label in ['PT:', 'INR:', 'PTT:', 'Anti-Xa (HEPLMW):']:
        assert label not in text and label in f['Lab Results / Trends']
    assert '1.2 (H) [01/04/26]' in text
    assert '0.14 [01/05/26]' in text


@pytest.mark.parametrize('source', ['PT', 'INR', 'PTT', 'FIB', 'HEPLMW', 'ANTI-XA'])
def test_coagulation_is_visible_without_a_hepatic_result(source):
    s = new_sheet('P4102')
    s['labs'] = parse_labs(f'{source}\t0.5 (H)\t01/06/2026').data
    f = fields_with_medications(s)
    assert 'Coagulation' in f['Lab Results / Trends']
    assert f'{display_component(source)}: 0.5 (H) [01/06/2026]' in f['Lab Results / Trends']
    assert f['Infectious Disease'].strip('-\n') == 'Cultures: None'


@pytest.mark.parametrize('source', ['CRP', 'C-REACTIVE PROTEIN', 'PROCAL', 'PROCALCITONIN'])
def test_inflammatory_aliases_remain_in_id_only(source):
    s = new_sheet('P4102')
    s['labs'] = parse_labs(f'{source}\t0.4 (H)\t01/06/2026').data
    s['admission_date'] = '01/01/2026'  # v6.30: ID markers require the encounter start
    before = deepcopy(s)
    f = fields_with_medications(s)
    assert source + ': 0.4 (H)' in f['Infectious Disease']
    assert not f['Lab Results / Trends']
    assert s == before


def test_latest_coag_values_and_individual_dates_are_kept():
    d = parse_labs('''ALT\t18\t01/06/2026
PT\t14.1 (H)\t01/06/2026
PT\t15.2 (H)\t01/05/2026
INR\t1.1\t01/05/2026
PTT\t29\t01/04/2026
HEPLMW\t0.46\t01/06/2026
HEPLMW\t0.38\t01/05/2026''').data
    before = deepcopy(d)
    card = next(c for c in result_cards(d, include_id_panels=False) if c['title'].startswith('Coagulation'))
    markup = without_style_tags(horizontal_card_markup(card))
    for text in ['PT: 14.1 (H) [01/06/26]', 'INR: 1.1 [01/05/26]', 'PTT: 29 [01/04/26]', 'Anti-Xa (HEPLMW): 0.46 [01/06/26]']:
        assert text in markup
    assert '15.2' not in markup and '0.38' not in markup
    assert d == before


def test_exclusion_moves_no_rows_and_can_be_restored():
    s = sample()
    old_rows = deepcopy(s['labs']['rows'])
    for row in s['labs']['rows']:
        if canonical(row['component']) in ('PT', 'INR', 'PTT', 'HEPLMW'):
            row['include'] = False
    assert 'Coagulation' not in fields_with_medications(s)['Lab Results / Trends']
    assert 'CRP:' in fields_with_medications(s)['Infectious Disease']
    assert len(s['labs']['rows']) == len(old_rows)
    s['labs']['rows'] = old_rows
    assert 'Coagulation' in fields_with_medications(s)['Lab Results / Trends']


def test_no_data_mutation_during_any_export():
    s = sample()
    before = deepcopy(s)
    for fn in [handoff_html, handoff_pdf, handoff_text]:
        fn(s)
        assert s == before
    assert SCHEMA_VERSION ==34


@pytest.mark.parametrize('exporter', [handoff_html, handoff_text])
def test_exports_put_coag_after_hepatic_without_duplicates(exporter):
    text = exporter(sample())
    assert text.index('Hepatic') < text.index('Coagulation') < text.index('Gas ART')
    for label in ['Coagulation', 'Anti-Xa (HEPLMW):', 'CRP:', 'PROCAL:']:
        assert text.count(label) == 1


def test_pdf_has_horizontal_coag_line_below_hepatic_and_markers_in_id():
    s = sample()
    doc = fitz.open(stream=handoff_pdf(s), filetype='pdf')
    assert len(doc) == 1
    page = doc[0]
    assert page.rect == fitz.Rect(0, 0, 792, 612)
    positions = {t: page.search_for(t)[0] for t in ['Hepatic', 'Coagulation', 'PT:', 'INR:', 'PTT:', 'Anti-Xa', 'CRP:', 'PROCAL:']}
    assert positions['Hepatic'].y0 < positions['Coagulation'].y0
    assert positions['Coagulation'].y0 - positions['Hepatic'].y0 < 16
    assert max(positions[t].y0 for t in ['PT:', 'INR:', 'PTT:', 'Anti-Xa']) - min(positions[t].y0 for t in ['PT:', 'INR:', 'PTT:', 'Anti-Xa']) < 1
    assert positions['PT:'].x0 < positions['INR:'].x0 < positions['PTT:'].x0 < positions['Anti-Xa'].x0
    for marker in ['CRP:', 'PROCAL:']:
        assert positions[marker].y0 < positions['Hepatic'].y0
    for block in page.get_text('blocks'):
        assert 0 <= block[0] < block[2] <= 792 and 0 <= block[1] < block[3] <= 612
    doc.close()


def test_print_all_preserves_routing_for_each_room():
    one, two = sample(), sample()
    two['room'] = 'P4104'
    pdf = PdfReader(BytesIO(handoffs_pdf([one, two])))
    assert len(pdf.pages) == 2
    for p in pdf.pages:
        text = p.extract_text()
        assert text.index('Hepatic') < text.index('Coagulation')
        assert text.count('Coagulation') == 1
        assert text.count('CRP:') == 1 and text.count('PROCAL:') == 1
    html = handoffs_html([one, two])
    assert html.count('Coagulation') == 2


def test_existing_saved_snapshot_reformats_without_reimport():
    vault = save_sheet_in(new_vault(), sample())
    before = deepcopy(vault)
    key = generate_key()
    reopened = open_vault(seal_vault(vault, key), key)
    assert reopened == before
    fields = fields_with_medications(reopened['rooms']['P4102'])
    assert 'Coagulation' in fields['Lab Results / Trends']
    assert 'Coagulation' not in fields['Infectious Disease']
    assert reopened == before


def test_lab_preview_uses_same_placement_and_excludes_id_markers():
    data = sample()['labs']
    html = laboratory_html(data)
    assert html.index('Hepatic') < html.index('Coagulation') < html.index('Gas ART')
    assert 'Anti-Xa (HEPLMW):' in html
    assert 'CRP:' not in html and 'PROCAL:' not in html
    assert laboratory_flowables(data, 720)
