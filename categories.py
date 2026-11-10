"""Single-destination medication categories, optional one-level subcategories.

Display only. No clinical values are copied into mapping rules. A saved row
contains a validated presentation snapshot so standalone saved handoffs print.
Definitions and rules live in the existing encrypted settings. Clinical source
fields, inclusion flags, infusion decisions and doses are never changed here.
"""
from __future__ import annotations
from copy import deepcopy
import re
import uuid
from medications import DESTINATIONS, is_bupivacaine, match_name, normalized, visible

SETTINGS_KEYS = {"medication_categories", "medication_category_rules"}
CATEGORY_SYSTEMS = tuple(x for x in DESTINATIONS if x != "Labs")


def default_categories() -> list[dict]:
    from medication_groups import GROUP_NAMES, GROUP_SECTIONS, CV_GROUPS, NEURO_PRIORITY_GROUPS
    from fen_gi import GROUP_NAMES as GI_NAMES
    from infusions import INFUSION_HEADINGS
    result = []
    for key, name in GROUP_NAMES.items():
        order = 100
        if key in NEURO_PRIORITY_GROUPS:
            order = 20 + 10 * NEURO_PRIORITY_GROUPS.index(key)
        elif key in CV_GROUPS:
            order = 10 + 10 * CV_GROUPS.index(key)
        elif key == "dvt":
            order = 5
        elif key == "antiplatelet":
            order = 10
        elif key in ("antibiotic", "antifungal", "antiviral"):
            order = 10 + 10 * ("antibiotic", "antifungal", "antiviral").index(key)
        result.append(dict(id="group:" + key, name=name, section=GROUP_SECTIONS[key], parent="", order=order))
    for n, (key, name) in enumerate(GI_NAMES.items()):
        result.append(dict(id="gi:" + key, name=name, section="FEN / GI", parent="", order=10 if key == "tpn" else 20 + 10*n))
    for key, name in INFUSION_HEADINGS.items():
        order = 10 if key == "Neurologic" else 90 if key == "Cardiovascular" else 15
        result.append(dict(id="infusion:" + key, name=name, section=key, parent="", order=order))
    return result


def add_missing_builtin_categories(settings: dict) -> dict:
    """Schema upgrade only. Never overwrite existing category names or placements."""
    result = deepcopy(settings)
    if "medication_categories" not in result:
        return result
    items = result["medication_categories"]
    if not isinstance(items, list):
        raise ValueError("The saved medication categories are invalid.")
    ids = {item.get("id") for item in items if isinstance(item, dict)}
    occupied = {(item.get("section"), item.get("parent"), normalized(item.get("name", "")))
                for item in items if isinstance(item, dict)}
    for item in default_categories():
        if item["id"] in ids:
            continue
        original_name = item["name"]
        n = 1
        while (item["section"], item["parent"], normalized(item["name"])) in occupied:
            item["name"] = original_name + (" (default)" if n == 1 else " (default " + str(n) + ")")
            n += 1
        items.append(item)
        ids.add(item["id"])
        occupied.add((item["section"], item["parent"], normalized(item["name"])))
    validate_settings(result)
    return result


def catalog(settings: dict) -> list[dict]:
    items = deepcopy(settings.get("medication_categories", default_categories()))
    # Version 6.57 archives can have a complete saved catalog without Epidural.
    # Expose this new category without rewriting the archive or its other
    # categories. The next intentional category edit can persist the addition.
    if isinstance(items, list) and not any(isinstance(c, dict) and c.get("id") == "group:epidural" for c in items):
        item = next(c for c in default_categories() if c["id"] == "group:epidural")
        occupied = {(c.get("section"), c.get("parent"), normalized(c.get("name", "")))
                    for c in items if isinstance(c, dict) and isinstance(c.get("name"), str)}
        n = 0
        while (item["section"], item["parent"], normalized(item["name"])) in occupied:
            n += 1
            item["name"] = "Epidural (default" + (" " + str(n) if n > 1 else "") + ")"
        items.append(item)
    return items


def _text(value: object, maximum: int = 80, empty: bool = False) -> bool:
    return isinstance(value, str) and len(value) <= maximum and (empty or bool(value.strip())) and not any(ord(c) < 32 for c in value)


