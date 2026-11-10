# Version 6.27: Pacemaker mode and rate

This complete ZIP adds the W section as an independent pacemaker snapshot. No direct GitHub changes are needed from ChatGPT. Upload the extracted folder contents to the application repository, keeping app.py at its root. Include pacemaker.py. Keep all existing Secrets, both passwords, the encryption key, token, mappings and private data repository. No new dependencies are required.

## Output

W rows identifying Pacemaker Yes, Pacer Mode AAI and Atrial Rate (beats/min) 140 BPM display as:

Pacemaker: AAI at 140 bpm

This line is bold in the Cardiovascular column, below cardiovascular vital signs and above lactate, CV Infusions, notes and other medications. The result appears in the preview, PDF, HTML, text and Print all. No system mapping is required.

The explicit source mode is retained. An atrial mode uses the documented atrial rate. A ventricular mode uses the documented ventricular rate. A generic set-rate field can be used when the matching chamber field is absent. Heart rate, output in milliamps, and the other chamber's rate are never substituted. Different dual-chamber rates remain separately labeled rather than merged. This is a transcription rule, not a recommendation or confirmation of capture.

Only mode and rate are in the compact summary. Device type, wires, output and sensing are not added. An explicit Off or Standby state does not print an active pacing rate. Missing mode or matching rate displays UNK with a review warning. The app does not infer the pacing mode.

## Updates and editing

Paste the full SmartPhrase or only the complete paired W section and click Create / update handoff. Omitted W preserves its previous snapshot. An included empty W or Pacemaker No clears it. Conflicting or unreadable W settings skip only W, preserving the prior snapshot for editing while hiding it from the printed handoff until reviewed or successfully reimported. Technical reports use the existing patient-free encrypted error log.

Open Edit handoff, expand Cardiovascular, then Edit pacemaker. Mode, documented atrial/ventricular rate, generic set rate, status and inclusion are editable. Room autosave captures edits. A new patient starts with no pacemaker snapshot. No confirmation step or new tab is added.

## Existing saved handoffs

Schema 20 migrates to 21 with pacemaker initialized to null. All prior fields, settings, IDs, reset generation and save timestamps are preserved. Installing the update does not clear any handoffs. Earlier supported schemas remain supported. Do not downgrade after saving with this version. Re-paste W to populate an existing handoff.

The sidebar shows: Version 6.27 | Pacemaker mode and rate

See TEST_REPORT.md for local validation and limits. The example and preview included in this ZIP are synthetic.
