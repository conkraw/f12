from recovery_helpers import assert_retained
"""P-matrix regression, export, persistence, callback and safety tests.

Synthetic values only. The chronological/column pattern mirrors Epic output.
"""
from copy import deepcopy
from pathlib import Path
from io import BytesIO
import json
import pytest
from pypdf import PdfReader
from cryptography.fernet import Fernet
from blood_gases import (parse_gases, gas_label, latest_sample, gas_summary, empty_gases,
                         validate_gases, legacy_gases, gas_card, FIELDS)
from models import (new_sheet, new_vault, save_sheet_in, upgrade_vault, validate_sheet,
                    fields_with_medications, ValidationError)
from importing import import_sections
from parser import parse_smartphrase
from labs import parse_labs, result_cards
from exports import handoff_text, handoff_pdf, handoff_html, handoffs_pdf, handoffs_html
from github_store import seal_vault, open_vault
from batching import available_handoffs
from test_callbacks import app, open_room

TABLE = """Results from last 7 days
Lab\tUnits\t01/03/26
0804\t01/01/26
2127\t01/01/26
2002
PH VEN\t\t -- \t -- \t7.20*
PCO2 VEN\tmmHg\t -- \t -- \t60*
PO2 VEN\tmmHg\t -- \t -- \t50
BASE EXC VEN\tmmol/L\t -- \t -- \t-3*
PH ART\t\t7.40\t  < >\t --
PCO2 ART\tmmHg\t40\t  < >\t --
PO2 ART, 'POCT PO2, ARTERIAL'\tmmHg\t90\t  < >\t --
BASE EXC ART, 'POCT BASE EXCESS, ARTERIAL'\tmmol/L\t1\t  < >\t --
PO2 (TEMP CORRECTED)\tmmHg\t90\t  < >\t50
BD, ISTAT, VEN\t%\t -- \t -- \t50
BASE DEFICIT ISTAT ART\t%\t30\t  < >\t --
 < > = values in this interval not displayed.
"""


def wrap(letter, text):
    return letter*16+'\n'+text+'\n'+letter*16


def imported(text=TABLE, base=None):
    result=import_sections(base or new_sheet('P4102'), wrap('p',text), new_vault()['settings'])
    assert not result.errors, result.errors
    return result.sheet


def parsed(text=TABLE):
    result=parse_gases(text)
    assert not result.error, result.error
    return result.data


def single(specimen='ART', date='01/03/26 0804', value='7.40'):
    return f'Results from last 7 days\nLab\tUnits\t{date}\nPH {specimen}\t\t{value}'


def test_exact_wrapped_header_pattern_reads_same_column_only():
    data=parsed()
    assert len(data['samples'])==2
    chosen,issues=latest_sample(data)
    assert not issues and chosen['specimen']=='ART' and chosen['date']=='01/03/26 0804'
    assert {k:v['value'] for k,v in chosen['values'].items()}=={'pH':'7.40','PCO2':'40','PO2':'90','Base excess':'1'}
    assert 'PO2 (TEMP CORRECTED)' not in str(data) and 'ISTAT' not in str(data)
    assert all('< >' not in v['value'] for sample in data['samples'] for v in sample['values'].values())


@pytest.mark.parametrize('specimen',['VEN','ART','CAP','VENOUS','ARTERIAL','CAPILLARY'])
@pytest.mark.parametrize('label',['PH','PCO2','PO2','HCO3','BASE EXC','BASE EXCESS','O2 SAT'])
def test_explicit_specimen_aliases(specimen,label):
    result=gas_label(label+' '+specimen)
    assert result and result[0] in ('VEN','ART','CAP') and result[1] in FIELDS


@pytest.mark.parametrize('label',['PO2 (TEMP CORRECTED)','BD, ISTAT, VEN','BASE DEFICIT ISTAT ART','PCO2','PH','O2SAT UNKNOWN'])
def test_untyped_or_unrequested_rows_do_not_acquire_guessed_type(label):
    assert gas_label(label) is None


@pytest.mark.parametrize('header',[
 '01/03/26 0804\t01/01/26 2127\t01/01/26 2002',
 '01/03/26\n0804\t01/01/26\n2127\t01/01/26\n2002',
 '01/03/26\t01/01/26\t01/01/26\n\t\t0804\t2127\t2002',
 '01/03/2026 08:04\t01/01/2026 21:27\t01/01/2026 20:02',
 '01/03/2026 8:04 AM\t01/01/2026 9:27 PM\t01/01/2026 8:02 PM',
])
def test_header_variants_preserve_positions(header):
    data=parsed('Lab\tUnits\t'+header+'\nPH ART\t\t7.40\t7.30\t7.20')
    latest,issues=latest_sample(data)
    assert not issues and latest['values']['pH']['value']=='7.40'
    assert '08:04' in gas_summary(data)


