"""v6.37 regression suite. Synthetic records only, based on v6.35."""
from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import re

import pytest
from pypdf import PdfReader
from models import new_sheet, new_vault, validate_sheet, validate_vault, save_sheet_in, upgrade_vault, SCHEMA_VERSION
from importing import import_sections
from import_review import diagnostic, review_summary
from difficult_airway import (empty_airway, validate_airway, collect_airway, airway_summary,
                              FIELDS, TEXT_LIMITS, MASK_OPTIONS, PASSAGE_OPTIONS, TITLE)
from exports import handoff_text, handoff_html, handoff_pdf, handoffs_pdf, print_fit_report, COLUMNS, WIDTHS
from labs import parse_labs, labs_text, printable_source_notes, result_cards
from cultures import parse_cultures, culture_display, cultures_text
from microbiology_display import culture_markup
from lab_layout import card_plan, laboratory_html, laboratory_flowables
from lab_windows import display_clock, lactate_summary, theophylline_summary, laboratory_data
from security import seal_vault, open_vault, generate_key
from batching import available_handoffs
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_print_fit_reset import Store
from user_guide import default_guide, publication

NOW = datetime(2026, 11, 8, 20, tzinfo=timezone.utc)


def block(letter, text):
    return letter*20+'\n'+text+'\n'+letter*20


def populated(room='P4102'):
    s=new_sheet(room)
    s['fields']['Diagnoses']='Synthetic print-layout example'
    s['fields']['Goals / Follow-up']='Preserve this separate plan.'
    s['difficult_airway']=dict(empty_airway(), enabled=True, mask_ventilation='Yes, with difficulty',
        tube_passage='Yes', view='Grade 2b with video laryngoscope', equipment='Video laryngoscope and flexible scope',
        tube_details='Oral route, 4.0 mm tube', issue='Limited mouth opening',
        plan='Use the documented team airway plan. Contact airway team.', source='01/03/26 09:30')
    return s


def pdf_text(s):
    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(handoff_pdf(s))).pages)


def test_no_airway_section_for_unselected_patient():
    s=new_sheet('P4102')
    for output in (handoff_text(s), handoff_html(s), pdf_text(s)):
        assert TITLE not in output
    s['difficult_airway']=empty_airway()
    assert not airway_summary(s)


def test_entered_details_export_once_at_end_and_source_preserved():
    s=populated();before=deepcopy(s)
    for text in (handoff_text(s), handoff_html(s), pdf_text(s)):
        assert text.count(TITLE)==1
        assert 'Limited mouth opening' in text
        assert text.index(TITLE)>text.index('Preserve this separate plan.')
    assert s==before


def test_enable_without_answers_does_not_invent_normal_findings():
    s=new_sheet('P4102');s['difficult_airway']=dict(empty_airway(),enabled=True)
    assert airway_summary(s)=='Details not entered.'
    assert 'Yes' not in airway_summary(s)


@pytest.mark.parametrize('mask', MASK_OPTIONS)
@pytest.mark.parametrize('passage', PASSAGE_OPTIONS)
def test_all_bag_mask_and_passage_choices(mask,passage):
    s=new_sheet('P4102');s['difficult_airway']=dict(empty_airway(),enabled=True,
        mask_ventilation=mask,tube_passage=passage)
    validate_sheet(s)
    txt=airway_summary(s)
    if mask=='No': assert 'Bag-mask ventilation: No' in txt
    if mask.startswith('Unknown'): assert 'Bag-mask ventilation:' not in txt
    if passage=='Unable to pass': assert 'Tube passage: Unable to pass' in txt
    if passage=='No': assert 'Tube passage: Not difficult' in txt


@pytest.mark.parametrize('field',TEXT_LIMITS)
def test_text_fields_length_limits_and_no_silent_truncation(field):
    d=empty_airway();d[field]='X'*TEXT_LIMITS[field];validate_airway(d)
    d[field]+='X'
    with pytest.raises(ValueError):validate_airway(d)


@pytest.mark.parametrize('field',TEXT_LIMITS)
def test_markup_escaped_in_clinician_fields(field):
    s=populated();s['difficult_airway'][field]='<b>literal</b> & <script>'
    markup=airway_summary(s,True)
    assert '&lt;b&gt;literal&lt;/b&gt; &amp; &lt;script&gt;' in markup
    assert '<script>' not in markup
    assert '<b>literal</b>' in pdf_text(s)


