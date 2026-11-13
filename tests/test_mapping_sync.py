"""Synthetic-only mapping synchronization, storage and failure-path tests."""
from copy import deepcopy
from dataclasses import replace
import base64
import json
import types

import pytest
from cryptography.fernet import Fernet

from categories import default_categories
from github_store import GitHubConfig, GitHubVault, ConflictError, StorageError
from mapping_sync import (
    ALLOWED_KEYS, BACKUP_FORMAT, MAPPING_KEYS, MappingRepository, Snapshot, SyncError,
    candidate_for, configuration_fingerprint, configured_repositories, create_backup,
    decrypt_archive, make_plan, mapping_bundle, overlapping_rules, scope_keys, synchronize,
)
from models import new_vault, new_sheet, validate_vault
from security import generate_key, seal_vault


def rule(name, dest="Respiratory"):
    return dict(name=name, match="prefix", destination=dest)


def vault(label, mappings=None):
    result = new_vault()
    result["settings"]["medication_mappings"] = deepcopy(mappings or [])
    result["settings"]["medication_visibility"] = [dict(name="synthetic hidden " + label, match="exact", hidden=True)]
    result["settings"]["patient_list_started_at"] = "2026-11-13T09:00:00+00:00"
    result["reset_generation"] = (label[0].lower() if label[0].lower() in "abcdef" else "a") * 32
    sheet = new_sheet("P4102")
    sheet["fields"]["Diagnoses"] = "SYNTHETIC_PATIENT_PRIVATE_" + label
    result["rooms"]["P4102"] = sheet
    validate_vault(result)
    return result


class FakeRepo:
    def __init__(self, label, value, key=None):
        self.label = self.source = label
        self.value = deepcopy(value)
        self.sha = "sha1"
        self.store = types.SimpleNamespace(key=key or generate_key())
        self.backups = []
        self.writes = []
        self.read_count = 0
        self.before_read = None
        self.before_save = None
        self.fail_backup = False
        self.fail_save = False
        self.timeout_after_save = False

    def read(self):
        self.read_count += 1
        if self.before_read:
            self.before_read(self)
        return deepcopy(self.value), self.sha

    def snapshot(self, keys=MAPPING_KEYS):
        return Snapshot(self.source, self.label, self.sha, mapping_bundle(self.value["settings"], keys))

    def backup(self, value, sha, keys):
        if self.fail_backup:
            raise StorageError("SYNTHETIC_SECRET_MUST_NOT_LEAK")
        self.backups.append(create_backup(value, sha, self.store.key, keys))
        return "encrypted-data/mapping-sync-backups/synthetic.enc"

    def save(self, value, sha):
        if self.before_save:
            self.before_save(self)
        if self.fail_save:
            raise StorageError("SYNTHETIC_SECRET_MUST_NOT_LEAK")
        if sha != self.sha:
            raise ConflictError("SYNTHETIC_CONFLICT")
        self.value = deepcopy(value)
        self.writes.append(deepcopy(value))
        self.sha += "s"
        if self.timeout_after_save:
            raise StorageError("Timeout after write")
        return self.sha


def make_repos():
    return [FakeRepo("A", vault("A", [rule("albuterol")])),
            FakeRepo("B", vault("B", [rule("montelukast")])),
            FakeRepo("C", vault("C", [rule("doxorubicin", "Hematology")]))]


def plan_for(repos, keys=MAPPING_KEYS):
    return make_plan([r.snapshot(keys) for r in repos], keys)


def without_mappings(value, keys=MAPPING_KEYS):
    result = deepcopy(value)
    for key in keys:
        result["settings"].pop(key, None)
    return result


def test_union_is_mapping_only_and_does_not_mutate_sources():
    repos = make_repos()
    before = [deepcopy(r.value) for r in repos]
    plan = plan_for(repos)
    assert not plan.conflicts
    merged = plan.resolve()
    assert len(merged["medication_mappings"]) == 3
    assert set(merged) == set(MAPPING_KEYS)
    assert "SYNTHETIC_PATIENT_PRIVATE" not in repr(plan)
    assert all("SYNTHETIC_PATIENT_PRIVATE" not in json.dumps(s.mappings) for s in plan.snapshots)
    for prior, repo in zip(before, repos):
        candidate = candidate_for(repo.value, merged)
        assert without_mappings(candidate) == without_mappings(prior)
        assert repo.value == prior


