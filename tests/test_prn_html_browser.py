"""Run the downloaded HTML PRN refresh script in Node with a small DOM stub."""
from datetime import datetime
import json
import os
import shutil
import subprocess

import pytest

from prn_html import PRN_PRINT_SCRIPT


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required to run the HTML script")


NODE_HARNESS = r"""
const fs = require('node:fs')
const vm = require('node:vm')
const input = JSON.parse(fs.readFileSync(0, 'utf8'))
const RealDate = Date
let currentTime = RealDate.parse(input.now)
const listeners = {window: {}, document: {}}
const intervals = []
const nodes = input.payloads.map((payload, index) => {
  let content = input.initial[index]
  return {
    getAttribute(name) {
      if (name !== 'data-prn-count') throw new Error('Unexpected attribute access')
      return payload
    },
    get textContent() { return content },
    set textContent(value) { content = String(value) },
    get innerHTML() { throw new Error('PRN refresh must not read innerHTML') },
    set innerHTML(value) { throw new Error('PRN refresh must not write innerHTML') }
  }
})
class FrozenDate extends RealDate {
  constructor(...args) { super(...(args.length ? args : [currentTime])) }
  static now() { return currentTime }
}
function subscribe(target, name, handler) {
  if (!listeners[target][name]) listeners[target][name] = []
  listeners[target][name].push(handler)
}
function schedule(handler, delay) {
  intervals.push({handler, delay})
  return intervals.length
}
const document = {
  hidden: false,
  querySelectorAll(selector) {
    if (selector !== '[data-prn-count]') throw new Error('Unexpected DOM selector')
    return nodes
  },
  addEventListener(name, handler) { subscribe('document', name, handler) }
}
const window = {
  addEventListener(name, handler) { subscribe('window', name, handler) },
  setInterval: schedule
}
const context = vm.createContext({window, document, Date: FrozenDate, Intl,
  JSON, Math, Number, String, Array, Object, setInterval: schedule})
vm.runInContext(input.script, context, {timeout: 2000})
const snapshots = [nodes.map(node => node.textContent)]
for (const step of input.steps) {
  currentTime = RealDate.parse(step.now)
  document.hidden = !!step.hidden
  if (step.event === 'interval') {
    intervals.forEach(entry => entry.handler())
  } else {
    const target = step.event === 'visibilitychange' ? 'document' : 'window'
    if (!listeners[target][step.event]) throw new Error('Expected event is not registered: ' + step.event)
    listeners[target][step.event].forEach(handler => handler())
  }
  snapshots.push(nodes.map(node => node.textContent))
}
process.stdout.write(JSON.stringify({snapshots, intervals: intervals.map(entry => entry.delay),
  windowEvents: Object.keys(listeners.window), documentEvents: Object.keys(listeners.document)}))
"""


def millis(value):
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def payload(events):
    return {
        "version": 2,
        "events": [[millis(stamp), doses] for stamp, doses in events],
    }


