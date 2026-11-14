# Current Shift, version 6.75

The two shift starts are 7am and 7pm. Before 7am, use the previous calendar
day's 7pm. From 7am to before 7pm, use today's 7am. At or after 7pm, use today's
7pm. Exact shift-start cutoffs have zero elapsed time and therefore no hourly rate.
3pm and 11pm are no longer shift boundaries.

The stored source timestamp remains the endpoint, regardless of print time.
Rate = category volume in mL / current-shift weight in kg / elapsed shift hours.
Do not divide by a fixed 12 hours. No changes were made to recorded volumes.

Current Shift (7pm - 6:30am)
UOP: 1.30 mL/kg/hr
Drains: 0.07 mL/kg/hr
Chest Tube: 0.13 mL/kg/hr
Other: 0.26 mL/kg/hr

This synthetic example uses 20 kg and volumes of 300, 15, 30 and 60 mL,
respectively, across 11.5 hours. Two-decimal rounding and small-rate handling
remain unchanged. No intake, total output or net is shown in Current Shift.

The shift parser still reads only the explicit current-shift H breakdown and
its Weight. The H summary's date/time is used only as the current-shift cutoff.
The separate 24-hour source-selection logic is unchanged from 6.74: valid
populated S keeps priority, while absent/validly empty S can use the explicit
24-hour summary in H. Shift amounts are never added into 24-hour totals.

Persisted current_shift snapshots contain only as_of, weight_kg and outputs.
New and existing snapshots are rendered using the corrected schedule. No
stored rate or label is carried forward from the previous 8-hour schedule.

Source validation, Eastern daylight-saving safeguards, missing-value handling,
independent output categories, encrypted storage and malformed-input recovery
are unchanged. The screen, text, HTML, individual PDF and Print All share the
same current-shift formatter.
