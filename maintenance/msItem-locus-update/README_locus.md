# msItem/locus audit & fix

Audits and fixes the **direct** `<locus>` children of `<msItem>`
(`msItem/locus`, **not** loci inside `incipit`/`explicit`) across
`data/manuscripts/tei/*.xml`, and keeps each locus's textual value in sync with
its `@from`/`@to`.

Run all commands from the **repository root**. Both scripts use an lxml
`recover=True` parser (the corpus contains pre-existing duplicate `xml:id`s that
strict parsers reject).

---

## Pipeline

```
1. locus_audit.py      → report + shortlist of problems
2. human review        → fill `final_fix` in the shortlist, save as *_reviewed.tsv
3. apply_locus_fixes.py → apply fixes, sync text, log every change
```

---

## Step 1 — Audit  (`locus_audit.py`)

```bash
python3 maintenance/msItem-locus-update/locus_audit.py
```

Read-only. Scans every `msItem/locus`, validates it, and writes:

| Output | Contents |
|---|---|
| `locus_audit_report.tsv` | one row per locus: ms_id, positional + readable xpath, unit, from, to, text, other attrs, issue codes |
| `locus_audit_summary.tsv` | count per issue code |
| `locus_to_fix.tsv` | **shortlist**: only loci needing a human fix/decision, with an empty `final_fix` column to fill |

### Issue codes

**ERROR** (malformed / not TEI-valid — goes to shortlist):
`RANGE_PACKED_IN_FROM`, `RANGE_PACKED_IN_TO` (range packed in one attr, e.g.
`5r-v`), `BAD_FROM_FORMAT`, `BAD_TO_FORMAT` (unrecognised token),
`DESCENDING_RANGE` (`@from` sorts after `@to`), `TEXT_ONLY` (text but no
`@from`), `WHITESPACE` (leading/trailing space in attr), `UNIT_ON_LOCUS`
(`@unit` is non-standard on `<locus>`; belongs on `citedRange`).

**REVIEW** (valid but needs a human eye — goes to shortlist):
`SIDE_INCONSISTENT` (one endpoint has r/v, the other not), `TEXT_ATTR_MISMATCH`
(text disagrees with attrs), `MIXED_CONTENT` (locus has child elements).

**Informational** (valid, **not** in shortlist):
`BOTH_EMPTY` (`from="" to=""`), `OPEN_ENDED` (`@from` only — single leaf),
`SELF_RANGE_OK` (`@from` == `@to`).

`suggested_fix` is auto-filled for mechanical cases (`Nr-v` split,
whitespace-trim); otherwise blank.

---

## Step 2 — Human review

1. Copy `locus_to_fix.tsv` → `locus_to_fix_reviewed.tsv`.
2. For each row, put the **complete replacement** in the `final_fix` column:
   one or more literal `<locus …>…</locus>` elements that wholly replace the
   target. A single locus may be split into several (discontinuous text).
   Leave `final_fix` empty to skip a row (un-reviewed).

Columns read by the apply script: `ms_id`, `from`, `to` (to locate the target),
`final_fix` (the replacement). Extra columns are ignored.

Example `final_fix` values:

```
<locus from="5r" to="5v">5r–5v</locus>
<locus from="68r" to="68v">68r–68v</locus><locus from="160v" to="160v">160v</locus>
```

Conventions: range text uses an en dash (`5r–5v`); a single leaf is just the
folio (`160v`); positional notes go in the text, not the attributes
(`<locus from="11r" to="11r">11r (top)</locus>`).

---

## Step 3 — Apply  (`apply_locus_fixes.py`)

```bash
python3 maintenance/msItem-locus-update/apply_locus_fixes.py          # dry-run (default, no writes)
python3 maintenance/msItem-locus-update/apply_locus_fixes.py --apply  # write changes
```

Input: `locus_to_fix_reviewed.tsv`. Two phases per file:

**Part A — reviewed fixes.** For each row with a `final_fix`, locate the target
by `(ms_id, @from, @to)` and **replace the whole element** with the reviewer's
`<locus>` element(s), inserted **in place** (a 1→N split yields N consecutive
siblings in the original's slot). `@from`/`@to` come entirely from `final_fix`
(never carried from the original, so a single-leaf replacement may legitimately
omit `@to`); auxiliary attributes (`xml:id`, `@n`, `@target`, `@scheme`) are
carried over from the original (`xml:id` only to the first element on a split,
with a warning).

**Part B — text ↔ attribute sync** for every other well-formed locus:
- **adds** text where none exists (`from="2r" to="10v"` → `2r–10v`; single leaf
  → `2r`);
- **normalises** cosmetic-only differences (hyphen, em dash, or spacing → en
  dash, same folios);
- **never overwrites** human prose/labels, or canonical text whose folios
  genuinely differ from the attributes (reported for review);
- **skips/reports** empty placeholders, mixed content, invalid ranges, unknown
  tokens.

### Outputs

| Output | Contents |
|---|---|
| modified `*.xml` | locus fixes + synced text; **only** when something changed |
| per-file `<change>` | a dated entry prepended to each modified file's `teiHeader/revisionDesc`, summarising that file's edits. Its `@source` holds the **basename of this run's change log** (e.g. `source="locus_change_log_20260624-131809.tsv"`), linking the in-document note to the detailed external log |
| `locus_change_log_<YYYYMMDD-HHMMSS>.tsv` | **detailed log, one row per locus** (incl. no-change), with readable xpath, `changed` flag, action, full before/after element, and a note |

Change-log `action` values: `replace_element` (Part A), `add_text`,
`fix_text_cosmetic`, `no_change`, `skip_empty`, `preserve_human`,
`review_mismatch`, `review_mixed`, `review_invalid`.

---

## Guarantees

- **Dry-run by default** — writes nothing without `--apply`; the change log is
  still produced so you can review first.
- **Idempotent** — re-running on already-consistent data makes no changes (so no
  `<change>` bloat).
- **Non-destructive** — Part B changes only the text value, only ever overwriting
  cosmetic restyling of identical data; attributes change only via reviewed
  Part A fixes.
- **Minimal diffs** — original XML declaration and trailing-newline state are
  preserved; only changed `<locus>` lines (and the new `<change>`) appear in the
  diff.
- **"OK" = well-formed & self-consistent**, not factually verified against the
  physical manuscript.

Recurring use as the corpus evolves: re-run Step 1 to catch new problems, review
them into the reviewed file, then re-run Step 3.

---

## Files

| File | Role |
|---|---|
| `locus_audit.py` | Step 1 — audit + shortlist generator |
| `apply_locus_fixes.py` | Step 3 — apply fixes + sync text + log |
| `locus_audit_report.tsv` / `locus_audit_summary.tsv` | audit outputs |
| `locus_to_fix.tsv` | generated shortlist (empty `final_fix`) |
| `locus_to_fix_reviewed.tsv` | reviewed shortlist (filled `final_fix`) — input to Step 3 |
| `locus_change_log_*.tsv` | per-run detailed change log |
