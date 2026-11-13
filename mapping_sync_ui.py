"""Admin-only UI for manual synchronization. No patient data in previews."""
from __future__ import annotations
import time
import uuid
from typing import Callable
import streamlit as st
from categories import target_label
from github_store import StorageError
from mapping_sync import (LABELS, MAPPING_KEYS, MergePlan, SyncError,
                          configuration_fingerprint, configured_repositories,
                          make_plan, overlapping_rules, scope_keys, synchronize)

PREFIX = "mapping_sync_"
PREVIEW_TTL = 15 * 60
SETUP = '''# Append to existing deployment Secrets. Keep [app] and [github] unchanged.
# This app's existing data repository is included automatically.
# Use DATA repositories, not repositories that only contain app.py.
[mapping_sync]
# Optional token with access to all three private data repositories.
# Omit to reuse the existing [github].token.
# token = "YOUR_SYNC_TOKEN"

[[mapping_sync.repositories]]
label = "App 2"
repository = "YOUR_ACCOUNT/SECOND_PRIVATE_DATA_REPOSITORY"
branch = "main"
# token = "OPTIONAL_TOKEN_FOR_THIS_REPOSITORY"

[[mapping_sync.repositories]]
label = "App 3"
repository = "YOUR_ACCOUNT/THIRD_PRIVATE_DATA_REPOSITORY"
branch = "main"
# token = "OPTIONAL_TOKEN_FOR_THIS_REPOSITORY"
'''


def clear_preview(state) -> None:
    for key in list(state):
        if key.startswith(PREFIX) and key not in (PREFIX + "include_visibility", PREFIX + "result"):
            state.pop(key, None)


def reset_approval() -> None:
    """A changed conflict choice needs a fresh acknowledgement."""
    st.session_state.pop(PREFIX + "confirm", None)
    st.session_state.pop(PREFIX + "overlap_reviewed", None)


def _repositories(store):
    return configured_repositories(store, st.secrets.to_dict())


def prepare_comparison(store, require_admin: Callable[[], bool], note: Callable) -> None:
    if not require_admin():
        return
    ss = st.session_state
    clear_preview(ss)
    ss.pop(PREFIX + "result", None)
    try:
        repos = _repositories(store)
        keys = scope_keys(bool(ss.get(PREFIX + "include_visibility", False)))
        snapshots = []
        for repo in repos:
            if not require_admin():
                raise SyncError("Admin authorization expired.")
            snapshots.append(repo.snapshot(keys))
        plan = make_plan(snapshots, keys)
        ss[PREFIX + "preview"] = {
            "plan": plan, "created": time.monotonic(), "nonce": uuid.uuid4().hex,
            "configuration": configuration_fingerprint(repos),
        }
    except (SyncError, StorageError, ValueError, TypeError, KeyError):
        # Do not render remote response bodies or potentially clinical errors.
        note("Comparison could not be completed. Check the two data-repository entries, private-repository permissions, shared key and app versions. No mappings or patient records were changed.", "error")


def _choices(preview, state) -> dict:
    return {entry.ident: state.get(PREFIX + preview["nonce"] + "_" + entry.ident, -1)
            for entry in preview["plan"].conflicts}


