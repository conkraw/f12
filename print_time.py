"""Print/export timestamps in US Eastern time, independent of server timezone."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def eastern_print_time(instant: datetime | None = None) -> str:
    instant = datetime.now(timezone.utc) if instant is None else instant
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A print timestamp must include its timezone.")
    return instant.astimezone(ZoneInfo("America/New_York")).strftime("%m/%d/%Y %I:%M:%S %p %Z")


# No clinical values are interpolated into JavaScript. The print event refreshes
# timestamps in downloaded HTML even when it is opened/printed much later.
PRINT_TIME_SCRIPT = """<script>
(function () {
  function updatePrintTime() {
    try {
      const options = {timeZone: 'America/New_York', year: 'numeric', month: '2-digit',
        day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: true, timeZoneName: 'short'};
      const parts = new Intl.DateTimeFormat('en-US', options).formatToParts(new Date());
      const get = type => parts.find(part => part.type === type).value;
      const text = `${get('month')}/${get('day')}/${get('year')} ${get('hour')}:${get('minute')}:${get('second')} ${get('dayPeriod')} ${get('timeZoneName')}`;
      document.querySelectorAll('[data-print-time]').forEach(node => {node.textContent = text;});
      document.querySelectorAll('[data-print-label]').forEach(node => {node.textContent = 'Printed: ';});
    } catch (error) { /* Preserve the clearly labeled export time on failure. */ }
  }
  window.addEventListener('beforeprint', updatePrintTime);
}());
</script>"""