def test_three_repositories_keep_separate_same_room_patients_and_hidden_preferences():
    repos = make_repos()
    before = [deepcopy(r.value) for r in repos]
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert result.complete
    assert all(row["Status"] == "Updated and verified" for row in result.rows)
    for repo, old in zip(repos, before):
        assert without_mappings(repo.value) == without_mappings(old)
        assert len(repo.writes) == 1 and len(repo.backups) == 1
        assert repo.value["rooms"]["P4102"]["fields"]["Diagnoses"].endswith(repo.label)


def test_conflicting_destination_requires_explicit_choice():
    repos = [FakeRepo("A", vault("A", [rule("diphenhydramine", "Neurologic")])),
             FakeRepo("B", vault("B", [rule("DIPHENHYDRAMINE", "Respiratory")]))]
    plan = plan_for(repos)
    assert len(plan.conflicts) == 1
    with pytest.raises(SyncError, match="every conflicting"):
        plan.resolve()
    merged = plan.resolve({plan.conflicts[0].ident: 1})
    assert merged["medication_mappings"] == [rule("diphenhydramine", "Respiratory")]


def test_same_mapping_different_case_deduplicates():
    repos = [FakeRepo("A", vault("A", [rule("Montelukast")])),
             FakeRepo("B", vault("B", [rule("montelukast")]))]
    plan = plan_for(repos)
    assert not plan.conflicts
    assert plan.resolve()["medication_mappings"] == [rule("montelukast")]


def test_backup_has_only_allowed_settings_and_keeps_optional_field_absence():
    original = vault("A", [rule("montelukast")])
    key = generate_key()
    encrypted = create_backup(original, "knownsha", key)
    assert b"montelukast" not in encrypted
    payload = json.loads(Fernet(key.encode()).decrypt(encrypted))
    assert payload["format"] == BACKUP_FORMAT
    assert set(payload["settings"]) <= ALLOWED_KEYS
    assert "medication_categories" not in payload["settings"]
    assert "SYNTHETIC_PATIENT_PRIVATE" not in json.dumps(payload)
    assert "rooms" not in payload and "rooms" not in payload["settings"]
    assert "patient_list_started_at" not in payload["settings"]
    assert "medication_visibility" not in payload["settings"]


