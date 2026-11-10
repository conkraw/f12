from style_assert_helpers import without_style_tags
"""Synthetic Q-matrix regression coverage. No patient records are bundled."""
from copy import deepcopy
from datetime import datetime
from io import BytesIO
import json
import re
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from cbc import (parse_cbc, validate_cbc, cbc_cards, cbc_component, empty_cbc,
                 cbc_selection_issues, cbc_summary)
from blood_gases import parse_gases, latest_sample
from labs import parse_labs, result_cards, empty_labs
from lab_layout import card_plan, laboratory_html, tree_text_fits
from models import new_sheet, new_vault, upgrade_vault, save_sheet_in, fields_with_medications, SCHEMA_VERSION
from parser import parse_smartphrase
from importing import import_sections
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf, handoffs_html
from medications import parse_medications, format_medication
from infusions import infusion_entry, neuro_body
from output_text import medication_output
from batching import available_handoffs
from github_store import seal_vault, open_vault
from test_callbacks import app, open_room

TABLE = '''Results from last 7 days
Lab\tUnits\t01/06/26
0436\t01/06/26
0435\t01/05/26
0605\t01/05/26
0408\t01/01/26
0427
WBC AUTO\tK/uL\t -- \t12.04*\t -- \t8.94\t11.83*
HEMOGLOBIN\tg/dL\t -- \t7.3*\t -- \t7.4*\t9.7*
HEMOGLOBIN ISTAT\tg/dL\t8.6*\t -- \t9.1*\t -- \t --
HEMATOCRIT\t%\t25*\t22.5*\t28*\t23.1*\t29.1*
MCV\tfL\t -- \t91.1\t -- \t91.5\t86.5
PLATELETS AUTO\tK/uL\t -- \t430*\t -- \t320\t440*
NEUTROS ABS\tK/uL\t -- \t -- \t -- \t -- \t9.15*
LYMPHS ABS AUTO\tK/uL\t -- \t -- \t -- \t -- \t1.17
MANUAL ABSOLUTE LYMPHOCYTE CV\tK/uL\t -- \t1.63\t -- \t1.20\t1.13
ANC\t\t -- \t10.26*\t -- \t4.98\t10.03*
 < > = values in this interval not displayed.
'''

def wrap(letter, body):
    return letter*16+'\n'+body+'\n'+letter*16

def parsed(text=TABLE):
    out=parse_cbc(text)
    assert not out.error,out.error
    return out.data

def imported(text=TABLE, base=None):
    out=import_sections(base or new_sheet('P4102'),wrap('q',text),new_vault()['settings'])
    assert not out.errors,out.errors
    return out.sheet

def cards(text=TABLE):
    return cbc_cards(empty_labs(),parsed(text))

def numeric_table(rows, dates='01/06/26 0900\t01/05/26 0900'):
    return 'Lab\tUnits\t'+dates+'\n'+rows


def test_q_boundaries_uppercase_and_missing_header_heading():
    out=parse_smartphrase('q'*16+'\n'+TABLE+'\n'+'Q'+'q'*15)
    assert 'q' in out.blocks and not out.invalid
    assert import_sections(new_sheet('P4102'),wrap('q',TABLE),new_vault()['settings']).sheet


def test_existing_g_complete_blood_count_subheading_not_reclassified_as_q():
    out=import_sections(new_sheet('P4102'),wrap('g','LABS:\nComplete Blood Count:\nWBC\t9\t01/06/26'),new_vault()['settings'])
    assert not out.errors and out.sheet['cbc'] is None


def test_regular_cbc_columns_do_not_pick_gas_only_istat_hct():
    out=cards()
    assert len(out)==2 and all(c['kind']=='cbc' for c in out)
    assert [c['rows']['HGB']['value'] for c in out]==['7.3*','7.4*']
    assert [c['rows']['HCT']['value'] for c in out]==['22.5*','23.1*']
    assert [c['rows']['WBC']['value'] for c in out]==['12.04*','8.94']
    assert all('8.6' not in str(c) for c in out)
    assert out[0]['rows']['HGB']['date']=='01/06/26 0435'
    assert out[1]['rows']['HGB']['date']=='01/05/26 0408'


