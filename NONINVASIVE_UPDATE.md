# Respiratory support update, version 5

This reads C and D as a snapshot of documented settings, not proof of current or simultaneous bedside support. The earlier requirement for a named C-block mode was too strict when Epic omitted that line. Missing Vent Mode now does not block diagnosis, medication or D-block imports.

## Display rules

| Current-paste pattern | RESP entry |
| --- | --- |
| Named BiLevel/BiPAP mode plus both D pressures | BiPAP with IPAP, EPAP and FiO2 |
| No Vent Mode, but both usable D pressures | BiPAP (pressure-based) with the documented pair and FiO2 |
| Missing either pressure, even with a leftover BiLevel mode | No BiPAP entry |
| CPAP mode with EPAP or PEEP | CPAP with pressure and FiO2 |
| Explicit high flow nasal cannula / HFNC | HFNC with D-block flow and FiO2 |
| Nasal cannula, including humidified Other (Comment), or LFNC | Nasal cannula with D-block flow and FiO2 |
| Pressure device plus CPAP/Bi-PAP mask and positive flow | HFNC (flow-based), retaining the existing user-defined convention |

A pressure pair may remain after support changes. The pressure-based label is therefore retained in the editor, encrypted save, PDF and HTML. Remove that entry if it is no longer applicable. No new confirmation checkbox is required. An explicit unknown/invasive mode, invasive airway label, or Ventilator On: No prevents the missing-mode fallback. Pressure inference does not read earlier handoffs.

Standard nasal cannula is recognized from its label, not a flow cutoff. Humidification does not make it HFNC. FiO2 21% remains the recorded value and does not change a labeled cannula into room air. Missing flows remain missing, with an editor notice. A recorded zero flow is not displayed as flowing support.

The mask-plus-flow HFNC convention remains visibly flow-based because the source names a mask, not a separate HFNC device. It can be removed directly when it does not apply.

## FiO2 sources

Named BiPAP and CPAP prefer C-block FiO2, falling back to D with a notice. Pressure-based BiPAP without a mode prefers D-block FiO2, matching the block containing its pressure pair. It can fall back to C with a notice. Nasal cannula and HFNC use D-block FiO2 only. These are documented values, not calculated effective oxygen concentrations. The app does not use VITALS or old-paste values.

Conflicting repeated fields still stop the import. Conflicting C PEEP and D EPAP for CPAP still stop the import. Unknown explicit modes are not replaced by guessed BiPAP modes.

## Import, edit and print

Choose a room, paste C and D together, and click Create / update handoff. The new respiratory snapshot replaces previous automatic entries. Pasting A/B only leaves respiratory support unchanged. Notes and medication mappings are kept separately.

All support entries appear above one ----- separator and the respiratory notes and medications. Each device has editable values and a Remove button. Print all retains both support entries and their source qualifiers, with one room starting on each landscape page.

Load nasal-cannula example reproduces the missing-mode pattern using a synthetic diagnosis and generic numeric settings. The expected support is BiPAP (pressure-based) plus Nasal cannula. The sidebar shows Version 5.

## Existing data

Schema 5 adds the nasal-cannula device and an explicit pressure_inferred flag. Schemas 1-4 migrate in memory without replacing the key, saved notes, medication mappings, room IDs or existing support values. The next successful save uses schema 5. Do not downgrade files after saving the new schema. Keep all deployment Secrets and the private data repository unchanged. No raw pasted source blocks are added to storage.

## Validation

313 local tests passed using synthetic examples, widget stubs and mocked GitHub storage calls. Checks include the missing-mode case, humidified nasal cannula, BiPAP/CPAP/HFNC combinations, source-specific FiO2, stale-setting removal, field conflicts, partial pressures, schema migration, encrypted round trips, per-room callbacks and landscape batch printing. The two-page regression PDF was rendered and inspected. The hosted Streamlit browser and authenticated private handoff store were not tested.
