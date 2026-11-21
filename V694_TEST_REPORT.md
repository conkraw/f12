# PICU Handoff 6.94 verification

## Automated regression result

408 tests passed with zero failures, errors or skipped tests. This comprises 389 existing regression checks and 19 new Home navigation tests.

The final selection covered:

- tests.test_callbacks: 13 tests
- tests.test_compact_workspace: 70 tests
- tests.test_home_navigation: 19 tests
- tests.test_measurement_notes_observed_pip: 1 tests
- tests.test_patient_list_startup: 50 tests
- tests.test_print_fit_reset: 49 tests
- tests.test_respiratory_update_check: 13 tests
- tests.test_room_replacement: 82 tests
- tests.test_save_before_print: 45 tests
- tests.test_save_status: 58 tests
- tests.test_ui_smoke: 8 tests

## Saving before Home

The Home tests verify pending current-room widget edits, other changed open drafts, newly created handoffs and inline medication mapping preferences. Clean and empty lists return Home without writing or changing saved timestamps.

Invalid editor values, known room conflicts and failed remote writes block navigation. A current-room save can succeed before a later room fails. In that case the user stays in the workspace, the confirmed save remains valid and the remaining edits are retained. No all-saved success message is shown.

Home does not delete handoffs, reset the archive, reload storage or log out. It locks Admin access separately and retains main authentication. PDF warming is skipped for Home, while existing invalidation and download safeguards remain active.

## Real Streamlit lifecycle check

The actual app ran through 23 AppTest UI stages with synthetic data and shared storage disabled. All stages passed without exceptions.

Home was the first sidebar button in Handoff, Print all, Admin and Import errors. A pending manual note delivered in the same event as the Home click was captured and saved before the original choices appeared.

After three Home-screen reruns, Streamlit had removed the hidden room and paste widget keys. Continue restored the selected room, its saved note and the server-known pending paste from nonwidget session state. The paste was neither imported nor included in the saved vault. Restoration requires matching room and saved/draft sheet identities.

The fresh-list choice displayed the existing deletion confirmation and kept the saved handoff until confirmation. Confirming cleared the census, drafts, paste and resume state. Later Home/Continue navigation did not restore any cleared patient information.

AppTest verifies the actual Streamlit widget and callback lifecycle. It is not a live browser or production storage test, and it does not capture browser screenshots. Text still held only in an unsubmitted browser form is outside the server-known paste preservation check.

The stage-by-stage result is included in examples/home_navigation_check.json.

## Scope and review

Only app.py and error_store.py changed as runtime files after 6.93. The archive schema remains 34. No dependencies or credentials changed. Respiratory history, its fallback and clinical parsing remain unchanged.

Independent review found no blocking save-loss, conflict, reset or session-state issue. Existing dependency deprecation warnings did not affect the test results.

No live Streamlit deployment or production archive write was performed.
