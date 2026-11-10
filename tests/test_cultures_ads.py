from recovery_helpers import assert_retained
"""Regression coverage for final ADS rows and F-block culture summaries.

All fixtures below are synthetic. No source clinician details or raw user
SmartPhrases are included in the delivery package.
"""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfReader

from parser import parse_smartphrase
from medications import parse_medications, set_visibility_rule, remap, visible, upsert_rule, format_medication
from cultures import (parse_cultures, validate_cultures, empty_cultures, compact_groups,
                      cultures_text, category_for, culture_date)
from importing import import_sections
from models import (new_sheet, new_vault, validate_sheet, validate_vault, upgrade_vault,
                    fields_with_medications, save_sheet_in, SCHEMA_VERSION)
from security import seal_vault, open_vault, generate_key
from exports import handoff_pdf, handoffs_pdf, handoff_html, handoff_text, handoffs_html
from batching import available_handoffs
from test_callbacks import app, open_room

SAMPLE=Path(__file__).parents[1]/'examples/synthetic_cultures_ads.txt'
ADS='vecuronium (Norcuron) 10 MG injection  - ADS Override Pull'
F='''CULTURES:
Susceptibility data from last 90 days.
Collected\tSpecimen Info\tOrganism\tCeftriaxone\tClindamycin\tVancomycin
01/06/26\tBlood, Arterial\tNo growth (In process)\t\t\t
01/06/26\tBlood, Arterial\tNo growth (Preliminary)\t\t\t
01/06/26\tAspirate from Trachea\tStreptococcus pneumoniae\t S\t S\t S
\t\tStaphylococcus aureus\t\t\t
\t\tBeta hemolytic Streptococcus, Group A\t\t\t
01/06/26\tBlood, Venous\tNo growth (In process)\t\t\t
01/06/26\tBlood, Venous\tNo growth (Preliminary)\t\t\t
'''


def block(letter, content):
    return letter*16+'\n'+content+'\n'+letter*16+'\n'


def import_text(text, sheet=None):
    result=import_sections(sheet or new_sheet('P4102'),text,new_vault()['settings'])
    assert not result.errors,result.errors
    return result.sheet


def parse(body):
    out=parse_cultures(body)
    assert not out.error,out.error
    return out.data


def test_preserve_final_ads_table_cells_at_section_boundary():
    raw='Medications:\n•\t'+ADS+'\t \t\t\t\t \t '
    parsed=parse_smartphrase(block('b',raw))
    assert parsed.blocks['b'].endswith('\t \t\t\t\t \t ')
    rows=parse_medications(parsed.blocks['b'])
    assert not rows.error and len(rows.rows)==1


@pytest.mark.parametrize('suffix',['','\t','\t '*2,'\t'*3,'\t'*6,'\t'*10,' '*6,'\u00a0\t \t'])
def test_name_only_ads_survives_clipboard_trim(suffix):
    sheet=import_text(block('b','Medications:\n•\t'+ADS+suffix))
    row=sheet['medications'][0]
    assert row['name']==' '.join(ADS.split())
    assert all(row[k]=='' for k in ('dose','route','frequency','last_rate','rate_time'))
    assert row['include'] and not row['hidden']
    assert '10 MG' in row['name'] and row['dose']==''


@pytest.mark.parametrize('name',['fentaNYL in NS 10 MCG/ML injection - ADS Override Pull',
    'midazolam PF (Versed) 2 MG/2ML injection - ADS Override Pull', ADS])
def test_repeated_identical_ads_entries_not_dropped(name):
    rows=import_text(block('b','Medications:\n'+'\n'.join('•\t'+name for _ in range(3))))['medications']
    assert len(rows)==3 and len({r['id'] for r in rows})==3
    assert all(r['name']==' '.join(name.split()) for r in rows)


@pytest.mark.parametrize('suffix',['\t2 mg','\t\tIntravenous',' extra unclear dose','\t\t\t\t\t\t\tEXTRA'])
def test_ads_exception_does_not_guess_nonempty_missing_columns(suffix):
    out=parse_medications('Medications:\n•\t'+ADS+suffix)
    assert out.error


