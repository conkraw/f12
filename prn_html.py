"""Refresh automatic paralytic PRN counts when an HTML handoff is printed.

The document carries only sanitized epoch/count pairs from imported vecuronium
and rocuronium records. Every refresh starts at yesterday's 7am Eastern and
ends at the current time, capped at the end of today's 6:59am minute.
"""
from __future__ import annotations

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
    from prn_counts import automatic_prn_events
    # Keep available future and next-day entries so a later print can refresh
    # its window when the Eastern calendar date changes at midnight.
    # Fractional milliseconds preserve subsecond cutoff comparisons.
    return {"version": 2, "events": [
        [instant.timestamp() * 1000, count]
        for instant, count in automatic_prn_events(data, medication)
    ]}


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
                raise ValueError("The automatic PRN count changed.")
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
    const day = new Date(0);
    day.setUTCFullYear(parts.year, parts.month - 1,
      parts.day - (previousDay ? 1 : 0));
    return day.toISOString().slice(0, 10);
  }
  function countText(payload, now, reportingDay) {
    if (!Number.isFinite(now) || !reportingDay || !payload || payload.version !== 2 ||
        !Array.isArray(payload.events) ||
        payload.events.length > 4096) return '';
    let count = 0;
    for (const event of payload.events) {
      if (!Array.isArray(event) || event.length !== 2 ||
          typeof event[0] !== 'number' || !Number.isFinite(event[0]) ||
          !Number.isInteger(event[1]) || event[1] < 0 || event[1] > 100) return '';
      const local = localParts(event[0]);
      if (event[0] <= now && dateKey(local, local.hour < 7) === reportingDay) {
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
      // Keep yesterday's 7am-to-6:59am window throughout today's date.
      // The event-day match excludes today's 7am and later entries.
      reportingDay = dateKey(local, true);
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