@pytest.mark.parametrize('specimen',['VEN','ART','CAP'])
def test_newer_type_wins_not_an_arterial_priority(specimen):
    source='Lab\tUnits\t01/03/26 0804\t01/03/26 0900\nPH ART\t\t7.40\t--\nPH '+specimen+'\t\t--\t7.35'
    data=parsed(source) if specimen!='ART' else parsed('Lab\tUnits\t01/03/26 0804\t01/03/26 0900\nPH ART\t\t7.40\t7.35')
    latest,_=latest_sample(data)
    assert latest['specimen']==specimen and latest['values']['pH']['value']=='7.35'


def test_unsorted_columns_chronological_selection():
    data=parsed('Lab\tUnits\t01/01/26 2300\t01/03/26 0100\t01/02/26 2100\nPH CAP\t\t7.20\t7.40\t7.30')
    assert latest_sample(data)[0]['values']['pH']['value']=='7.40'


def test_newer_incomplete_not_completed_using_older_values():
    data=parsed('Lab\tUnits\t01/03/26 0900\t01/03/26 0800\nPH ART\t\t7.40\t7.30\nPCO2 ART\tmmHg\t--\t45')
    chosen,_=latest_sample(data)
    assert list(chosen['values'])==['pH']
    assert '45' not in gas_summary(data)


def test_latest_column_without_ph_still_keeps_documented_result():
    data=parsed('Lab\tUnits\t01/03/26 0900\t01/03/26 0800\nPH VEN\t\t--\t7.30\nPCO2 VEN\tmmHg\t50\t45')
    assert 'pH' not in latest_sample(data)[0]['values']
    assert latest_sample(data)[0]['values']['PCO2']['value']=='50'


def test_hidden_interval_values_are_not_newer_results():
    data=parsed('Lab\tUnits\t01/03/26 0900\t01/03/26 0800\nPH VEN\t\t< >\t7.30')
    assert latest_sample(data)[0]['date'].endswith('0800')


@pytest.mark.parametrize('missing',['--','---','< >','<>','—','','Pending','N/A'])
def test_all_empty_cells_do_not_make_a_gas(missing):
    assert parsed(single(value=missing))==empty_gases()


def test_source_flags_zero_negatives_and_decimals_are_preserved():
    d=parsed('Lab\tUnits\t01/03/26 0804\nPH CAP\t\t7.201*\nBASE EXC CAP\tmmol/L\t-4*\nPCO2 CAP\tmmHg\t0')
    text=gas_summary(d)
    assert '7.201*' in text and '-4* mmol/L' in text and 'PCO2: 0 mmHg' in text


@pytest.mark.parametrize('source',[
 'Lab\tUnits\t01/33/26 0804\nPH ART\t\t7.40',
 'Lab\tUnits\t01/03/26 9999\nPH ART\t\t7.40',
 'Lab\tUnits\t01/03/26\n804\nPH ART\t\t7.40',
 'Lab\tUnits\t01/03/26 0804\t01/02/26 0804\nPH ART\t\t7.40',
 'Lab\tUnits\t01/03/26 0804\nPH ART\t\t7.40\tEXTRA',
 'Lab\tUnits\t01/03/26 0804\nPH ART\t\tunknown-result',
 'Lab\tUnits\t01/03/26 0804\nPH ART\t\t7.40\nPH ART\t\t7.35',
 'PH ART\t\t7.40',
])
def test_malformed_tables_block_import_without_erasing_existing(source):
    base=imported();before=deepcopy(base)
    result=import_sections(base,wrap('p',source),new_vault()['settings'])
    assert_retained(result, before, "p")
    assert base==before


def test_duplicates_identical_do_not_duplicate_component():
    d=parsed(single()+'\nPH ART\t\t7.40')
    assert len(d['samples'])==1 and len(d['samples'][0]['values'])==1


def test_date_only_same_day_ties_are_visible_not_guessed():
    d=parsed('Lab\tUnits\t01/03/26\t01/03/26\nPH VEN\t\t7.30\t--\nPH ART\t\t--\t7.40')
    latest,issues=latest_sample(d)
    assert latest['specimen']=='VEN' and issues
    assert 'source-order tie' in gas_card({'rows':[],'notes':[]},d)['title']


def test_same_timestamp_multiple_types_keep_first_source_type_with_notice():
    d=parsed(single('VEN')+'\nPH ART\t\t7.40')
    selected,issues=latest_sample(d)
    assert selected['specimen']=='VEN' and issues


def test_paired_p_without_extra_heading_and_with_optional_heading():
    for body in (TABLE,'Blood Gas:\n'+TABLE,'Latest blood gas:\n'+TABLE):
        assert not parse_smartphrase(wrap('p',body)).invalid
        assert imported(body)['blood_gas']['samples']


