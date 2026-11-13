"""Admin-only UI for manual synchronization. No patient data in previews."""
from __future__ import annotations
import time
import uuid
import logging
from typing import Callable
import streamlit as st
from categories import target_label
from github_store import StorageError
from mapping_sync import (LABELS, MAPPING_KEYS, MergePlan, SyncError,
                          configuration_fingerprint, configured_repositories,
                          make_plan, overlapping_rules, scope_keys, synchronize)
from sync_diagnostics import DiagnosticError, passed, safe_error

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
        if key.startswith(PREFIX) and key not in (PREFIX + "include_visibility", PREFIX + "result", PREFIX + "diagnostics"):
            state.pop(key, None)


def reset_approval() -> None:
    """A changed conflict choice needs a fresh acknowledgement."""
    st.session_state.pop(PREFIX + "confirm", None)
    st.session_state.pop(PREFIX + "overlap_reviewed", None)


def _repositories(store):
    return configured_repositories(store, st.secrets.to_dict())


def _metadata(repo) -> dict:
    config = getattr(repo.store, "config", None)
    return {"App": repo.label, "Data repository": getattr(config, "repository", ""),
            "Branch": getattr(config, "branch", ""),
            "Archive path": "encrypted-data/handoff-v1.enc",
            "Token source": getattr(repo, "credential_source", "Existing GitHub token")}


def _record_failure(checks, exc, step):
    error = safe_error(exc, step)
    row = error.row()
    if not checks or checks[-1] != row:
        checks.append(row)
    return error


def prepare_comparison(store, require_admin: Callable[[], bool], note: Callable,
                       diagnostics_only: bool = False) -> None:
    """Check every configured repository. Keep no patient data in the UI state."""
    if not require_admin():
        return
    ss = st.session_state
    clear_preview(ss)
    ss.pop(PREFIX + "result", None)
    report = {"at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
              "version": "6.66", "mode": "Read-only diagnostics" if diagnostics_only else "Mapping comparison",
              "complete": False, "repositories": [], "comparison": []}
    ss[PREFIX + "diagnostics"] = report
    try:
        repos = _repositories(store)
    except Exception as exc:
        error = _record_failure(report["comparison"], exc, "Read Streamlit Secrets configuration")
        note("Mapping Sync configuration failed. See the diagnostic panel for the field to correct. No remote writes were attempted.", "error")
        logging.getLogger(__name__).warning("Mapping Sync configuration check: %s at %s", error.code, error.step)
        return
    keys = scope_keys(bool(ss.get(PREFIX + "include_visibility", False)))
    snapshots = []
    expired = False
    for index, repo in enumerate(repos, 1):
        checks = []
        record = dict(_metadata(repo), checks=checks)
        report["repositories"].append(record)
        if expired or not require_admin():
            expired = True
            error = DiagnosticError("ADMIN_EXPIRED", "Admin authorization")
            checks.append(error.row())
            continue
        try:
            snapshots.append(repo.snapshot(keys, checks=checks))
        except Exception as exc:
            error = _record_failure(checks, exc, "Read mapping-only snapshot")
            logging.getLogger(__name__).warning("Mapping Sync repository %s: %s at %s", index, error.code, error.step)
            # Continue checking other repositories to expose every failing source.
    if expired or len(snapshots) != len(repos):
        note("One or more repository checks failed. See the failed step and next action below. No mappings or patient records were changed.", "error")
        return
    if diagnostics_only:
        report["complete"] = True
        note("Read-only checks passed. Write permission has not been tested. Use Compare mappings to prepare a merge.", "info")
        return
    if len(repos) < 2:
        error = DiagnosticError("CONFIG_INVALID", "Repository count",
                                detail="At least two distinct data repositories are required for a comparison.")
        report["comparison"].append(error.row())
        note("Add the other data repositories in Streamlit Secrets. The current repository is included automatically.", "error")
        return
    try:
        if not require_admin():
            raise DiagnosticError("ADMIN_EXPIRED", "Admin authorization")
        plan = make_plan(snapshots, keys)
        ss[PREFIX + "preview"] = {
            "plan": plan, "created": time.monotonic(), "nonce": uuid.uuid4().hex,
            "configuration": configuration_fingerprint(repos),
        }
        passed(report["comparison"], "Build mapping comparison", "The mapping-only comparison is ready. Review conflicts before any save.")
        report["complete"] = True
    except Exception as exc:
        _record_failure(report["comparison"], exc, "Build mapping comparison")
        note("Repository reads passed, but the mapping comparison failed. See the comparison step below. Nothing was changed.", "error")


def diagnostic_text(report: dict) -> str:
    """Serialize only known safe fields. Never export state, snapshots or exceptions."""
    lines = ["PICU Handoff Mapping Sync diagnostics", "App version: " + report.get("version", "6.66"),
             "Checked: " + report.get("at", ""), "Mode: " + report.get("mode", ""),
             "Read-only checks. No backup or archive writes were attempted.",
             "A successful read does not confirm write permission or another app's code version.",
             "Repository names and branches are included. Tokens, keys, medication names and patient content are excluded.", ""]
    for record in report.get("repositories", []):
        for name in ("App", "Data repository", "Branch", "Archive path", "Token source"):
            lines.append(name + ": " + str(record.get(name, "")))
        for check in record.get("checks", []):
            lines.append(" | ".join(str(check.get(name, "")) for name in ("Step", "Result", "Code", "HTTP", "Detail", "Next step")))
        lines.append("")
    for check in report.get("comparison", []):
        lines.append(" | ".join(str(check.get(name, "")) for name in ("Step", "Result", "Code", "HTTP", "Detail", "Next step")))
    return "\n".join(lines)