def test_ordinary_name_only_medication_still_fails_safely():
    result=parse_medications('Medications:\n•\tacetaminophen injection 100 mg')
    assert result.error


def test_twelve_rows_including_eight_ads_entries_import_together():
    sheet=import_text(SAMPLE.read_text())
    assert len(sheet['medications'])==12
    ads=[r for r in sheet['medications'] if 'ADS Override Pull' in r['name']]
    assert len(ads)==8 and len({r['id'] for r in sheet['medications']})==12
    assert len(sheet['cultures']['rows'])==9
    assert sheet['vitals'] and sheet['labs']['rows'] and sheet['nutrition']
    assert all(not r['hidden'] for r in ads)
    assert 'Test clinician' not in json.dumps(sheet)


def test_hide_exact_override_keeps_active_drug_visible():
    sheet=import_text(SAMPLE.read_text())
    rows=sheet['medications']
    name=next(r['name'] for r in rows if 'fentaNYL' in r['name'])
    rules=set_visibility_rule([],name,True)
    routed=remap(rows,upsert_rule([],'fentanyl','Neurologic'),rules)
    assert sum(r['hidden'] for r in routed)==3
    active=parse_medications('Medications:\n•\tfentaNYL injection 10 mcg\t10 mcg\tIntravenous\tq1h PRN',visibility=rules).rows[0]
    assert visible(active)
    restored=remap(routed,[],set_visibility_rule(rules,name,False))
    assert not any(r['hidden'] for r in restored)


def test_multiorganism_rows_are_linked_and_sensitivities_removed():
    data=parse(F)
    assert len(data['rows'])==5
    resp=data['rows'][2]
    assert resp['specimen']=='Aspirate from Trachea'
    assert resp['organisms']==['Streptococcus pneumoniae','Staphylococcus aureus','Beta hemolytic Streptococcus, Group A']
    stored=json.dumps(data)
    assert 'Ceftriaxone' not in stored and 'Clindamycin' not in stored and 'Vancomycin' not in stored
    assert len(compact_groups(data))==3
    text=cultures_text(data)
    for organism in resp['organisms']:assert organism in text
    assert text.count('NGTD') == 2 and 'No growth' not in text
    assert 'No growth (In process)' in stored and 'No growth (Preliminary)' in stored


@pytest.mark.parametrize('site,category',[
 ('Blood, Central Line','Blood'),('Blood, Arterial','Blood'),('Blood, Venous','Blood'),
 ('Aspirate from Trachea','Respiratory'),('Sputum','Respiratory'),('Bronchoalveolar lavage','Respiratory'),
 ('Urine','Urine'),('CSF','CSF'),('Wound swab','Wound'),('Stool','Stool'),
 ('Swab from Pericardium','Other: swab from pericardium'),('Aspirate','Other: aspirate'),('Other','Other: other')])
def test_specimen_categories_do_not_invent_unspecified_sites(site,category):
    assert category_for(site)==category


def test_latest_two_per_type_not_latest_two_overall():
    data=parse('CULTURES:\nCollected\tSpecimen Info\tOrganism\n'+'\n'.join(
       f'01/{day:02}/26\t{site}\t{site} result {day}' for site in ('Blood','Sputum','Urine') for day in (4,6,5)))
    selected=compact_groups(data)
    assert len(selected)==6
    for kind in ('Blood','Respiratory','Urine'):
        assert [g['date'] for g in selected if g['category']==kind]==['01/06/26','01/05/26']
    assert len(data['rows'])==9


def test_duplicate_status_rows_do_not_use_up_both_slots():
    data=parse('CULTURES:\nCollected\tSpecimen Info\tOrganism\n'+
       '01/06/26\tBlood, Central Line\tNo growth (In process)\n'+
       '01/06/26\tBlood, Central Line\tNo growth (Preliminary)\n'+
       '01/06/26\tBlood, Central Line\tNo growth (In process)\n'+
       '01/06/26\tBlood, Central Line\tNo growth (Preliminary)\n'+
       '12/12/25\tBlood\tNo growth\n12/11/25\tBlood\tNo growth')
    groups=compact_groups(data)
    assert [g['date'] for g in groups]==['01/06/26','12/12/25']
    assert len(groups[0]['organisms'])==2 and len(groups[0]['row_ids'])==4
    assert len(data['rows'])==6


