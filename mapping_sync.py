"""Manual, allowlisted mapping synchronization for existing PICU archives.

The archive contains patients AND settings. It is decrypted transiently, never
copied between repositories. Previews retain mappings only. Every write starts
with that destination's current archive, modifies only the selected settings,
and uses its SHA. No migration, directory scan, patient merge or blind retry.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Callable
from urllib.parse import quote
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken
from categories import catalog, default_categories
from github_store import GitHubConfig, GitHubVault, StorageError, ConflictError
from medications import normalized
from models import SCHEMA_VERSION, new_vault, validate_vault
from security import seal_vault
from sync_diagnostics import SyncError, DiagnosticError, passed, failed, safe_error, http_error

MAPPING_KEYS = (
    "medication_categories", "medication_category_rules", "medication_mappings",
    "medication_infusions", "medication_gi_groups", "medication_groups",
)
VISIBILITY_KEY = "medication_visibility"
ALLOWED_KEYS = frozenset(MAPPING_KEYS + (VISIBILITY_KEY,))
LABELS = {
    "medication_categories": "Categories and subcategories",
    "medication_category_rules": "Category assignments",
    "medication_mappings": "System mappings",
    "medication_infusions": "Infusion display mappings",
    "medication_gi_groups": "FEN / GI groups",
    "medication_groups": "Medication groups",
    VISIBILITY_KEY: "Hidden-medication preferences",
}
BACKUP_FORMAT = "picu-mapping-sync-backup"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def scope_keys(include_visibility: bool = False) -> tuple[str, ...]:
    return MAPPING_KEYS + ((VISIBILITY_KEY,) if include_visibility else ())


def _check_scope(keys) -> tuple[str, ...]:
    result = tuple(keys)
    if result not in (MAPPING_KEYS, MAPPING_KEYS + (VISIBILITY_KEY,)):
        raise SyncError("The mapping scope is invalid. No archive was changed.")
    return result


def mapping_bundle(settings: dict, keys=MAPPING_KEYS) -> dict:
    """Extract only approved configuration lists, never an entire settings dict."""
    keys = _check_scope(keys)
    result = {key: deepcopy(settings.get(key, [])) for key in keys}
    result["medication_categories"] = catalog(settings)
    validate_bundle(result, keys)
    return result


def validate_bundle(bundle: dict, keys=MAPPING_KEYS) -> None:
    keys = _check_scope(keys)
    if not isinstance(bundle, dict) or set(bundle) != set(keys):
        raise SyncError("Only the approved mapping settings can be synchronized.")
    probe = new_vault()
    probe["settings"].update(deepcopy(bundle))
    try:
        validate_vault(probe)
    except (ValueError, KeyError, TypeError):
        raise SyncError("The combined mappings are invalid or exceed an app limit. Review category names, parent relationships and rule counts. Nothing was saved.") from None


@dataclass(frozen=True)
class Snapshot:
    source: str
    label: str
    sha: str
    mappings: dict = field(repr=False)


@dataclass
class Variant:
    value: dict
    sources: list[str]


@dataclass
class Entry:
    ident: str
    setting: str
    key: tuple
    variants: list[Variant]

    @property
    def conflict(self) -> bool:
        return len(self.variants) > 1


@dataclass
class MergePlan:
    snapshots: list[Snapshot] = field(repr=False)
    keys: tuple[str, ...]
    entries: list[Entry]
    aliases: dict[str, str]

    @property
    def conflicts(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.conflict]

    def resolve(self, choices: dict[str, int] | None = None) -> dict:
        choices = choices or {}
        result = {key: [] for key in self.keys}
        for entry in self.entries:
            index = choices.get(entry.ident, 0 if not entry.conflict else -1)
            if type(index) is not int or not 0 <= index < len(entry.variants):
                raise SyncError("Choose a destination for every conflicting mapping before saving.")
            result[entry.setting].append(deepcopy(entry.variants[index].value))
        for key in result:
            result[key].sort(key=lambda row: _json(rule_identity(key, row)))
        validate_bundle(result, self.keys)
        return result


def rule_identity(setting: str, row: dict) -> tuple:
    if setting == "medication_categories":
        return (row["id"],)
    if setting in ("medication_mappings", VISIBILITY_KEY):
        return (normalized(row["name"]), row["match"])
    return (normalized(row["name"]), normalized(row.get("route", "")),
            normalized(row.get("frequency", "")), row.get("match", "exact"))


def _category_aliases(snapshots: list[Snapshot]) -> dict[str, str]:
    """Unify independently created categories with the same display location.

    Equal IDs always share an identity. Equivalent names/locations may unify
    custom IDs, but two different built-in IDs are never collapsed. Definitions
    that disagree still become explicit conflicts after ID normalization.
    """
    builtins = {row["id"] for row in default_categories()}
    definitions = [row for snap in snapshots for row in snap.mappings["medication_categories"]]
    parent = {row["id"]: row["id"] for row in definitions}

    def root(ident):
        while parent[ident] != ident:
            parent[ident] = parent[parent[ident]]
            ident = parent[ident]
        return ident

    def join(a, b):
        a, b = root(a), root(b)
        if a == b:
            return
        if a in builtins and b in builtins:
            return
        chosen = a if a in builtins else b if b in builtins else min(a, b)
        parent[b if chosen == a else a] = chosen

    # First top-level, then children, so equal custom parents have equal IDs.
    for child in (False, True):
        locations = {}
        for row in definitions:
            if bool(row["parent"]) != child:
                continue
            location = (row["section"], root(row["parent"]) if child else "", normalized(row["name"]))
            if location in locations:
                join(row["id"], locations[location])
            else:
                locations[location] = row["id"]
    return {ident: root(ident) for ident in parent}


def make_plan(snapshots: list[Snapshot], keys=MAPPING_KEYS) -> MergePlan:
    keys = _check_scope(keys)
    if not 2 <= len(snapshots) <= 10 or len({snap.source for snap in snapshots}) != len(snapshots):
        raise SyncError("Configure two to ten distinct repositories to compare.")
    for snap in snapshots:
        validate_bundle(snap.mappings, keys)
    aliases = _category_aliases(snapshots)
    groups: dict[tuple, Entry] = {}
    for snap in snapshots:
        for setting in keys:
            for raw in snap.mappings[setting]:
                row = deepcopy(raw)
                if setting == "medication_categories":
                    row["id"] = aliases[row["id"]]
                    if row["parent"]:
                        row["parent"] = aliases[row["parent"]]
                else:
                    # These fields are already matched without case/spacing.
                    for key in ("name", "route", "frequency"):
                        if key in row:
                            row[key] = normalized(row[key])
                    if setting == "medication_category_rules":
                        row["target"] = aliases.get(row["target"], row["target"])
                identity = rule_identity(setting, row)
                key = (setting, identity)
                entry = groups.setdefault(key, Entry(_digest(key), setting, identity, []))
                existing = next((v for v in entry.variants if v.value == row), None)
                if existing is not None:
                    if snap.label not in existing.sources:
                        existing.sources.append(snap.label)
                else:
                    entry.variants.append(Variant(row, [snap.label]))
    entries = sorted(groups.values(), key=lambda e: (keys.index(e.setting), _json(e.key)))
    return MergePlan(deepcopy(snapshots), keys, entries, aliases)


def candidate_for(vault: dict, merged: dict, keys=MAPPING_KEYS) -> dict:
    """Keep every destination-specific value outside the allowlist unchanged."""
    keys = _check_scope(keys)
    validate_bundle(merged, keys)
    candidate = deepcopy(vault)
    for key in keys:
        candidate["settings"][key] = deepcopy(merged[key])
    try:
        validate_vault(candidate)
    except (ValueError, KeyError, TypeError):
        raise SyncError("The destination archive is not compatible. Update that app before synchronizing.") from None
    before, after = deepcopy(vault), deepcopy(candidate)
    for key in keys:
        before["settings"].pop(key, None)
        after["settings"].pop(key, None)
    if before != after:
        raise SyncError("A nonmapping field changed. The write was blocked.")
    return candidate


def _validate_mapping_families(settings: dict, checks=None) -> None:
    """Report the failing family without including its values or validator text."""
    from categories import validate_catalog, validate_category_rules
    from medications import validate_rules, validate_visibility
    from medication_groups import validate_group_rules
    from fen_gi import validate_gi_rules
    from infusions import validate_infusion_rules
    if not isinstance(settings, dict):
        failed(checks, DiagnosticError("MAPPING_SETTINGS_INVALID", "Mapping settings"))
    try:
        items = catalog(settings)
        validate_catalog(items)
    except Exception:
        failed(checks, DiagnosticError("MAPPING_SETTINGS_INVALID", "Categories and subcategories"))
    passed(checks, "Categories and subcategories", "Category definitions passed validation.")
    validators = (
        ("Category assignments", lambda value: validate_category_rules(value, items), "medication_category_rules"),
        ("System mappings", validate_rules, "medication_mappings"),
        ("Infusion display mappings", validate_infusion_rules, "medication_infusions"),
        ("FEN / GI groups", validate_gi_rules, "medication_gi_groups"),
        ("Medication groups", validate_group_rules, "medication_groups"),
        ("Hidden-medication preferences", validate_visibility, "medication_visibility"),
    )
    for label, validator, name in validators:
        try:
            validator(settings.get(name, []))
        except Exception:
            failed(checks, DiagnosticError("MAPPING_SETTINGS_INVALID", label))
        passed(checks, label, "This mapping family passed validation.")


def decrypt_archive(token: bytes, key: str, checks=None) -> dict:
    """Authenticate and validate in memory. Never upgrade or rewrite an archive."""
    if not isinstance(token, bytes) or len(token) > 800_000:
        failed(checks, DiagnosticError("ARCHIVE_TOO_LARGE", "Archive size"))
    passed(checks, "Archive size", "The encrypted file is within the safety limit.")
    try:
        cipher = Fernet(key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError, AttributeError):
        failed(checks, DiagnosticError("KEY_FORMAT_INVALID", "Encryption key format"))
    passed(checks, "Encryption key format", "This app's key has valid Fernet formatting. The key is never displayed.")
    try:
        plaintext = cipher.decrypt(token)
    except (InvalidToken, ValueError, TypeError):
        failed(checks, DiagnosticError("DECRYPTION_FAILED", "Decrypt archive"))
    passed(checks, "Decrypt archive", "The archive authenticated and decrypted with this app's existing key.")
    try:
        raw = json.loads(plaintext.decode("utf-8"))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        failed(checks, DiagnosticError("ARCHIVE_JSON_INVALID", "Archive JSON"))
    finally:
        del plaintext
    passed(checks, "Archive JSON", "The decrypted content is valid JSON. Its contents are not included in diagnostics.")
    actual = raw.get("schema") if isinstance(raw, dict) else None
    if type(actual) is not int or actual != SCHEMA_VERSION:
        observed = str(actual) if type(actual) is int and 0 <= actual <= 99999 else "missing or invalid"
        failed(checks, DiagnosticError("ARCHIVE_SCHEMA_MISMATCH", "Archive schema",
               detail="The archive uses a different schema. Saved schema: " + observed
                      + ". This app expects: " + str(SCHEMA_VERSION) + "."))
    passed(checks, "Archive schema", "Saved schema " + str(actual) + " is supported. This does not verify the deployed code version of the other app.")
    _validate_mapping_families(raw.get("settings"), checks)
    try:
        validate_vault(raw)
    except Exception:
        failed(checks, DiagnosticError("ARCHIVE_VALIDATION_FAILED", "Complete archive validation"))
    passed(checks, "Complete archive validation", "The saved structure passed validation without migration. No patient content is included in this report.")
    return raw


def create_backup(vault: dict, sha: str, key: str, keys=MAPPING_KEYS) -> bytes:
    keys = _check_scope(keys)
    payload = {
        "format": BACKUP_FORMAT, "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_archive_sha": sha, "scope": list(keys),
        # Preserve absence of optional fields as well as their exact values.
        "settings": {name: deepcopy(vault["settings"][name]) for name in keys if name in vault["settings"]},
    }
    encrypted = Fernet(key.encode("ascii")).encrypt(_json(payload).encode("utf-8"))
    if len(encrypted) > 800_000:
        raise SyncError("The mapping backup is too large. No archive was changed.")
    return encrypted


class MappingRepository:
    """Use only the fixed archive and mapping-backup path with safe diagnostics."""
    def __init__(self, label: str, store: GitHubVault, credential_source: str = "Existing GitHub token"):
        self.label, self.store = label, store
        self.credential_source = credential_source
        self.source = _digest([store.config.api_base.rstrip("/"), store.config.repository.casefold(), store.config.branch])

    def _request(self, method, endpoint, step, checks=None, expected=(200,), not_found="HTTP_ERROR", **kwargs):
        try:
            response = self.store._request(method, endpoint, **kwargs)
        except Exception as exc:
            failed(checks, safe_error(exc, step))
        if response.status_code not in expected:
            failed(checks, http_error(response.status_code, step, not_found))
        return response

    def _data(self, response, step, checks=None):
        try:
            return self.store._json(response)
        except Exception:
            failed(checks, DiagnosticError("RESPONSE_INVALID", step, response.status_code))

    def _check_repo(self, checks=None):
        response = self._request("GET", "", "Repository access", checks, not_found="REPOSITORY_NOT_FOUND")
        data = self._data(response, "Repository access", checks)
        passed(checks, "Repository access", "GitHub allowed access to the configured repository.", response.status_code)
        if data.get("private") is not True:
            failed(checks, DiagnosticError("REPOSITORY_NOT_PRIVATE", "Private repository check"))
        if data.get("archived") is True:
            failed(checks, DiagnosticError("REPOSITORY_ARCHIVED", "Private repository check"))
        passed(checks, "Private repository check", "GitHub reports an active private repository.")
        response = self._request("GET", "/branches/" + quote(self.store.config.branch, safe=""),
                                 "Branch access", checks, not_found="BRANCH_NOT_FOUND")
        self._data(response, "Branch access", checks)
        passed(checks, "Branch access", "The configured branch is reachable.", response.status_code)

    def read(self, checks=None) -> tuple[dict, str]:
        self._check_repo(checks)
        response = self._request("GET", self.store._contents_path(), "Archive file access", checks,
                                 not_found="ARCHIVE_NOT_FOUND", params={"ref": self.store.config.branch})
        data = self._data(response, "Archive file access", checks)
        if data.get("type") != "file" or data.get("encoding") != "base64" or not isinstance(data.get("sha"), str) or not data["sha"]:
            failed(checks, DiagnosticError("ARCHIVE_RESPONSE_INVALID", "Archive file access", response.status_code))
        passed(checks, "Archive file access", "The fixed encrypted archive file was read successfully.", response.status_code)
        try:
            content = base64.b64decode("".join(data["content"].split()), validate=True)
        except (ValueError, KeyError, TypeError, AttributeError):
            failed(checks, DiagnosticError("ARCHIVE_ENCODING_INVALID", "Archive encoding"))
        passed(checks, "Archive encoding", "The file's transport encoding is valid.")
        return decrypt_archive(content, self.store.key, checks), data["sha"]

    def snapshot(self, keys=MAPPING_KEYS, checks=None) -> Snapshot:
        vault, sha = self.read(checks)
        try:
            bundle = mapping_bundle(vault["settings"], keys)
        except Exception:
            failed(checks, DiagnosticError("MAPPING_SETTINGS_INVALID", "Extract mapping-only snapshot"))
        passed(checks, "Extract mapping-only snapshot", "Only approved mapping settings were retained for comparison. No patient records were retained in the snapshot.")
        return Snapshot(self.source, self.label, sha, bundle)

    def backup(self, vault: dict, sha: str, keys=MAPPING_KEYS) -> str:
        self._check_repo()
        token = create_backup(vault, sha, self.store.key, keys)
        path = "encrypted-data/mapping-sync-backups/" + uuid.uuid4().hex + ".enc"
        response = self._request("PUT", "/contents/" + path, "Write encrypted mapping backup", expected=(201,), json={
            "message": "Back up encrypted mapping settings", "branch": self.store.config.branch,
            "content": base64.b64encode(token).decode("ascii"),
        })
        data = self._data(response, "Confirm encrypted mapping backup")
        if not isinstance(data.get("content"), dict) or not data["content"].get("sha"):
            raise DiagnosticError("BACKUP_NOT_CONFIRMED", "Confirm encrypted mapping backup")
        return path

    def save(self, vault: dict, sha: str) -> str:
        self._check_repo()
        encrypted = seal_vault(vault, self.store.key)
        # Always use the destination's latest SHA. No retries or force writes.
        try:
            response = self._request("PUT", self.store._contents_path(), "Save merged mappings", expected=(200, 201), json={
                "message": "Update encrypted handoff archive", "branch": self.store.config.branch,
                "content": base64.b64encode(encrypted).decode("ascii"), "sha": sha,
            })
        except DiagnosticError as exc:
            if exc.code == "SAVE_CONFLICT":
                raise ConflictError("The write was refused.", status_code=exc.status_code, diagnostic_code="SAVE_CONFLICT") from None
            raise
        data = self._data(response, "Confirm mapping save")
        saved = data.get("content")
        if not isinstance(saved, dict) or not isinstance(saved.get("sha"), str) or not saved["sha"]:
            raise DiagnosticError("SAVE_NOT_CONFIRMED", "Confirm mapping save")
        return saved["sha"]


def _config_error(field: str, detail: str):
    raise DiagnosticError("CONFIG_INVALID", "Secrets: " + field, detail=detail) from None


def configured_repositories(current: GitHubVault, secrets: dict) -> list[MappingRepository]:
    config = secrets.get("mapping_sync", {})
    if not isinstance(config, Mapping):
        _config_error("mapping_sync", "Use a top-level [mapping_sync] table in Streamlit Secrets.")
    if set(config) - {"token", "repositories"}:
        _config_error("mapping_sync", "Use only optional token and [[mapping_sync.repositories]] entries. The section contains an unsupported field.")
    shared_token = config.get("token") or current.config.token
    if not isinstance(shared_token, str) or not shared_token.strip():
        _config_error("mapping_sync.token", "The shared token must be nonempty text. Omit it to reuse [github].token.")
    shared_source = "mapping_sync.token" if config.get("token") else "github.token (this app)"
    current_store = GitHubVault(replace(current.config, token=shared_token), current.key)
    repos = [MappingRepository("This app", current_store, shared_source)]
    entries = config.get("repositories", [])
    if not isinstance(entries, list) or len(entries) > 10:
        _config_error("mapping_sync.repositories", "Use [[mapping_sync.repositories]] for a list of no more than ten repository entries.")
    seen = {repos[0].source}
    labels = {"this app"}
    for index, entry in enumerate(entries, 1):
        field = "mapping_sync.repositories entry " + str(index)
        if not isinstance(entry, Mapping) or set(entry) - {"label", "repository", "branch", "token"}:
            _config_error(field, "Use only label, repository, branch and optional token in each entry.")
        label, repo_name, branch = entry.get("label", ""), entry.get("repository", ""), entry.get("branch", "main")
        token = entry.get("token") or shared_token
        for name, value in (("label", label), ("repository", repo_name), ("branch", branch), ("token", token)):
            if not isinstance(value, str):
                _config_error(field + "." + name, "This field must be text in TOML.")
        if not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
            _config_error(field + ".label", "Use a unique, single-line label of 1 to 80 characters.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_name.strip()):
            _config_error(field + ".repository", "Use owner/repository, not a full GitHub URL or a folder path. Select the private DATA repository.")
        if not branch or not re.fullmatch(r"[A-Za-z0-9_./-]+", branch) or ".." in branch:
            _config_error(field + ".branch", "Use the exact branch name without surrounding spaces, URLs or '..'.")
        if not token.strip():
            _config_error(field + ".token", "A nonempty token is required. Omit this field to use the shared token.")
        try:
            store = GitHubVault(replace(current.config, repository=repo_name.strip(), branch=branch, token=token), current.key)
        except StorageError:
            _config_error(field, "This repository configuration did not pass validation. Check its fields and the existing API setting.")
        source = field + ".token" if entry.get("token") else shared_source
        remote = MappingRepository(label.strip(), store, source)
        if remote.source == repos[0].source:
            continue
        if remote.source in seen:
            _config_error(field + ".repository", "This repository and branch are already included. Remove the duplicate entry.")
        if label.strip().casefold() in labels:
            _config_error(field + ".label", "This label is already used. Give each app a different label.")
        seen.add(remote.source)
        labels.add(label.strip().casefold())
        repos.append(remote)
    if len(repos) > 10:
        _config_error("mapping_sync.repositories", "Compare at most ten repositories including this app.")
    return repos


def configuration_fingerprint(repos: list[MappingRepository]) -> str:
    # A digest only. Never retain or display a copy of credentials in a preview.
    return _digest([(repo.source, repo.label, _digest(repo.store.config.token), _digest(repo.store.key)) for repo in repos])


@dataclass
class SyncResult:
    rows: list[dict]
    complete: bool = False


def synchronize(repos: list[MappingRepository], plan: MergePlan, merged: dict,
                authorize: Callable[[], bool]) -> SyncResult:
    """Preflight all destinations, back up all changed maps, then write serially.

    GitHub has no cross-repository transaction. On failure, stop and return exact
    per-repository outcomes. Never claim rollback or retry with an unreviewed SHA.
    """
    validate_bundle(merged, plan.keys)
    if [r.source for r in repos] != [s.source for s in plan.snapshots]:
        raise SyncError("Repository configuration changed. Compare again.")
    # Prevent a caller from injecting a value not present in the reviewed plan.
    expected_choices = {}
    for entry in plan.entries:
        selected = next((row for row in merged[entry.setting]
                         if rule_identity(entry.setting, row) == entry.key), None)
        match = next((i for i, option in enumerate(entry.variants) if option.value == selected), None)
        if match is None:
            raise SyncError("The proposed mappings were not part of the reviewed comparison.")
        expected_choices[entry.ident] = match
    if plan.resolve(expected_choices) != merged:
        raise SyncError("The proposed mappings were not part of the reviewed comparison.")
    result = SyncResult([{"App": r.label, "Status": "Not attempted", "Backup": "", "Detail": "", "Phase": "", "Step": "", "Code": "", "HTTP": "", "Next step": ""} for r in repos])
    changed = []
    phase, active = "preflight", 0
    operation = "Read current archive"
    try:
        # No remote writes during preflight, including backup writes.
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not authorize():
                raise DiagnosticError("ADMIN_EXPIRED", "Admin authorization")
            operation = "Read current archive"
            vault, sha = repo.read()
            bundle = mapping_bundle(vault["settings"], plan.keys)
            if bundle != snap.mappings:
                raise DiagnosticError("MAPPING_CHANGED", "Recheck mapping changes")
            candidate = candidate_for(vault, merged, plan.keys)
            seal_vault(candidate, repo.store.key)  # Also enforce encrypted size before writes.
            changed.append(candidate != vault)
            result.rows[active]["Status"] = "Ready" if candidate != vault else "Already current"
        phase = "backup"
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not changed[active]:
                continue
            if not authorize():
                raise DiagnosticError("ADMIN_EXPIRED", "Admin authorization")
            operation = "Read current archive"
            vault, sha = repo.read()
            if mapping_bundle(vault["settings"], plan.keys) != snap.mappings:
                raise DiagnosticError("MAPPING_CHANGED", "Recheck mapping changes")
            operation = "Create encrypted mapping backup"
            result.rows[active]["Backup"] = repo.backup(vault, sha, plan.keys)
            result.rows[active]["Status"] = "Backed up, not updated"
        phase = "write"
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not authorize():
                raise DiagnosticError("ADMIN_EXPIRED", "Admin authorization")
            operation = "Read current archive"
            vault, sha = repo.read()
            if mapping_bundle(vault["settings"], plan.keys) != snap.mappings:
                raise DiagnosticError("MAPPING_CHANGED", "Recheck mapping changes")
            if not changed[active]:
                continue
            candidate = candidate_for(vault, merged, plan.keys)
            # From this point a network failure may mean the write completed.
            result.rows[active]["Status"] = "Save not confirmed"
            operation = "Save merged mappings"
            new_sha = repo.save(candidate, sha)
            result.rows[active]["Status"] = "Saved, verification pending"
            operation = "Verify saved mappings"
            verified, verified_sha = repo.read()
            if mapping_bundle(verified["settings"], plan.keys) != merged:
                raise DiagnosticError("VERIFY_MISMATCH", "Verify saved mappings")
            # A later patient-only save may legitimately produce another SHA.
            result.rows[active]["Status"] = "Updated and verified"
        result.complete = True
    except ConflictError as exc:
        result.rows[active].update({"Phase": phase, "Step": operation, "Code": "SAVE_CONFLICT", "HTTP": str(getattr(exc, "status_code", "") or ""), "Next step": "Reload and compare. Check branch rules and write permissions."})
        result.rows[active]["Status"] = "Not saved: concurrent change"
        result.rows[active]["Detail"] = "A write was refused because the archive changed or a repository rule blocked it. Compare again. No automatic overwrite or rollback."
    except Exception as exc:
        diagnostic = safe_error(exc, operation)
        result.rows[active].update({"Phase": phase, "Step": diagnostic.step, "Code": diagnostic.code, "HTTP": str(diagnostic.status_code or ""), "Next step": diagnostic.action})
        # Do not echo exception bodies. A future transport/validator may include data.
        if phase == "preflight":
            result.rows[active]["Status"] = "Preflight failed"
        elif phase == "backup":
            result.rows[active]["Status"] = "Backup not confirmed"
        elif result.rows[active]["Status"] in ("Ready", "Already current", "Backed up, not updated", "Not attempted"):
            result.rows[active]["Status"] = "Not updated: recheck required"
        result.rows[active]["Detail"] = {
            "preflight": "Preflight stopped. Check access, encryption key, app versions and whether mappings changed. No mapping writes were started.",
            "backup": "Backup stage stopped. Some encrypted backups may exist, but no mapping writes were started. Compare again.",
            "write": "Synchronization stopped. The listed earlier updates may have completed. Reload and compare before retrying. No automatic rollback was attempted.",
        }[phase] + " " + diagnostic.detail
    return result


def overlapping_rules(bundle: dict, limit: int = 100) -> list[dict]:
    """Conservative review of mixed-layer or overlapping-prefix rules.

    These are not automatically deleted or resolved. Distinct exact/prefix and
    route/frequency filters may be intentional, and the app's normal precedence
    remains in effect. Review must be acknowledged separately in the Admin UI.
    """
    families = ("medication_category_rules", "medication_mappings", "medication_groups", "medication_gi_groups")
    buckets: dict[str, list[tuple[str, dict]]] = {}
    for setting in families:
        for row in bundle[setting]:
            name = normalized(row["name"])
            token = re.split(r"[^a-z0-9]", name, maxsplit=1)[0]
            buckets.setdefault(token, []).append((setting, row))
    warnings = []
    for rows in buckets.values():
        for index, (a_type, a) in enumerate(rows):
            for b_type, b in rows[index + 1:]:
                a_name, b_name = normalized(a["name"]), normalized(b["name"])
                def matches(prefix, rule, text):
                    return prefix == text or (rule.get("match", "exact") == "prefix"
                        and text.startswith(prefix) and len(text) > len(prefix)
                        and not text[len(prefix)].isalnum())
                if not (matches(a_name, a, b_name) or matches(b_name, b, a_name)):
                    continue
                if any(a.get(key) and b.get(key) and normalized(a[key]) != normalized(b[key])
                       for key in ("route", "frequency")):
                    continue
                if a_type == b_type and (a.get("target", a.get("destination", a.get("mode"))) ==
                                         b.get("target", b.get("destination", b.get("mode")))):
                    continue
                warnings.append({"Medication / prefix": a["name"], "Also matches": b["name"],
                                 "Rule types": LABELS[a_type] + " / " + LABELS[b_type]})
                if len(warnings) >= limit:
                    return warnings
    return warnings