def validate_catalog(items: list[dict]) -> None:
    # Preserve all 250 pre-6.58 slots when the new required Epidural category
    # is added. Duplicate IDs and every other catalog rule are still checked.
    extra_builtin = (isinstance(items, list) and
                     any(isinstance(item, dict) and item.get("id") == "group:epidural" for item in items))
    if not isinstance(items, list) or len(items) > 250 + int(extra_builtin):
        raise ValueError("Use at most 250 medication categories and subcategories, plus the Epidural built-in.")
    ids, labels = {}, set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "name", "section", "parent", "order"}:
            raise ValueError("A medication category has an invalid structure.")
        if not _text(item["id"], 100) or not _text(item["parent"], 100, True) or not _text(item["name"]):
            raise ValueError("Category names must be single-line text of 1 to 80 characters.")
        if item["section"] not in CATEGORY_SYSTEMS or type(item["order"]) is not int or not 0 <= item["order"] <= 999:
            raise ValueError("Choose a valid system and category order from 0 to 999.")
        key = (item["section"], item["parent"], normalized(item["name"]))
        if item["id"] in ids or key in labels:
            raise ValueError("That category already exists in this location.")
        ids[item["id"]] = item
        labels.add(key)
    for item in items:
        if item["parent"]:
            parent = ids.get(item["parent"])
            if not parent or parent["parent"] or parent["id"] == item["id"] or parent["section"] != item["section"]:
                raise ValueError("A subcategory needs one top-level parent in the same system.")
    # Built-in identifiers must remain available for old automatic rules.
    if not {r["id"] for r in default_categories()}.issubset(ids):
        raise ValueError("Built-in categories may be renamed or moved, but not removed.")


def validate_category_rules(rules: list[dict], items: list[dict]) -> None:
    if not isinstance(rules, list) or len(rules) > 1500:
        raise ValueError("The category mapping list is invalid or too large.")
    ids = {c["id"] for c in items}
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"name", "match", "route", "frequency", "target"}:
            raise ValueError("A category mapping has an invalid structure.")
        if not _text(rule["name"], 4000) or any(not _text(rule[k], 4000, True) for k in ("route", "frequency")):
            raise ValueError("Use single-line medication, route and frequency text.")
        if rule["match"] not in ("prefix", "exact") or (rule["target"] not in ids and rule["target"] not in system_targets()):
            raise ValueError("Choose an existing category or an uncategorized system.")
        key = (normalized(rule["name"]), rule["match"], normalized(rule["route"]), normalized(rule["frequency"]))
        if key in seen:
            raise ValueError("One medication matching rule can have only one destination.")
        seen.add(key)


def validate_settings(settings: dict) -> None:
    items = catalog(settings)
    validate_catalog(items)
    validate_category_rules(settings.get("medication_category_rules", []), items)


def system_targets() -> dict[str, str]:
    return {"system:" + section: section for section in CATEGORY_SYSTEMS}


def target_label(target: str, items: list[dict]) -> str:
    if target == "auto":
        return "Automatic / existing mappings"
    if target in system_targets():
        return system_targets()[target] + " / No category"
    node = next((x for x in items if x["id"] == target), None)
    if node is None:
        return "Unavailable category"
    parent = next((x for x in items if x["id"] == node["parent"]), None)
    return " / ".join([node["section"]] + ([parent["name"]] if parent else []) + [node["name"]])


def target_snapshot(target: str, items: list[dict]) -> dict:
    if target in system_targets():
        return {"id": target, "name": "", "section": system_targets()[target], "parent_id": "", "parent_name": "", "order": 999, "parent_order": 999}
    node = next((x for x in items if x["id"] == target), None)
    if node is None:
        raise ValueError("The selected category no longer exists.")
    parent = next((x for x in items if x["id"] == node["parent"]), None)
    return {"id": node["id"], "name": node["name"], "section": node["section"],
            "parent_id": parent["id"] if parent else "", "parent_name": parent["name"] if parent else "",
            "order": node["order"], "parent_order": parent["order"] if parent else node["order"]}


def validate_snapshot(value: dict) -> None:
    if not isinstance(value, dict) or set(value) != {"id", "name", "section", "parent_id", "parent_name", "order", "parent_order"}:
        raise ValueError("A medication category assignment is invalid.")
    if value["section"] not in CATEGORY_SYSTEMS:
        raise ValueError("A medication category has an invalid system.")
    for field, n in (("id", 100), ("name", 80), ("parent_id", 100), ("parent_name", 80)):
        if not _text(value[field], n, field != "id"):
            raise ValueError("A medication category contains invalid text.")
    if bool(value["parent_id"]) != bool(value["parent_name"]) or (value["parent_id"] and not value["name"]):
        raise ValueError("A medication subcategory is missing its parent.")
    if any(type(value[k]) is not int or not 0 <= value[k] <= 999 for k in ("order", "parent_order")):
        raise ValueError("A medication category order is invalid.")


def rule_key(rule: dict) -> tuple:
    return normalized(rule["name"]), rule["match"], normalized(rule["route"]), normalized(rule["frequency"])


