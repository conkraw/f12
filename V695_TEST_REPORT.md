# PICU Handoff 6.95 verification

## Automated result

718 selected tests passed with zero failures, errors or skipped tests. This includes 35 new lumbar core tests, 19 new lumbar integration tests and 664 existing regression tests.

| Test module | Passed |
| --- | ---: |
| tests.test_batch_exports | 8 |
| tests.test_devices | 103 |
| tests.test_empty_groups_icp_cpp | 85 |
| tests.test_home_navigation | 19 |
| tests.test_import_recovery | 34 |
| tests.test_lumbar_drain_core | 35 |
| tests.test_lumbar_drain_integration | 19 |
| tests.test_measurement_notes_observed_pip | 74 |
| tests.test_neuro_groups_compact_trends | 122 |
| tests.test_neuro_weight | 83 |
| tests.test_respiratory_update_check | 13 |
| tests.test_room_replacement | 82 |
| tests.test_ui_smoke | 8 |
| tests.test_vent_first_reported_fallback | 33 |

## Lumbar drain behavior

The new tests cover explicit lumbar drain labels in both device blocks, the shared Epic category prefix, older Other-category records, the documented status, missing status and conflicting repeated status.

Matching device identities across U and V collapse to one Neuro line. Conflicting statuses for that identity display UNK. Distinct device identities remain separate. Unrelated drains cannot supply a status or date.

Include controls, removed-device markers and failed-section hiding prevent inappropriate output. Replacing a room with a new paste that has no lumbar drain cannot recover old lumbar details from retained widget values.

Lumbar punctures, culture specimen descriptions and generic surgical drains in a lumbar location do not create a lumbar drain. EVDs, ICP monitors, scalp drains and other devices retain their existing routes.

## Placement, editing and persistence

Text, HTML and PDF checks verify the exact six-hyphen separator after the last visible WAT line, followed by the lumbar drain and then ICP/CPP. When WAT is absent, blank or excluded, the drain follows CAPD without creating a score.

Device status and Include edits reach the saved handoff. Encrypted save/reload checks preserve both current Drain records and older Other records. A handoff containing only a lumbar drain remains available in Print all.

The existing Home navigation and ventilator fallback tests were included in this release's regression selection.

## Supplied source and visual check

The supplied source contains a lumbar drain marked Clamped, no lumbar device date and no WAT value. Its lumbar line appears in the Neuro score area with the required separator. The separate scalp drain remains in the footer. No EVD is created, no date is borrowed and the lumbar entry causes no V-section warning.

The supplied clinical source was not added to fixtures or previews. The included examples/lumbar_drain_preview.pdf uses synthetic content. Its two examples cover WAT present and WAT absent. Each fits on one page at the existing 8-point font without tighter spacing. Both PDF pages were rendered to images and visually checked for placement and clipping.

## Scope

Changed runtime files: app.py, batching.py, devices.py, error_store.py, import_review.py and models.py.

The archive schema remains 34. There are no new runtime files or dependencies. Independent review found no blocking issue in the lumbar routing, status handling or sample import.

Existing dependency deprecation warnings did not affect the test result. UI harness checks passed. No live Streamlit deployment or production archive write was performed.