def test_changed_patient_after_preview_is_preserved():
    repos = make_repos()
    plan = plan_for(repos)
    repos[1].value["rooms"]["P4102"]["fields"]["Diagnoses"] = "SYNTHETIC_NEWER_PATIENT_EDIT"
    repos[1].sha = "newpatientsha"
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert result.complete
    assert repos[1].value["rooms"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_NEWER_PATIENT_EDIT"


def test_changed_mappings_after_preview_stop_all_writes():
    repos = make_repos()
    plan = plan_for(repos)
    repos[2].value["settings"]["medication_mappings"].append(rule("sildenafil"))
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert not result.complete
    assert not any(r.writes or r.backups for r in repos)


def test_patient_change_between_backup_and_save_uses_latest_archive():
    repos = make_repos()
    plan = plan_for(repos)
    def update(repo):
        if repo.read_count == 3:
            repo.value["rooms"]["P4102"]["fields"]["Diagnoses"] = "SYNTHETIC_LATEST_PATIENT"
            repo.sha = "newer"
    repos[0].before_read = update
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert result.complete
    assert repos[0].value["rooms"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_LATEST_PATIENT"


def test_race_during_put_refuses_stale_archive_and_stops_later_repos():
    repos = make_repos()
    plan = plan_for(repos)
    def concurrent_change(repo):
        repo.value["rooms"]["P4102"]["fields"]["Diagnoses"] = "SYNTHETIC_CONCURRENT_PATIENT"
        repo.sha = "raced"
    repos[1].before_save = concurrent_change
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert not result.complete
    assert result.rows[0]["Status"] == "Updated and verified"
    assert result.rows[1]["Status"] == "Not saved: concurrent change"
    assert not repos[1].writes and not repos[2].writes
    assert repos[1].value["rooms"]["P4102"]["fields"]["Diagnoses"] == "SYNTHETIC_CONCURRENT_PATIENT"


def test_failure_in_backup_phase_starts_no_mapping_writes():
    repos = make_repos()
    repos[1].fail_backup = True
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert not result.complete
    assert not any(r.writes for r in repos)
    assert len(repos[0].backups) == 1
    assert "SYNTHETIC_SECRET" not in repr(result)


def test_network_failure_reports_partial_sync_without_rollback():
    repos = make_repos()
    repos[1].fail_save = True
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert not result.complete
    assert result.rows[0]["Status"] == "Updated and verified"
    assert result.rows[1]["Status"] == "Save not confirmed"
    assert not repos[2].writes
    assert "SYNTHETIC_SECRET" not in repr(result)


def test_timeout_after_write_is_not_misreported_as_unsaved():
    repos = make_repos()
    repos[0].timeout_after_save = True
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert not result.complete and repos[0].writes
    assert result.rows[0]["Status"] == "Save not confirmed"
    assert not repos[1].writes


def test_authorization_checked_before_any_reads_or_writes():
    repos = make_repos()
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: False)
    assert not result.complete
    assert not any(r.writes or r.backups or r.read_count for r in repos)


def test_visibility_is_opt_in_with_conflict_review():
    repos = make_repos()[:2]
    for i, repo in enumerate(repos):
        repo.value["settings"]["medication_visibility"] = [dict(name="synthetic med", match="exact", hidden=bool(i))]
    plan = plan_for(repos, scope_keys(True))
    assert len(plan.conflicts) == 1
    merged = plan.resolve({plan.conflicts[0].ident: 1})
    result = synchronize(repos, plan, merged, lambda: True)
    assert result.complete
    assert all(repo.value["settings"]["medication_visibility"][0]["hidden"] for repo in repos)


def custom_catalog(parent_id, child_id):
    return default_categories() + [
        dict(id=parent_id, name="Synthetic parent", section="Respiratory", parent="", order=110),
        dict(id=child_id, name="Synthetic child", section="Respiratory", parent=parent_id, order=120),
    ]


def test_custom_category_ids_are_reconciled_with_references():
    repos = make_repos()[:2]
    for repo, p, c in [(repos[0], "custom:p1", "custom:c1"), (repos[1], "custom:p2", "custom:c2")]:
        repo.value["settings"]["medication_categories"] = custom_catalog(p, c)
        repo.value["settings"]["medication_category_rules"] = [
            dict(name="synthetic med", match="prefix", route="", frequency="", target=c)]
    plan = plan_for(repos)
    assert not plan.conflicts
    merged = plan.resolve()
    customs = [r for r in merged["medication_categories"] if r["id"].startswith("custom:")]
    assert len(customs) == 2
    assert len(merged["medication_category_rules"]) == 1
    assert merged["medication_category_rules"][0]["target"] == "custom:c1"
    assert next(r for r in customs if r["id"] == "custom:c1")["parent"] == "custom:p1"


def test_same_category_id_different_definition_requires_review():
    repos = make_repos()[:2]
    for repo in repos:
        repo.value["settings"]["medication_categories"] = default_categories()
    repos[1].value["settings"]["medication_categories"][0]["name"] = "Changed built-in name"
    plan = plan_for(repos)
    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].setting == "medication_categories"
    with pytest.raises(SyncError):
        plan.resolve()


def test_injection_of_patient_or_nonmapping_settings_is_rejected():
    repos = make_repos()
    plan = plan_for(repos)
    merged = plan.resolve()
    for key in ("rooms", "diagnoses_destination", "patient_list_started_at"):
        bad = dict(merged, **{key: "not allowed"})
        with pytest.raises(SyncError):
            candidate_for(repos[0].value, bad)
    with pytest.raises(SyncError):
        mapping_bundle(repos[0].value["settings"], MAPPING_KEYS + ("rooms",))


def test_unreviewed_new_mapping_injection_is_rejected():
    repos = make_repos()
    plan = plan_for(repos)
    merged = plan.resolve()
    merged["medication_mappings"].append(rule("unreviewed"))
    with pytest.raises(SyncError, match="reviewed"):
        synchronize(repos, plan, merged, lambda: True)
    assert not any(r.writes for r in repos)


def test_old_schema_unknown_schema_wrong_key_and_malformed_archive_rejected():
    key = generate_key()
    value = vault("A")
    assert decrypt_archive(seal_vault(value, key), key) == value
    with pytest.raises(SyncError):
        decrypt_archive(seal_vault(value, key), generate_key())
    for schema in (33, 999):
        value["schema"] = schema
        token = Fernet(key.encode()).encrypt(json.dumps(value).encode())
        with pytest.raises(SyncError, match="different schema"):
            decrypt_archive(token, key)
    for data in (b"not encrypted", Fernet(key.encode()).encrypt(b'{}')):
        with pytest.raises(SyncError):
            decrypt_archive(data, key)