def set_category_rule(settings: dict, name: str, target: str, match: str = "prefix", route: str = "", frequency: str = "") -> dict:
    result = deepcopy(settings)
    rule = dict(name=match_name(name), target=target, match=match, route=normalized(route), frequency=normalized(frequency))
    rules = [deepcopy(r) for r in result.get("medication_category_rules", []) if rule_key(r) != rule_key(rule)]
    if target != "auto":
        rules.append(rule)
    result["medication_category_rules"] = sorted(rules, key=rule_key)
    validate_settings(result)
    return result


def matching_target(row: dict, settings: dict) -> str:
    name, route, frequency = match_name(row.get("name", "")), normalized(row.get("route", "")), normalized(row.get("frequency", ""))
    matches = []
    for rule in settings.get("medication_category_rules", []):
        term = rule["name"]
        if rule["route"] and rule["route"] != route or rule["frequency"] and rule["frequency"] != frequency:
            continue
        if name == term or (rule["match"] == "prefix" and name.startswith(term) and len(name) > len(term) and not name[len(term)].isalnum()):
            matches.append(((rule["match"] == "exact", len(term), bool(rule["route"]), bool(rule["frequency"])), rule["target"]))
    return max(matches)[1] if matches else ""


def legacy_target(row: dict) -> str:
    """Compute one legacy placement, honoring prior explicit overrides."""
    from medication_groups import group_for
    from fen_gi import group_for as gi_group, effective_section
    from infusions import is_infusion, INFUSION_SECTIONS
    group = group_for(row)
    if group:
        return "group:" + group
    gi = gi_group(row)
    if gi:
        return "gi:" + gi
    section = effective_section(row)
    if section in INFUSION_SECTIONS and is_infusion(row):
        return "infusion:" + section
    return ""


def apply_category_rules(rows: list[dict], settings: dict) -> list[dict]:
    validate_settings(settings)
    items = catalog(settings)
    defaults = {c["id"]: c for c in default_categories()}
    definitions = {c["id"]: c for c in items}
    result = deepcopy(rows)
    for row in result:
        row.pop("category_path", None)
        if is_bupivacaine(row.get("name", "")):
            row["section"] = "Neurologic"
            # The explicit bupivacaine placement takes precedence over older
            # name, group, and category assignments. No source amount changes.
            row["category_path"] = target_snapshot("group:epidural", default_categories())
            continue
        target = matching_target(row, settings)
        if target:
            row["category_path"] = target_snapshot(target, items)
        else:
            legacy = legacy_target(row)
            if legacy and definitions.get(legacy) != defaults.get(legacy):
                row["category_path"] = target_snapshot(legacy, items)
    return result


def placement(row: dict) -> dict:
    # Render saved handoffs correctly before any reimport or settings save.
    if is_bupivacaine(row.get("name", "")):
        return target_snapshot("group:epidural", default_categories())
    if row.get("category_path") is not None:
        return row["category_path"]
    target = legacy_target(row)
    if target:
        return target_snapshot(target, default_categories())
    from fen_gi import effective_section
    section = effective_section(row)
    return {"id": "system:" + section, "name": "", "section": section, "parent_id": "", "parent_name": "", "order": 999, "parent_order": 999}


def save_category(settings: dict, name: str, section: str, parent: str = "", ident: str = "", order: int = 100) -> dict:
    result = deepcopy(settings)
    items = catalog(result)
    ident = ident or "custom:" + uuid.uuid4().hex
    items = [i for i in items if i["id"] != ident] + [dict(id=ident, name=name.strip(), section=section, parent=parent, order=order)]
    # Moving a parent moves its children with it. Nesting a parent with children is rejected.
    for child in items:
        if child["parent"] == ident:
            child["section"] = section
    result["medication_categories"] = items
    validate_settings(result)
    return result


def delete_category(settings: dict, ident: str) -> dict:
    if ident in {c["id"] for c in default_categories()}:
        raise ValueError("A built-in category can be renamed or moved, but not deleted.")
    if any(c["parent"] == ident for c in catalog(settings)) or any(r["target"] == ident for r in settings.get("medication_category_rules", [])):
        raise ValueError("Move the assigned medication rules and subcategories before deleting this category.")
    result = deepcopy(settings)
    result["medication_categories"] = [c for c in catalog(settings) if c["id"] != ident]
    validate_settings(result)
    return result


def _display_root_key(path: dict):
    """Keep the fixed Epidural heading separate from a renamed saved category.

    A bupivacaine order always uses the canonical snapshot. Other drugs may
    intentionally use a renamed group:epidural category or its children. Their
    saved IDs stay intact, but different displayed roots must not merge just
    because their IDs match. Matching default Epidural snapshots still merge.
    """
    ident = path["parent_id"] or path["id"]
    if ident == "group:epidural":
        return ident, path["parent_name"] or path["name"]
    return ident


