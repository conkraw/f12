"""Admin category editor and one-destination picker. No patient text is logged."""
from __future__ import annotations
from copy import deepcopy
from categories import (CATEGORY_SYSTEMS, catalog, target_label, system_targets,
                        save_category, delete_category, set_category_rule, rule_key,
                        matching_target, placement)
from medications import match_name, normalized


def targets(settings: dict) -> list[str]:
    items = catalog(settings)
    return sorted([c["id"] for c in items] + list(system_targets()), key=lambda k: target_label(k, items).casefold())


def local_target(row: dict, settings: dict) -> str:
    key = (match_name(row["name"]), "exact", normalized(row["route"]), normalized(row["frequency"]))
    return next((r["target"] for r in settings.get("medication_category_rules", []) if rule_key(r) == key), "auto")


def placement_picker(row: dict, number: int, room: str, store, callback) -> None:
    import streamlit as st
    settings = st.session_state["vault"]["settings"]
    items = catalog(settings)
    key = "med_draft_" + row["id"] + "_category_target"
    options = ["auto"] + targets(settings)
    if key not in st.session_state or st.session_state[key] not in options:
        st.session_state[key] = local_target(row, settings)
    st.selectbox("Category for order " + str(number), options, key=key,
                 format_func=lambda k: target_label(k, items), on_change=callback,
                 args=(room, row["id"], key, store))
    path = placement(row)
    st.caption("Placement: " + " / ".join(v for v in [path["section"], path["parent_name"], path["name"]] if v))


