from copy import deepcopy
import pytest
from models import (DEFAULT_ROOMS, SYSTEMS, ValidationError, apply_diagnoses, new_sheet,
                    new_vault, normalize_room, save_sheet_in, validate_vault)
from security import generate_key, hash_password, open_vault, seal_vault, verify_password
from exports import handoff_html, handoff_text


def test_password_and_wrong_password():
    hashed = hash_password('synthetic test password only')
    assert 'synthetic' not in hashed
    assert verify_password('synthetic test password only', hashed)
    assert not verify_password('a wrong password', hashed)


@pytest.mark.parametrize('encoded', ['', 'nonsense', 'pbkdf2_sha256$1$aa$bb', None])
def test_malformed_password_hash(encoded):
    assert not verify_password('synthetic test password only', encoded)


def test_password_minimum():
    with pytest.raises(ValueError):
        hash_password('short')


def test_roundtrip_encrypted_vault():
    key = generate_key()
    vault = new_vault()
    sheet = apply_diagnoses(new_sheet('P4102'), 'PRIVATE_SENTINEL', 'Diagnoses')
    vault = save_sheet_in(vault, sheet)
    token = seal_vault(vault, key)
    assert b'P4102' not in token and b'PRIVATE_SENTINEL' not in token
    assert open_vault(token, key) == vault


def test_wrong_key_and_tamper_fail_closed():
    key = generate_key()
    encrypted = seal_vault(new_vault(), key)
    with pytest.raises(ValidationError):
        open_vault(encrypted, generate_key())
    with pytest.raises(ValidationError):
        open_vault(encrypted[:-5] + b'ABCDE', key)


def test_no_unapproved_vault_fields():
    vault = new_vault()
    vault['raw_paste'] = 'PRIVATE_SENTINEL'
    with pytest.raises(ValidationError):
        seal_vault(vault, generate_key())


def test_rooms_exact():
    assert DEFAULT_ROOMS == ['P4102','P4104','P4106','P4108','P4110','P4112','P4114','P4116',
                             'P4201','P4203','P4209','P4211','P4213','P4215','P4217','P4219','P4221','P4223']


@pytest.mark.parametrize('room,expected', [('4102','P4102'), ('p4104','P4104'), ('P4201','P4201'), ('p4213','P4213'), ('4307','4307')])
def test_room_aliases(room, expected):
    assert normalize_room(room) == expected


@pytest.mark.parametrize('room', ['', '<script>', 'x'*17, '../../repo'])
def test_invalid_room(room):
    with pytest.raises(ValidationError):
        normalize_room(room)


def test_diagnosis_apply_keeps_other_fields_and_original():
    sheet = new_sheet('P4102')
    sheet['fields']['Respiratory'] = 'Existing respiratory note'
    updated = apply_diagnoses(sheet, 'Example diagnosis', 'Diagnoses')
    assert updated['fields']['Respiratory'] == sheet['fields']['Respiratory']
    assert sheet['fields']['Diagnoses'] == ''


def test_append_and_replace():
    sheet = apply_diagnoses(new_sheet('P4102'), 'First', 'Diagnoses')
    assert apply_diagnoses(sheet,'Second','Diagnoses',True)['fields']['Diagnoses'] == 'First\nSecond'
    assert apply_diagnoses(sheet,'Second','Diagnoses')['fields']['Diagnoses'] == 'Second'


def test_new_patient_gets_blank_fields_and_new_reference():
    first, second = new_sheet('P4102'), new_sheet('P4102')
    assert first['id'] != second['id']
    assert all(value == '' for value in second['fields'].values())


def test_save_only_requested_room():
    vault = save_sheet_in(new_vault(), apply_diagnoses(new_sheet('P4102'),'First patient example','Diagnoses'))
    updated = save_sheet_in(vault, new_sheet('P4104'))
    assert updated['rooms']['P4102'] == vault['rooms']['P4102']
    assert 'P4104' not in vault['rooms']


def test_room_map_integrity():
    vault = new_vault()
    vault['rooms']['P4102'] = new_sheet('P4104')
    with pytest.raises(ValidationError):
        validate_vault(vault)


def test_export_escapes_html_and_preserves_text():
    sheet = apply_diagnoses(new_sheet('P4102'), '<script>unsafe()</script> & example', 'Diagnoses')
    result = handoff_html(sheet)
    assert '<script>unsafe' not in result
    assert '&lt;script&gt;' in result
    assert '&amp;' in result
    assert '<script>unsafe' in handoff_text(sheet)


def test_empty_sections_not_claimed_normal():
    html = handoff_html(new_sheet('P4102'))
    assert 'Blank sections are not confirmed normal' in html
    assert '<th>RESP</th>' in html