def test_newer_negative_blood_does_not_remove_other_site_positive():
    data=parse('CULTURES:\nCollected\tSpecimen Info\tOrganism\n'+
        '01/06/26\tBlood, Venous\tNo growth\n01/06/26\tBlood, Central Line\tNo growth\n'+
        '01/05/26\tBlood\tNo growth\n01/02/26\tSwab from Pericardium\tCandida parapsilosis')
    text=cultures_text(data)
    assert 'Candida parapsilosis' in text and '01/02/26' in text
    assert '01/05/26' not in text


def test_identical_same_date_site_rows_combined_only_for_display():
    data=parse('CULTURES:\n01/06/26\tBlood, Venous\tNo growth (In process)\n01/06/26\tBlood, Venous\tNo growth (In process)')
    assert len(data['rows'])==2 and len(compact_groups(data))==1
    assert cultures_text(data).count('NGTD')==1


def test_dates_sorted_as_dates_and_times_keep_distinct_groups():
    data=parse('CULTURES:\n12/31/25\tBlood\tOlder\n01/01/26 0800\tBlood\tEarly\n01/01/26 0900\tBlood\tLater')
    groups=compact_groups(data)
    assert [g['organisms'] for g in groups]==[['Later'],['Early']]


def test_same_date_ties_use_source_order_not_claimed_collection_order():
    data=parse('CULTURES:\n01/06/26\tBlood, Venous\tA\n01/06/26\tBlood, Arterial\tB\n01/06/26\tBlood, Central Line\tC')
    assert [g['specimen'] for g in compact_groups(data)]==['Blood, Venous','Blood, Arterial']


@pytest.mark.parametrize('body', ['CULTURES:', 'CULTURES:\n\n', 'CULTURES:\nNo results found for the last 90 days.'])
def test_empty_f_clears_only_previous_culture_snapshot(body):
    original=import_text(block('f',F))
    original['fields']['Infectious Disease']='Keep this note'
    changed=import_text(block('f',body),original)
    assert not changed['cultures']['rows']
    assert changed['fields']['Infectious Disease']=='Keep this note'
    assert original['cultures']['rows']


def test_f_omitted_preserves_cultures_and_partial_f_import_preserves_other_sections():
    original=import_text(SAMPLE.read_text())
    changed=import_text(block('e','VITALS:\nHeart Rate: 120'),original)
    assert changed['cultures']==original['cultures']
    changed=import_text(block('f',F),original)
    for key,value in original.items():
        if key!='cultures': assert changed[key]==value


@pytest.mark.parametrize('body',[
    'CULTURES:\n\t\tNo preceding specimen',
    'CULTURES:\n01/06/26 Blood Venous No growth',
    'CULTURES:\n01/06/26\t\tNo growth',
    'CULTURES:\n01/06/26\tBlood\t',
    'CULTURES:\n13/45/26\tBlood\tNo growth',
    'CULTURES:\nNo results found.\n01/06/26\tBlood\tNo growth',
    'CULTURES:\n01/06/26\tBlood\tNo growth\n\tOther site\tUnknown date',
    'CULTURES:\n01/06/26\tBlood\tNo growth\nCollected\tSpecimen Info\tOrganism\n\t\tOrphan'
])
def test_ambiguous_cultures_fail_without_partial_overwrite(body):
    original=import_text(block('a','Diagnoses:\n1. Existing'))
    before=deepcopy(original)
    out=import_sections(original,block('a','Diagnoses:\n1. Replacement')+block('f',body),new_vault()['settings'])
    assert_retained(out, before, "f")
    assert original==before


def test_aligned_columns_and_indented_rows_supported():
    data=parse('CULTURES:\n  01/06/26\tBlood, Venous\tNo growth\n01/05/26  Blood  No growth')
    assert len(data['rows'])==2