def category_admin(store, require_admin, commit, reapply, note) -> None:
    """All mutating callbacks recheck the second-password Admin grant."""
    import streamlit as st
    ss = st.session_state
    settings = ss["vault"]["settings"]
    items = catalog(settings)
    def publish(updated):
        candidate = deepcopy(ss["vault"])
        candidate["settings"] = updated
        commit(candidate, store)
        reapply()
        for key in list(ss):
            if key.startswith(("category_edit_", "category_rule_")):
                ss.pop(key, None)
        note("Categories and medication assignments saved." if store else "Categories and assignments updated in this test session.", "success")
    def save_definition(ident):
        if not require_admin():
            return
        try:
            current = ss["vault"]["settings"]
            parent = ss["category_edit_parent"]
            section = ss["category_edit_section"]
            if parent:
                section = next(c["section"] for c in catalog(current) if c["id"] == parent)
            publish(save_category(current, ss["category_edit_name"], section, parent, ident, int(ss["category_edit_order"])))
        except Exception as exc:
            # Storage errors are static/patient-free. Unexpected errors do not echo text.
            from github_store import StorageError
            if isinstance(exc, (ValueError, StorageError)):
                note(str(exc) + " No category changes were saved.", "error")
            else:
                note("Category changes could not be saved. Existing assignments were kept.", "error")
    def remove_definition(ident):
        if not require_admin():
            return
        try:
            publish(delete_category(ss["vault"]["settings"], ident))
        except Exception as exc:
            from github_store import StorageError
            note(str(exc) if isinstance(exc, (ValueError, StorageError)) else "Category deletion was not saved.", "error")
    def save_mapping(original):
        if not require_admin():
            return
        try:
            updated = deepcopy(ss["vault"]["settings"])
            if original:
                updated["medication_category_rules"] = [r for r in updated.get("medication_category_rules", []) if rule_key(r) != original]
            updated = set_category_rule(updated, ss["category_rule_name"], ss["category_rule_target"],
                                        ss["category_rule_match"], ss["category_rule_route"], ss["category_rule_frequency"])
            publish(updated)
        except Exception as exc:
            from github_store import StorageError
            note(str(exc) if isinstance(exc, (ValueError, StorageError)) else "The category assignment was not saved.", "error")
    def remove_mapping(original):
        if not require_admin():
            return
        try:
            updated = deepcopy(ss["vault"]["settings"])
            updated["medication_category_rules"] = [r for r in updated.get("medication_category_rules", []) if rule_key(r) != original]
            publish(updated)
        except Exception:
            note("The assignment was not removed. Existing settings were kept.", "error")
    def reset_edit():
        for key in list(ss):
            if key.startswith("category_edit_") and key != "category_edit_choice":
                ss.pop(key, None)
    def reset_rule():
        for key in list(ss):
            if key.startswith("category_rule_") and key != "category_rule_choice":
                ss.pop(key, None)
    with st.expander("Medication categories and subcategories", expanded=True):
        st.caption("Create a category in a system, or add one subcategory beneath a category. Each order prints once in its selected destination. These are display labels, not prescribing recommendations.")
        choices = [""] + [c["id"] for c in sorted(items, key=lambda c: target_label(c["id"], items).casefold())]
        if ss.get("category_edit_choice", "") not in choices:
            ss.pop("category_edit_choice", None)
        ident = st.selectbox("Add or edit category", choices, key="category_edit_choice", on_change=reset_edit,
                             format_func=lambda k: "Add a category or subcategory" if not k else target_label(k, items))
        item = next((c for c in items if c["id"] == ident), {"name": "", "section": "Respiratory", "parent": "", "order": 100})
        for field in ("name", "section", "parent", "order"):
            ss.setdefault("category_edit_" + field, item[field])
        parents = [""] + [c["id"] for c in items if not c["parent"] and c["id"] != ident]
        if ss["category_edit_parent"] not in parents:
            ss["category_edit_parent"] = ""
        with st.form("category_definition_form"):
            st.text_input("Category name", key="category_edit_name", max_chars=80)
            st.selectbox("System for top-level category", CATEGORY_SYSTEMS, key="category_edit_section")
            st.selectbox("Parent category (optional)", parents, key="category_edit_parent",
                         format_func=lambda k: "None: top-level category" if not k else target_label(k, items))
            st.number_input("Display order (smaller first)", min_value=0, max_value=999, step=1, key="category_edit_order")
            st.caption("A subcategory uses its parent's system. Equal display orders are alphabetical.")
            st.form_submit_button("Save category", on_click=save_definition, args=(ident,))
        if ident and ident.startswith("custom:"):
            st.button("Delete category", key="delete_category", on_click=remove_definition, args=(ident,))
        st.caption("Built-in categories can be renamed, reordered or moved. A custom category with assigned rules or children must be emptied before deletion.")
    with st.expander("Assign medications to categories", expanded=True):
        st.caption("Use a generic name such as albuterol for all formulations, or an exact full product name. Optional route and frequency filters narrow the rule. One destination replaces the previous placement. Exact rules take priority, then the longest matching prefix.")
        rules = settings.get("medication_category_rules", [])
        options = [-1] + list(range(len(rules)))
        if ss.get("category_rule_choice", -1) not in options:
            ss.pop("category_rule_choice", None)
        choice = st.selectbox("Add or edit medication assignment", options, key="category_rule_choice", on_change=reset_rule,
                              format_func=lambda k: "Add medication assignment" if k < 0 else rules[k]["name"] + " -> " + target_label(rules[k]["target"], items))
        current = rules[choice] if choice >= 0 else dict(name="", match="prefix", route="", frequency="", target="group:beta_agonist")
        for field in ("name", "match", "route", "frequency", "target"):
            ss.setdefault("category_rule_" + field, current[field])
        with st.form("category_assignment_form"):
            st.text_input("Medication name or prefix", key="category_rule_name", max_chars=4000)
            st.selectbox("Name matching", ["prefix", "exact"], key="category_rule_match")
            st.text_input("Route filter (blank means any route)", key="category_rule_route", max_chars=100)
            st.text_input("Frequency filter (blank means any frequency)", key="category_rule_frequency", max_chars=100)
            st.selectbox("Only destination", targets(settings), key="category_rule_target", format_func=lambda k: target_label(k, items))
            st.form_submit_button("Save category assignment", on_click=save_mapping, args=(rule_key(current) if choice >= 0 else None,))
        if choice >= 0:
            st.button("Delete category assignment", key="delete_category_rule", on_click=remove_mapping, args=(rule_key(current),))
        if rules:
            st.caption("Assignments selected in an open handoff appear here automatically.")