def test_p_does_not_invalidate_blood_gas_subheading_in_g():
    result=import_sections(new_sheet('P4102'),wrap('g','LABS:\nBlood Gas:\nPHA\t7.40\t01/03/26'),new_vault()['settings'])
    assert not result.errors


def test_partial_import_and_empty_p_semantics():
    base=imported();base['fields']['Respiratory']='Keep manual note'
    base['labs']=parse_labs('LABS:\nPHA\t7.41\t01/04/26').data
    for letter,body in [('a','Diagnoses:\n1. Synthetic note'),('g','LABS:\nWBC\t10\t01/03/26')]:
        changed=import_sections(base,wrap(letter,body),new_vault()['settings'])
        assert not changed.errors and changed.sheet['blood_gas']==base['blood_gas']
    changed=imported('',base)
    assert changed['blood_gas']==empty_gases()
    assert 'Gas ART' not in handoff_text(changed), 'An explicit empty P must not resurrect old G gas rows'
    assert changed['fields']['Respiratory']=='Keep manual note'


def test_p_reimport_replaces_no_accumulation():
    original=imported()
    again=imported(single('CAP'),original)
    assert len(again['blood_gas']['samples'])==1
    assert 'Gas CAP' in handoff_text(again) and 'Gas ART' not in handoff_text(again)


def test_conflicting_any_section_remains_atomic():
    original=imported();before=deepcopy(original)
    change=import_sections(original,wrap('p',TABLE)+'\n'+wrap('b','Medications:\nbad row'),new_vault()['settings'])
    assert_retained(change, before, "b")
    assert original==before


def test_p_takes_precedence_over_more_recent_legacy_g():
    s=imported()
    s['labs']=parse_labs('LABS:\nPHV\t7.11\t01/09/26\nAST\t20\t01/09/26').data
    for text in (handoff_text(s),handoff_html(s)):
        assert 'Gas ART' in text and 'Gas VEN' not in text and '7.11' not in text and 'AST' in text


def test_legacy_fallback_only_one_specimen_date_not_mixed():
    l=parse_labs('LABS:\nPHA\t7.40\t01/03/26 0800\nPCO2A\t40\t01/02/26 0800\nPHV\t7.30\t01/01/26 0800').data
    c=gas_card(l)
    assert c['title'].startswith('Gas ART') and set(c['rows'])=={'pH'}
    assert 'legacy G' in c['title']
    assert len([x for x in result_cards(l) if x['title'].startswith('Gas ')])==1


def test_single_and_batch_exports_only_one_gas_per_room():
    one=imported();one['fields']['Diagnoses']='Synthetic example only'
    two=imported(single('CAP','01/04/26 1100','7.32'));two['room']='P4104'
    for sheet in [one,two]:
        original=deepcopy(sheet)
        pdf=PdfReader(BytesIO(handoff_pdf(sheet)))
        assert len(pdf.pages)==1
        for text in (handoff_text(sheet),handoff_html(sheet),pdf.pages[0].extract_text()):
            assert text.count('Gas '+latest_sample(sheet['blood_gas'])[0]['specimen'])==1
            assert '7.20' not in text and 'PO2 (TEMP CORRECTED)' not in text and 'ISTAT' not in text
        assert sheet==original
    pages=PdfReader(BytesIO(handoffs_pdf([one,two]))).pages
    assert len(pages)==2
    assert 'Gas ART' in pages[0].extract_text() and 'Gas CAP' not in pages[0].extract_text()
    assert 'Gas CAP' in pages[1].extract_text() and 'Gas ART' not in pages[1].extract_text()
    assert handoffs_html([one,two]).count('Gas ART')==1


def test_gas_only_room_in_print_all_and_empty_p_not_blank_patient():
    s=imported();assert list(available_handoffs(new_vault(),{'P4102':s}))==['P4102']
    s=imported('',s);assert not available_handoffs(new_vault(),{'P4102':s})


def test_schema11_migration_preserves_old_fields_mapping_infusion_and_notes():
    s=imported();s.pop("feeds", None);s.pop("devices", None);s.pop("neuro_devices", None);s.pop("pacemaker", None);s.pop("diet", None);s.pop("import_warnings", None);s.pop("intake_output", None);s.pop("recurring_orders", None);s.pop("cbc", None);s.pop('blood_gas')
    old=new_vault();old['schema']=11;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old["settings"].pop("medication_gi_groups", None);old['rooms']['P4102']=s
    old['settings']['medication_mappings']=[{'name':'test','match':'prefix','destination':'Neurologic'}]
    before=deepcopy(old)
    updated=upgrade_vault(old)
    assert old==before and updated['schema']==33
    assert updated['settings']==dict(old['settings'], medication_gi_groups=[], medication_groups=[])
    assert updated['rooms']['P4102']==dict(s,blood_gas=None,cbc=None,recurring_orders=None,intake_output=None,import_warnings={},feeds=None,devices=None,neuro_devices=None,pacemaker=None,diet=None)
    key=Fernet.generate_key().decode()
    token=Fernet(key.encode()).encrypt(json.dumps(old).encode())
    assert open_vault(token,key)==updated