def test_id_vitals_stay_above_cultures_notes_and_medications():
    sheet=import_text(SAMPLE.read_text())
    sheet['fields']['Infectious Disease']='PLAN_SENTINEL'
    sheet['medications']=remap(sheet['medications'],upsert_rule([],'ceftriaxone','Infectious Disease'))
    text=fields_with_medications(sheet)['Infectious Disease']
    assert text.startswith('Temp:')
    assert text.index('Temp:')<text.index('Cultures')<text.index('Antibiotics')<text.index('cefTRIAXone')<text.index('PLAN_SENTINEL')
    assert '\n------\nCultures\n' in text


def test_cultures_survive_pdf_html_text_batch_and_encryption():
    sheet=import_text(block('f',F))
    expected=['Streptococcus pneumoniae','Staphylococcus aureus','Beta hemolytic Streptococcus, Group A','Blood, Arterial']
    for content in (handoff_html(sheet),handoff_text(sheet),handoffs_html([sheet])):
        for name in expected:assert name in content
        assert 'Ceftriaxone' not in content
    for pdf in (handoff_pdf(sheet),handoffs_pdf([sheet])):
        pages=PdfReader(BytesIO(pdf)).pages
        text=' '.join(p.extract_text() for p in pages)
        text=re.sub(r'\s+',' ',text)
        for name in expected:assert name in text
        assert 'Ceftriaxone' not in text
    vault=save_sheet_in(new_vault(),sheet)
    key=generate_key()
    ciphertext=seal_vault(vault,key)
    assert b'Staphylococcus aureus' not in ciphertext
    assert open_vault(ciphertext,key)==vault


def test_cultures_only_handoff_included_in_print_all():
    sheet=import_text(block('f',F))
    assert 'P4102' in available_handoffs(new_vault(),{'P4102':sheet})
    for row in sheet['cultures']['rows']:row['include']=False
    assert not available_handoffs(new_vault(),{'P4102':sheet})


def test_script_markup_is_escaped_in_export():
    sheet=import_text(block('f','CULTURES:\n01/06/26\tBlood\t<script>alert(1)</script>'))
    html=handoff_html(sheet)
    assert '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html
    assert handoff_pdf(sheet).startswith(b'%PDF')


def test_all_original_fields_preserved_from_schema_seven():
    sheet=import_text(SAMPLE.read_text())
    vault=save_sheet_in(new_vault(),sheet)
    vault['schema']=7;vault.pop("reset_generation", None);vault["settings"].pop("medication_groups", None);vault["settings"].pop("medication_gi_groups", None);vault['settings'].pop('medication_infusions', None)
    for row in vault['rooms'].values():
        row.pop("feeds", None);row.pop("devices", None);row.pop("neuro_devices", None);row.pop("pacemaker", None);row.pop("diet", None);row.pop("import_warnings", None);row.pop("intake_output", None);row.pop("recurring_orders", None);row.pop("cbc", None);row.pop('blood_gas', None);row.pop('cultures');row.pop('dosing_weight');row.pop('viral_panel', None);row.pop('admission_date')
    before=deepcopy(vault)
    changed=upgrade_vault(vault)
    assert changed['schema']==SCHEMA_VERSION==32 and vault==before
    assert changed['settings']==dict(before['settings'], medication_infusions=[], medication_gi_groups=[], medication_groups=[])
    for key,value in before['rooms']['P4102'].items():assert changed['rooms']['P4102'][key]==value
    assert changed['rooms']['P4102']['cultures']==empty_cultures()
    key=generate_key()
    old_token=Fernet(key.encode()).encrypt(json.dumps(before).encode())
    assert open_vault(old_token,key)==changed


def test_culture_schema_unknown_keys_fail_closed():
    data=parse(F)
    data['rows'][0]['sensitivity']='S'
    with pytest.raises(ValueError):validate_cultures(data)


def test_latest_selection_does_not_mutate_snapshot():
    data=parse(F);before=deepcopy(data)
    compact_groups(data);cultures_text(data)
    assert data==before


