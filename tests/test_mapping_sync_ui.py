"""Admin callback and render tests using a widget stub, not a live browser."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import time
import types

import pytest

from mapping_sync import configuration_fingerprint, make_plan, overlapping_rules
from test_mapping_sync import FakeRepo, make_repos, plan_for, rule


@pytest.fixture
def ui(monkeypatch):
    stub = types.ModuleType("streamlit")
    stub.session_state = {}
    stub.secrets = types.SimpleNamespace(to_dict=lambda: {})
    monkeypatch.setitem(sys.modules, "streamlit", stub)
    path = Path(__file__).parents[1] / "mapping_sync_ui.py"
    spec = importlib.util.spec_from_file_location("mapping_sync_ui_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preview(ui, repos):
    plan = plan_for(repos)
    ui.st.session_state.update(mapping_sync_preview={"plan": plan, "created": time.monotonic(),
        "nonce": "nonce", "configuration": "synthetic_config"}, mapping_sync_confirm=True)
    return plan


def stub_config(ui, monkeypatch, repos):
    monkeypatch.setattr(ui, "_repositories", lambda store: repos)
    monkeypatch.setattr(ui, "configuration_fingerprint", lambda sources: "synthetic_config")


def test_compare_and_save_callbacks_deny_locked_admin(ui):
    events = []
    ui.prepare_comparison(None, lambda: False, lambda *args: events.append(args))
    ui.approve_sync(None, lambda: False, lambda store: True, lambda *args: events.append(args))
    assert ui.st.session_state == {} and events == []


def test_compare_retains_mapping_only_snapshot(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    events = []
    ui.prepare_comparison(None, lambda: True, lambda *args: events.append(args))
    assert ui.st.session_state["mapping_sync_preview"]["plan"].snapshots
    assert "SYNTHETIC_PATIENT_PRIVATE" not in repr(ui.st.session_state)
    assert not any(repo.writes or repo.backups for repo in repos)
    assert not events


def test_approve_updates_and_invalidates_preview_without_touching_drafts(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    preview(ui, repos)
    draft = {"fields": {"Diagnoses": "UNSAVED_SYNTHETIC_DRAFT"}}
    ui.st.session_state["drafts"] = {"P4102": deepcopy(draft)}
    stale_keys = ("category_rule_name", "infusion_rule_mode_0", "gi_rule_mode_0",
                  "group_rule_mode_0", "antiepileptic_extra_names")
    for key in stale_keys:
        ui.st.session_state[key] = "outdated widget"
    calls, events = [], []
    ui.approve_sync(None, lambda: True, lambda store: calls.append("reloaded") or True, lambda *args: events.append(args))
    assert ui.st.session_state["mapping_sync_result"]["complete"]
    assert "mapping_sync_preview" not in ui.st.session_state
    assert all(key not in ui.st.session_state for key in stale_keys)
    assert ui.st.session_state["drafts"]["P4102"] == draft
    assert calls == ["reloaded"]


@pytest.mark.parametrize("reason", ["expired", "unconfirmed", "configuration", "scope", "conflict"])
def test_approval_stale_or_unreviewed_data_is_blocked(ui, monkeypatch, reason):
    repos = make_repos()
    if reason == "conflict":
        repos[1].value["settings"]["medication_mappings"] = [rule("albuterol", "Neurologic")]
    stub_config(ui, monkeypatch, repos)
    preview(ui, repos)
    ss = ui.st.session_state
    if reason == "expired":
        ss["mapping_sync_preview"]["created"] -= 901
    elif reason == "unconfirmed":
        ss["mapping_sync_confirm"] = False
    elif reason == "configuration":
        ss["mapping_sync_preview"]["configuration"] = "old"
    elif reason == "scope":
        ss["mapping_sync_include_visibility"] = True
    events = []
    ui.approve_sync(None, lambda: True, lambda store: True, lambda *args: events.append(args))
    assert not any(repo.writes or repo.backups for repo in repos)
    assert events[-1][-1] == "error"


def test_mixed_rule_overlap_requires_acknowledgement(ui, monkeypatch):
    repos = make_repos()
    repos[0].value["settings"]["medication_category_rules"] = [
        dict(name="albuterol", match="prefix", route="", frequency="", target="group:beta_agonist")]
    stub_config(ui, monkeypatch, repos)
    plan = preview(ui, repos)
    assert overlapping_rules(plan.resolve())
    events = []
    ui.approve_sync(None, lambda: True, lambda store: True, lambda *args: events.append(args))
    assert "overlapping" in events[-1][0]
    assert not any(repo.writes for repo in repos)


def test_failed_save_is_reported_and_preview_cannot_be_reused(ui, monkeypatch):
    repos = make_repos()
    repos[1].fail_save = True
    stub_config(ui, monkeypatch, repos)
    preview(ui, repos)
    events = []
    ui.approve_sync(None, lambda: True, lambda store: True, lambda *args: events.append(args))
    assert not ui.st.session_state["mapping_sync_result"]["complete"]
    assert "mapping_sync_preview" not in ui.st.session_state
    assert events[-1][-1] == "warning"


class Context:
    def __enter__(self): return self
    def __exit__(self, *args): return False


def equip(ui):
    st = ui.st
    st.rendered = []
    for name in ("caption", "info", "error", "warning", "write", "subheader", "dataframe", "code"):
        setattr(st, name, lambda *args, _name=name, **kwargs: st.rendered.append((_name, args)))
    st.expander = lambda *args, **kwargs: Context()
    st.container = lambda *args, **kwargs: Context()
    st.button = lambda *args, **kwargs: False
    st.download_button = lambda *args, **kwargs: False
    def checkbox(label, value=False, key=None, **kwargs):
        st.session_state.setdefault(key, value)
        return st.session_state[key]
    def radio(label, options, key=None, **kwargs):
        st.session_state.setdefault(key, options[0])
        return st.session_state[key]
    st.checkbox, st.radio = checkbox, radio


def test_admin_render_complete_plan_and_conflict_plan(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    # The actual renderer displays config metadata but not secret values.
    for repo in repos:
        repo.store.config = types.SimpleNamespace(repository="synthetic/" + repo.label, branch="main")
    equip(ui)
    preview(ui, repos)
    ui.mapping_sync_admin(object(), lambda: True, lambda store: True, lambda *args: None)
    assert any(name == "dataframe" for name, args in ui.st.rendered)
    repos[1].value["settings"]["medication_mappings"] = [rule("albuterol", "Neurologic")]
    plan = preview(ui, repos)
    ui.mapping_sync_admin(object(), lambda: True, lambda store: True, lambda *args: None)
    assert any("conflicting mapping" in str(args) for name, args in ui.st.rendered)
    entry = plan.conflicts[0]
    ui.st.session_state["mapping_sync_nonce_" + entry.ident] = 1
    ui.mapping_sync_admin(object(), lambda: True, lambda store: True, lambda *args: None)


def test_changed_conflict_choice_clears_old_approval(ui):
    ui.st.session_state.update(mapping_sync_confirm=True, mapping_sync_overlap_reviewed=True)
    ui.reset_approval()
    assert not ui.st.session_state.get("mapping_sync_confirm")
    assert not ui.st.session_state.get("mapping_sync_overlap_reviewed")


def test_diagnostics_continue_after_failure_and_report_safe_details(ui, monkeypatch):
    from sync_diagnostics import DiagnosticError
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    attempts = []
    original = repos[2].snapshot
    def broken(keys, checks=None):
        attempts.append('second')
        raise DiagnosticError('DECRYPTION_FAILED', 'Decrypt archive')
    def third(keys, checks=None):
        attempts.append('third')
        return original(keys, checks=checks)
    repos[1].snapshot = broken
    repos[2].snapshot = third
    events = []
    ui.prepare_comparison(None, lambda: True, lambda *args: events.append(args))
    report = ui.st.session_state['mapping_sync_diagnostics']
    assert len(report['repositories']) == 3
    assert attempts == ['second', 'third']
    assert 'mapping_sync_preview' not in ui.st.session_state
    assert report['repositories'][1]['checks'][-1]['Code'] == 'DECRYPTION_FAILED'
    assert report['repositories'][2]['checks'][-1]['Result'] == 'Passed'
    assert not report['complete']
    text = ui.diagnostic_text(report)
    assert 'SYNTHETIC_PATIENT_PRIVATE' not in text
    assert not any(repo.writes or repo.backups for repo in repos)
    assert events[-1][1] == 'error'
    equip(ui)
    ui.render_diagnostics(report)
    assert any('Decrypt archive' in str(args) for name, args in ui.st.rendered)


def test_read_only_diagnostics_do_not_create_merge_preview(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    events = []
    ui.prepare_comparison(None, lambda: True, lambda *args: events.append(args), True)
    assert ui.st.session_state['mapping_sync_diagnostics']['complete']
    assert 'mapping_sync_preview' not in ui.st.session_state
    assert not any(repo.writes or repo.backups for repo in repos)
    assert 'Write permission has not been tested' in events[-1][0]


def test_unknown_error_is_safe_and_no_stale_preview_can_be_saved(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    preview(ui, repos)
    def broken(keys, checks=None):
        raise KeyError('SYNTHETIC_TOKEN_AND_PATIENT_MUST_NOT_LEAK')
    repos[0].snapshot = broken
    ui.prepare_comparison(None, lambda: True, lambda *args: None)
    assert 'mapping_sync_preview' not in ui.st.session_state
    report = ui.st.session_state['mapping_sync_diagnostics']
    assert 'SYNTHETIC_TOKEN_AND_PATIENT' not in ui.diagnostic_text(report)
    assert report['repositories'][0]['checks'][-1]['Code'] == 'UNEXPECTED_ERROR'


def test_configuration_failure_is_visible_with_safe_field_detail(ui, monkeypatch):
    from sync_diagnostics import DiagnosticError
    def broken(store):
        raise DiagnosticError('CONFIG_INVALID', 'Secrets: mapping_sync.repositories entry 2.repository',
                              detail='Use owner/repository, not a URL.')
    monkeypatch.setattr(ui, '_repositories', broken)
    ui.prepare_comparison(None, lambda: True, lambda *args: None)
    report = ui.st.session_state['mapping_sync_diagnostics']
    assert 'entry 2.repository' in ui.diagnostic_text(report)
    equip(ui)
    ui.mapping_sync_admin(object(), lambda: True, lambda store: True, lambda *args: None)
    assert any('entry 2.repository' in str(args) for name, args in ui.st.rendered)


def test_admin_expiry_stops_remaining_network_checks(ui, monkeypatch):
    repos = make_repos()
    stub_config(ui, monkeypatch, repos)
    checks = iter([True, True, False])
    ui.prepare_comparison(None, lambda: next(checks, False), lambda *args: None)
    report = ui.st.session_state['mapping_sync_diagnostics']
    assert report['repositories'][0]['checks'][-1]['Result'] == 'Passed'
    assert all(r['checks'][-1]['Code'] == 'ADMIN_EXPIRED' for r in report['repositories'][1:])
    assert not report['complete']
    assert 'mapping_sync_preview' not in ui.st.session_state