@pytest.mark.parametrize('bad',[[],{},True,{'enabled':True},dict(empty_airway(),enabled='false'),
    dict(empty_airway(),mask_ventilation='Normal'),dict(empty_airway(),tube_passage='Maybe'),
    dict(empty_airway(),view='bad\x00text'),dict(empty_airway(),extra='discard me')])
def test_invalid_airway_records_rejected(bad):
    with pytest.raises(ValueError):validate_airway(bad)


def test_toggle_off_keeps_detail_but_omits_output():
    s=populated();s['difficult_airway']['enabled']=False
    assert s['difficult_airway']['issue']=='Limited mouth opening'
    assert not airway_summary(s)
    assert 'Limited mouth opening' not in pdf_text(s)


def test_encrypted_roundtrip_and_25_upgrade_preserve_every_prior_value():
    v=save_sheet_in(new_vault(),populated());key=generate_key()
    assert open_vault(seal_vault(v,key),key)==v
    old=new_vault();old['schema']=25
    s=new_sheet('P4104');s['fields']['Other']='Legacy note';s['updated_at']='2026-11-08T10:00:00+00:00'
    old['rooms']['P4104']=s;before=deepcopy(old)
    upgraded=upgrade_vault(old)
    assert old==before and upgraded['schema']==33
    assert upgraded['rooms']==old['rooms'] and upgraded['settings']==old['settings']


def test_airway_only_room_is_not_dropped_from_print_all():
    s=new_sheet('P4102');s['difficult_airway']=dict(empty_airway(),enabled=True)
    assert list(available_handoffs(new_vault(),{'P4102':s}))==['P4102']


def test_no_cross_room_information_in_pdf_packet():
    a=populated('P4102');a['difficult_airway']['issue']='AIRWAY_SENTINEL_A'
    b=new_sheet('P4104');b['fields']['Diagnoses']='Room B synthetic'
    doc=PdfReader(BytesIO(handoffs_pdf([a,b])))
    assert len(doc.pages)==2
    assert 'AIRWAY_SENTINEL_A' in doc.pages[0].extract_text()
    assert 'AIRWAY_SENTINEL_A' not in doc.pages[1].extract_text()
    assert TITLE not in doc.pages[1].extract_text()


def test_unrelated_import_preserves_manual_airway():
    s=populated()
    r=import_sections(s,block('a','Diagnoses:\n1. Synthetic new diagnosis'),new_vault()['settings'])
    assert not r.errors
    assert r.sheet['difficult_airway']==s['difficult_airway']


def test_pending_edit_captured_before_switch_and_reloaded(app):
    open_room(app);ss=app.st.session_state;s=populated();app.set_editor('P4102',s)
    key='dairway_'+s['id']+'_issue';ss[key]='PENDING_EDIT_SENTINEL'
    snap=app.editor_snapshot('P4102')
    assert snap['difficult_airway']['issue']=='PENDING_EDIT_SENTINEL'
    ss['room_choice']='P4104';app.open_room(None)
    assert ss['vault']['rooms']['P4102']['difficult_airway']['issue']=='PENDING_EDIT_SENTINEL'
    assert key not in ss
    assert 'difficult_airway' not in ss['drafts']['P4104']


def test_new_patient_does_not_inherit_airway(app):
    open_room(app);ss=app.st.session_state;app.set_editor('P4102',populated())
    app.start_new_patient()
    assert not airway_summary(ss['drafts']['P4102'])


def test_reset_clears_all_airway_records_and_custom_rooms(app):
    from test_print_fit_reset import populated as populate_app
    ss=populate_app(app);ss['drafts']['P4102']['difficult_airway']=populated()['difficult_airway']
    app.clear_all_handoffs(None)
    assert not ss['vault']['rooms'] and not ss['drafts']


def test_callback_room_and_sheet_guard(app):
    open_room(app);ss=app.st.session_state;s=ss['drafts']['P4102'];before=deepcopy(s)
    key='dairway_'+s['id']+'_enabled';ss[key]=True
    app.difficult_airway_change('P4104',s['id'])
    app.difficult_airway_change('P4102','0'*32)
    assert ss['drafts']['P4102']==before
    app.difficult_airway_change('P4102',s['id'])
    assert ss['drafts']['P4102']['difficult_airway']['enabled']


