"""Real Streamlit form checks with the existing PICU authentication callback."""
from pathlib import Path
import time

import pytest

from security import hash_password


TEST_PASSWORD = "synthetic-picu-login-password"
TEST_HASH = hash_password(TEST_PASSWORD)


def user_state(at):
    state = at.session_state
    to_dict = getattr(state, "to_dict", None)
    return to_dict() if callable(to_dict) else state.filtered_state


@pytest.fixture
def login_app():
    # Keep browser lifecycle testing optional for minimal parser-only installs.
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    source = f'''
import sys
sys.path.insert(0, {str(Path(__file__).parents[1])!r})
import streamlit as st
from app import authenticate, clear_session
from login_ui import render_login

if st.session_state.get("authenticated"):
    st.success("Patient list ready")
    with st.sidebar:
        st.caption("Workspace")
        st.button("Log out", on_click=clear_session)
else:
    render_login(st, {TEST_HASH!r}, authenticate)
'''
    result = AppTest.from_string(source, default_timeout=15).run()
    assert not result.exception
    return result


def test_sign_in_and_logout_remove_password_and_login_page(login_app):
    at = login_app
    assert at.text_input[0].label == "Password"
    assert at.text_input[0].proto.type == at.text_input[0].proto.PASSWORD
    assert at.button[0].label == "Sign in"
    assert not user_state(at).get("authenticated")
    assert "vault" not in user_state(at)

    at.text_input[0].set_value(TEST_PASSWORD)
    at.button[0].click().run()
    assert not at.exception
    assert user_state(at)["authenticated"] is True
    assert "login_password" not in user_state(at)
    assert "login_error" not in user_state(at)
    assert at.success[0].value == "Patient list ready"
    assert not any("picu-login-marker" in item.value for item in at.markdown)

    at.sidebar.button[0].click().run()
    assert not at.exception
    assert not user_state(at).get("authenticated")
    assert at.text_input[0].value == ""
    assert not at.success


def test_failed_password_and_cooldown_cannot_open_patient_workspace(login_app):
    at = login_app
    at.text_input[0].set_value("incorrect-synthetic-password")
    at.button[0].click().run()
    assert not at.exception
    assert not user_state(at).get("authenticated")
    assert user_state(at)["attempts"] == 1
    assert at.text_input[0].value == ""
    assert at.error[0].value == "Password not accepted. Wait briefly before trying again."

    # A correct password during the existing cooldown must still be blocked.
    at.session_state["retry_after"] = time.monotonic() + 60
    at.text_input[0].set_value(TEST_PASSWORD)
    at.button[0].click().run()
    assert not at.exception
    assert not user_state(at).get("authenticated")
    assert at.text_input[0].value == ""
    assert not at.success

    # Simulate expiration without a blocking wait or changing production logic.
    at.session_state["retry_after"] = 0
    at.text_input[0].set_value(TEST_PASSWORD)
    at.button[0].click().run()
    assert not at.exception
    assert user_state(at)["authenticated"] is True
    assert "attempts" not in user_state(at)
    assert "retry_after" not in user_state(at)
    assert "login_password" not in user_state(at)
