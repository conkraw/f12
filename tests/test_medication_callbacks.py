from copy import deepcopy
from pathlib import Path
from test_callbacks import app, open_room
from medications import upsert_rule
from github_store import StorageError

SAMPLE = Path(__file__).parents[1] / 'examples' / 'synthetic_smartphrase.txt'


def read(app):
    open_room(app)
    app.st.session_state['paste'] = SAMPLE.read_text()
    app.create_handoff()


def map_first(app, destination='Neurologic', store=None):
    ss=app.st.session_state
    row=ss['drafts']['P4102']['medications'][0]
    ss['map_test']=destination
    app.medication_row_change('P4102',row['id'],'section','map_test',store)


def test_one_click_import_all_three_sections(app):
    read(app)
    sheet=app.st.session_state['drafts']['P4102']
    assert sheet['fields']['Diagnoses'] and len(sheet['medications'])==9
    assert sheet['ventilation']['mode']=='Volume Targeted Pressure Control - PS'


def test_inline_mapping_immediately_saved_to_admin_without_saving_handoff(app):
    read(app)
    map_first(app)
    ss=app.st.session_state
    assert ss['vault']['settings']['medication_mappings']==[{'name':'acetaminophen','match':'prefix','destination':'Neurologic'}]
    assert ss['drafts']['P4102']['medications'][0]['section']=='Neurologic'
    assert ss['vault']['rooms']=={}


def test_inline_mapping_persists_with_expected_sha(app):
    read(app)
    ss=app.st.session_state
    ss['vault_sha']='before'
    class Store:
        saved=None
        def save(self, candidate, sha):
            assert sha=='before'
            self.saved=deepcopy(candidate)
            return 'after'
    store=Store()
    map_first(app,store=store)
    assert store.saved['settings']['medication_mappings'][0]['name']=='acetaminophen'
    assert store.saved['rooms']=={}
    assert ss['vault_sha']=='after'


def test_failed_inline_mapping_rolls_back_without_false_success(app):
    read(app)
    ss=app.st.session_state
    before=deepcopy(ss['drafts']['P4102'])
    class BrokenStore:
        def save(self, candidate, sha):
            raise StorageError('Synthetic save failure.')
    map_first(app,store=BrokenStore())
    assert ss['drafts']['P4102']==before
    assert ss['vault']['settings']['medication_mappings']==[]
    assert ss['map_test']=='Neurologic'  # Return to the original effective Fever Control destination.
    assert ss['notice'][0]=='error'


def test_future_import_different_dose_uses_saved_mapping(app):
    read(app)
    map_first(app)
    ss=app.st.session_state
    ss['paste']='bbbbbbbb\nMedications:\n• acetaminophen injection 250 mg\t250 mg\tIntravenous\tq6h\nbbbbbbbb'
    app.create_handoff()
    row=ss['drafts']['P4102']['medications'][0]
    assert row['section']=='Neurologic' and row['dose']=='250 mg'
    assert len(ss['vault']['settings']['medication_mappings'])==1


def test_other_medications_selection_is_remembered(app):
    read(app)
    map_first(app)
    map_first(app,'Other Medications')
    ss=app.st.session_state
    assert len(ss['vault']['settings']['medication_mappings'])==1
    assert ss['vault']['settings']['medication_mappings'][0]['destination']=='Other Medications'


def test_mapping_both_albuterol_orders_keeps_separate_doses_and_frequencies(app):
    read(app)
    ss=app.st.session_state
    row=ss['drafts']['P4102']['medications'][1]
    ss['map_test']='Respiratory'
    app.medication_row_change('P4102',row['id'],'section','map_test')
    albuterol=[r for r in ss['drafts']['P4102']['medications'] if r['name'].startswith('albuterol')]
    assert len(albuterol)==2 and all(r['section']=='Respiratory' for r in albuterol)
    assert {r['frequency'] for r in albuterol}=={'q4h','q2h PRN'}


def test_remap_open_drafts_but_does_not_rewrite_saved_rooms(app):
    read(app)
    app.save_room(None)
    ss=app.st.session_state
    before=deepcopy(ss['vault']['rooms']['P4102'])
    map_first(app)
    assert ss['vault']['rooms']['P4102']==before
    assert ss['drafts']['P4102']['medications'][0]['section']=='Neurologic'


def test_admin_can_edit_without_any_handoff_open(app):
    ss=app.st.session_state
    ss.update(mapping_name='acetaminophen',mapping_destination='Neurologic',mapping_match='prefix')
    app.save_admin_rule(None)
    assert ss['vault']['settings']['medication_mappings'][0]['destination']=='Neurologic'
    ss['admin_rule_index']=0
    app.select_admin_rule()
    ss['mapping_destination']='Other Medications'
    app.save_admin_rule(None)
    assert len(ss['vault']['settings']['medication_mappings'])==1
    assert ss['vault']['settings']['medication_mappings'][0]['destination']=='Other Medications'
    assert not ss['drafts']


def test_admin_can_remove_rule_without_handoff(app):
    ss=app.st.session_state
    ss['vault']['settings']['medication_mappings']=upsert_rule([],'acetaminophen','Neurologic')
    ss['admin_rule_index']=0
    app.remove_admin_rule(None)
    assert ss['vault']['settings']['medication_mappings']==[]


def test_bad_medication_block_cannot_partially_apply(app):
    read(app)
    ss=app.st.session_state
    before=deepcopy(ss['drafts']['P4102'])
    ss['paste']='aaaaaaaa\nDiagnoses:\n1. Changed diagnosis\naaaaaaaa\nbbbbbbbb\nMedications:\n• med\t1 mg\tIV\tq4h\n• no tabs here\nbbbbbbbb'
    app.create_handoff()
    assert ss['drafts']['P4102']['medications']==before['medications']
    assert ss['drafts']['P4102']['fields']['Diagnoses']=='Changed diagnosis'
    assert 'b' in ss['drafts']['P4102']['import_warnings']
    assert ss['import_result']['errors']


def test_medication_details_edit_does_not_save_mapping_or_vault(app):
    read(app)
    ss=app.st.session_state
    row=ss['drafts']['P4102']['medications'][0]
    ss['edit_test']='Changed route'
    app.medication_row_change('P4102',row['id'],'route','edit_test')
    assert row['route']=='Changed route'
    assert not ss['vault']['settings']['medication_mappings']


def test_reimport_replaces_without_duplication_or_confirmations(app):
    read(app)
    ss=app.st.session_state
    ss['drafts']['P4102']['fields']['Respiratory']='Keep note'
    ss['paste']=SAMPLE.read_text()
    app.create_handoff()
    assert len(ss['drafts']['P4102']['medications'])==9
    assert ss['drafts']['P4102']['fields']['Respiratory']=='Keep note'
