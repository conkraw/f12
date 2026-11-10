"""One atomic census reset. Clinical records and rules are never confused.

No network access here. The caller must commit successfully before clearing its
session. A durable generation prevents an old tab from restoring cleared drafts
when it reloads a newer archive. It is not a physical purge of Git history.
"""
from __future__ import annotations
from copy import deepcopy
import uuid
from models import DEFAULT_ROOMS, validate_vault, new_sheet, save_sheet_in, normalize_room
from difficult_airway import has_airway_details, validate_airway


def cleared_vault(vault: dict, *, keep_difficult_airway: bool = False,
                  airway_by_room: dict | None = None) -> dict:
    """Build a new census without modifying the original.

    A keep-airway reset retains only validated difficult_airway records and
    their room labels. Each retained record gets a new otherwise-blank sheet.
    Existing enabled/hidden status and all airway answers remain unchanged.
    Passing airway_by_room supplies the full set, including captured local
    edits. The caller is responsible for checking stale draft conflicts.
    """
    validate_vault(vault)
    if type(keep_difficult_airway) is not bool:
        raise ValueError("Choose either full delete or keep difficult-airway details.")
    result = deepcopy(vault)
    result['rooms'] = {}
    result['settings']['rooms'] = list(DEFAULT_ROOMS)
    result['reset_generation'] = uuid.uuid4().hex
    if keep_difficult_airway:
        records = ({room: sheet.get('difficult_airway') for room, sheet in vault['rooms'].items()}
                   if airway_by_room is None else airway_by_room)
        if not isinstance(records, dict) or len(records) > 100:
            raise ValueError("The difficult-airway room list is invalid or too large.")
        for room, data in records.items():
            if normalize_room(room) != room:
                raise ValueError("An airway room label is not normalized.")
            validate_airway(data)
            if not has_airway_details(data):
                continue
            sheet = new_sheet(room)
            sheet['difficult_airway'] = deepcopy(data)
            if room not in result['settings']['rooms']:
                result['settings']['rooms'].append(room)
            result = save_sheet_in(result, sheet)
    validate_vault(result)
    return result


def census_was_reset(previous: dict, current: dict) -> bool:
    return previous.get('reset_generation', '') != current.get('reset_generation', '')