def test_airway_tab_immediately_after_problems_with_no_admin_gate(app,monkeypatch):
    open_room(app);ss=app.st.session_state;app.set_editor('P4102',populated())
    ss.pop('admin_unlocked',None);equip(app,monkeypatch)
    names=[];original=app.st.tabs
    app.st.tabs=lambda labels,**kwargs: (names.extend(labels) or original(labels,**kwargs))
    app.handoff_page(None)
    assert names[names.index('Problems')+1]=='Difficult airway'


def test_publication_caption_uses_saved_publication_not_room_time(app):
    g=publication('.TEAM','SOURCE','',default_guide()['instructions'])
    g['updated_at']='2026-11-08T18:45:23+00:00'
    text=app.smartphrase_publish_caption(g)
    assert '11/08/2026' in text and '01:45:23 PM EST' in text and 'published' in text
    assert 'session only' in app.smartphrase_publish_caption(g,session_only=True)
    assert 'refresh failed' in app.smartphrase_publish_caption(g,stale=True)
    assert 'not published' in app.smartphrase_publish_caption(default_guide())


def test_publication_timestamp_hidden_without_selected_room(app,monkeypatch):
    equip(app,monkeypatch);seen=[];app.st.caption=lambda text,*a,**k:seen.append(text)
    g=publication('.TEAM','SOURCE','',default_guide()['instructions']);g['updated_at']='2026-11-08T18:45:23+00:00'
    app.st.session_state['user_guide']=g
    app.handoff_page(None)
    assert not any('01:45:23 PM EST' in line or line.startswith(('SmartPhrase published:', 'SmartPhrase saved in this session only:', 'SmartPhrase:')) for line in seen)


@pytest.mark.parametrize('value',['No growth','No growth (In process)','No growth (Preliminary)',
    'No growth (Final)','No growth to date','No growth after 5 days','NO GROWTH'])
def test_negative_culture_display_only(value):
    assert culture_display(value)=='NGTD'


@pytest.mark.parametrize('value',['Staphylococcus aureus','No growth of bacteria, Candida isolated',
    'Culture pending','Negative','Normal flora'])
def test_not_other_culture_results(value):
    assert culture_display(value)==value


def test_ngtd_deduplicates_status_without_changing_stored_organisms():
    data=parse_cultures('CULTURES:\n01/03/26\tBlood, Venous\tNo growth (In process)\n01/03/26\tBlood, Venous\tNo growth (Preliminary)').data
    before=deepcopy(data)
    assert cultures_text(data).count('NGTD')==1
    assert culture_markup(data).count('NGTD')==1
    assert data==before


@pytest.mark.parametrize('message',[ 'No results found for: "INR", "PT", "PTT", "FIB"',
    'No results found for: "PHV", "PCO2V"','No results found for: "THEOPH"',
    'No results found for: "CK", "NTPROBNP"','No lab exists for component: "PHC"'])
def test_missing_laboratory_messages_not_on_sheet(message):
    s=new_sheet('P4102');s['labs']['notes']=[message]
    before=deepcopy(s)
    for text in (handoff_text(s),handoff_html(s),pdf_text(s)):
        assert message not in text and 'Source:' not in text
    assert s==before
    assert laboratory_html(s['labs'])==''


def test_nonmissing_lab_note_preserved():
    data={'rows':[],'notes':['Source result comment for verification.']}
    assert 'Source result comment' in laboratory_html(data)
    assert 'Source result comment' in labs_text(data)


def test_labeled_trees_keep_dates_values_without_large_titles_or_notes():
    data=parse_labs('LABS:\nComponent\tValue\tDate\nWBC\t8.0\t11/08/2026\nHGB\t10.2 (L)\t11/08/2026\nNA\t138\t11/08/2026').data
    text=laboratory_html(data)
    for forbidden in ('latest column','preceding','same-draw','CBC','BMP'):
        assert forbidden not in text
    for kept in ('WBC','Hgb','Hct','Plt','Na','11/08/26','10.2 (L)','138'):
        assert kept in text


def test_seven_columns_and_no_font_picker():
    assert len(COLUMNS)==7 and sum(WIDTHS)==pytest.approx(1)
    assert 'Labs' not in [section for _,section in COLUMNS]
    source=(Path(__file__).parents[1]/'app.py').read_text()
    assert 'Handoff font size (pt)' not in source and 'from print_options' not in source
    assert not (Path(__file__).parents[1]/'print_options.py').exists()


