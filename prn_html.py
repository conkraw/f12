"""Refresh confirmed PRN suffixes when a downloaded HTML handoff is printed.

The document carries only sanitized epoch/count pairs for already reviewed
medications. The browser cannot approve a new reporting day, infer a dose from
a volume, or retrieve new administrations. Unresolved entries and a changed
7am day remove the numeric suffix until a newly reviewed export is generated.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from html import escape
import json
import re


def _without_counts(blocks: list[tuple]) -> list[tuple]:
    result = []
    for kind, item in blocks:
        if kind == "medication" and isinstance(item, dict) and "_prn_count" in item:
            item = {key: value for key, value in item.items() if key != "_prn_count"}
        result.append((kind, item))
    return result


def _count_payload(data: dict, medication: str) -> dict:
    from prn_counts import EASTERN, event_time
    start = event_time(data["reviewed"][medication]["window_start"])
    following = datetime.combine(start.date() + timedelta(days=1), time(7), EASTERN)
    start_utc, following_utc = start.astimezone(timezone.utc), following.astimezone(timezone.utc)
    events = []
    for event in data["events"]:
        if event["medication"] != medication:
            continue
        instant = event_time(event["timestamp"]).astimezone(timezone.utc)
        if start_utc <= instant < following_utc:
            # Fractional milliseconds keep subsecond events on the correct
            # side of the cutoff even though browser clocks have ms precision.
            events.append([instant.timestamp() * 1000, event["dose_count"]])
    return {"version": 1, "window_start_ms": start_utc.timestamp() * 1000,
            "window_date": start.date().isoformat(), "events": events}


def mark_live_prn_counts(sheet: dict, body_markup: str, blocks: list[tuple], esc=escape) -> str:
    """Wrap generated count suffixes only, never matching arbitrary notes.

    Walk rendered blocks in order to locate each medication's exact output.
    Removing the chosen suffix must reproduce its count-free rendering. This
    also protects manually entered text containing the same number or phrase.
    Unsupported markup or stale metadata falls back to count-free output.
    """
    from infusions import render_body_blocks
    from medications import format_medication
    from output_text import medication_output
    from prn_counts import canonical_medication, prn_counts, validate_prn

    counted = [(kind, item) for kind, item in blocks
               if kind == "medication" and isinstance(item, dict) and "_prn_count" in item]
    if not counted:
        return body_markup
    # ReportLab uses a separate escaping function and must never receive spans.
    if esc is not escape:
        return body_markup
    try:
        data = sheet.get("prn")
        validate_prn(data)
        counts = prn_counts(sheet)
        cursor = 0
        replacements = []
        for kind, item in blocks:
            rendered = render_body_blocks([(kind, item)], True, esc)
            if not rendered:
                continue
            offset = body_markup.find(rendered, cursor)
            if offset < 0:
                raise ValueError("The medication markup changed.")
            cursor = offset + len(rendered)
            if kind != "medication" or not isinstance(item, dict) or "_prn_count" not in item:
                continue
            medication = canonical_medication(item.get("name", ""))
            count = item["_prn_count"]
            if type(count) is not int or medication not in counts or counts[medication] != count:
                raise ValueError("The reviewed PRN count changed.")
            plain_row = {key: value for key, value in item.items() if key != "_prn_count"}
            plain = esc(medication_output(format_medication(plain_row)))
            suffix = esc(" \u00d7 " + str(count))
            candidates = [match.start() for match in re.finditer(re.escape(suffix), rendered)
                          if rendered[:match.start()] + rendered[match.end():]
                          in {plain, plain + esc(" | PRN")}]
            if not candidates:
                raise ValueError("The generated PRN suffix was not located.")
            payload = _count_payload(data, medication)
            encoded = escape(json.dumps(payload, ensure_ascii=True, allow_nan=False,
                                        separators=(",", ":")), quote=True)
            span = '<span data-prn-count="' + encoded + '">' + suffix + '</span>'
            replacements.append((offset + candidates[0], len(suffix), span))
        for offset, length, replacement in reversed(replacements):
            body_markup = body_markup[:offset] + replacement + body_markup[offset + length:]
        return body_markup
    except (ValueError, TypeError, KeyError, OverflowError):
        return render_body_blocks(_without_counts(blocks), True, esc)


PRN_PRINT_SCRIPT = """<script>
(function () {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  });
  function localParts(instant) {
    const parts = formatter.formatToParts(new Date(instant));
    const get = type => Number(parts.find(part => part.type === type).value);
    return {year: get('year'), month: get('month'), day: get('day'),
      hour: get('hour'), minute: get('minute'), second: get('second')};
  }
  function dateKey(parts, previousDay) {
    return new Date(Date.UTC(parts.year, parts.month - 1,
      parts.day - (previousDay ? 1 : 0))).toISOString().slice(0, 10);
  }
  function countText(payload, now, reportingDay) {
    if (!payload || payload.version !== 1 ||
        typeof payload.window_start_ms !== 'number' || !Number.isFinite(payload.window_start_ms) ||
        payload.window_start_ms % 1000 !== 0 ||
        typeof payload.window_date !== 'string' || !/^\\d{4}-\\d{2}-\\d{2}$/.test(payload.window_date) ||
        payload.window_date !== reportingDay || !Array.isArray(payload.events) ||
        payload.events.length > 4096) return '';
    const start = localParts(payload.window_start_ms);
    if (dateKey(start, false) !== payload.window_date || start.hour !== 7 ||
        start.minute !== 0 || start.second !== 0 || payload.window_start_ms > now) return '';
    let count = 0;
    for (const event of payload.events) {
      if (!Array.isArray(event) || event.length !== 2 ||
          typeof event[0] !== 'number' || !Number.isFinite(event[0]) ||
          (event[1] !== null && (!Number.isInteger(event[1]) || event[1] < 0 || event[1] > 100))) return '';
      if (event[0] >= payload.window_start_ms && event[0] <= now) {
        if (event[1] === null) return '';
        count += event[1];
      }
    }
    return ' \\u00d7 ' + String(count);
  }
  function updatePrnCounts() {
    const now = Date.now();
    let reportingDay = '';
    try {
      const local = localParts(now);
      reportingDay = dateKey(local, local.hour < 7);
    } catch (error) { /* An invalid browser clock suppresses numeric counts. */ }
    document.querySelectorAll('[data-prn-count]').forEach(node => {
      let text = '';
      try {
        text = countText(JSON.parse(node.getAttribute('data-prn-count')), now, reportingDay);
      } catch (error) { /* Invalid metadata must not preserve a stale number. */ }
      node.textContent = text;
    });
  }
  window.addEventListener('beforeprint', updatePrnCounts);
  window.addEventListener('focus', updatePrnCounts);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) updatePrnCounts();
  });
  window.setInterval(updatePrnCounts, 60000);
}());
</script>"""
