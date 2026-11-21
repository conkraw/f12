"""Synthetic runtime-readiness and handoff-preservation regressions."""
from copy import deepcopy

import pytest

import noninvasive
from models import new_sheet, new_vault, save_sheet_in
from test_callbacks import app, open_room
from test_ui_smoke import equip


PRVC = "Volume Targeted Pressure Control - Intermittent Mandatory Ventilation"
NAVA = "Neurally Adjusted Ventilatory Assist"
PS_CPAP = "Pressure Support - Continuous Positive Airway Pressure"


def block(letter, text):
    marker = letter * 24
    return marker + "\n" + text.rstrip() + "\n" + marker + "\n"


def synthetic_source(mixed=True):
    settings = f"""Invasive Ventilation:
Mode: Vent Mode: {PRVC}
Respiratory Rate: Resp Rate (Set): 18
Set TV: Vt (Set, mL): 90 mL
Set PEEP: PEEP (cm H2O): 5 cm H2O
FiO2: FiO2 set (%): 46 %
Pressure Support: Pressure Support (cm H2O): 10 cm H20
NAVA Ventilator Settings:
NAVA Level: NAVA level: 2.5
Set PEEP: PEEP (cm H2O): 6 cm H2O
Set FIO2: FiO2 (%): 29 %
CPAP Trial Settings:
Pressure Support: Pressure Support (cm H2O): 8 cm H20
Set PEEP: PEEP (cm H2O): 7 cm H2O
FiO2: FiO2 set (%): 41 %
All Vent Modes:
Vent Mode: {PRVC} (11/20/26 0600 : SYNTHETIC_AUTHOR, RRT)
Vent Mode: {PRVC} (11/20/26 1800 : SYNTHETIC_AUTHOR, RRT)
Vent Mode: {PRVC} (11/20/26 1600 : SYNTHETIC_AUTHOR, RRT)
"""
    if mixed:
        settings += (
            f"Vent Mode: {NAVA} (11/20/26 1300 : SYNTHETIC_AUTHOR, RRT)\n"
            f"Vent Mode: {PS_CPAP} (11/20/26 1500 : SYNTHETIC_AUTHOR, RRT)\n"
            f"Vent Mode: {NAVA} (11/20/26 1200 : SYNTHETIC_AUTHOR, RRT)\n"
        )
    return (
        block("a", "Diagnoses:\n1. SYNTHETIC_NEW_RECORD")
        + block("c", settings)
        + block("d", "Non-invasive Ventilation:\nO2 Delivery Method: Endotracheal tube\nFiO2 (%): 21 %")
    )


def prepare_saved_room(app):
    ss = app.st.session_state
    old = new_sheet("P4102")
    old["fields"]["Diagnoses"] = "SYNTHETIC_PREVIOUS_RECORD"
    other = new_sheet("P4104")
    other["fields"]["Diagnoses"] = "SYNTHETIC_OTHER_ROOM"
    ss["vault"] = save_sheet_in(save_sheet_in(new_vault(), old), other)
    open_room(app)
    ss["paste"] = synthetic_source()
    return ss


class NoArchiveAccess:
    def __init__(self):
        self.loads = 0
        self.writes = 0

    def load(self):
        self.loads += 1
        raise AssertionError("The incomplete update must not open the archive")

    def save(self, candidate, sha):
        self.writes += 1
        raise AssertionError("The incomplete update must not write the archive")


def main_setup(app, monkeypatch, store):
    equip(app, monkeypatch)
    monkeypatch.setattr(app, "load_config", lambda: ({"idle_minutes": 15, "password_hash": "synthetic"}, store))
    monkeypatch.setattr(app, "idle_guard", lambda minutes: None)


def test_bundled_runtime_passes_without_mutating_user_session(app):
    ss = app.st.session_state
    ss["paste"] = "SYNTHETIC_USER_PASTE_MUST_NOT_BE_READ_BY_CHECK"
    before = deepcopy(ss)
    assert app.respiratory_parser_ready() is True
    assert ss == before


def test_check_rejects_unscoped_legacy_selector_used_by_respiratory_reader(app, monkeypatch):
    monkeypatch.setattr(noninvasive, "select_ventilation_source", lambda source: source)
    assert app.respiratory_parser_ready() is False