def test_lactate_theophylline_ck_date_overlap_keeps_date_and_original_value():
    s=new_sheet('P4102')
    s['labs']=parse_labs('LABS:\nComponent\tValue\tDate\nLACWB\t1.4\t11/07/2026\nTHEOPH\t8\t11/07/2026\nCK\t120\t11/07/2026').data
    before=deepcopy(s)
    with display_clock(NOW):
        for text in (handoff_text(s),handoff_html(s),pdf_text(s)):
            assert 'unverified' not in text and 'time not supplied' not in text
            assert '11/07/26' in text or '11/07/2026' in text
    assert s==before


def test_import_warnings_remain_in_app_data_not_exports():
    s=populated()
    for section,action in [('i','not_updated'),('g','not_updated'),('r','orders_hidden'),('t','feeds_hidden'),('x','diet_hidden')]:
        s['import_warnings'][section]=[diagnostic(section,'section_parse_failed',action=action)]
    assert review_summary(s)
    before=deepcopy(s)
    for text in (handoff_text(s),handoff_html(s),pdf_text(s)):
        assert 'IMPORT REVIEW' not in text
        assert 'Review needed.' not in text and 'Not updated.' not in text
    assert s==before


def test_synthetic_airway_sheet_fits_one_page_at_eight_points():
    report=print_fit_report(populated())
    assert report['page_count']==1 and report['font_size']==8


def test_handoff_summary_titles_hide_selection_qualifiers_but_keep_specimen():
    from lab_layout import horizontal_card_markup
    c={'kind':'branch','title':'Gas VEN | latest | legacy G, same-draw unverified',
       'rows':{'pH':{'component':'pH','value':'7.40','date':'11/08/2026'}}}
    text=horizontal_card_markup(c)
    assert 'Gas VEN' in text and '7.40' in text
    assert 'latest' not in text and 'unverified' not in text


def test_failed_shared_publication_does_not_advance_timestamp(app,monkeypatch):
    from github_store import StorageError
    from test_callbacks import TEST_ADMIN_CONFIG
    open_room(app);ss=app.st.session_state
    guide=publication('.ORIGINAL','Original source','',default_guide()['instructions'])
    guide['updated_at']='2026-11-08T18:45:23+00:00'
    ss.update(user_guide=guide,guide_loaded=True,guide_sha='old',guide_editor_sha='old',
              guide_edit_smartphrase_name='.CHANGED',guide_edit_smartphrase_text='Changed source',
              guide_edit_setup_notes='',guide_edit_instructions=default_guide()['instructions'])
    class BadStore:
        def save(self,*a):raise StorageError('Synthetic rejected publication')
    monkeypatch.setattr(app,'GuideStore',lambda store:BadStore())
    app.save_user_guide(object())
    assert ss['user_guide']==guide
    assert '01:45:23 PM EST' in app.smartphrase_publish_caption(ss['user_guide'])


def test_airway_pending_edit_and_save_conflict_retains_draft(app):
    from github_store import ConflictError
    open_room(app);ss=app.st.session_state;s=populated();app.set_editor('P4102',s)
    ss['dairway_'+s['id']+'_issue']='KEEP_AFTER_FAILURE'
    before=deepcopy(ss['vault']);store=Store(before,sha=None,failure=ConflictError('Synthetic conflict'))
    app.save_room(store)
    assert ss['vault']==before
    assert app.editor_snapshot('P4102')['difficult_airway']['issue']=='KEEP_AFTER_FAILURE'
    assert ss['drafts']['P4102']['updated_at'] is None


def test_labs_mapped_medication_survives_removed_column():
    s=new_sheet('P4102')
    r=import_sections(s,block('b','Medications:\nMedication\tDose\tRoute\tFrequency\tProvider\tLast Rate\tLast Admin\n'
        '•\tExample testing medicine\t1 mg\tOral\tDaily\tProvider\t\t'),new_vault()['settings'])
    assert not r.errors
    s=r.sheet;s['medications'][0]['section']='Labs'
    for text in (handoff_text(s),handoff_html(s),pdf_text(s)):
        assert text.count('Example testing medicine')==1
        assert 'other medications' in text.lower()
