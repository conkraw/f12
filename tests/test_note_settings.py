"""Optional phrase settings stay patient-free and use the encrypted vault."""
from copy import deepcopy

import pytest

from handoff_reset import cleared_vault
from models import new_vault, validate_vault, ValidationError
from note_settings import normalize_note_settings, normalize_phrase_name


@pytest.mark.parametrize("name", ["ACKZEXAMPLE", "@ACKZEXAMPLE@", ".ACKZEXAMPLE", " ackzexample "])
def test_copied_reference_is_stored_as_a_name(name):
    assert normalize_phrase_name(name) == "ACKZEXAMPLE"


@pytest.mark.parametrize("name", ["NAME\nPLAN", "NAME@OTHER", "NAME:123", "<script>", "A" * 121, 123])
def test_phrase_settings_reject_template_content_and_invalid_values(name):
    with pytest.raises(ValueError):
        normalize_phrase_name(name)


def test_defaults_do_not_modify_original_settings():
    original = {"phrase_overrides": {"acute_hypoxemic_invasive": "@ACKZEXAMPLE@"}}
    before = deepcopy(original)
    clean = normalize_note_settings(original)
    assert original == before
    assert clean == {"phrase_style": "at", "phrase_overrides": {"acute_hypoxemic_invasive": "ACKZEXAMPLE"}}


def test_legacy_vault_without_note_settings_remains_valid():
    vault = new_vault()
    validate_vault(vault)
    assert "note_utility" not in vault["settings"]


def test_saved_phrase_settings_survive_patient_list_reset():
    vault = new_vault()
    settings = normalize_note_settings({"phrase_style": "dot", "phrase_overrides": {"acute_hypoxemic_invasive": "ACKZEXAMPLE"}})
    vault["settings"]["note_utility"] = settings
    validate_vault(vault)
    assert cleared_vault(vault)["settings"]["note_utility"] == settings


@pytest.mark.parametrize("value", [None, {}, {"phrase_style": "invalid", "phrase_overrides": {}},
                                  {"phrase_style": "at", "phrase_overrides": {}, "patient": "unwanted"}])
def test_saved_note_settings_require_a_normalized_known_structure(value):
    vault = new_vault()
    vault["settings"]["note_utility"] = value
    with pytest.raises(ValidationError):
        validate_vault(vault)