def test_check_suppresses_exception_details_and_returns_false(app, monkeypatch, capsys, caplog):
    def broken_import(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_PRIVATE_EXCEPTION_DETAIL")

    monkeypatch.setattr(app, "import_replacement", broken_import)
    assert app.respiratory_parser_ready() is False
    captured = capsys.readouterr()
    assert "SYNTHETIC_PRIVATE_EXCEPTION_DETAIL" not in captured.out + captured.err + caplog.text
    assert "SYNTHETIC_PRIVATE_EXCEPTION_DETAIL" not in repr(app.st.session_state)


def test_failed_runtime_check_preserves_paste_drafts_and_archive_without_write(app, monkeypatch):
    ss = prepare_saved_room(app)
    before = {key: deepcopy(ss[key]) for key in ("paste", "vault", "drafts", "base_sheets")}
    store = NoArchiveAccess()
    monkeypatch.setattr(noninvasive, "select_ventilation_source", lambda source: source)

    app.create_handoff(store)

    for key, value in before.items():
        assert ss[key] == value
    assert store.loads == 0 and store.writes == 0
    assert ss["notice"][0] == "error"
    assert "respiratory update is incomplete" in ss["notice"][1].casefold()
    assert "SYNTHETIC_AUTHOR" not in ss["notice"][1]
    assert "pending_error_events" not in ss


@pytest.mark.parametrize("mixed", [True, False], ids=["multiple-modes", "repeated-same-mode"])
def test_current_runtime_imports_full_source_without_repeated_field_conflict(app, mixed):
    ss = prepare_saved_room(app)
    other_before = deepcopy(ss["vault"]["rooms"]["P4104"])
    ss["paste"] = synthetic_source(mixed)

    app.create_handoff()

    assert ss["paste"] == ""
    assert not ss["import_result"]["errors"]
    saved = ss["vault"]["rooms"]["P4102"]
    assert saved == ss["drafts"]["P4102"]
    assert saved["fields"]["Diagnoses"] == "SYNTHETIC_NEW_RECORD"
    assert saved["ventilation"]["mode"] == PRVC
    assert saved["ventilation"]["values"]["FiO2 set (%)"] == "46 %"
    assert saved["ventilation"]["values"]["Vt (Set, mL)"] == "90 mL"
    history = saved["ventilation"]["mode_history"]
    assert history["reported_at"] == "2026-11-20T18:00"
    assert history["latest_confirmed"] is True
    if mixed:
        entries = history["other_modes"]
        assert [item["mode"] for item in entries] == [PS_CPAP, NAVA]
        assert entries[0]["values"]["FiO2 set (%)"] == "41 %"
        assert entries[1]["values"]["FiO2 (%)"] == "29 %"
    else:
        assert history["other_modes"] == []
    assert ss["vault"]["rooms"]["P4104"] == other_before


def test_startup_stops_incomplete_update_before_opening_archive(app, monkeypatch):
    store = NoArchiveAccess()
    main_setup(app, monkeypatch, store)
    ss = app.st.session_state
    ss.pop("vault", None)
    errors = []
    app.st.error = lambda value, *args, **kwargs: errors.append(str(value))
    monkeypatch.setattr(app, "respiratory_parser_ready", lambda: False)

    app.main()

    assert store.loads == 0 and store.writes == 0
    assert "vault" not in ss
    assert any("respiratory update is incomplete" in message.casefold() for message in errors)


def test_startup_shows_functional_ready_status_in_sidebar(app, monkeypatch):
    main_setup(app, monkeypatch, None)
    captions = []
    app.st.caption = lambda value, *args, **kwargs: captions.append(str(value))
    monkeypatch.setattr(app, "patient_list_startup", lambda store: True)
    monkeypatch.setattr(app, "handoff_page", lambda store: None)

    app.main()

    assert "Respiratory mode-history parser: ready" in captions


@pytest.mark.parametrize("guard", ["session", "room", "concurrent-change"])
def test_existing_import_guards_run_before_runtime_check(app, monkeypatch, guard):
    ss = prepare_saved_room(app)
    if guard == "session":
        ss["authenticated"] = False
    elif guard == "room":
        ss.pop("current_room", None)
    else:
        changed = deepcopy(ss["vault"]["rooms"]["P4102"])
        changed["fields"]["Diagnoses"] = "SYNTHETIC_CONCURRENT_CHANGE"
        ss["vault"] = save_sheet_in(ss["vault"], changed)

    def must_not_check():
        raise AssertionError("Existing guard must return before readiness check")

    monkeypatch.setattr(app, "respiratory_parser_ready", must_not_check)
    app.create_handoff()


def test_unauthenticated_startup_does_not_run_parser_check(app, monkeypatch):
    store = NoArchiveAccess()
    main_setup(app, monkeypatch, store)
    app.st.session_state["authenticated"] = False
    logins = []
    monkeypatch.setattr(app, "render_login", lambda *args: logins.append(True))

    def must_not_check():
        raise AssertionError("Parser check must follow authentication")

    monkeypatch.setattr(app, "respiratory_parser_ready", must_not_check)
    app.main()

    assert logins == [True]
    assert store.loads == 0 and store.writes == 0