def test_cultures_editor_callback_and_invalid_date_restore(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=import_text(block('f',F))
    row=ss['drafts']['P4102']['cultures']['rows'][0]
    ss['cx_edit']='01/01/26'
    app.culture_row_change('P4102',row['id'],'date','cx_edit')
    assert ss['drafts']['P4102']['cultures']['rows'][0]['date']=='01/01/26'
    ss['cx_edit']='invalid'
    app.culture_row_change('P4102',row['id'],'date','cx_edit')
    assert ss['cx_edit']=='01/01/26' and ss['notice'][0]=='error'
    ss['cx_org']='First organism\nSecond organism'
    app.culture_row_change('P4102',row['id'],'organisms','cx_org')
    assert ss['drafts']['P4102']['cultures']['rows'][0]['organisms']==['First organism','Second organism']


def test_excluding_culture_keeps_row_for_restore(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=import_text(block('f',F))
    row=ss['drafts']['P4102']['cultures']['rows'][0]
    ss['cx_inc']=False
    app.culture_row_change('P4102',row['id'],'include','cx_inc')
    assert len(ss['drafts']['P4102']['cultures']['rows'])==5
    assert ss['drafts']['P4102']['cultures']['rows'][0]['include'] is False
    ss['cx_inc']=True;app.culture_row_change('P4102',row['id'],'include','cx_inc')
    assert ss['drafts']['P4102']['cultures']['rows'][0]['include'] is True


def test_cross_room_culture_edit_is_ignored(app):
    open_room(app);ss=app.st.session_state
    ss['drafts']['P4102']=import_text(block('f',F))
    row=ss['drafts']['P4102']['cultures']['rows'][0]
    open_room(app,'P4104');ss['cx_edit']='01/01/26'
    app.culture_row_change('P4102',row['id'],'date','cx_edit')
    assert row['date']=='01/06/26'


def test_complete_render_with_duplicate_ads_and_culture_rows(app,monkeypatch):
    from test_ui_smoke import equip
    open_room(app);app.load_cultures_sample();app.create_handoff()
    ss=app.st.session_state
    assert not ss['import_result']['errors']
    assert len(ss['drafts']['P4102']['medications'])==12
    downloads=equip(app,monkeypatch)
    app.handoff_page(None)
    assert any(isinstance(data,bytes) and data.startswith(b'%PDF') for _,data in downloads)


def test_update_clears_culture_widget_keys(app):
    open_room(app);ss=app.st.session_state
    ss['culture_old_field']='Old'
    app.load_cultures_sample();app.create_handoff()
    assert 'culture_old_field' not in ss


def test_current_session_migration_preserves_unsaved_notes(app):
    open_room(app);app.load_cultures_sample();app.create_handoff();app.save_room(None)
    ss=app.st.session_state
    ss['vault']['schema']=7;ss['vault'].pop("reset_generation", None);ss['vault']["settings"].pop("medication_groups", None);ss['vault']["settings"].pop("medication_gi_groups", None);ss['vault']['settings'].pop('medication_infusions', None)
    for sheet in (ss['vault']['rooms']['P4102'],ss['drafts']['P4102'],ss['base_sheets']['P4102']):
        sheet.pop('cultures');sheet.pop('dosing_weight');sheet.pop("feeds", None);sheet.pop("devices", None);sheet.pop("neuro_devices", None);sheet.pop("pacemaker", None);sheet.pop("diet", None);sheet.pop("import_warnings", None);sheet.pop("intake_output", None);sheet.pop("recurring_orders", None);sheet.pop("cbc", None);sheet.pop('blood_gas', None);sheet.pop('viral_panel', None);sheet.pop('admission_date')
    ss['drafts']['P4102']['fields']['Neurologic']='Unsaved note'
    app.upgrade_existing_session()
    assert ss['vault']['schema']==32
    assert ss['drafts']['P4102']['fields']['Neurologic']=='Unsaved note'
    assert ss['drafts']['P4102']['cultures']==empty_cultures()