def test_latest_absolute_counts_independent_automatic_or_manual():
    first=cards()[0]['rows']
    assert first['ANC']['value']=='10.26*' and first['ANC']['date']=='01/06/26 0435'
    assert first['ALC']['value']=='1.63 K/uL' and first['ALC']['date']=='01/06/26 0435'
    assert 'ANC' not in cards()[1]['rows'] and 'ALC' not in cards()[1]['rows']
    changed=TABLE.replace('9.15*','9.15*').replace('NEUTROS ABS\tK/uL\t --', 'NEUTROS ABS\tK/uL\t11.7*')
    assert cards(changed)[0]['rows']['ANC']['value']=='11.7* K/uL'


@pytest.mark.parametrize('label', ['NEUTROS ABS','NEUTROABS','ANC','ABSOLUTE NEUTROPHIL COUNT'])
def test_anc_aliases(label):
    out=cards(numeric_table('WBC AUTO\tK/uL\t9\t8\n'+label+'\tK/uL\t0.00*\t1.2'))
    assert out[0]['rows']['ANC']['value']=='0.00* K/uL'


@pytest.mark.parametrize('label',['LYMPHS ABS AUTO','LYMPHSABS','MANUAL ABSOLUTE LYMPHOCYTE CV','MANUAL ABSOLUTE LYMPHOCYTE COUNT','ALC'])
def test_alc_aliases(label):
    out=cards(numeric_table('WBC AUTO\tK/uL\t9\t8\n'+label+'\tK/uL\t0.81*\t1.2'))
    assert out[0]['rows']['ALC']['value']=='0.81* K/uL'


def test_percentages_not_used_or_calculated():
    source=numeric_table('WBC AUTO\tK/uL\t9\t8\nLYMPHOCYTES\t%\t40\t30\nANC\t%\t50\t40')
    out=cards(source)[0]['rows']
    assert out['ANC']['value']=='--' and out['ALC']['value']=='--'


def test_missing_counts_always_have_under_tree_placeholders():
    card=cards(numeric_table('WBC AUTO\tK/uL\t9\t8'))[0]
    assert card['rows']['ANC']=={'component':'ANC','value':'--','date':''}
    height,plan=card_plan(card,180)
    assert any(item[0]=='text' and item[3]=='ANC: --' for item in plan)
    assert any(item[0]=='text' and item[3]=='ALC: --' for item in plan)


def test_only_istat_when_no_standard_hemoglobin_anywhere():
    text=numeric_table('WBC AUTO\tK/uL\t9\t8\nHEMOGLOBIN ISTAT\tg/dL\t8.1*\t7.9*\nHEMATOCRIT\t%\t24\t23')
    out=cards(text)
    assert [c['rows']['HGB']['value'] for c in out]==['8.1*','7.9*']
    assert all(c['rows']['HGB']['component']=='Hgb (ISTAT)' for c in out)
    assert 'Hgb (ISTAT)' in handoff_text(imported(text))


def test_one_standard_does_not_fill_other_slot_with_istat():
    text=numeric_table('WBC AUTO\tK/uL\t9\t8\nHEMOGLOBIN\tg/dL\t8.1*\t--\nHEMOGLOBIN ISTAT\tg/dL\t--\t7.9*')
    out=cards(text)
    assert out[0]['rows']['HGB']['value']=='8.1*'
    assert 'HGB' not in out[1]['rows']


def test_newest_incomplete_cbc_does_not_backfill_prior_draw():
    text=numeric_table('WBC AUTO\tK/uL\t9\t8\nHEMOGLOBIN\tg/dL\t--\t7.9*')
    out=cards(text)
    assert 'HGB' not in out[0]['rows'] and out[1]['rows']['HGB']['value']=='7.9*'


def test_unordered_headers_sort_by_timestamp_not_position():
    text=numeric_table('WBC AUTO\tK/uL\t8\t9\nHEMOGLOBIN\tg/dL\t7.1\t7.2','01/05/26 0900\t01/06/26 0900')
    assert cards(text)[0]['rows']['WBC']['value']=='9'


