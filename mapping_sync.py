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

from cryptography.fernet import Fernet, InvalidToken
from categories import catalog, default_categories
from github_store import GitHubConfig, GitHubVault, StorageError, ConflictError
from medications import normalized
from models import SCHEMA_VERSION, new_vault, validate_vault
from security import seal_vault

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


class SyncError(ValueError):
    """Messages deliberately exclude server bodies, keys and patient content."""


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


def decrypt_archive(token: bytes, key: str) -> dict:
    """Do NOT upgrade a patient archive as a side effect of a mapping sync."""
    try:
        if len(token) > 800_000:
            raise ValueError
        raw = json.loads(Fernet(key.encode("ascii")).decrypt(token).decode("utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA_VERSION:
            raise SyncError("The archive uses a different schema. Update that app and save its archive before syncing. No automatic patient-data migration is performed here.")
        validate_vault(raw)
        return raw
    except SyncError:
        raise
    except (InvalidToken, ValueError, KeyError, TypeError, UnicodeError):
        raise SyncError("An archive could not be decrypted or validated. Check the shared encryption key and app versions. Nothing was overwritten.") from None


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
    """Use only the existing fixed archive and a separate mapping-backup path."""
    def __init__(self, label: str, store: GitHubVault):
        self.label, self.store = label, store
        self.source = _digest([store.config.api_base.rstrip("/"), store.config.repository.casefold(), store.config.branch])

    def read(self) -> tuple[dict, str]:
        store = self.store
        store._check_repo()
        response = store._request("GET", store._contents_path(), params={"ref": store.config.branch})
        if response.status_code != 200:
            raise SyncError("The configured archive was not found or could not be read. Check the data repository, not the app-code repository. No empty archive was created.")
        data = store._json(response)
        if data.get("type") != "file" or data.get("encoding") != "base64" or not isinstance(data.get("sha"), str) or not data["sha"]:
            raise SyncError("The encrypted archive response is invalid or too large.")
        try:
            content = base64.b64decode("".join(data["content"].split()), validate=True)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SyncError("The archive encoding is invalid.") from None
        return decrypt_archive(content, store.key), data["sha"]

    def snapshot(self, keys=MAPPING_KEYS) -> Snapshot:
        vault, sha = self.read()
        return Snapshot(self.source, self.label, sha, mapping_bundle(vault["settings"], keys))

    def backup(self, vault: dict, sha: str, keys=MAPPING_KEYS) -> str:
        self.store._check_repo()
        token = create_backup(vault, sha, self.store.key, keys)
        path = "encrypted-data/mapping-sync-backups/" + uuid.uuid4().hex + ".enc"
        response = self.store._request("PUT", "/contents/" + path, json={
            "message": "Back up encrypted mapping settings", "branch": self.store.config.branch,
            "content": base64.b64encode(token).decode("ascii"),
        })
        if response.status_code != 201 or not self.store._json(response).get("content", {}).get("sha"):
            raise SyncError("The encrypted mapping backup was not confirmed. The archive was not changed by this step.")
        return path

    def save(self, vault: dict, sha: str) -> str:
        return self.store.save(vault, sha)


def configured_repositories(current: GitHubVault, secrets: dict) -> list[MappingRepository]:
    config = secrets.get("mapping_sync", {})
    if not isinstance(config, dict):
        raise SyncError("The mapping_sync Secrets section must be a table.")
    shared_token = config.get("token") or current.config.token
    if not isinstance(shared_token, str):
        raise SyncError("The mapping sync token must be text in deployment Secrets.")
    current_store = GitHubVault(replace(current.config, token=shared_token), current.key)
    repos = [MappingRepository("This app", current_store)]
    entries = config.get("repositories", [])
    if not isinstance(entries, list) or len(entries) > 10:
        raise SyncError("Configure a list of no more than ten mapping repositories.")
    seen = {repos[0].source}
    labels = {"this app"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"label", "repository", "branch", "token"}:
            raise SyncError("Use only label, repository, branch and optional token in each mapping repository entry.")
        label = entry.get("label", "")
        repo_name = entry.get("repository", "")
        branch = entry.get("branch", "main")
        token = entry.get("token") or shared_token
        if not all(isinstance(value, str) for value in (label, repo_name, branch, token)):
            raise SyncError("Mapping repository settings must be text.")
        if not label.strip() or len(label) > 80 or any(ord(c) < 32 for c in label):
            raise SyncError("Each repository needs a short, single-line label.")
        try:
            store = GitHubVault(replace(current.config, repository=repo_name.strip(), branch=branch, token=token), current.key)
        except StorageError:
            raise SyncError("A mapping repository setting is invalid. Use owner/repository and an existing branch.") from None
        remote = MappingRepository(label.strip(), store)
        if remote.source == repos[0].source:
            # Permits the same complete three-repository configuration in every app.
            continue
        if remote.source in seen or label.strip().casefold() in labels:
            raise SyncError("Repository entries and labels must be unique.")
        seen.add(remote.source)
        labels.add(label.strip().casefold())
        repos.append(remote)
    if len(repos) > 10:
        raise SyncError("Compare at most ten repositories at once.")
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
    result = SyncResult([{"App": r.label, "Status": "Not attempted", "Backup": "", "Detail": ""} for r in repos])
    changed = []
    phase, active = "preflight", 0
    try:
        # No remote writes during preflight, including backup writes.
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not authorize():
                raise SyncError("Admin authorization expired. Unlock Admin and compare again.")
            vault, sha = repo.read()
            bundle = mapping_bundle(vault["settings"], plan.keys)
            if bundle != snap.mappings:
                raise SyncError("Mappings changed after the comparison. Compare again before saving.")
            candidate = candidate_for(vault, merged, plan.keys)
            seal_vault(candidate, repo.store.key)  # Also enforce encrypted size before writes.
            changed.append(candidate != vault)
            result.rows[active]["Status"] = "Ready" if candidate != vault else "Already current"
        phase = "backup"
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not changed[active]:
                continue
            if not authorize():
                raise SyncError("Admin authorization expired. Unlock Admin and compare again.")
            vault, sha = repo.read()
            if mapping_bundle(vault["settings"], plan.keys) != snap.mappings:
                raise SyncError("Mappings changed before backup. Compare again.")
            result.rows[active]["Backup"] = repo.backup(vault, sha, plan.keys)
            result.rows[active]["Status"] = "Backed up, not updated"
        phase = "write"
        for active, (repo, snap) in enumerate(zip(repos, plan.snapshots)):
            if not authorize():
                raise SyncError("Admin authorization expired. Unlock Admin and compare again.")
            vault, sha = repo.read()
            if mapping_bundle(vault["settings"], plan.keys) != snap.mappings:
                raise SyncError("Mappings changed before this repository could be saved. Compare again.")
            if not changed[active]:
                continue
            candidate = candidate_for(vault, merged, plan.keys)
            # From this point a network failure may mean the write completed.
            result.rows[active]["Status"] = "Save not confirmed"
            new_sha = repo.save(candidate, sha)
            result.rows[active]["Status"] = "Saved, verification pending"
            verified, verified_sha = repo.read()
            if mapping_bundle(verified["settings"], plan.keys) != merged:
                raise SyncError("A save was acknowledged, but the current mappings differ. Reload and compare before retrying.")
            # A later patient-only save may legitimately produce another SHA.
            result.rows[active]["Status"] = "Updated and verified"
        result.complete = True
    except ConflictError:
        result.rows[active]["Status"] = "Not saved: concurrent change"
        result.rows[active]["Detail"] = "A write was refused because the archive changed or a repository rule blocked it. Compare again. No automatic overwrite or rollback."
    except (SyncError, StorageError, ValueError, KeyError, TypeError):
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
        }[phase]
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
