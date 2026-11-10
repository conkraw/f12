from recovery_helpers import assert_retained
"""Synthetic regressions for Epic taper connectors and scheduled orders.

No patient records, real provider names, credentials or external services.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
import pytest
import fitz

from medications import (parse_medications, format_medication, destination_for,
    rule_for_inline_mapping, suggested_key, upsert_rule, set_visibility_rule,
    hidden_for, remap, match_name, visibility_name)
from importing import import_sections
from models import (new_sheet, new_vault, save_sheet_in, validate_sheet, validate_vault,
                    fields_with_medications, upgrade_vault)
from parser import parse_smartphrase
from security import generate_key, seal_vault, open_vault
from exports import handoff_pdf, handoff_html, handoff_text, handoffs_pdf
from test_callbacks import app, open_room

ROOT = Path(__file__).parents[1]
SAMPLE = (ROOT/'examples/synthetic_medication_taper.txt').read_text()


def order(name='Example steroid injection 2 mg', dose='2 mg', frequency='q12h',
          route='Intravenous', rate='', bullet='•\t', trailing=True):
    cells = [name, dose, route, frequency]
    if trailing:
        cells += ['PROVIDER_PRIVATE_SENTINEL', rate, 'ADMIN_PRIVATE_SENTINEL']
    return bullet + '\t'.join(cells)


def taper(connector='\tFollowed by', bullet='•\t'):
    return '\n'.join(['Medications:',
        order(bullet=bullet), connector,
        order('[START ON 1/4/2026] Example steroid injection 1 mg', '1 mg', bullet=bullet),
        connector,
        order('[START ON 1/5/2026] Example steroid injection 0.5 mg', '0.5 mg',
              'q24h SCH', bullet=bullet)])


def imported():
    out = import_sections(new_sheet('P4102'), SAMPLE, new_vault()['settings'])
    assert not out.errors, out.errors
    return out.sheet


@pytest.mark.parametrize('connector', ['Followed by','\tFollowed by','    Followed by',
    '\t\tFollowed by\t', '  FOLLOWED BY  ', '\tFollowed by:', '• Followed by',
    'Followed\u00a0by', 'Followed   by', '▪\tFollowed by'])
def test_connector_is_not_a_table_column(connector):
    result = parse_medications(taper(connector))
    assert not result.error, result.issues
    assert len(result.rows) == 3
    assert [r['dose'] for r in result.rows] == ['2 mg','1 mg','0.5 mg']
    assert [r['frequency'] for r in result.rows] == ['q12h','q12h','q24h SCH']
    assert all(r['route'] == 'Intravenous' for r in result.rows)
    assert result.rows[1]['name'].startswith('Followed by: [START ON 1/4/2026]')
    assert result.rows[2]['name'].startswith('Followed by: [START ON 1/5/2026]')
    assert result.rows[0]['name'].startswith('Example steroid')
    assert 'PRIVATE_SENTINEL' not in json.dumps(result.rows)


@pytest.mark.parametrize('bullet', ['•\t', '• ', '●\t', '▪ ', '◦ ', '- ', ''])
def test_bullet_variants_and_tabular_rows_without_bullets(bullet):
    result = parse_medications(taper(bullet=bullet))
    assert not result.error and len(result.rows) == 3


@pytest.mark.parametrize('ending',['\n','\r\n','\r'])
def test_line_endings(ending):
    result = parse_medications(taper().replace('\n',ending))
    assert not result.error and len(result.rows)==3


def test_connector_in_extra_final_tab_cell():
    source = 'Medications:\n' + order() + '\tFollowed by\t \n' + order('[START ON 1/4/2026] Example steroid injection 1 mg','1 mg')
    result = parse_medications(source)
    assert not result.error and len(result.rows)==2
    assert result.rows[1]['name'].startswith('Followed by:')
    assert 'PRIVATE_SENTINEL' not in json.dumps(result.rows)


def test_omitted_trailing_cells_and_blank_rate_do_not_shift():
    source = 'Medications:\n'+order(trailing=False)+'\n\tFollowed by\n'+order(
        '[START ON 1/4/2026] Example steroid injection 1 mg','1 mg',trailing=False)
    result = parse_medications(source)
    assert not result.error and len(result.rows)==2
    assert all(r['last_rate']==r['rate_time']=='' for r in result.rows)


def test_blank_topical_dose_after_connector_is_still_blank():
    result = parse_medications('Medications:\n'+order()+'\nFollowed by\n'+order(
        '[START ON 1/4/2026] Example cream','',route='Topical',frequency='PRN'))
    assert not result.error
    assert result.rows[1]['dose']=='' and result.rows[1]['route']=='Topical'


def test_wrapped_medication_name_after_connector():
    row = order('[START ON 1/4/2026] Example steroid\nsyringe 1 mg','1 mg')
    result = parse_medications('Medications:\n'+order()+'\nFollowed by\n'+row)
    assert not result.error and len(result.rows)==2
    assert 'steroid syringe' in result.rows[1]['name']


def test_wrapped_start_label_with_newline_keeps_mapping():
    row=order('[START ON 1/4/2026]\nExample steroid injection 1 mg','1 mg')
    rules=upsert_rule([], 'Example steroid', 'Neurologic')
    result=parse_medications('Medications:\n'+row,rules)
    assert not result.error
    assert result.rows[0]['section']=='Neurologic'
    assert '[START ON 1/4/2026]' in format_medication(result.rows[0])


def test_followed_by_literal_inside_name_is_not_deleted():
    result=parse_medications('Medications:\n'+order('Example followed by text injection 2 mg'))
    assert not result.error
    assert result.rows[0]['name']=='Example followed by text injection 2 mg'


@pytest.mark.parametrize('source', [
    'Medications:\nFollowed by\n'+order(),
    'Medications:\n'+order()+'\nFollowed by',
    'Medications:\n'+order()+'\nFollowed by\nFollowed by\n'+order(),
    'Medications:\n'+order()+'\nFollowed by\nmissing columns',
])
def test_incomplete_or_ambiguous_sequence_does_not_silently_pass(source):
    result=parse_medications(source)
    assert result.error
    sheet=new_sheet('P4102');sheet['fields']['Neurologic']='Previous note'
    before=deepcopy(sheet)
    out=import_sections(sheet,'b'*12+'\n'+source+'\n'+'b'*12,new_vault()['settings'])
    assert_retained(out, before, "b")
    assert sheet==before


def test_arbitrary_eighth_column_still_rejected():
    result=parse_medications('Medications:\n'+order()+'\tunexpected data')
    assert result.error


def test_tabless_taper_is_not_guessed():
    result=parse_medications(taper().replace('\t',' '))
    assert result.error


@pytest.mark.parametrize('prefix', [
    '[START ON 1/4/2026] ', '[START ON 01/04/26 0800] ',
    'Followed by: [START ON 1/4/2026] ',
    '[Held by provider] [START ON 1/4/2026] ',
    'Followed by: [START ON 1/4/2026] [Held by provider] ',
    '[Discontinued] [START ON 1/4/2026] ',
])
def test_known_annotations_do_not_block_mapping_and_remain_in_output(prefix):
    name=prefix+'dexAMETHasone (Example) injection 1 mg'
    rules=upsert_rule([], 'dexamethasone', 'Neurologic')
    result=parse_medications('Medications:\n'+order(name,'1 mg'),rules)
    assert not result.error and result.rows[0]['section']=='Neurologic'
    assert result.rows[0]['name']==name
    assert prefix.strip() in format_medication(result.rows[0])
    assert suggested_key(name)=='dexamethasone'
    assert rule_for_inline_mapping(name,rules)==('dexamethasone','prefix')


def test_suggested_rule_does_not_store_start_date_or_sequence_words():
    assert rule_for_inline_mapping('Followed by: [START ON 1/5/2026] dexAMETHasone 0.5 mg',[])==('dexamethasone','prefix')


def test_user_exact_dated_mapping_still_works_and_remains_specific():
    name='[START ON 1/4/2026] Example steroid 1 mg'
    rules=upsert_rule([],name,'Neurologic','exact')
    assert destination_for('Followed by: '+name,rules)=='Neurologic'
    assert destination_for(name.replace('1/4/2026','1/5/2026'),rules)=='Other Medications'


def test_unknown_bracket_annotation_is_not_stripped_for_routing():
    rules=upsert_rule([],'example','Neurologic')
    assert destination_for('[UNKNOWN context] Example 1 mg',rules)=='Other Medications'


def test_exact_generic_mapping_matches_timed_order():
    rules=upsert_rule([],'Example steroid 1 mg','Neurologic','exact')
    assert destination_for('Followed by: [START ON 1/4/2026] Example steroid 1 mg',rules)=='Neurologic'


def test_no_fuzzy_matching_when_order_is_scheduled():
    rules=upsert_rule([],'albuterol','Respiratory')
    assert destination_for('[START ON 1/4/2026] levalbuterol 1 mg',rules)=='Other Medications'


def test_hide_one_dated_step_does_not_hide_the_other_date():
    first='Followed by: [START ON 1/4/2026] Example steroid 0.5 mg'
    other='Followed by: [START ON 1/5/2026] Example steroid 0.5 mg'
    visibility=set_visibility_rule([],first,True)
    assert hidden_for(first,visibility)
    assert hidden_for(first.replace('Followed by: ',''),visibility)
    assert not hidden_for(other,visibility)
    assert not hidden_for('Example steroid 0.5 mg',visibility)
    visibility=set_visibility_rule(visibility,first,False)
    assert not hidden_for(first,visibility)
    assert len(visibility)==1


def test_explicit_visibility_prefix_can_cover_scheduled_steps():
    rules=set_visibility_rule([],'Example steroid',True,'prefix')
    assert hidden_for('Followed by: [START ON 1/4/2026] Example steroid 1 mg',rules)
    assert not hidden_for('Example steroidX 1 mg',rules)


def test_full_import_retains_all_sections_and_separate_taper_orders():
    sheet=imported()
    assert len(sheet['medications'])==5
    assert len(sheet['vitals'])==4
    assert len(sheet['labs']['rows'])==20
    assert sheet['ventilation'] is None and sheet['noninvasive']==[]
    assert sheet['fields']['Diagnoses']=='Synthetic medication-taper practice only'
    steroids=[r for r in sheet['medications'] if 'dexamethasone' in r['name'].lower()]
    assert len(steroids)==3
    assert [r['dose'] for r in steroids]==['2 mg','1 mg','0.5 mg']
    assert all(r['section']=='Other Medications' for r in steroids)


def test_sequence_and_dates_remain_through_encryption_and_same_schema():
    s=imported();key=generate_key()
    v=save_sheet_in(new_vault(),s)
    token=seal_vault(v,key)
    restored=open_vault(token,key)
    assert restored==v and restored['schema']==33
    assert upgrade_vault(restored)==restored
    assert '[START ON 1/4/2026]' in restored['rooms']['P4102']['medications'][2]['name']
    assert 'Followed by:' in restored['rooms']['P4102']['medications'][2]['name']


def test_reimport_is_replacement_and_does_not_duplicate_taper_or_notes():
    s=imported();s['fields']['Neurologic']='Keep my note'
    out=import_sections(s,SAMPLE,new_vault()['settings'])
    assert len(out.sheet['medications'])==5
    assert out.sheet['fields']['Neurologic']=='Keep my note'
    assert out.sheet['medications'][2]['name'].count('Followed by:')==1


def test_unrelated_orders_after_taper_do_not_get_sequence_prefix():
    s=imported()
    assert not s['medications'][-1]['name'].startswith('Followed by:')
    assert '@ 25 mL/hr' in format_medication(s['medications'][-1])


def test_dates_and_frequency_in_text_html_and_pdf():
    s=imported();s['medications']=remap(s['medications'],upsert_rule([],'dexamethasone','Neurologic'))
    outputs=[handoff_text(s), handoff_html(s)]
    doc=fitz.open(stream=handoff_pdf(s),filetype='pdf')
    outputs.append(' '.join(page.get_text() for page in doc))
    for output in outputs:
        text=re.sub(r'\s+',' ',output)
        assert '[START ON 1/4/2026]' in text and '[START ON 1/5/2026]' in text
        assert text.count('Followed by:')==2
        assert 'q24h SCH' in text
        assert 'Example Provider' not in text
    assert doc[0].rect.width>doc[0].rect.height


def test_batch_print_preserves_sequence_in_each_room():
    one=imported();two=deepcopy(one);two['room']='P4104'
    doc=fitz.open(stream=handoffs_pdf([one,two]),filetype='pdf')
    assert len(doc)>=2
    text=' '.join(p.get_text() for p in doc)
    assert text.count('Followed by:')==4
    assert 'P4102' in text and 'P4104' in text


def test_taper_callback_creates_handoff_without_confirmation(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE
    app.create_handoff()
    assert not ss['import_result']['errors']
    assert len(ss['drafts']['P4102']['medications'])==5
    assert ss['paste']==''


def test_inline_taper_mapping_is_remembered_for_all_steps(app):
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    med=ss['drafts']['P4102']['medications'][2]
    key='med_draft_'+med['id']+'_section';ss[key]='Neurologic'
    app.medication_row_change('P4102',med['id'],'section',key,None)
    assert ss['vault']['settings']['medication_mappings']==[
        {'name':'dexamethasone','match':'prefix','destination':'Neurologic'}]
    steroid_rows=[r for r in ss['drafts']['P4102']['medications'] if 'dexamethasone' in r['name'].lower()]
    assert len(steroid_rows)==3 and all(r['section']=='Neurologic' for r in steroid_rows)
    app.save_room(None)
    assert ss['vault']['rooms']['P4102']['medications'][2]['section']=='Neurologic'


def test_synthetic_taper_button_loads_fixture(app):
    open_room(app);app.load_taper_sample()
    assert app.st.session_state['paste']==SAMPLE
    app.create_handoff()
    assert not app.st.session_state['import_result']['errors']


def test_ui_render_and_download_with_taper(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app);ss=app.st.session_state;ss['paste']=SAMPLE;app.create_handoff()
    downloads=equip(app,monkeypatch);app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)
