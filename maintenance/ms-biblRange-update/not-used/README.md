# not-used (deprecated)

These files are the **earlier add-only** citedRange approach. They are **no
longer used** — superseded by `../biblRange_audit.py` + `../biblRange_sync.py`
(audit → review → mirror-sync). Kept only for reference.

| File | Was |
|---|---|
| `ms_biblRange_update.py` | add-only generator (never removed CRs, wrote empty `<citedRange>` with no text, required both `@from`+`@to`) |
| `test_biblRange.py` | bidirectional-coverage test for the old script |
| `ms_biblRange_report.tsv`, `ms_biblRange_warnings.tsv` | its last-run outputs |

Do not run these. See `../README.md` for the current process.
