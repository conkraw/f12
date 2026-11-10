from recovery_helpers import assert_retained
from models import fields_with_medications
"""Synthetic PN connector and compact print regressions. No patient records."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import re
import pytest
import fitz
from pypdf import PdfReader
from medications import (parse_medications, format_medication, remap, upsert_rule,
                         destination_for, suggested_key, hidden_for, set_visibility_rule)
from importing import import_sections
from models import new_sheet, new_vault, save_sheet_in, upgrade_vault
from labs import parse_labs
from lab_layout import laboratory_html, horizontal_card_markup
from exports import handoff_pdf, handoffs_pdf, handoff_html, handoffs_html, handoff_text, print_layout_info
from security import generate_key, seal_vault, open_vault
from test_callbacks import app, open_room
from test_ui_smoke import equip

ROOT = Path(__file__).parents[1]
SAMPLE = (ROOT/'examples/synthetic_compact_pn.txt').read_text()


def order(name='Pediatric 2-in-1 PN (Continuous)', dose='600 mL', rate='25 mL/hr at 01/03/26 0900', trailing=True):
    cells=[name,dose,'Intravenous','Continuous PN']
    if trailing:cells+=['PRIVATE_PROVIDER_TOKEN',rate,'PRIVATE_ADMIN_TOKEN']
    return '•\t'+'\t'.join(cells)


def paired(connector='\tAnd'):
    return 'Medications:\n'+order()+'\n'+connector+'\n'+order('fat emulsion (Example) bag','2 g/kg (Dosing Weight)','2.5 mL/hr at 01/03/26 0900')


def sheet():
    out=import_sections(new_sheet('P4102'),SAMPLE,new_vault()['settings'])
    assert not out.errors,out.errors
    out.sheet["admission_date"] = "01/01/2026"  # v6.30: synthetic encounter window
    return out.sheet


@pytest.mark.parametrize('connector',['And','\tAnd','    And','\t\tAnd\t','AND','and:','• And','▪\tAnd',' And: '])
def test_and_is_structure_not_extra_pn_column(connector):
    result=parse_medications(paired(connector))
    assert not result.error,result.issues
    assert len(result.rows)==2
    pn,lipid=result.rows
    assert pn['dose']=='600 mL' and pn['last_rate']=='25 mL/hr'
    assert lipid['dose']=='2 g/kg (Dosing Weight)' and lipid['last_rate']=='2.5 mL/hr'
    assert lipid['name']=='And: fat emulsion (Example) bag'
    assert all(r['frequency']=='Continuous PN' and r['route']=='Intravenous' for r in result.rows)
    assert pn['rate_time']==lipid['rate_time']=='01/03/26 0900'
    assert 'PRIVATE_' not in json.dumps(result.rows)


@pytest.mark.parametrize('newline',['\n','\r\n','\r'])
def test_and_line_endings(newline):
    result=parse_medications(paired().replace('\n',newline))
    assert not result.error and len(result.rows)==2


def test_connector_in_extra_last_tab_cell():
    result=parse_medications('Medications:\n'+order()+'\tAnd\t\n'+order('fat emulsion bag','2 g/kg','3 mL/hr'))
    assert not result.error and result.rows[1]['name']=='And: fat emulsion bag'


def test_and_with_omitted_trailing_fields():
    source='Medications:\n'+order(trailing=False)+'\nAnd\n'+order('fat emulsion bag','2 g/kg',trailing=False)
    result=parse_medications(source)
    assert not result.error and len(result.rows)==2
    assert all(r['last_rate']=='' for r in result.rows)


def test_word_and_inside_ingredient_name_is_not_split():
    name='sodium acetate in dextrose and sodium chloride infusion'
    result=parse_medications('Medications:\n'+order(name))
    assert not result.error and len(result.rows)==1 and result.rows[0]['name']==name


@pytest.mark.parametrize('prefix',['And: ','And: [START ON 1/4/2026] ','And: [Held by provider] '])
def test_linked_order_mapping_ignores_connector_not_clinical_text(prefix):
    name=prefix+'fat emulsion (Example) bag'
    rules=upsert_rule([],'fat emulsion','FEN / GI')
    assert destination_for(name,rules)=='FEN / GI'
    assert suggested_key(name)=='fat emulsion'
    result=parse_medications('Medications:\n'+order(name),rules)
    assert not result.error and format_medication(result.rows[0]).startswith(name)


def test_exact_hide_restore_linked_formulation():
    name='And: [START ON 1/4/2026] fat emulsion (Example) bag'
    rules=set_visibility_rule([],name,True)
    assert hidden_for(name,rules)
    assert hidden_for(name.replace('And: ',''),rules)
    assert not hidden_for(name.replace('1/4/2026','1/5/2026'),rules)
    assert not hidden_for('Pediatric 2-in-1 PN (Continuous)',rules)
    assert not hidden_for(name,set_visibility_rule(rules,name,False))


@pytest.mark.parametrize('source',[
    'Medications:\nAnd\n'+order(),
    'Medications:\n'+order()+'\nAnd',
    'Medications:\n'+order()+'\nAnd\nAnd\n'+order(),
    'Medications:\n'+order()+'\nAnd\nFollowed by\n'+order(),
    'Medications:\n'+order()+'\nAnd\nmissing table columns',
    'Medications:\n'+order()+'\tunknown eighth column',
])
def test_ambiguous_connectors_or_columns_still_stop_atomic_import(source):
    original=sheet();baseline=deepcopy(original)
    out=import_sections(original,'b'*12+'\n'+source+'\n'+'b'*12,new_vault()['settings'])
    assert_retained(out, baseline, "b")
    assert original==baseline


def test_followed_by_and_and_in_same_table_keep_relationships():
    source='Medications:\n'+order()+'\nAnd\n'+order('fat emulsion bag')+'\nFollowed by\n'+order('[START ON 1/4/26] fat emulsion bag')
    out=parse_medications(source)
    assert not out.error and len(out.rows)==3
    assert out.rows[1]['name'].startswith('And:')
    assert out.rows[2]['name'].startswith('Followed by: [START ON')


def test_full_synthetic_case_retains_all_18_orders_and_every_imported_section():
    s=sheet()
    assert len(s['medications'])==18
    assert len(s['labs']['rows'])==45
    assert len(s['vitals'])==5
    assert s['noninvasive'][0]['device']=='HFNC'
    assert s['nutrition']['weight']=='8.8 kg'
    assert s['neuro_vitals']['k'] and s['neuro_vitals']['l']
    assert s['medications'][1]['name'].startswith('[Held by provider]')
    assert s['medications'][15]['name'].startswith('[START ON 1/4/2026]')


def test_new_export_formats_keep_linked_pn_details():
    s=sheet()
    outputs=[handoff_html(s),handoff_text(s)]
    outputs+=['\n'.join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(s))).pages)]
    for text in outputs:
        for token in ['Pediatric 2-in-1 PN','And: fat emulsion','25 mL/hr','2.5 mL/hr','[Held by provider]','[START ON 1/4/2026]']:
            assert token in text
        assert 'TEST_PROVIDER_NOT_RETAINED' not in text and 'TEST_ADMIN_NOT_RETAINED' not in text


def test_synthetic_18_order_case_is_one_landscape_page_with_all_labs():
    s=sheet();doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert len(doc)==1 and doc[0].rect==fitz.Rect(0,0,792,612)
    layout=print_layout_info(s)
    assert layout['fits_one_page'] and 6.5 <= layout['font_size'] <= 8.0
    text=doc[0].get_text()
    for term in ('Hepatic','Coagulation','Gas ART','Inflammatory','01/03/26','01/02/26'):
        assert term in text
    for block in doc[0].get_text('blocks'):
        assert 0<=block[0]<block[2]<=792 and 0<=block[1]<block[3]<=612


def test_new_lab_summaries_are_horizontal_and_only_latest_gas():
    s=sheet();html=handoff_html(s)
    assert html.count('<svg ')==4
    assert html.count('class="lab-summary"')==3  # only inflammatory markers print in ID
    fields = fields_with_medications(s)
    assert 'Coagulation' not in fields['Infectious Disease']
    assert 'Coagulation' in fields['Lab Results / Trends']
    assert 'Inflammatory markers' in fields['Infectious Disease']
    assert 'Gas ART' in html and 'Gas VEN' not in html
    assert 'Hepatic [01/03/26]' in html
    assert 'AST: 31 | ALT: 22 | ALKPHOS: 210' in html
    assert 'font-size:8pt' in html
    page=fitz.open(stream=handoff_pdf(s),filetype='pdf')[0]
    rects=[page.search_for(word)[0] for word in ('AST:','ALT:','ALKPHOS:')]
    assert max(r.y0 for r in rects)-min(r.y0 for r in rects)<1
    assert rects[0].x0<rects[1].x0<rects[2].x0


def test_mixed_lab_dates_stay_attached_to_each_result():
    card={'title':'Hepatic | latest','kind':'branch','rows':{
        'ALT':{'component':'ALT','value':'21','date':'01/03/2026'},
        'AST':{'component':'AST','value':'32 (H)','date':'01/02/2026'}}}
    text=horizontal_card_markup(card)
    assert 'ALT: 21 [01/03/26]' in text and 'AST: 32 (H) [01/02/26]' in text


def test_horizontal_output_escapes_source_and_preserves_long_lab_value():
    s=sheet();s['labs']['rows'][0]['value']='X'*200+'END_LONG_RESULT'
    s['labs']['rows'][5]['value']='<script>not executable</script>'+' Y'*250+'END_EXTRA_RESULT'
    html=handoff_html(s)
    assert '<script>not' not in html and '&lt;script&gt;' in html
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    text='\n'.join(p.get_text() for p in doc)
    assert 'END_LONG_RESULT' in text and 'END_EXTRA_RESULT' in text
    for page in doc:
        for block in page.get_text('blocks'):
            assert block[0]>=0 and block[2]<=793 and block[1]>=0 and block[3]<=613


def test_more_content_continues_without_dropping_or_duplicate_entries():
    s=sheet();s['fields']['Neurologic']='\n'.join(f'NEURO_SENTINEL_{i:04d}' for i in range(180))
    s['fields']['Other Medications']='\n'.join(f'MED_SENTINEL_{i:04d}' for i in range(140))
    s['fields']['Access']='\n'.join(f'ACCESS_SENTINEL_{i:04d}' for i in range(55))
    assert not print_layout_info(s)['fits_one_page']
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert len(doc)>1
    text='\n'.join(p.get_text() for p in doc)
    for prefix,count in [('NEURO',180),('MED',140),('ACCESS',55)]:
        for i in range(count):assert text.count(f'{prefix}_SENTINEL_{i:04d}')==1
    assert 'And: fat emulsion' in text
    for page in doc:
        for block in page.get_text('blocks'):
            assert block[0]>=0 and block[2]<=793 and block[1]>=0 and block[3]<=613


def test_batch_compact_one_page_per_room():
    first=sheet();second=sheet();second['room']='P4104'
    doc=fitz.open(stream=handoffs_pdf([first,second]),filetype='pdf')
    assert len(doc)==2
    assert 'Room P4102' in doc[0].get_text() and 'Room P4104' in doc[1].get_text()
    assert handoffs_html([first,second]).count('<main>')==2


def test_render_and_example_callback(app,monkeypatch):
    open_room(app);app.load_compact_sample();app.create_handoff()
    assert len(app.st.session_state['drafts']['P4102']['medications'])==18
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    pdfs=[data for label,data in downloads if label=='Download this handoff (PDF)']
    assert len(fitz.open(stream=pdfs[0],filetype='pdf'))==1


def test_same_schema_roundtrip_preserves_mapping_hiding_and_all_order_fields():
    s=sheet();name=s['medications'][5]['name']
    v=save_sheet_in(new_vault(),s)
    v['settings']['medication_mappings']=upsert_rule([],'fat emulsion','FEN / GI')
    v['settings']['medication_visibility']=set_visibility_rule([],name,True)
    key=generate_key();restored=open_vault(seal_vault(v,key),key)
    assert restored==v and restored['schema']==32 and upgrade_vault(v)==v


def test_bounded_small_font_fits_crowded_column_without_deleting_lines():
    s=new_sheet('P4102')
    s['fields']['Neurologic']='\n'.join(f'ROW_{i:03d}' for i in range(57))
    info=print_layout_info(s)
    assert info['fits_one_page'] and 6.5 <= info['font_size'] < 8.0
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    assert len(doc)==1
    text=doc[0].get_text()
    for i in range(57):assert text.count(f'ROW_{i:03d}')==1