def approve_sync(store, require_admin: Callable[[], bool], reload_archive: Callable,
                 note: Callable) -> None:
    if not require_admin():
        return
    ss = st.session_state
    preview = ss.get(PREFIX + "preview")
    if preview is None:
        note("Compare the repositories before saving.", "error")
        return
    attempted = False
    try:
        if time.monotonic() - preview["created"] >= PREVIEW_TTL:
            raise SyncError("The comparison expired. Compare again before saving.")
        repos = _repositories(store)
        if configuration_fingerprint(repos) != preview["configuration"]:
            raise SyncError("The repository configuration changed. Compare again.")
        plan = preview["plan"]
        if plan.keys != scope_keys(bool(ss.get(PREFIX + "include_visibility", False))):
            raise SyncError("The selected mapping scope changed. Compare again.")
        if not ss.get(PREFIX + "confirm", False):
            raise SyncError("Confirm the app versions and reviewed mapping merge before saving.")
        merged = plan.resolve(_choices(preview, ss))
        if overlapping_rules(merged) and not ss.get(PREFIX + "overlap_reviewed", False):
            raise SyncError("Review and acknowledge the overlapping rules before saving.")
        attempted = True
        result = synchronize(repos, plan, merged, authorize=require_admin)
        ss[PREFIX + "result"] = {"complete": result.complete, "rows": result.rows,
                                  "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}
        clear_preview(ss)
        # Reload only this app's archive with its existing safe reset handling.
        # Do not reapply mappings to, or persist, any patient handoff here.
        refreshed = reload_archive(store)
        for key in list(ss):
            if key.startswith(("category_edit_", "category_rule_", "mapping_",
                               "infusion_rule_mode_", "gi_rule_mode_", "group_rule_mode_")) and not key.startswith(PREFIX):
                ss.pop(key, None)
            elif key in ("admin_rule_index", "admin_rooms", "admin_diagnosis_dest",
                         "antiepileptic_extra_names"):
                ss.pop(key, None)
        if result.complete:
            message = "Mapping synchronization completed. Each repository kept its own patient records. Reload the saved archive in the other apps before continuing."
            if not refreshed:
                message += " This app also needs Reload saved archive before further edits."
            note(message, "info" if refreshed else "warning")
        else:
            note("Synchronization stopped. Review the per-repository results below. Some repositories may already have been updated. Compare again before retrying.", "warning")
    except SyncError as exc:
        note(str(exc), "error")
    except (StorageError, ValueError, TypeError, KeyError):
        if attempted:
            clear_preview(ss)
            reload_archive(store)
        note("Synchronization was not confirmed. Reload and compare before retrying. Do not assume all repositories were updated.", "error")


def _description(entry, value: dict, items: list[dict]) -> str:
    if entry.setting == "medication_categories":
        parent = next((c["name"] for c in items if c["id"] == value["parent"]), value["parent"])
        return " / ".join(filter(None, (value["section"], parent, value["name"]))) + " | order " + str(value["order"])
    if "target" in value:
        return target_label(value["target"], items)
    if "destination" in value:
        return value["destination"]
    if "hidden" in value:
        return "Hidden" if value["hidden"] else "Visible"
    return value.get("mode", "")


def mapping_sync_admin(store, require_admin: Callable[[], bool], reload_archive: Callable,
                       note: Callable) -> None:
    with st.expander("Mapping Sync", expanded=False):
        # Rendering is not an authorization substitute. Every callback checks too.
        if not require_admin():
            return
        st.caption("Compare saved mappings across your apps, review conflicts, then save the approved merge. Nothing synchronizes automatically.")
        st.caption("Your archive contains mappings and patient records together. Sync reads it in server memory and changes only mapping settings in each destination. It never copies patient records between repositories.")
        if store is None:
            st.info("Mapping Sync requires the existing encrypted GitHub storage connection.")
            return
        try:
            repos = _repositories(store)
        except (SyncError, StorageError, ValueError, KeyError, TypeError):
            st.error("Check the mapping_sync section in deployment Secrets.")
            with st.expander("Setup example"):
                st.code(SETUP, language="toml")
            return
        if len(repos) < 2:
            st.info("Add the other two private data repositories to deployment Secrets. Your current repository is already included.")
            st.code(SETUP, language="toml")
            st.caption("All apps must use the same encryption key. Tokens stay in Secrets and need access to the selected private data repositories. Follow MAPPING_SYNC_SETUP.md in this update.")
            return
        st.dataframe([{"App": r.label, "Data repository": r.store.config.repository,
                       "Branch": r.store.config.branch} for r in repos], hide_index=True, width="stretch")
        st.caption("Archive path: encrypted-data/handoff-v1.enc. No folder scan or whole-folder copy is performed.")
        st.checkbox("Also merge hidden-medication preferences", value=False, key=PREFIX + "include_visibility",
                    help="Off by default. Each app keeps its own hide/show preferences unless you select this.")
        st.button("Compare mappings", key=PREFIX + "compare", on_click=prepare_comparison,
                  args=(store, require_admin, note))
        ss = st.session_state
        result = ss.get(PREFIX + "result")
        if result:
            st.caption("Last sync attempt in this session: " + result["at"])
            st.dataframe(result["rows"], hide_index=True, width="stretch")
            if not result["complete"]:
                st.warning("No cross-repository rollback is performed. Check every status and compare again before retrying.")
        preview = ss.get(PREFIX + "preview")
        if not preview:
            return
        plan: MergePlan = preview["plan"]
        if (time.monotonic() - preview["created"] >= PREVIEW_TTL
                or configuration_fingerprint(repos) != preview["configuration"]
                or plan.keys != scope_keys(bool(ss.get(PREFIX + "include_visibility", False)))):
            st.warning("The comparison expired or the configuration changed. Compare mappings again.")
            return
        st.subheader("Review mappings")
        st.dataframe([dict(App=snap.label, **{LABELS[key]: len(snap.mappings[key]) for key in plan.keys})
                      for snap in plan.snapshots], hide_index=True, width="stretch")
        st.write(str(len(plan.conflicts)) + " conflicting entries need a choice.")
        st.caption("This is an additive merge, not a deletion sync. A mapping deleted in one app can return if another app still has it. Doses, patient notes, room lists, diagnoses settings and daily-reset information are not shared.")
        # Definitions are displayed even before conflicts have been selected.
        items = [entry.variants[0].value for entry in plan.entries if entry.setting == "medication_categories"]
        for entry in plan.conflicts:
            first = entry.variants[0].value
            title = LABELS[entry.setting] + ": " + first.get("name", entry.key[0])[:180]
            with st.container(border=True):
                st.write(title)
                if entry.setting != "medication_categories":
                    st.caption("Match: " + first.get("match", "exact") + " | Route: " + (first.get("route") or "Any")
                               + " | Frequency: " + (first.get("frequency") or "Any"))
                labels = {i: ", ".join(variant.sources) + ": " + _description(entry, variant.value, items)
                          for i, variant in enumerate(entry.variants)}
                st.radio("Choose the mapping to keep", [-1] + list(labels),
                         format_func=lambda i, lookup=labels: "Choose one" if i == -1 else lookup[i],
                         key=PREFIX + preview["nonce"] + "_" + entry.ident, on_change=reset_approval)
        try:
            merged = plan.resolve(_choices(preview, ss))
        except SyncError as exc:
            st.info(str(exc))
            return
        items = merged["medication_categories"]
        with st.expander("Full proposed mapping list", expanded=False):
            rows = []
            for entry in plan.entries:
                selected = next(row for row in merged[entry.setting]
                                if row.get("id", "") == entry.key[0]) if entry.setting == "medication_categories" else entry.variants[_choices(preview, ss).get(entry.ident, 0)].value
                rows.append({"Type": LABELS[entry.setting], "Name / prefix": selected.get("name", ""),
                             "Match": selected.get("match", ""), "Route": selected.get("route", ""),
                             "Frequency": selected.get("frequency", ""),
                             "Proposed mapping": _description(entry, selected, items)})
            st.dataframe(rows, hide_index=True, width="stretch")
        overlaps = overlapping_rules(merged)
        if overlaps:
            st.warning("Some rules overlap or use different mapping layers. Category assignments take priority over older mappings. Review these combinations before saving.")
            st.dataframe(overlaps, hide_index=True, width="stretch")
            st.caption("At most 100 combinations are shown. Exact/prefix and route/frequency filters stay distinct. Existing app precedence is retained.")
            st.checkbox("I reviewed the overlapping rules and their precedence.", key=PREFIX + "overlap_reviewed")
        st.checkbox("All selected apps are updated to v6.65 or later, and I approve this mapping-only merge.", key=PREFIX + "confirm")
        st.caption("Before any mapping writes, encrypted mapping-only backups are created in each changed repository. If a save fails, later repositories are not written. The result table reports what completed.")
        st.button("Save merged mappings to all listed apps", type="primary", key=PREFIX + "save",
                  disabled=not ss.get(PREFIX + "confirm", False) or bool(overlaps and not ss.get(PREFIX + "overlap_reviewed", False)),
                  on_click=approve_sync, args=(store, require_admin, reload_archive, note))