@pytest.mark.parametrize('head', [
 '01/06/26\n0900\t01/05/26\n0800',
 '01/06/26 0900\t01/05/26 0800',
 '01/06/26\t01/05/26\n\t\t0900\t0800',
 '01/06/2026 9:00 AM\t01/05/2026 8:00 AM',
 '01/06/2026\t01/05/2026',
])
def test_headers(head):
    data=parsed(numeric_table('WBC AUTO\tK/uL\t9\t8',head))
    assert len(data['rows'])==2


@pytest.mark.parametrize('value',['--',' - ','< >','<>','', 'N/A'])
def test_hidden_empty_cells_never_become_results(value):
    data=parsed(numeric_table('WBC AUTO\tK/uL\t9\t'+value))
    assert len(data['rows'])==1


@pytest.mark.parametrize('value',['0','0.00*','<0.1*','11.26*','2.25','1.2 (L)'])
def test_numeric_counts_preserve_value_and_flags(value):
    out=cards(numeric_table('ANC\tK/uL\t'+value+'\t--'))[0]
    assert out['rows']['ANC']['value']==value+' K/uL'


@pytest.mark.parametrize('text', [
 'Lab\tUnits\t01/06/26 0900\t01/05/26 0800\nWBC AUTO\tK/uL\t9',
 'Lab\tUnits\t01/06/26 9900\nWBC AUTO\tK/uL\t9',
 'Lab\tUnits\t01/06/26 0900\nWBC AUTO\tK/uL\tunknown',
 'Lab\tUnits\t01/06/26 0900\nWBC AUTO\tK/uL\t9\nWBC AUTO\tK/uL\t8',
 'Lab\tUnits\t01/06/26 0900\nUnknown row\tK/uL\t9',
])
def test_bad_q_leaves_entire_previous_handoff_unchanged(text):
    base=imported(); before=deepcopy(base)
    out=import_sections(base,wrap('a','Diagnoses:\n1. New synthetic text')+'\n'+wrap('q',text),new_vault()['settings'])
    assert out.errors or out.diagnostics
    assert out.sheet is not None and base==before
    assert out.sheet['fields']['Diagnoses']=='New synthetic text'
    assert 'q' in out.sheet['import_warnings']
    if out.errors:
        assert out.sheet['cbc']==before['cbc']
    else:
        assert not any(row['include'] for row in out.sheet['cbc']['rows'])


def test_empty_omitted_and_q_precedence():
    base=imported()
    base['labs']=parse_labs('LABS:\nWBC\t999\t01/07/26\nHGB\t99\t01/07/26\nNA\t140\t01/07/26').data
    original=deepcopy(base)
    assert 'WBC: 999' not in handoff_text(base)
    out=import_sections(base,wrap('g','LABS:\nNA\t139\t01/08/26'),new_vault()['settings'])
    assert not out.errors and out.sheet['cbc']==base['cbc']
    cleared=imported('',base)
    assert cleared['cbc']==empty_cbc() and cleared['labs']==base['labs']
    assert not [c for c in result_cards(cleared['labs'],cbc=cleared['cbc']) if c['kind']=='cbc']
    assert original==base


def test_legacy_g_works_and_absolute_counts_are_latest():
    data=parse_labs('LABS:\nWBC\t9\t01/06/26\nWBC\t8\t01/05/26\nHGB\t8\t01/06/26\nANC\t1.1\t01/06/26\nNEUTROABS\t2.2\t01/05/26\nLYMPHSABS\t0.5\t01/06/26').data
    out=cbc_cards(data)
    assert len(out)==2 and out[0]['rows']['ANC']['value']=='1.1'
    assert out[0]['rows']['ALC']['value']=='0.5'
    assert out[0]['rows']['HGB']['value']=='8'


def test_trees_still_render_for_timed_columns_and_counts_are_below_nodes():
    first=cards()[0]
    assert tree_text_fits(first,180)
    height,plan=card_plan(first,180)
    positions={item[3]:item[2] for item in plan if item[0]=='text'}
    assert positions['ANC: 10.26* [01/06/26 04:35]'] < positions['12.04*']
    assert positions['ALC: 1.63 K/uL [01/06/26 04:35]'] < positions['22.5*']
    assert '04:35' in positions


