"""Synthetic display labels. Source order context and calculations stay intact."""
from copy import deepcopy
from datetime import datetime
from html import escape
import re

import fitz
import pytest

from categories import medication_blocks
from exports import handoff_html, handoff_pdf, handoff_text, handoffs_html, handoffs_pdf
from infusion_rates import administration_display
from infusions import infusion_entry
from medications import (DESTINATIONS, destination_for, format_medication, hidden_for,
                         parse_medications, set_visibility_rule, upsert_rule)
from models import fields_with_medications, new_sheet, new_vault, save_sheet_in
from output_text import medication_name_output
from problem_review import _medication_active
from security import generate_key, open_vault, seal_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip


START = '[START ON 01/02/2099]'


def table_row(name, dose='SYNTHETIC_DOSE', route='Oral', frequency='q4h', rate='', admin=''):
    return '•\t' + '\t'.join([name, dose, route, frequency, '', rate, admin])


def order(name, **kwargs):
    parsed = parse_medications('Medications:\n' + table_row(name, **kwargs))
    assert not parsed.error, parsed.issues
    return parsed.rows[0]


@pytest.mark.parametrize('source,expected', [
    ('And: Synthetic alpha', 'Synthetic alpha'),
    ('Or:Synthetic beta', 'Synthetic beta'),
    ('Alternative order: Synthetic gamma', 'Synthetic gamma'),
    (START + ' Synthetic delta', 'Synthetic delta'),
    (' or : [start on 01/02/2099 0800] Synthetic epsilon ', 'Synthetic epsilon'),
    ('And: ' + START + ' [Held by provider] Or: Synthetic alpha', '[Held by provider] Synthetic alpha'),
    ('[Discontinued] Or: ' + START + ' Synthetic beta', '[Discontinued] Synthetic beta'),
    ('[Held by provider] And: ' + START + ' [Discontinued] Or: Synthetic gamma',
     '[Held by provider] [Discontinued] Synthetic gamma'),
    ('Followed by: ' + START + ' And: Synthetic delta', 'Followed by: Synthetic delta'),
    ('Followed by ' + START + ' Synthetic epsilon', 'Followed by Synthetic epsilon'),
    ('Or:\u00a0[Held by provider]\n' + START + '\tSynthetic zeta', '[Held by provider] Synthetic zeta'),
    ('Or: [UNKNOWN context] ' + START + ' Synthetic alpha', '[UNKNOWN context] ' + START + ' Synthetic alpha'),
    ('And: Synthetic alpha ' + START + ' Or: qualifier', 'Synthetic alpha ' + START + ' Or: qualifier'),
    ('Andro synthetic', 'Andro synthetic'),
    ('Oral synthetic', 'Oral synthetic'),
    ('Synthetic And: Or: wording', 'Synthetic And: Or: wording'),
    ('[START ON ] Synthetic alpha', '[START ON ] Synthetic alpha'),
    ('[START ON incomplete Synthetic alpha', '[START ON incomplete Synthetic alpha'),
])
def test_name_only_cleanup_is_narrow_and_preserves_other_annotations(source, expected):
    assert medication_name_output(source) == expected
    assert medication_name_output(expected) == expected


@pytest.mark.parametrize('name', ['And:', 'Or:', START, 'Or: ' + START,
                                 '[Held by provider] And: ' + START,
                                 'Alternative order: ' + START])
def test_annotation_only_names_do_not_become_blank(name):
    row = order(name)
    assert medication_name_output(name) == name
    assert format_medication(row).startswith(name)
    assert infusion_entry(row).splitlines()[0] == name


@pytest.mark.parametrize('connector', ['And', 'Or'])
@pytest.mark.parametrize('layout', ['standalone', 'trailing_cell', 'inline'])
def test_table_and_inline_connectors_keep_both_orders_and_blank_columns(connector, layout):
    first = table_row('Synthetic first', dose='SYNTHETIC_FIRST', route='Oral')
    following_name = START + ' Synthetic second'
    following = table_row(following_name, dose='', route='Intravenous', frequency='q6h PRN')
    if layout == 'standalone':
        source = first + '\n\t' + connector + '\n' + following
    elif layout == 'trailing_cell':
        source = first + '\t' + connector + '\n' + following
    else:
        source = first + '\n' + table_row(connector + ': ' + following_name,
                                          dose='', route='Intravenous', frequency='q6h PRN')
    parsed = parse_medications('Medications:\n' + source)
    assert not parsed.error and len(parsed.rows) == 2
    before = deepcopy(parsed.rows)
    second = parsed.rows[1]
    assert second['name'] == connector + ': ' + following_name
    assert second['dose'] == second['last_rate'] == second['rate_time'] == ''
    assert second['route'] == 'Intravenous' and second['frequency'] == 'q6h PRN'
    assert len({row['id'] for row in parsed.rows}) == 2
    for render in (format_medication, infusion_entry):
        assert render(second).startswith('Synthetic second')
        assert connector + ':' not in render(second) and '[START ON' not in render(second)
        assert 'Intravenous' in render(second) and 'q6h PRN' in render(second)
    assert parsed.rows == before


