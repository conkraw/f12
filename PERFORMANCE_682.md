# Dated-score performance verification for 6.82

Measured November 16, 2026 with synthetic data in the local Python runtime.
These timings do not measure the live Streamlit deployment or network saves.

## Unnecessary saves during room navigation

A separate callback check reproduced an unwanted save introduced in 6.81.
Taking a snapshot of an unchanged older WAT value normalized that saved value,
so switching rooms wrote the archive and prepared the PDF again even though
the user had not edited the score. The same case made no save in 6.80.

Version 6.82 compares the editor value with its sanitized display baseline and
normalizes only an actual edit. Merely displaying that baseline leaves the
stored record and existing import warning unchanged.

The 26 new callback tests in tests/test_dated_score_edit_performance_682.py
verify zero shared-store saves and zero PDF warming calls for unchanged legacy
room navigation. Real score, date and inclusion edits save and warm once.
They also cover warning recovery, invalid-edit rollback and other-room isolation.
These checks count calls through the app with storage and widget stubs. They do
not assign a network duration to the avoided save.

## What caused the repeated work

Version 6.81 sent compact score dates through the general laboratory date parser.
That parser tries date and time formats in sequence. The two-digit-year date
format exceeds Python's five-entry format cache, causing repeated compilation.
Score values are checked during validation, selection and display, and an HTML
handoff currently requests neurologic output five times.

In 30 warmed HTML renders, 6.81 performed 6,750 strptime attempts and 4,680 date
format compilations. The 6.82 score parser removed those compilations for the
same dated score fixture. Its 2,190 score-date parses took about 0.012 profiled
seconds, compared with about 0.178 seconds in the general date parser in 6.81.
Laboratory parsing itself was not changed.

## Timing comparisons

The table shows median milliseconds per operation across five repetitions.
Version 6.80 uses its supported legacy CAPD and WAT values. Versions 6.81 and
6.82 use the same scores with the requested dates. All cases include the same
timestamped SBS and invasive-mode evidence.

| Lightweight synthetic handoff | 6.80 legacy | 6.81 dated | 6.82 dated |
| --- | ---: | ---: | ---: |
| Neurologic/vitals output | 0.145 | 0.533 | 0.156 |
| PDF content signature | 6.94 | 9.78 | 6.39 |
| HTML handoff | 4.71 | 6.39 | 4.34 |
| PDF handoff | 15.65 | 18.96 | 13.40 |

The wider fixture adds 40 synthetic laboratory rows. Its timings include
existing laboratory display work, which the score change does not remove.

| Handoff with 40 laboratory rows | 6.80 legacy | 6.81 dated | 6.82 dated |
| --- | ---: | ---: | ---: |
| PDF content signature | 12.46 | 16.47 | 15.10 |
| HTML handoff | 11.04 | 13.23 | 12.95 |
| PDF handoff | 23.96 | 28.32 | 28.24 |
| Warm Print all, 18 rooms | 324.86 | 392.45 | 314.33 |

The warmed Print all median in this run was about 20% lower in 6.82 than in
6.81 and close to the 6.80 result. The larger single-sheet rendering timings
were more variable and show a smaller change. The measured local times should
not be read as a promised speedup on the deployed server.

## PDF reuse and output equivalence

Every version built 18 clinical PDF bodies during initial preparation. All six
subsequent packets, one warmup and five measured packets, reused those bodies.
There were zero additional clinical-body builds in each version. Each packet
contained 18 pages and left the supplied records unchanged.

A separate comparison used identical synthetic records with an observed SBS,
an explicit SBS target and a nasal-cannula case. After fixing generated IDs and
save metadata, 6.81 and 6.82 produced exactly matching stored records, text and
HTML hashes. Recording dates and values were not normalized away. The source
attribution remained absent, and the nasal-cannula case omitted SBS.

## Reproducing the checks

The benchmark script accepts a version directory, a score variant and optional
laboratory and Print all cases:

    python3 validation/profile_scores_682.py --app-root /path/to/app --variant dated --labs --print-all --output results.json

Use --variant legacy for 6.80. Both legacy and dated fixtures were measured in
6.81 and 6.82. PERFORMANCE_682.json contains every raw repetition, profile call
counts, the environment, cache counts and output-equivalence hashes.

The output comparison uses separate processes so modules from different
versions cannot mix:

    python3 validation/check_score_output_682.py /path/to/6.81 /path/to/6.82

These checks do not access a live server, shared archive or patient paste.
