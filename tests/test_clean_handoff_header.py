"""v6.50 header regression checks. UI uses stubs, not a live browser."""
from copy import deepcopy
import inspect

import pytest
from test_callbacks import app, open_room
from test_ui_smoke import equip
from test_user_guide_admin import remote_store, prepare_editor
from user_guide import default_guide


@pytest.mark.parametrize('room', [None, 'P4102', 'P4301'])
@pytest.mark.parametrize('guide_state', ['published', 'unpublished', 'undated'])
def test_removed_header_controls_all_guide_and_room_states(app, monkeypatch, room, guide_state):
    equip(app, monkeypatch)
    if room:
        open_room(app, room)
        app.save_room(None)
    guide = default_guide()
    guide['instructions'] = 'SHORT_INSTRUCTIONS_STAY'
    if guide_state != 'unpublished':
        guide['smartphrase_text'] = 'SOURCE_ONLY_IN_ADMIN'
    if guide_state == 'published':
        guide['updated_at'] = '2026-11-09T16:20:44+00:00'
    app.st.session_state['user_guide'] = guide
    before = deepcopy({key: app.st.session_state[key] for key in ('vault', 'drafts', 'base_sheets', 'user_guide')})
    captions, buttons, markdown = [], [], []
    app.st.caption = lambda value, *a, **kw: captions.append(str(value))
    app.st.button = lambda label, *a, **kw: buttons.append(str(label)) or False
    app.st.markdown = lambda value, *a, **kw: markdown.append(str(value))
    def forbidden(*args, **kwargs):
        raise AssertionError('Removed publication/source UI must not be invoked')
    monkeypatch.setattr(app, 'smartphrase_publish_caption', forbidden)
    monkeypatch.setattr(app, 'render_smartphrase', forbidden)
    app.handoff_page(None)
    assert 'SHORT_INSTRUCTIONS_STAY' in markdown
    assert not any(text.startswith(('SmartPhrase published:', 'SmartPhrase saved in this session only:', 'SmartPhrase:')) for text in captions)
    assert 'Refresh SmartPhrase publication' not in buttons
    assert 'refresh_handoff_guide' not in inspect.getsource(app.handoff_page)
    assert not any('SOURCE_ONLY_IN_ADMIN' in text for text in markdown)
    for key, value in before.items():
        assert app.st.session_state[key] == value
    if room:
        assert 'Save handoff' in buttons
        assert any('Last saved' in caption for caption in captions)


def test_admin_keeps_publication_metadata_and_source_editor(app, monkeypatch):
    equip(app, monkeypatch)
    guide = default_guide()
    guide.update(smartphrase_text='KEEP_ADMIN_SOURCE', updated_at='2026-11-09T16:20:44+00:00')
    app.st.session_state['user_guide'] = guide
    before = deepcopy(guide)
    captions, labels = [], []
    app.st.caption = lambda text, **kw: captions.append(text)
    app.st.form_submit_button = lambda label, **kw: labels.append(label) or False
    app.guide_admin(None)
    assert app.st.session_state['guide_edit_smartphrase_text'] == 'KEEP_ADMIN_SOURCE'
    assert any('11/09/2026' in text for text in captions)
    assert 'Save instructions and SmartPhrase' in labels
    assert app.st.session_state['user_guide'] == before


def test_publication_success_does_not_reference_removed_button(app):
    store, remote = remote_store()
    prepare_editor(app, store)
    before = deepcopy(app.st.session_state['vault'])
    app.save_user_guide(store)
    assert app.st.session_state['notice'][0] == 'success'
    message = str(app.st.session_state['notice'])
    assert 'Refresh SmartPhrase publication' not in message
    assert app.st.session_state['user_guide']['updated_at']
    assert app.st.session_state['vault'] == before
    assert any(method == 'PUT' for method, _, _ in remote.calls)


def test_automatic_guide_loading_remains_on_handoff(app, monkeypatch):
    equip(app, monkeypatch)
    app.st.session_state['handoff_guide_checked'] = 0
    called = []
    def load(store, refresh=False):
        called.append(refresh)
        return default_guide()
    monkeypatch.setattr(app, 'load_user_guide', load)
    app.handoff_page(object())
    assert called == [True]
    assert app.st.session_state['handoff_guide_checked'] > 0