def run_script(payloads, *, now, steps, initial=None, host_tz="UTC"):
    script = PRN_PRINT_SCRIPT.strip()
    assert script.startswith("<script>") and script.endswith("</script>")
    request = {
        "script": script[len("<script>"):-len("</script>")],
        "payloads": [item if isinstance(item, str) else json.dumps(item) for item in payloads],
        "initial": initial or [" × 99"] * len(payloads),
        "now": now,
        "steps": steps,
    }
    result = subprocess.run(
        [NODE, "-e", NODE_HARNESS], input=json.dumps(request), capture_output=True,
        text=True, check=True, timeout=10, env={**os.environ, "TZ": host_tz},
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("host_tz", ["UTC", "America/Los_Angeles", "Asia/Tokyo"])
def test_4am_print_uses_previous_7am_and_inclusive_cutoff(host_tz):
    data = payload([
        ("2026-11-21T06:59:59-05:00", 100),
        ("2026-11-21T07:00:00-05:00", 1),
        ("2026-11-21T23:55:00-05:00", 2),
        ("2026-11-22T03:59:00-05:00", 1),
        ("2026-11-22T04:00:00-05:00", 1),
        ("2026-11-22T04:00:01-05:00", 50),
    ])
    result = run_script([data], now="2026-11-22T04:00:00-05:00", host_tz=host_tz,
                        steps=[{"now": "2026-11-22T04:00:00-05:00", "event": "beforeprint"}])
    assert result["snapshots"] == [[" × 99"], [" × 5"]]


def test_script_preserves_initial_server_clock_and_registers_refreshes():
    result = run_script([payload([])], now="2027-01-01T12:00:00Z", steps=[], initial=[" × 0"])
    assert result["snapshots"] == [[" × 0"]]
    assert set(result["windowEvents"]) >= {"beforeprint", "focus"}
    assert "visibilitychange" in result["documentEvents"]
    assert result["intervals"] == [60000]


def test_after_7am_keeps_yesterdays_window_and_excludes_todays_daytime():
    data = payload([
        ("2026-11-21T12:00:00-05:00", 3),
        ("2026-11-22T07:00:00-05:00", 1),
        ("2026-11-22T08:30:00-05:00", 1),
    ])
    result = run_script([data], now="2026-11-22T06:59:59-05:00", steps=[
        {"now": "2026-11-22T06:59:59-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T07:00:00-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T08:00:00-05:00", "event": "focus"},
        {"now": "2026-11-22T23:59:59-05:00", "event": "interval"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 3"], [" × 3"], [" × 3"], [" × 3"]]


def test_future_overnight_entries_enter_until_the_0659_cap():
    data = payload([
        ("2026-11-22T03:30:00-05:00", 1),
        ("2026-11-22T04:10:00-05:00", 1),
        ("2026-11-22T06:59:59-05:00", 1),
        ("2026-11-22T07:00:00-05:00", 50),
    ])
    result = run_script([data], now="2026-11-22T04:00:00-05:00", steps=[
        {"now": "2026-11-22T04:00:00-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T04:10:00-05:00", "event": "focus"},
        {"now": "2026-11-22T06:59:59-05:00", "event": "interval"},
        {"now": "2026-11-22T07:00:00-05:00", "event": "beforeprint"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 1"], [" × 2"], [" × 3"], [" × 3"]]


def test_full_0659_minute_is_included_but_exactly_0700_is_excluded():
    data = payload([
        ("2026-11-21T06:59:59.999-05:00", 50),
        ("2026-11-21T07:00:00-05:00", 1),
        ("2026-11-22T06:59:59.999-05:00", 1),
        ("2026-11-22T07:00:00-05:00", 50),
    ])
    result = run_script([data], now="2026-11-22T06:59:59.998-05:00", steps=[
        {"now": "2026-11-22T06:59:59.998-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T06:59:59.999-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T07:00:00-05:00", "event": "beforeprint"},
        {"now": "2026-11-22T20:00:00-05:00", "event": "beforeprint"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 1"], [" × 2"], [" × 2"], [" × 2"]]


def test_next_midnight_advances_previous_calendar_day_and_excludes_future():
    data = payload([
        ("2026-11-21T23:00:00-05:00", 3),
        ("2026-11-22T06:59:59-05:00", 1),
        ("2026-11-22T07:00:00-05:00", 1),
        ("2026-11-22T23:59:59-05:00", 1),
        ("2026-11-23T00:00:00-05:00", 1),
        ("2026-11-23T00:00:01-05:00", 1),
    ])
    result = run_script([data], now="2026-11-22T23:59:59-05:00", steps=[
        {"now": "2026-11-22T23:59:59-05:00", "event": "beforeprint"},
        {"now": "2026-11-23T00:00:00-05:00", "event": "beforeprint"},
        {"now": "2026-11-23T00:00:01-05:00", "event": "interval"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 4"], [" × 3"], [" × 4"]]


def test_visibility_refresh_occurs_only_when_page_is_visible():
    data = payload([("2026-11-22T03:00:00-05:00", 2)])
    result = run_script([data], now="2026-11-22T04:00:00-05:00", steps=[
        {"now": "2026-11-22T04:00:00-05:00", "event": "visibilitychange", "hidden": True},
        {"now": "2026-11-22T04:00:00-05:00", "event": "visibilitychange", "hidden": False},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 99"], [" × 2"]]


@pytest.mark.parametrize("now,reset,events", [
    (
        "2026-11-01T06:30:00-05:00", "2026-11-01T07:00:00-05:00",
        [("2026-10-31T07:00:00-04:00", 1), ("2026-11-01T01:30:00-04:00", 1),
         ("2026-11-01T01:30:00-05:00", 1)],
    ),
    (
        "2026-03-08T06:30:00-04:00", "2026-03-08T07:00:00-04:00",
        [("2026-03-07T07:00:00-05:00", 1), ("2026-03-08T01:30:00-05:00", 1),
         ("2026-03-08T03:30:00-04:00", 1)],
    ),
    (
        "2026-01-01T06:30:00-05:00", "2026-01-01T07:00:00-05:00",
        [("2025-12-31T08:00:00-05:00", 1), ("2025-12-31T23:00:00-05:00", 1),
         ("2026-01-01T04:00:00-05:00", 1)],
    ),
])
def test_dst_and_calendar_rollovers_keep_yesterdays_window_after_7am(now, reset, events):
    result = run_script([payload(events)], now=now, host_tz="Pacific/Honolulu", steps=[
        {"now": now, "event": "beforeprint"}, {"now": reset, "event": "beforeprint"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 3"], [" × 3"]]


def test_new_year_midnight_advances_window_by_eastern_calendar_date():
    data = payload([
        ("2025-12-30T12:00:00-05:00", 4),
        ("2025-12-31T07:00:00-05:00", 1),
        ("2025-12-31T23:59:59-05:00", 1),
        ("2026-01-01T00:00:00-05:00", 1),
        ("2026-01-01T00:00:01-05:00", 1),
    ])
    result = run_script([data], now="2025-12-31T23:59:59-05:00", host_tz="Asia/Tokyo", steps=[
        {"now": "2025-12-31T23:59:59-05:00", "event": "beforeprint"},
        {"now": "2026-01-01T00:00:00-05:00", "event": "beforeprint"},
    ])
    assert result["snapshots"] == [[" × 99"], [" × 4"], [" × 3"]]


def test_multiple_rooms_refresh_independently_and_malformed_data_fails_closed():
    current = payload([("2026-11-21T10:00:00-05:00", 4)])
    zero = payload([])
    old = payload([("2026-11-20T10:00:00-05:00", 8)])
    result = run_script([current, zero, old, "{not JSON"], now="2026-11-22T04:00:00-05:00", steps=[
        {"now": "2026-11-22T04:00:00-05:00", "event": "beforeprint"},
    ])
    assert result["snapshots"][1] == [" × 4", " × 0", " × 0", ""]


@pytest.mark.parametrize("bad", [
    {"version": 99, "events": []},
    {"version": 1, "window_start_ms": 1795262400000, "window_date": "2026-11-21", "events": []},
    {"version": 2, "events": [[1795273200000, -1]]},
    {"version": 2, "events": [[1795273200000, "2"]]},
    {"version": 2, "events": [[1795273200000, None]]},
    {"version": 2, "events": [[1795273200000, 1.5]]},
    {"version": 2, "events": [[1795273200000, 101]]},
    {"version": 2, "events": [["not a timestamp", 1]]},
    {"version": 2, "events": [[1e30, 1]]},
    {"version": 2, "events": "not a list"},
])
def test_invalid_payload_fields_suppress_count(bad):
    result = run_script([bad], now="2026-11-22T04:00:00-05:00", steps=[
        {"now": "2026-11-22T04:00:00-05:00", "event": "beforeprint"},
    ])
    assert result["snapshots"][1] == [""]


def test_invalid_browser_clock_does_not_leave_a_stale_count():
    result = run_script([payload([])], now="2026-11-22T04:00:00-05:00", steps=[
        {"now": "invalid", "event": "beforeprint"},
    ])
    assert result["snapshots"][1] == [""]
