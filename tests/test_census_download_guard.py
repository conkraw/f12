"""Synthetic lazy-download checks around concurrent patient-list resets."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import traceback

import pytest

import census_guard
from census_guard import guard_download


class Store:
    def __init__(self, generation="original"):
        self.generation = generation
        self.sha = "sha-before"
        self.loads = 0
        self.fail_on = None
        self.after_load = None

    def load(self):
        self.loads += 1
        if self.fail_on == self.loads:
            raise RuntimeError("SENSITIVE_SOURCE_SENTINEL token=PRIVATE_TOKEN_SENTINEL")
        result = ({"reset_generation": self.generation, "rooms": {}}, self.sha)
        if self.after_load:
            self.after_load(self.loads)
        return result

    def save(self, *args, **kwargs):
        raise AssertionError("The download guard must never write shared storage")


def test_reset_before_generation_rejects_without_rendering_and_revokes():
    store = Store("new-list")
    revoked = Event()
    called = []
    generate = guard_download(lambda: called.append(True), store, "original", cancelled=revoked)
    with pytest.raises(ValueError, match="Reload.*prepare a new download"):
        generate()
    assert called == [] and store.loads == 1 and revoked.is_set()


def test_reset_during_generation_rejects_bytes_after_rendering():
    store = Store()
    started, release, revoked = Event(), Event(), Event()

    def render():
        started.set()
        assert release.wait(5), "Test worker did not receive release"
        return b"synthetic-pdf-bytes"

    generate = guard_download(render, store, "original", cancelled=revoked)
    with ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(generate)
        try:
            assert started.wait(5), "Test worker did not begin rendering"
            store.generation = "new-list"
        finally:
            release.set()
        with pytest.raises(ValueError, match="patient list changed"):
            future.result(timeout=5)
    assert store.loads == 2 and revoked.is_set()


def test_normal_save_with_new_sha_and_same_generation_is_allowed():
    store = Store()

    def render():
        store.sha = "sha-after-an-unrelated-normal-save"
        return b"synthetic-pdf-bytes"

    assert guard_download(render, store, "original")() == b"synthetic-pdf-bytes"
    assert store.loads == 2


def test_legacy_empty_generation_is_valid_when_unchanged():
    store = Store("")
    assert guard_download(lambda: b"synthetic", store, "")() == b"synthetic"
    assert store.loads == 2


@pytest.mark.parametrize("fail_on", [1, 2])
def test_network_failure_fails_closed_without_sensitive_exception_details(fail_on):
    store = Store()
    store.fail_on = fail_on
    called = []

    def render():
        called.append(True)
        return b"synthetic-pdf-bytes"

    with pytest.raises(ValueError, match="could not be verified") as error:
        guard_download(render, store, "original")()
    shown = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert "SENSITIVE_SOURCE_SENTINEL" not in str(error.value)
    assert "PRIVATE_TOKEN_SENTINEL" not in str(error.value)
    assert "SENSITIVE_SOURCE_SENTINEL" not in shown
    assert "PRIVATE_TOKEN_SENTINEL" not in shown
    assert "RuntimeError:" not in shown
    assert error.value.__suppress_context__
    assert len(called) == fail_on - 1
    assert store.loads == fail_on


def test_cancelled_event_before_generation_skips_render_and_network():
    store, revoked = Store(), Event()
    revoked.set()
    called = []
    with pytest.raises(ValueError, match="cleared"):
        guard_download(lambda: called.append(True), store, "original", cancelled=revoked)()
    assert called == [] and store.loads == 0


def test_cancelled_event_during_generation_rejects_result():
    store, revoked = Store(), Event()

    def render():
        revoked.set()
        return b"synthetic-pdf-bytes"

    with pytest.raises(ValueError, match="cleared"):
        guard_download(render, store, "original", cancelled=revoked)()
    assert store.loads == 1


@pytest.mark.parametrize("cancel_on_load", [1, 2])
def test_cancel_during_storage_read_is_checked_before_render_or_release(cancel_on_load):
    store, revoked, called = Store(), Event(), []
    store.after_load = lambda call: revoked.set() if call == cancel_on_load else None
    with pytest.raises(ValueError, match="cleared"):
        guard_download(lambda: called.append(True) or b"synthetic", store, "original", cancelled=revoked)()
    assert len(called) == cancel_on_load - 1
    assert store.loads == cancel_on_load


def test_expired_download_does_not_render_or_read_storage(monkeypatch):
    store, called = Store(), []
    monkeypatch.setattr(census_guard.time, "monotonic", lambda: 100.0)
    with pytest.raises(ValueError, match="expired"):
        guard_download(lambda: called.append(True), store, "original", expires_at=100.0)()
    assert called == [] and store.loads == 0


def test_expiry_during_generation_rejects_bytes(monkeypatch):
    store, clock = Store(), [99.0]
    monkeypatch.setattr(census_guard.time, "monotonic", lambda: clock[0])

    def render():
        clock[0] = 100.0
        return b"synthetic-pdf-bytes"

    with pytest.raises(ValueError, match="expired"):
        guard_download(render, store, "original", expires_at=100.0)()
    assert store.loads == 1


@pytest.mark.parametrize("expire_on_load", [1, 2])
def test_expiry_during_shared_read_is_checked_before_render_or_release(monkeypatch, expire_on_load):
    store, clock, called = Store(), [99.0], []
    monkeypatch.setattr(census_guard.time, "monotonic", lambda: clock[0])

    def after_load(call):
        if call == expire_on_load:
            clock[0] = 100.0

    store.after_load = after_load
    with pytest.raises(ValueError, match="expired"):
        guard_download(lambda: called.append(True) or b"synthetic", store, "original", expires_at=100.0)()
    assert len(called) == expire_on_load - 1


@pytest.mark.parametrize("response", [None, ({}, "sha"), ({"reset_generation": None}, "sha"), ({"reset_generation": 1}, "sha")])
def test_malformed_storage_response_fails_closed(response):
    class BrokenStore(Store):
        def load(self):
            return response

    called = []
    with pytest.raises(ValueError, match="could not be verified"):
        guard_download(lambda: called.append(True), BrokenStore(), "original")()
    assert called == []


def test_session_only_returns_original_value_without_shared_storage():
    value = b"synthetic-pdf-bytes"
    assert guard_download(lambda: value, None, "")() is value


def test_session_only_still_blocks_local_cancel_after_generation():
    revoked = Event()

    def render():
        revoked.set()
        return b"synthetic-pdf-bytes"

    with pytest.raises(ValueError, match="cleared"):
        guard_download(render, None, "", cancelled=revoked)()


def test_each_click_rechecks_shared_generation_without_writes():
    store = Store()
    generate = guard_download(lambda: b"synthetic", store, "original")
    assert generate() == b"synthetic"
    store.generation = "changed-after-first-click"
    with pytest.raises(ValueError, match="patient list changed"):
        generate()
    assert store.loads == 3
