from recovery_helpers import assert_retained
"""O-block parsing, positive-only display, archive compatibility and UI callbacks."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import uuid

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader
from viral import (parse_viral_panel, empty_viral_panel, result_status, positive_names,
                   viral_text, validate_viral_panel, display_name)
from parser import parse_smartphrase, SECTION_NAMES
from models import (new_sheet, new_vault, save_sheet_in, validate_sheet, validate_vault,
                    upgrade_vault, fields_with_medications, SCHEMA_VERSION, ValidationError)
from importing import import_sections
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, patient_column
from security import open_vault, seal_vault, generate_key
from batching import available_handoffs
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
SAMPLE = '''Respiratory Viral Panel:
Lab Results
Component\tValue\tDate
\tADENOVIRDNA\tNot Detected\t01/01/2026
\tHUMRHINENRNA\tDetected (A)\t01/01/2026
\tFLUAVIRUSRNA\tNot Detected\t01/01/2026
\tPARAFLU1RNA\tNot Detected\t01/01/2026
\tPARAFLU2RNA\tNot Detected\t01/01/2026
\tPARAFLU3RNA\tNot Detected\t01/01/2026
\tPARAFLU4RNA\tNot Detected\t01/01/2026
\tRESPSYNVRNA\tNot Detected\t01/01/2026
\tSARSRNA\tNot Detected\t01/01/2026'''


def block(letter, body):
    return letter * 12 + '\n' + body + '\n' + letter * 12


def imp(text, sheet=None):
    result = import_sections(sheet or new_sheet('P4102'), text, new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


def data(body=SAMPLE):
    result = parse_viral_panel(body)
    assert not result.error, result.error
    return result.data


def o(body):
    return block('o', 'Respiratory Viral Panel:\n' + body)


def test_supplied_pattern_one_combined_positive_nine_retained_rows():
    snapshot = data()
    assert len(snapshot['rows']) == 9
    assert positive_names(snapshot) == ['Rhinovirus/enterovirus']
    assert viral_text(snapshot) == 'Rapid Viral Panel: Rhinovirus/enterovirus'
    row = snapshot['rows'][1]
    assert (row['component'], row['result'], row['date']) == ('HUMRHINENRNA', 'Detected (A)', '01/01/2026')
    assert 'Adenovirus' not in viral_text(snapshot)


@pytest.mark.parametrize('value', ['Detected', 'DETECTED', 'Positive', 'positive (A)', 'Detected (A)',
    'Detected (AB)', 'Detected (Abnormal)', 'Detected*', 'Detected (A) *', 'Detected [A]',
    ' Detected\u00a0 (A) ', 'Positive (H)'])
def test_explicit_positive_status(value):
    assert result_status(value) == 'positive'


@pytest.mark.parametrize('value', ['Not Detected', 'NOT DETECTED', 'Not   detected (A)',
    'Negative', 'negative (A)', 'Undetected', 'Non-detected', 'Non Detected', 'Not Detected*'])
def test_negatives_never_match_detected_substring(value):
    assert result_status(value) == 'negative'
    assert viral_text(data('ADENOVIRDNA\t'+value+'\t01/01/2026')) == ''


@pytest.mark.parametrize('value', ['', 'Pending', 'In process', 'Inconclusive', 'Indeterminate',
    'Not tested', 'Positive control', 'Presumptive positive', 'Cannot exclude positive',
    'Detected?','Not Detected / Detected', 'Detected but repeat requested', '--', '1', 'True',
    'Reactive', 'No positive results', 'Negative; previously Positive'])
def test_uncertain_results_are_not_printed_as_positive(value):
    assert result_status(value) == 'unresolved'
    r = parse_viral_panel('ADENOVIRDNA\t'+value+'\t01/01/2026')
    assert not r.error and not viral_text(r.data) and r.issues


@pytest.mark.parametrize('body', ['', 'Lab Results\nComponent\tValue\tDate',
    'No results found for: "HUMRHINENRNA", "ADENOVIRDNA"', 'No results found.', 'None', '--'])
def test_empty_or_no_result_panels_are_valid_empty_snapshots(body):
    assert parse_viral_panel('Respiratory Viral Panel:\n'+body).data == empty_viral_panel()
    assert not parse_viral_panel('Respiratory Viral Panel:\n'+body).error


def test_unknown_positive_kept_as_original_code_not_invented_species():
    r = parse_viral_panel('NEW_LOCAL_COMPONENT\tPositive (A)\t01/01/2026')
    assert not r.error and viral_text(r.data) == 'Rapid Viral Panel: NEW_LOCAL_COMPONENT' and r.issues
    assert display_name('SARSRNA') == 'SARSRNA'


@pytest.mark.parametrize('code,label', [('ADENOVIRDNA','Adenovirus'), ('FLUAVIRUSRNA','Influenza A'),
    ('FLUBVIRUSRNA','Influenza B'), ('PARAFLU1RNA','Parainfluenza 1'), ('PARAFLU4RNA','Parainfluenza 4'),
    ('RESPSYNVRNA','RSV'), ('HUMRHINENRNA','Rhinovirus/enterovirus'), ('rhinovirus','Rhinovirus')])
def test_literal_display_aliases(code,label):
    assert display_name(code) == label


def test_multiple_positives_are_listed_once_in_source_order():
    snapshot = data(SAMPLE + '\nRESPSYNVRNA\tDetected (A)\t01/02/2026\nHUMRHINENRNA\tDetected (A)\t01/01/2026')
    assert viral_text(snapshot) == 'Rapid Viral Panel: Rhinovirus/enterovirus, RSV'
    assert len(snapshot['rows']) == 11


def test_newest_negative_does_not_retain_older_positive():
    s = data('HUMRHINENRNA\tPositive\t01/01/2026\nHUMRHINENRNA\tNot Detected\t01/02/2026')
    assert not viral_text(s)
    s['rows'][1]['include'] = False
    assert not viral_text(s), 'Hiding a newer negative must not resurrect an earlier positive'


def test_newest_pending_does_not_retain_older_positive():
    assert not viral_text(data('RESPSYNVRNA\tPositive\t01/01/2026\nRESPSYNVRNA\tPending\t01/02/2026'))


def test_date_sort_not_string_order():
    assert not viral_text(data('RESPSYNVRNA\tPositive\t9/30/2025\nRESPSYNVRNA\tNegative\t10/1/2025'))


def test_explicit_times_disambiguate_result_change():
    s = data('RESPSYNVRNA\tPositive\t01/01/2026 08:30\nRESPSYNVRNA\tNegative\t01/01/2026 13:40')
    assert not viral_text(s)


@pytest.mark.parametrize('dates', [('01/01/2026','01/01/2026'),
    ('01/01/2026','01/01/2026 13:00'), ('01/01/2026 08:30','01/01/2026 08:30')])
def test_conflicting_latest_results_not_guessed(dates):
    r = parse_viral_panel('RESPSYNVRNA\tPositive\t'+dates[0]+'\nRESPSYNVRNA\tNegative\t'+dates[1])
    assert r.error and r.data == empty_viral_panel()


def test_older_conflict_does_not_override_a_clear_newer_result():
    s = data('RESPSYNVRNA\tPositive\t01/01/2026\nRESPSYNVRNA\tNegative\t01/01/2026\nRESPSYNVRNA\tDetected\t01/02/2026')
    assert viral_text(s) == 'Rapid Viral Panel: RSV'


@pytest.mark.parametrize('row', ['HUMRHINENRNA  Detected (A)  01/01/2026',
    'HUMRHINENRNA Detected (A) 01/01/2026', '\tHUMRHINENRNA\tDetected (A)\t01/01/2026\t ',
    'HUMRHINENRNA\tDetected (A)\t01/01/2026'])
def test_supported_paste_whitespace(row):
    assert viral_text(data(row)) == 'Rapid Viral Panel: Rhinovirus/enterovirus'


def test_multiword_component_uses_tab_columns():
    assert viral_text(data('Human Rhinovirus/Enterovirus\tDetected (A)\t01/01/2026')) == 'Rapid Viral Panel: Rhinovirus/enterovirus'


@pytest.mark.parametrize('row', ['HUMRHINENRNA\tDetected\t02/30/2026',
    'HUMRHINENRNA\tDetected', 'Some unstructured prose', 'SECRET_SENTINEL\tPositive\tinvalid'])
def test_malformed_rows_do_not_leak_source_in_errors(row):
    r = parse_viral_panel(row)
    assert r.error and 'SECRET_SENTINEL' not in r.error and r.data == empty_viral_panel()


def test_uppercase_o_divider_and_heading_case():
    r = parse_smartphrase('OOOOOOOO\nrespiratory viral panel:\nHUMRHINENRNA\tDetected\t01/01/2026\nOOOOOOOO')
    assert 'o' in r.blocks and 'o' not in r.invalid


def test_o_only_import_and_reimport_replace_not_append():
    s = imp(block('o', SAMPLE))
    again = imp(block('o', SAMPLE), s)
    assert len(again['viral_panel']['rows']) == 9
    assert fields_with_medications(again)['Diagnoses'].count('Rapid Viral Panel:') == 1


def test_omitted_o_preserves_panel_and_unrelated_notes():
    s = imp(block('o', SAMPLE)); s['fields']['Neurologic'] = 'Synthetic manual note'
    updated = imp(block('a','Diagnoses:\n1. Synthetic changed diagnosis'),s)
    assert updated['viral_panel'] == s['viral_panel'] and updated['fields']['Neurologic'] == s['fields']['Neurologic']


@pytest.mark.parametrize('text', [o(''),o('HUMRHINENRNA\tNot Detected\t01/02/2026'), o('No results found.')])
def test_empty_or_negative_new_o_clears_old_positive(text):
    s = imp(block('o',SAMPLE));updated = imp(text,s)
    assert not viral_text(updated['viral_panel'])
    assert 'Rapid Viral Panel:' not in handoff_text(updated)
    assert fields_with_medications(updated)['Diagnoses'] == 'Dosing weight: none'


def test_invalid_o_blocks_atomic_import_and_preserves_original():
    s = imp(block('o', SAMPLE)); before = deepcopy(s)
    bad = block('a','Diagnoses:\n1. Should not apply') + '\noooooooo\nRespiratory Viral Panel:\n'
    r = import_sections(s,bad,new_vault()['settings'])
    assert_retained(r, before, "o")
    assert s == before


def test_summary_prints_below_weights_in_patient_column_only():
    s=imp(block('a','Diagnoses:\n1. Synthetic diagnosis')+'\n'+block('i','NUTRITION:\n01/01/26\t12 kg (Z= -0.2)*\nDosing Weight: 11 kg')+'\n'+block('o',SAMPLE))
    f=fields_with_medications(s)
    assert f['Diagnoses']=='Synthetic diagnosis\n----\nWeight: 12 kg\nZ-score: -0.2\nDosing weight: 11 kg\n----\nRapid Viral Panel: Rhinovirus/enterovirus'
    assert f['Infectious Disease'].strip('-\n')=='Cultures: None' and not f['Lab Results / Trends']
    text=patient_column(s,f)
    assert text.index('Weight:') < text.index('Rapid Viral Panel:')


def test_pdf_html_text_positive_only_and_no_o_dates_or_flags():
    s = imp(block('o',SAMPLE))
    for text in (handoff_text(s), handoff_html(s), '\n'.join(p.extract_text() for p in PdfReader(BytesIO(handoff_pdf(s))).pages)):
        assert 'Rhinovirus/enterovirus' in text and 'Rapid Viral Panel:' in text
        for omitted in ['Not Detected','ADENOVIRDNA','01/01/2026','Detected (A)']:
            assert omitted not in text


def test_no_positive_has_no_empty_separator():
    s = imp(o('ADENOVIRDNA\tNot Detected\t01/01/2026'))
    assert fields_with_medications(s)['Diagnoses'] == 'Dosing weight: none'


def test_positive_only_room_is_in_print_all_but_negative_only_is_not():
    s=imp(block('o',SAMPLE)); empty=imp(o('ADENOVIRDNA\tNot Detected\t01/01/2026'),new_sheet('P4104'))
    assert list(available_handoffs(new_vault(),{'P4102':s,'P4104':empty})) == ['P4102']
    s2=imp(o('RESPSYNVRNA\tPositive\t01/01/2026'),new_sheet('P4104'))
    pages=PdfReader(BytesIO(handoffs_pdf([s,s2]))).pages
    assert len(pages)==2 and 'Rhinovirus' in pages[0].extract_text() and 'RSV' in pages[1].extract_text()


def test_saved_snapshot_and_ui_names_are_encrypted_round_trip():
    s=imp(block('o',SAMPLE));s['viral_panel']['rows'][1]['name']='Synthetic custom label'
    v=save_sheet_in(new_vault(),s);key=generate_key();token=seal_vault(v,key)
    assert b'HUMRHINENRNA' not in token and b'Synthetic custom label' not in token
    assert open_vault(token,key)==v


def test_v9_migration_keeps_every_previous_field():
    s=imp((ROOT/'examples/synthetic_demographics_labs.txt').read_text())
    v=save_sheet_in(new_vault(),s);v['schema']=9;v.pop("reset_generation", None);v["settings"].pop("medication_groups", None);v["settings"].pop("medication_gi_groups", None);v['settings'].pop('medication_infusions', None)
    v['rooms']['P4102'].pop("feeds", None);v['rooms']['P4102'].pop("devices", None);v['rooms']['P4102'].pop("neuro_devices", None);v['rooms']['P4102'].pop("pacemaker", None);v['rooms']['P4102'].pop("diet", None);v['rooms']['P4102'].pop("import_warnings", None);v['rooms']['P4102'].pop("intake_output", None);v['rooms']['P4102'].pop("recurring_orders", None);v['rooms']['P4102'].pop("cbc", None);v['rooms']['P4102'].pop('blood_gas', None)
    v['rooms']['P4102'].pop('sbs_vent_mode', None)  # Not present in schema 9.
    del v['rooms']['P4102']['viral_panel']
    before=deepcopy(v);m=upgrade_vault(v)
    assert v==before and m['schema']==SCHEMA_VERSION==34 and m['settings']==dict(v['settings'], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    for key,value in v['rooms']['P4102'].items():assert m['rooms']['P4102'][key]==value
    assert m['rooms']['P4102']['viral_panel']==empty_viral_panel()
    key=generate_key()
    token=Fernet(key.encode()).encrypt(json.dumps(v).encode())
    assert open_vault(token,key)==m


@pytest.mark.parametrize('field,value',[('name',''),('component',''),('name','a\nline'),('include','true'),('date','yesterday'),('result',42)])
def test_invalid_stored_panel_rejected(field,value):
    s=imp(block('o',SAMPLE));s['viral_panel']['rows'][1][field]=value
    with pytest.raises(ValidationError):validate_sheet(s)


def test_duplicate_ids_rejected():
    d=data();d['rows'][1]['id']=d['rows'][0]['id']
    with pytest.raises(ValueError):validate_viral_panel(d)


def test_latest_hidden_positive_stays_retained_and_can_be_restored():
    s=data();s['rows'][1]['include']=False
    assert not viral_text(s) and len(s['rows'])==9
    s['rows'][1]['include']=True
    assert viral_text(s)=='Rapid Viral Panel: Rhinovirus/enterovirus'


def test_callbacks_import_edit_exclude_restore_save(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block('o',SAMPLE);app.create_handoff()
    assert ss['paste']=='' and not ss['import_result']['errors']
    row=ss['drafts']['P4102']['viral_panel']['rows'][1]
    ss['viral_test']='Rhinovirus/enterovirus';app.viral_row_change('P4102',row['id'],'name','viral_test')
    ss['viral_hide']=False;app.viral_row_change('P4102',row['id'],'include','viral_hide')
    assert not viral_text(ss['drafts']['P4102']['viral_panel'])
    ss['viral_hide']=True;app.viral_row_change('P4102',row['id'],'include','viral_hide')
    app.save_room(None)
    assert viral_text(ss['vault']['rooms']['P4102']['viral_panel'])=='Rapid Viral Panel: Rhinovirus/enterovirus'
    assert ss['vault']['rooms']['P4102']['viral_panel']==ss['drafts']['P4102']['viral_panel']


def test_callbacks_invalid_edit_rolls_back_and_other_room_ignored(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block('o',SAMPLE);app.create_handoff()
    row=ss['drafts']['P4102']['viral_panel']['rows'][1]
    ss['viral_bad']='not a date';app.viral_row_change('P4102',row['id'],'date','viral_bad')
    assert ss['viral_bad']=='01/01/2026'
    open_room(app,'P4104');ss['viral_cross']='wrong room';app.viral_row_change('P4102',row['id'],'name','viral_cross')
    assert ss['drafts']['P4102']['viral_panel']['rows'][1]['name']=='Rhinovirus/enterovirus'


def test_new_patient_and_editor_cleanup_clear_viral_widget_state(app):
    open_room(app);ss=app.st.session_state;ss['paste']=block('o',SAMPLE);app.create_handoff()
    ss['viral_old_widget']='previous';app.start_new_patient()
    assert ss['drafts']['P4102']['viral_panel']==empty_viral_panel() and 'viral_old_widget' not in ss


def test_expired_session_cannot_edit_viral_result(app):
    open_room(app);ss=app.st.session_state;ss['authenticated']=False
    app.viral_row_change('P4102','x','name','fake')
    assert not ss


def test_full_page_render_and_widget_keys(app,monkeypatch):
    open_room(app);app.load_viral_sample();app.create_handoff()
    assert not app.st.session_state['import_result']['errors']
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(isinstance(content,bytes) and content.startswith(b'%PDF') for _,content in downloads)


def test_source_labels_escaped_in_html_and_pdf_printable():
    d=data('NEW_TEST\tPositive\t01/01/2026');d['rows'][0]['name']='<script>example</script>'
    s=new_sheet('P4102');s['viral_panel']=d
    assert '<script>example</script>' not in handoff_html(s)
    assert '&lt;script&gt;' in handoff_html(s)
    assert handoff_pdf(s).startswith(b'%PDF')
