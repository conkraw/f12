"""Compact empty medication groups using the same single destination as medications.

None means no orders assigned to that group in this handoff, not a review of
Epic outside the pasted list. Hidden/excluded orders suppress a false None.
Failed medication imports cannot establish an empty group.
"""
from copy import deepcopy

REQUIRED_GROUPS = ("group:dvt", "gi:bowel", "gi:prophylaxis", "gi:diuretic", "group:fever")
LAYOUT_KEY = "empty_group_layout"


def refresh_empty_group_layout(sheet: dict, settings: dict) -> None:
    """Refresh presentation-only snapshots on the caller's own draft/copy.

    Store only nondefault definitions. Uncustomized old handoff fields therefore
    remain unchanged on open/save. No medication or timestamp is edited here.
    """
    from categories import catalog, default_categories, target_snapshot
    definitions = catalog(settings)
    defaults = default_categories()
    custom = [target_snapshot(ident, definitions) for ident in REQUIRED_GROUPS
              if target_snapshot(ident, definitions) != target_snapshot(ident, defaults)]
    if custom:
        sheet[LAYOUT_KEY] = custom
    else:
        sheet.pop(LAYOUT_KEY, None)


def validate_empty_group_layout(layout: list[dict]) -> None:
    from categories import validate_snapshot
    if not isinstance(layout, list) or len(layout) > len(REQUIRED_GROUPS):
        raise ValueError("The empty medication group layout is invalid.")
    ids = set()
    for path in layout:
        validate_snapshot(path)
        if path["id"] not in REQUIRED_GROUPS or path["id"] in ids or not path["name"]:
            raise ValueError("The empty medication group layout contains an invalid category.")
        ids.add(path["id"])


def empty_group_paths(sheet: dict, rows: list[dict]) -> list[dict]:
    from categories import default_categories, target_snapshot, placement
    if "b" in sheet.get("import_warnings", {}):
        return []
    layout = sheet.get(LAYOUT_KEY, [])
    validate_empty_group_layout(layout)
    paths = {ident: target_snapshot(ident, default_categories()) for ident in REQUIRED_GROUPS}
    paths.update({p["id"]: deepcopy(p) for p in layout})
    occupied = set()
    for row in rows:
        # Deliberately count hidden and excluded entries: not printed != absent.
        path = placement(row)
        occupied.add(path["id"])
        if path["parent_id"]:
            occupied.add(path["parent_id"])
        if path["id"] in paths:
            paths[path["id"]] = path
    result = [deepcopy(p) for ident, p in paths.items() if ident not in occupied]
    for path in result:
        if path["id"] == "gi:prophylaxis" and path["name"] == "GI prophylaxis":
            path["name"] = "GI Prophylaxis"
    return result