@pytest.mark.parametrize('admin,expected', [
    ('', 'Last Admin rate: UNK'),
    ('5.5 mL/hr at 01/02/2099 0800', 'Last Admin rate: 5.5 mL/hr'),
    ('Stopped at 01/02/2099 0800', 'Last Admin: Stopped'),
    ('Held at 01/02/2099 0800', 'Last Admin: Held'),
])
def test_clean_name_does_not_change_requested_titration_or_admin_status(admin, expected):
    row = order('Or: [Held by provider] ' + START + ' norepinephrine SYNTHETIC',
                dose='7.25 mL/hr', route='Intravenous', frequency='Continuous',
                rate='9.5 mL/hr', admin=admin)
    before = deepcopy(row)
    view = administration_display(row)
    for output in (format_medication(row), infusion_entry(row),
                   infusion_entry(row, handoff_only=True), infusion_entry(row, rich=True)):
        assert '[Held by provider]' in output
        assert 'Or:' not in output and '[START ON' not in output
        assert expected in output and 'Dose: 7.25' not in output
        if 'Stopped' in expected or expected.endswith(': Held'):
            assert '9.5 mL/hr' not in output
    assert administration_display(row) == view and row == before


@pytest.mark.parametrize('custom', ['And: Custom wording', 'Or: ' + START + ' Custom wording',
                                   '[Discontinued] Followed by: Custom <tag>'])
def test_custom_handoff_wording_remains_authoritative(custom):
    row = order('Or: ' + START + ' Synthetic original')
    row['custom_text'] = custom
    before = deepcopy(row)
    assert format_medication(row) == custom
    assert infusion_entry(row) == custom
    assert infusion_entry(row, rich=True, handoff_only=True) == '<b>' + escape(custom) + '</b>'
    assert row == before


def test_all_systems_and_export_paths_clean_labels_without_merging_source_orders():
    sheet = new_sheet('P4102')
    names = []
    for index, section in enumerate(DESTINATIONS):
        name = 'Synthetic' + chr(ord('A') + index)
        names.append(name)
        row = order(('And: ' if index % 2 else 'Or: ') + START + ' ' + name)
        row.update(section=section, group_mode='other', gi_mode='other', infusion_mode='other')
        sheet['medications'].append(row)
    infusion = sheet['medications'][0]
    infusion.update(dose='7 mL/hr', route='Intravenous', frequency='Continuous',
                    last_rate='9 mL/hr', last_admin_rate='5 mL/hr',
                    last_admin_time='01/02/2099 0800', last_admin_status='rate',
                    infusion_mode='infusion')
    before = deepcopy(sheet)
    outputs = [handoff_text(sheet), handoff_html(sheet), handoffs_html([sheet])]
    for data in (handoff_pdf(sheet), handoffs_pdf([sheet])):
        with fitz.open(stream=data, filetype='pdf') as document:
            outputs.append('\n'.join(page.get_text() for page in document))
    for output in outputs:
        compact = re.sub(r'\s+', ' ', output)
        assert '[START ON' not in output and 'Alternative order:' not in output
        assert 'And:' not in output and 'Or:' not in output
        for name in names:
            assert compact.count(name) == 1
        assert 'Last Admin rate: 5 mL/hr' in compact
        assert 'Recorded rate: 9 mL/hr' in compact
        assert 'Intravenous | Continuous' in compact
    fields = fields_with_medications(sheet)
    assert all(names[index] in fields[section] for index, section in enumerate(DESTINATIONS))
    assert sheet == before


def test_rendering_preserves_dated_visibility_future_logic_and_encrypted_source():
    first = order('Or: ' + START + ' Synthetic scheduled')
    second = order('Or: [START ON 01/03/2099] Synthetic scheduled')
    rows = [first, second]
    before = deepcopy(rows)
    visibility = set_visibility_rule([], first['name'], True)
    rules = upsert_rule([], 'Synthetic scheduled', 'Hematology')
    for row in rows:
        assert destination_for(row['name'], rules) == 'Hematology'
        assert not _medication_active(row, datetime(2098, 12, 31, 12))
        assert _medication_active(row, datetime(2099, 1, 4, 12))
        assert format_medication(row).startswith('Synthetic scheduled')
        assert infusion_entry(row).startswith('Synthetic scheduled')
    assert hidden_for(first['name'], visibility)
    assert not hidden_for(second['name'], visibility)
    assert rows == before and first['id'] != second['id']
    sheet = new_sheet('P4102')
    sheet['medications'] = rows
    vault = save_sheet_in(new_vault(), sheet)
    key = generate_key()
    assert open_vault(seal_vault(vault, key), key) == vault
    assert [row['name'] for row in vault['rooms']['P4102']['medications']] == [row['name'] for row in before]


def test_detached_alternative_alias_is_cleaned_after_grouping_and_escaped():
    row = order('Or: ' + START + ' Synthetic <marker> & label')
    row['section'] = 'Neurologic'
    before = deepcopy(row)
    rendered, = [item for kind, item in medication_blocks('Neurologic', '', [row])
                 if kind in ('medication', 'infusion')]
    assert rendered['_display_name'].startswith('Alternative order:')
    assert format_medication(rendered).startswith('Synthetic <marker> & label')
    rich = infusion_entry(rendered, rich=True)
    assert '<b>Synthetic &lt;marker&gt; &amp; label</b>' in rich
    assert 'Alternative order:' not in rich and '[START ON' not in rich
    assert row == before and '_display_name' not in row


def test_editor_summary_is_clean_but_medication_name_field_keeps_source(app, monkeypatch):
    open_room(app)
    equip(app, monkeypatch)
    row = order('And: [Held by provider] ' + START + ' Synthetic editor')
    before = deepcopy(row)
    texts = []
    app.st.text = lambda value, **kwargs: texts.append(value)
    app.medication_editor([row], 'P4102', None)
    assert any('[Held by provider] Synthetic editor' in text for text in texts)
    assert all('And:' not in text and '[START ON' not in text for text in texts)
    assert app.st.session_state['med_draft_' + row['id'] + '_name'] == before['name']
    assert row == before