def medication_blocks(section: str, notes: str, rows: list[dict], sheet: dict | None = None) -> list[tuple]:
    """One emitted entry per visible source order, never one per matching rule."""
    from fen_gi import effective_section
    from infusions import is_infusion, supports_infusion_display
    from medication_groups import group_for
    meds = [r for r in rows if visible(r) and effective_section(r) == section]
    if section == "Neurologic":
        meds.sort(key=lambda r: match_name(r.get("name", "")).split(" ", 1)[0])
    roots, plain = {}, []
    for row in meds:
        path = placement(row)
        if not path["name"]:
            plain.append(row)
            continue
        root_id = _display_root_key(path)
        root_name = path["parent_name"] or path["name"]
        root_order = path["parent_order"]
        root = roots.setdefault(root_id, dict(name=root_name, order=root_order, direct=[], children={}))
        if path["parent_id"]:
            child = root["children"].setdefault(path["id"], dict(name=path["name"], order=path["order"], rows=[]))
            child["rows"].append(row)
        else:
            root["direct"].append(row)
    if sheet is not None:
        from empty_groups import empty_group_paths
        for path in empty_group_paths(sheet, rows):
            if path["section"] != section:
                continue
            root_id = _display_root_key(path)
            root = roots.setdefault(root_id, dict(name=path["parent_name"] or path["name"],
                order=path["parent_order"], direct=[], children={}))
            if path["parent_id"]:
                root["children"].setdefault(path["id"], dict(name=path["name"],
                    order=path["order"], rows=[], empty=True))
            else:
                root["empty"] = True
    if sheet is not None and section == "Hematology":
        from lab_windows import anti_xa_today_summary
        level = anti_xa_today_summary(sheet)
        if level:
            # Prefer an already rendered DVT root/subcategory, including a
            # renamed category. A lab never counts as a medication order.
            bucket = roots.get("group:dvt")
            if bucket is None:
                bucket = next((root["children"]["group:dvt"] for root in roots.values()
                               if "group:dvt" in root["children"]), None)
            if bucket is None:
                path = target_snapshot("group:dvt", default_categories())
                candidates = list(sheet.get("empty_group_layout", []))
                candidates += [placement(row) for row in rows]
                for candidate in candidates:
                    if candidate["id"] == "group:dvt" and candidate["section"] == section:
                        path = candidate
                root_id = _display_root_key(path)
                root = roots.setdefault(root_id, dict(name=path["parent_name"] or path["name"],
                    order=path["parent_order"], direct=[], children={}))
                bucket = (root["children"].setdefault(path["id"], dict(name=path["name"],
                    order=path["order"], rows=[])) if path["parent_id"] else root)
            bucket.setdefault("labs", []).append(("lab", level))
    anchor = theophylline_anchor(sheet) if sheet else ""
    def entries(items):
        blocks = []
        for row in items:
            emphasize = is_infusion(row) and (supports_infusion_display(row) or group_for(row) == "antiepileptic")
            blocks.append(("infusion" if emphasize else "medication", row))
            if row["id"] == anchor:
                from lab_windows import theophylline_summary
                level = theophylline_summary(sheet)
                if level:
                    blocks.append(("lab", "  " + level))
        return blocks
    if not roots and section != "FEN / GI":
        return ([("notes", notes.rstrip())] if notes.strip() else []) + entries(plain)
    groups = []
    for root in sorted(roots.values(), key=lambda x: (x["order"], x["name"].casefold())):
        if root.get("empty") and not root["direct"] and not root["children"]:
            block = [("empty_group", root["name"])]
        else:
            block = [("heading", root["name"])] + entries(root["direct"])
        for child in sorted(root["children"].values(), key=lambda x: (x["order"], x["name"].casefold())):
            if child.get("empty") and not child["rows"]:
                block += [("empty_group", child["name"])]
            else:
                block += [("subheading", child["name"])] + entries(child["rows"])
            block += child.get("labs", [])
        block += root.get("labs", [])
        groups.append(block)
    if notes.strip():
        groups.append([("notes", notes.rstrip())])
    if plain:
        heading = "Other FEN/GI medications" if section == "FEN / GI" else "Other Medications"
        groups.append(([("heading", heading)] if roots else []) + entries(plain))
    result = []
    for group in groups:
        if result and not (section == "Respiratory" and group[0][0] == "heading" and group[0][1] != "Other Medications"):
            result.append(("separator", "-----"))
        result.extend(group)
    return result


def theophylline_anchor(sheet: dict | None) -> str:
    if not sheet:
        return ""
    from fen_gi import effective_section
    from lab_windows import theophylline_summary
    if not theophylline_summary(sheet):
        return ""
    # Keep a fallback respiratory result when there is no visible rendered drug.
    return next((r["id"] for r in sheet.get("medications", []) if visible(r)
                 and re.match(r"^aminophylline(?=$|[\s(,])", match_name(r.get("name", "")))
                 and effective_section(r) != "Labs"), "")
