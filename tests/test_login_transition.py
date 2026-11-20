"""Real app login transitions, observed before archive loading completes.

Final AppTest trees cannot expose an intermediate unstyled password form.
Capture actual Streamlit messages and inspect them at the archive-load entry
point, before that load returns or raises. All credentials and data are synthetic.
"""
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import time
import uuid

import pytest

from github_store import StorageError
from models import new_vault
from security import hash_password


PASSWORD = "synthetic-login-transition-password"
PASSWORD_HASH = hash_password(PASSWORD)
ROOT = Path(__file__).parents[1]


def element_type(message):
    if message.delta.WhichOneof("type") != "new_element":
        return ""
    return message.delta.new_element.WhichOneof("type")


def delta_path(message):
    return tuple(message.metadata.delta_path)


def state_values(at):
    to_dict = getattr(at.session_state, "to_dict", None)
    return to_dict() if callable(to_dict) else at.session_state.filtered_state


def login_paths(messages):
    """Find the styled login's essential elements without a DOM snapshot."""
    paths = {}
    for message in messages:
        kind = element_type(message)
        element = message.delta.new_element
        if kind == "markdown":
            if 'id="picu-login-marker"' in element.markdown.body:
                paths["styles_and_marker"] = delta_path(message)
            if 'class="picu-login-heading"' in element.markdown.body:
                paths["heading"] = delta_path(message)
        elif kind == "text_input" and element.text_input.label == "Password":
            paths["password"] = delta_path(message)
        elif kind == "button" and element.button.label == "Sign in":
            paths["submit"] = delta_path(message)
    assert set(paths) == {"styles_and_marker", "heading", "password", "submit"}
    return paths


def assert_login_uses_one_clearable_subtree(messages):
    assert messages and element_type(messages[0]) == "empty"
    root = delta_path(messages[0])
    paths = login_paths(messages)
    assert all(path[:len(root)] == root and len(path) > len(root)
               for path in paths.values())
    return root, paths


@pytest.fixture
def transition_app(monkeypatch):
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext

    observed = SimpleNamespace(messages=[], load_observations=[], fail_load=False,
                               login_root=None, prior_login_paths={})
    original_enqueue = ScriptRunContext.enqueue

    def record_message(context, message):
        if message.HasField("delta"):
            copied = ForwardMsg()
            copied.CopyFrom(message)
            observed.messages.append(copied)
        return original_enqueue(context, message)

    monkeypatch.setattr(ScriptRunContext, "enqueue", record_message)

    class Store:
        def load(self):
            # This is the point where a real network request may stall. The
            # first main-view delta must already have removed every prior
            # login element, including its style/marker and password field.
            messages = tuple(observed.messages)
            assert messages and element_type(messages[0]) == "empty"
            cleared_root = delta_path(messages[0])
            assert cleared_root == observed.login_root
            assert all(path[:len(cleared_root)] == cleared_root
                       for path in observed.prior_login_paths.values())
            assert not any(element_type(message) == "text_input"
                           for message in messages)
            observed.load_observations.append(messages)
            if observed.fail_load:
                raise StorageError("Synthetic archive load failure.")
            return new_vault(), None

    support_name = "picu_login_transition_support_" + uuid.uuid4().hex
    support = ModuleType(support_name)
    support.config = {"password_hash": PASSWORD_HASH, "idle_minutes": 15}
    support.store = Store()
    monkeypatch.setitem(sys.modules, support_name, support)
    source = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
import app as picu
import {support_name} as support

def ready(store):
    st.success("Synthetic patient list ready")
    st.button("Log out", on_click=picu.clear_session)
    return False

previous_config = picu.load_config
previous_startup = picu.patient_list_startup
try:
    picu.load_config = lambda: (support.config, support.store)
    picu.patient_list_startup = ready
    picu.main()
finally:
    picu.load_config = previous_config
    picu.patient_list_startup = previous_startup
'''
    at = AppTest.from_string(source, default_timeout=15).run()
    assert not at.exception
    observed.login_root, observed.prior_login_paths = (
        assert_login_uses_one_clearable_subtree(observed.messages))
    assert not observed.load_observations
    observed.messages.clear()
    return at, observed


def sign_in(at):
    at.text_input[0].set_value(PASSWORD)
    next(button for button in at.button if button.label == "Sign in").click().run()
    assert not at.exception


@pytest.mark.parametrize("load_fails", [False, True])
def test_login_is_removed_before_archive_load_returns_or_raises(transition_app, load_fails):
    at, observed = transition_app
    observed.fail_load = load_fails
    sign_in(at)

    assert len(observed.load_observations) == 1
    assert state_values(at)["authenticated"] is True
    assert "login_password" not in state_values(at)
    assert not at.text_input
    assert not any('id="picu-login-marker"' in item.value for item in at.markdown)
    if load_fails:
        assert at.error[0].value == "Synthetic archive load failure."
        assert "vault" not in state_values(at)
    else:
        assert at.success[0].value == "Synthetic patient list ready"
        assert "vault" in state_values(at)


@pytest.mark.parametrize("return_reason", ["logout", "expiry"])
def test_actual_main_restores_styled_login_after_logout_or_expiry(transition_app, return_reason):
    at, observed = transition_app
    sign_in(at)
    observed.messages.clear()

    if return_reason == "logout":
        next(button for button in at.button if button.label == "Log out").click().run()
    else:
        at.session_state["last_activity"] = time.monotonic() - 16 * 60
        at.run()

    assert not at.exception
    assert not state_values(at).get("authenticated")
    assert "vault" not in state_values(at)
    assert at.text_input[0].value == ""
    root, paths = assert_login_uses_one_clearable_subtree(observed.messages)
    assert root == observed.login_root
    assert paths["password"][:len(root)] == root
    assert len(observed.load_observations) == 1