def test_new_gas_encrypted_roundtrip():
    vault=save_sheet_in(new_vault(),imported())
    key=Fernet.generate_key().decode()
    encrypted=seal_vault(vault,key)
    # Short letter sequences can occur by chance in base64 ciphertext.
    # Check complete plaintext markers plus exact decrypt/validate round-trip.
    assert b'7.40' not in encrypted and b'"specimen": "ART"' not in encrypted
    assert open_vault(encrypted,key)==vault


@pytest.mark.parametrize('bad',[
 {'samples':'wrong','notes':[]},
 {'samples':[],'notes':'wrong'},
 {'samples':[],'notes':[],'unexpected':'should not be dropped'},
])
def test_invalid_stored_gas_data_rejected(bad):
    with pytest.raises(ValueError):validate_gases(bad)


@pytest.mark.parametrize('field,bad',[('date','tomorrow'),('specimen','UNKNOWN'),('include','yes'),('values',{})])
def test_invalid_stored_sample_rejected(field,bad):
    d=parsed();d['samples'][0][field]=bad
    with pytest.raises(ValueError):validate_gases(d)


def test_editor_updates_selected_value_and_no_cross_room(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=imported()
    row=ss['drafts']['P4102']['blood_gas']['samples'][0]
    ss['correction']='7.42'
    app.gas_edit('P4102',row['id'],'pH','value','correction')
    assert latest_sample(ss['drafts']['P4102']['blood_gas'])[0]['values']['pH']['value']=='7.42'
    ss['correction']='7.10'
    app.gas_edit('P4104',row['id'],'pH','value','correction')
    assert latest_sample(ss['drafts']['P4102']['blood_gas'])[0]['values']['pH']['value']=='7.42'


def test_editor_invalid_value_rolls_back(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=imported()
    row=ss['drafts']['P4102']['blood_gas']['samples'][0];ss['correction']='--'
    app.gas_edit('P4102',row['id'],'pH','value','correction')
    assert ss['correction']=='7.40' and ss['notice'][0]=='error'


def test_autosave_captures_pending_gas_edit_before_switch(app):
    open_room(app);ss=app.st.session_state;ss['drafts']['P4102']=imported()
    row=ss['drafts']['P4102']['blood_gas']['samples'][0]
    key='gas_'+row['id']+'_0_value';ss[key]='7.43'
    open_room(app,'P4104')
    assert ss['vault']['rooms']['P4102']['blood_gas']['samples'][0]['values']['pH']['value']=='7.43'
    assert key not in ss


def test_ui_render_and_downloads_keep_gases(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app);app.st.session_state['drafts']['P4102']=imported()
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_schema11_keeps_nonempty_infusion_rules():
    from infusions import set_infusion_rule
    old=new_vault();old['schema']=11;old.pop("reset_generation", None);old["settings"].pop("medication_groups", None);old["settings"].pop("medication_gi_groups", None)
    old['settings']['medication_infusions']=set_infusion_rule([],{'name':'Synthetic medicine','route':'Intravenous','frequency':'Continuous'},'other')
    new=upgrade_vault(old)
    assert new['settings']==dict(old['settings'], medication_gi_groups=[], medication_groups=[])


def test_session11_upgrade_keeps_unsaved_gas_independent_notes(app):
    open_room(app);ss=app.st.session_state;app.save_room(None)
    ss['drafts']['P4102']['fields']['Neurologic']='UNSAVED sentinel'
    ss['vault']['schema']=11;ss['vault'].pop("reset_generation", None);ss['vault']["settings"].pop("medication_groups", None);ss['vault']["settings"].pop("medication_gi_groups", None)
    for sheet in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):
        sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas')
    app.upgrade_existing_session()
    assert ss['vault']['schema']==33
    assert ss['drafts']['P4102']['blood_gas'] is None
    assert ss['drafts']['P4102']['fields']['Neurologic']=='UNSAVED sentinel'


def test_edited_unit_is_escaped_not_executed():
    s=imported();s['blood_gas']['samples'][0]['values']['PCO2']['unit']='<b>unsafe</b>'
    text=handoff_html(s)
    assert '&lt;b&gt;unsafe&lt;/b&gt;' in text and '<b>unsafe</b>' not in text


def test_exclude_newest_chooses_next_without_merging():
    s=imported();s['blood_gas']['samples'][0]['include']=False
    chosen,_=latest_sample(s['blood_gas'])
    assert chosen['specimen']=='VEN' and chosen['values']['pH']['value']=='7.20*'
    assert 'Gas ART' not in handoff_text(s)