def test_exports_cbc_snapshot_no_istat_hgb_or_shifted_hct():
    sheet=imported(); before=deepcopy(sheet)
    text=PdfReader(BytesIO(handoff_pdf(sheet))).pages[0].extract_text()
    for output in (handoff_text(sheet),without_style_tags(handoff_html(sheet)),text):
        assert '7.3*' in output and '22.5*' in output and '10.26*' in output and '1.63' in output
        assert '8.6*' not in output and '25*' not in output
        assert 'ANC' in output and 'ALC' in output
    assert sheet==before
    second=deepcopy(sheet);second['room']='P4104'
    pages=PdfReader(BytesIO(handoffs_pdf([sheet,second]))).pages
    assert len(pages)==2
    assert without_style_tags(handoffs_html([sheet,second])).count('10.26*')==2


def test_cbc_only_room_print_all_and_cleared_q_not_counted_as_content():
    sheet=imported()
    assert list(available_handoffs(new_vault(),{'P4102':sheet}))==['P4102']
    sheet=imported('',sheet)
    assert available_handoffs(new_vault(),{'P4102':sheet})=={}


def test_schema12_upgrade_preserves_old_gases_rows_mappings_and_fields():
    sheet=new_sheet('P4102');sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop('recurring_orders');sheet.pop('cbc')
    sheet['blood_gas']=parse_gases('Lab\tUnits\t01/06/26 0900\nPH ART\t\t7.40').data
    sheet['fields']['Neurologic']='Preserved separate note'
    old=new_vault();old['schema']=12;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old["settings"].pop("medication_gi_groups", None);old['rooms']['P4102']=sheet
    before=deepcopy(old)
    key=Fernet.generate_key().decode()
    cipher=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    new=open_vault(cipher,key)
    assert old==before and new['schema']==SCHEMA_VERSION==34
    assert new['rooms']['P4102']==dict(sheet,cbc=None,recurring_orders=None,intake_output=None,import_warnings={},feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    assert new['settings']==dict(old['settings'], medication_gi_groups=[], medication_groups=[])
    assert open_vault(seal_vault(new,key),key)==new


def test_cbc_editor_and_autosave_snapshot(app):
    open_room(app)
    ss=app.st.session_state;sheet=imported();room=sheet['room'];ss['drafts'][room]=sheet
    row=sheet['cbc']['rows'][0]
    key='cbc_'+row['id']+'_value';ss[key]='10.1'
    app.cbc_edit(room,row['id'],'value',key)
    assert ss['drafts'][room]['cbc']['rows'][0]['value']=='10.1'
    dkey='cbc_date_'+sheet['id']+'_'+str(row['column']);ss[dkey]='01/06/26 0500'
    app.cbc_edit(room,'','date',dkey,row['column'])
    assert all(r['date']=='01/06/26 0500' for r in ss['drafts'][room]['cbc']['rows'] if r['column']==row['column'])
    ss[key]='11.2'
    snapshot=app.editor_snapshot(room)
    assert snapshot['cbc']['rows'][0]['value']=='11.2'
    ss[key]='bad'
    app.cbc_edit(room,row['id'],'value',key)
    assert ss[key]=='10.1'


@pytest.mark.parametrize('label', ['POCT PCO2, VENOUS','POCT PCO2, ARTERIAL','POCT PCO2, CAPILLARY'])
def test_additional_explicit_poc_gas_labels_and_generic_ph(label):
    data=parse_gases('Lab\tUnits\t01/06/26 1609\n'+label+'\tmmHg\t54*\nPH\t\t7.37')
    assert not data.error
    latest,_=latest_sample(data.data)
    assert latest['values']['pH']['value']=='7.37' and latest['values']['PCO2']['value']=='54*'


def test_untyped_ph_never_assigned_when_column_has_two_types():
    gas=parse_gases('Lab\tUnits\t01/06/26 0900\nPCO2 VEN\tmmHg\t50\nPCO2 ART\tmmHg\t40\nPH\t\t7.40')
    assert not gas.error and all('pH' not in r['values'] for r in gas.data['samples'])
    assert any('could not be assigned' in x for x in gas.issues)


def test_no_lab_exists_p_is_empty_not_import_error():
    result=import_sections(new_sheet('P4102'),wrap('p','No lab exists for component: "PHC", "PCO2C"')+'\n'+wrap('q',TABLE),new_vault()['settings'])
    assert not result.errors and result.sheet['blood_gas']=={'samples':[],'notes':[]}
    assert result.sheet['cbc']['rows']


def medication():
    result=parse_medications('Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n•\tExample infusion\t1 mcg/kg/hr (Dosing Weight)\tIntravenous\tContinuous\t\t2 mL/hr\t',[])
    assert not result.error
    row=result.rows[0];row['section']='Neurologic'
    return row


@pytest.mark.parametrize('section',['Neurologic','Other Medications','FEN / GI','Infectious Disease'])
def test_dosing_weight_removed_from_outputs_only(section):
    row=medication();row['section']=section
    sheet=new_sheet('P4102');sheet['medications']=[row];before=deepcopy(sheet)
    assert '(Dosing Weight)' in format_medication(row)
    assert '(Dosing Weight)' in infusion_entry(row)
    for output in (handoff_text(sheet),without_style_tags(handoff_html(sheet)),PdfReader(BytesIO(handoff_pdf(sheet))).pages[0].extract_text()):
        assert '(Dosing Weight)' not in output
        assert '1 mcg/kg/hr' in re.sub(r'\s+', ' ', output)
        assert 'Dosing weight: none' in output
    assert sheet==before
    vault=save_sheet_in(new_vault(),sheet);key=Fernet.generate_key().decode()
    assert '(Dosing Weight)' in open_vault(seal_vault(vault,key),key)['rooms']['P4102']['medications'][0]['dose']


@pytest.mark.parametrize('text', ['Dose: 1 mg/kg (Dosing Weight)', 'Dose: 1 mg/kg (dosing weight)', '( Dosing Weight ) 1 mg/kg', 'Infusion (Dosing Weight)\nDose: 1 mg/kg'])
def test_output_cleanup_does_not_alter_other_qualifiers(text):
    out=medication_output(text+' (Order-Specific) [Held by provider]')
    assert 'dosing weight' not in out.casefold() and '1 mg/kg' in out
    assert '(Order-Specific)' in out and '[Held by provider]' in out


def test_custom_medication_output_only_and_notes_untouched():
    row=medication();row['custom_text']='Custom (Dosing Weight) 1 mcg/kg/hr'
    sheet=new_sheet('P4102');sheet['medications']=[row];sheet['fields']['Other']='Note (Dosing Weight) preserved'
    before=deepcopy(sheet)
    text=handoff_text(sheet)
    assert 'Custom 1 mcg/kg/hr' in text and 'Note (Dosing Weight) preserved' in text
    assert sheet==before


def test_conflicting_cbc_alias_cannot_silently_select_one():
    out=parse_cbc('Lab\tUnits\t01/06/26 0900\nWBC\tK/uL\t9\nWBC AUTO\tK/uL\t8')
    assert not out.error and out.diagnostics
    assert all(not row['include'] for row in out.data['rows'])


def test_long_result_wraps_without_losing_missing_count_placeholders():
    text=numeric_table('HEMOGLOBIN\tg/dL\t7.123456789012345678901234567890123456789\t8.1')
    sheet=imported(text)
    output=without_style_tags(handoff_html(sheet))
    assert '7.123456789012345678901234567890123456789' in output
    assert 'ANC: --' in output and 'ALC: --' in output
    assert handoff_pdf(sheet).startswith(b'%PDF')


def test_full_cbc_page_render_uses_unique_widget_keys(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app)
    app.st.session_state['drafts']['P4102']=imported()
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_no_qualifier_keeps_original_spacing_and_annotations():
    text='Example   name | 1 mg/kg (Order-Specific)'
    assert medication_output(text)==text