def test_idempotent_second_sync_has_no_new_writes_or_backups():
    repos = make_repos()
    plan = plan_for(repos)
    assert synchronize(repos, plan, plan.resolve(), lambda: True).complete
    counts = [(len(r.backups), len(r.writes)) for r in repos]
    plan = plan_for(repos)
    result = synchronize(repos, plan, plan.resolve(), lambda: True)
    assert result.complete
    assert all(r["Status"] == "Already current" for r in result.rows)
    assert counts == [(len(r.backups), len(r.writes)) for r in repos]


def test_configuration_uses_same_key_and_fixed_path_and_all_repo_list():
    key = generate_key()
    current = GitHubVault(GitHubConfig("local-token", "owner/one"), key)
    conf = {"mapping_sync": {"token": "shared-token", "repositories": [
        {"label": "One", "repository": "owner/one"},
        {"label": "Two", "repository": "owner/two"},
        {"label": "Three", "repository": "owner/three", "token": "third-token"},
    ]}}
    repos = configured_repositories(current, conf)
    assert len(repos) == 3
    assert [r.store.config.token for r in repos] == ["shared-token", "shared-token", "third-token"]
    assert all(r.store.key == key and r.store.config.path == "encrypted-data/handoff-v1.enc" for r in repos)
    assert configuration_fingerprint(repos) != configuration_fingerprint(configured_repositories(current, {}))
    conf["mapping_sync"]["repositories"][1]["api_base"] = "https://untrusted.example"
    with pytest.raises(SyncError):
        configured_repositories(current, conf)


def test_overlapping_prefix_and_mixed_layer_rules_are_flagged():
    settings = new_vault()["settings"]
    settings["medication_mappings"] = [rule("synthetic med", "Neurologic")]
    settings["medication_category_rules"] = [dict(name="synthetic med 10 mg", match="exact", route="", frequency="", target="group:beta_agonist")]
    warnings = overlapping_rules(mapping_bundle(settings))
    assert len(warnings) == 1


class Response:
    def __init__(self, code, data):
        self.status_code, self.data = code, data
    def json(self):
        return deepcopy(self.data)


class FakeHTTP:
    def __init__(self, archive, key, private=True):
        self.archive, self.key, self.private = archive, key, private
        self.calls = []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if "/branches/" in url:
            return Response(200, {})
        if "/contents/" not in url:
            return Response(200, {"private": self.private})
        if method == "GET":
            return Response(200, {"type": "file", "encoding": "base64", "sha": "readsha",
                                  "content": base64.b64encode(seal_vault(self.archive, self.key)).decode()})
        return Response(201, {"content": {"sha": "writtensha"}})


def test_github_reads_fixed_archive_and_writes_only_encrypted_mapping_backup():
    key = generate_key()
    value = vault("A", [rule("montelukast")])
    http = FakeHTTP(value, key)
    store = GitHubVault(GitHubConfig("test-token", "owner/data"), key, session=http)
    repo = MappingRepository("Test", store)
    snap = repo.snapshot()
    assert snap.sha == "readsha"
    path = repo.backup(value, "readsha")
    assert path.startswith("encrypted-data/mapping-sync-backups/")
    put = next(c for c in http.calls if c[0] == "PUT")
    payload = json.loads(Fernet(key.encode()).decrypt(base64.b64decode(put[2]["json"]["content"])))
    assert set(payload["settings"]) <= ALLOWED_KEYS
    assert "SYNTHETIC_PATIENT_PRIVATE" not in json.dumps(payload)
    assert all(c[2]["allow_redirects"] is False for c in http.calls)
    assert all("/contents/encrypted-data/handoff-v1.enc" in c[1] for c in http.calls if c[0] == "GET" and "/contents/" in c[1])


def test_public_repository_is_refused_before_archive_read():
    key = generate_key()
    http = FakeHTTP(vault("A"), key, private=False)
    store = GitHubVault(GitHubConfig("test", "owner/data"), key, session=http)
    with pytest.raises(StorageError):
        MappingRepository("Test", store).snapshot()
    assert not any("/contents/" in c[1] for c in http.calls)
