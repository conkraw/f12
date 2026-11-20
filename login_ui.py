"""Centered password entry using the app's existing authentication callback.

The login page has no external assets or requests. Styles that affect the
page or sidebar require the login marker, which disappears after sign in.
Password verification, throttling and session lifetime remain in app.py.
"""
from __future__ import annotations

from typing import Callable


LOGIN_STYLES = """
<style>
.stApp:has(#picu-login-marker) {
    background: radial-gradient(ellipse at 50% 15%, #e7f1f3 0, #f5f8fa 48%, #fafcfd 100%);
}
.stApp:has(#picu-login-marker) [data-testid="stSidebar"],
.stApp:has(#picu-login-marker) [data-testid="stSidebarCollapsedControl"] {
    display: none;
}
.stApp:has(#picu-login-marker) [data-testid="stHeader"] {
    background: transparent;
}
.stApp:has(#picu-login-marker) [data-testid="stMainBlockContainer"] {
    max-width: 100%;
    padding: clamp(2rem, 11vh, 7rem) 1.25rem 3rem;
}
.st-key-picu_login_card {
    width: 100%;
    max-width: 460px;
    margin: 0 auto;
    padding: 2.35rem 2.2rem 1.85rem;
    border: 1px solid #dce7eb;
    border-top: 4px solid #176b72;
    border-radius: 19px;
    background: #ffffff;
    box-shadow: 0 18px 55px rgba(24, 60, 80, .08), 0 2px 8px rgba(24, 60, 80, .025);
}
.picu-login-heading {
    text-align: center;
    margin-bottom: .55rem;
}
.picu-login-symbol {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 58px;
    height: 58px;
    margin: 0 auto 1.25rem;
    border: 1px solid #c7dfe2;
    border-radius: 17px;
    color: #176b72;
    background: #edf6f6;
}
.picu-login-kicker {
    color: #176b72;
    font-size: .7rem;
    font-weight: 750;
    letter-spacing: .14em;
    line-height: 1.5;
    margin: 0 0 .65rem;
}
.picu-login-heading h1 {
    margin: 0;
    padding: 0;
    color: #183c50;
    font-size: 2.05rem;
    font-weight: 750;
    line-height: 1.2;
    letter-spacing: -.04em;
}
.picu-login-heading p {
    color: #5b7180;
    font-size: .93rem;
    line-height: 1.55;
    margin: .75rem 0 0;
}
.st-key-picu_login_card [data-testid="stForm"] {
    padding: .75rem 0 0;
    border: 0;
    background: transparent;
}
.st-key-picu_login_card [data-testid="stTextInput"] label {
    color: #183c50;
    font-weight: 600;
}
.st-key-picu_login_card [data-testid="stTextInput"] [data-baseweb="input"] {
    min-height: 47px;
    border-color: #cddde3;
    border-radius: 10px;
    background: #fbfdfe;
}
.st-key-picu_login_card [data-testid="stTextInput"] input {
    color: #183c50;
    background: transparent;
}
.st-key-picu_login_card [data-testid="stTextInput"] input::placeholder {
    color: #7c8c98;
}
.st-key-picu_login_card [data-testid="stFormSubmitButton"] button {
    min-height: 47px;
    margin-top: .25rem;
    border: 1px solid #176b72;
    border-radius: 10px;
    color: #ffffff;
    background: #176b72;
    font-size: .95rem;
    font-weight: 650;
}
.st-key-picu_login_card [data-testid="stFormSubmitButton"] button:hover {
    border-color: #105960;
    background: #105960;
}
.st-key-picu_login_card button:focus-visible,
.st-key-picu_login_card input:focus-visible {
    outline: 3px solid #8bb9c0;
    outline-offset: 3px;
}
.st-key-picu_login_card [data-testid="stAlert"] {
    border-radius: 10px;
    font-size: .9rem;
}
.picu-login-footnote {
    margin: .2rem 0 0;
    color: #6a7f8d;
    font-size: .78rem;
    line-height: 1.5;
    text-align: center;
}
@media (max-width: 600px) {
    .stApp:has(#picu-login-marker) [data-testid="stMainBlockContainer"] {
        padding: 2.25rem 1rem 2rem;
    }
    .st-key-picu_login_card {
        padding: 1.85rem 1.4rem 1.5rem;
        border-radius: 15px;
    }
    .picu-login-heading h1 { font-size: 1.8rem; }
}
</style>
"""

LOGIN_HEADING = """
<div class="picu-login-heading">
    <div class="picu-login-symbol" aria-hidden="true">
        <svg width="33" height="33" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M5 21h7l4-10 7 19 4-9h8" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
    </div>
    <div class="picu-login-kicker">PEDIATRIC CRITICAL CARE</div>
    <h1>PICU Handoff</h1>
    <p>Your rounds and signout workspace.</p>
</div>
"""


def render_login(st, encoded: str, authenticate: Callable[[str], None]) -> None:
    """Render the password form without changing existing authentication rules.

    Call only when unauthenticated. Streamlit runs ``authenticate`` before
    rerunning the app, so a successful sign in removes this entire view.
    A form also preserves Enter-to-submit and avoids reruns while typing.
    """
    st.markdown(LOGIN_STYLES + '<div id="picu-login-marker" aria-hidden="true"></div>',
                unsafe_allow_html=True)
    with st.container(key="picu_login_card"):
        st.markdown(LOGIN_HEADING, unsafe_allow_html=True)
        with st.form("login", clear_on_submit=True, border=False):
            st.text_input("Password", type="password", key="login_password",
                          max_chars=1024, placeholder="Enter your password",
                          autocomplete="current-password")
            st.form_submit_button("Sign in", type="primary", width="stretch",
                                  on_click=authenticate, args=(encoded,))
        if st.session_state.get("login_error"):
            st.error(st.session_state["login_error"])
        st.markdown('<p class="picu-login-footnote">For the PICU care team</p>',
                    unsafe_allow_html=True)