def render_diagnostics(report) -> None:
    if not report:
        return
    st.subheader("Mapping Sync diagnostics")
    st.caption(report["mode"] + " | " + report["at"] + " | Version " + report["version"])
    st.caption("These checks are read-only. They do not create backups, save mappings or change patient records. Write permission is checked only during an approved save.")
    rows = []
    for record in report["repositories"]:
        bad = next((check for check in record["checks"] if check["Result"] == "Failed"), None)
        last = bad or (record["checks"][-1] if record["checks"] else {})
        rows.append({"App": record["App"], "Data repository": record["Data repository"],
                     "Result": "Failed" if bad else "Passed" if record["checks"] else "Not checked",
                     "Step": last.get("Step", ""), "Code": last.get("Code", ""), "HTTP": last.get("HTTP", "")})
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    for record in report["repositories"]:
        errors = [check for check in record["checks"] if check["Result"] == "Failed"]
        with st.expander(record["App"] + " - " + ("Action needed" if errors else "Checks passed"), expanded=bool(errors)):
            st.caption("Data repository: " + record["Data repository"] + " | Branch: " + record["Branch"])
            st.caption("Archive: " + record["Archive path"] + " | Token source: " + record["Token source"] + " (value hidden)")
            for check in errors:
                st.error(check["Step"] + ": " + check["Detail"])
                st.write("Next step: " + check["Next step"])
                st.caption("Code: " + check["Code"] + (" | HTTP " + check["HTTP"] if check["HTTP"] else ""))
            st.dataframe(record["checks"], hide_index=True, width="stretch")
    for check in report["comparison"]:
        if check["Result"] == "Failed":
            st.error(check["Step"] + ": " + check["Detail"])
            st.write("Next step: " + check["Next step"])
            st.caption("Code: " + check["Code"])
    with st.expander("Copy diagnostic report", expanded=False):
        st.caption("Contains repository names and branches, but no credentials or patient content. Review before sharing.")
        st.code(diagnostic_text(report), language="text")
    st.download_button("Download diagnostic report", data=diagnostic_text(report),
                       file_name="mapping_sync_diagnostics.txt", mime="text/plain",
                       key=PREFIX + "download_diagnostics")


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
    except Exception as exc:
        error = safe_error(exc, "Approve mapping synchronization")
        if attempted:
            clear_preview(ss)
            reload_archive(store)
        note("Synchronization was not confirmed. " + error.step + ": " + error.detail + " " + error.action, "error")


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
        except Exception as exc:
            error = safe_error(exc, "Read Streamlit Secrets configuration")
            st.error(error.step + ": " + error.detail)
            st.write("Next step: " + error.action)
            st.caption("Code: " + error.code)
            with st.expander("Setup example"):
                st.code(SETUP, language="toml")
            return
        if len(repos) < 2:
            st.info("Add the other two private data repositories to deployment Secrets. Your current repository is already included.")
            st.code(SETUP, language="toml")
            st.caption("All apps must use the same encryption key. Tokens stay in Secrets and need access to the selected private data repositories. Follow MAPPING_SYNC_SETUP.md in this update.")
            return
        st.dataframe([{"App": r.label, "Data repository": r.store.config.repository,
                       "Branch": r.store.config.branch,
                       "Token source (value hidden)": getattr(r, "credential_source", "Existing GitHub token")}
                      for r in repos], hide_index=True, width="stretch")
        st.caption("Archive path: encrypted-data/handoff-v1.enc. No folder scan or whole-folder copy is performed.")
        st.checkbox("Also merge hidden-medication preferences", value=False, key=PREFIX + "include_visibility",
                    help="Off by default. Each app keeps its own hide/show preferences unless you select this.")
        st.button("Check connections (read only)", key=PREFIX + "diagnose", on_click=prepare_comparison,
                  args=(store, require_admin, note, True))
        st.button("Compare mappings", key=PREFIX + "compare", on_click=prepare_comparison,
                  args=(store, require_admin, note))
        ss = st.session_state
        render_diagnostics(ss.get(PREFIX + "diagnostics"))
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
        st.checkbox("All selected apps are updated to v6.66 or later, and I approve this mapping-only merge.", key=PREFIX + "confirm")
        st.caption("Before any mapping writes, encrypted mapping-only backups are created in each changed repository. If a save fails, later repositories are not written. The result table reports what completed.")
        st.button("Save merged mappings to all listed apps", type="primary", key=PREFIX + "save",
                  disabled=not ss.get(PREFIX + "confirm", False) or bool(overlaps and not ss.get(PREFIX + "overlap_reviewed", False)),
                  on_click=approve_sync, args=(store, require_admin, reload_archive, note))
