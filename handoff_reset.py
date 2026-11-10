"""One atomic census reset. Clinical records and rules are never confused.

No network access here. The caller must commit successfully before clearing its
session. A durable generation prevents an old tab from restoring cleared drafts
when it reloads a newer archive. It is not a physical purge of Git history.
"""
from __future__ import annotations
from copy import deepcopy
import uuid
from models import DEFAULT_ROOMS, validate_vault


def cleared_vault(vault: dict) -> dict:
    validate_vault(vault)
    result = deepcopy(vault)
    result['rooms'] = {}
    result['settings']['rooms'] = list(DEFAULT_ROOMS)
    result['reset_generation'] = uuid.uuid4().hex
    validate_vault(result)
    return result


def census_was_reset(previous: dict, current: dict) -> bool:
    return previous.get('reset_generation', '') != current.get('reset_generation', '')
