# citedRange ↔ locus sync (manuscript joins)

Generates folio `<citedRange>` in a **host** manuscript by mirroring the
`<msItem>/<locus>` of the **referenced** ("joined") manuscript it points to.

A join: a `<bibl>` in the host's `physDesc` with `<ptr target=".../manuscript/N"/>`.
The referenced ms N's locus is copied in as the citedRange:

```
referenced  <locus from="1r" to="1v">1r–1v</locus>
host        <citedRange unit="folios" from="1r" to="1v">1r–1v</citedRange>   (before <ptr>)
```

Run from the **repository root**. Needs `lxml`. Both scripts use a `recover=True`
parser (corpus has pre-existing duplicate `xml:id`s).

> **Prerequisite — clean referenced loci.** The sync copies locus `@from`/`@to`,
> so loci must be valid first. Run the `msItem-locus-update` task if needed (see
> `../msItem-locus-update/README_locus.md`); the audit's `REF_LOCUS_INVALID`
> tells you whether any referenced locus is still malformed (currently 0).

## Pipeline

```
1. biblRange_audit.py   read-only: report + summary + review shortlist
2. fix any flagged source issues (blockers, invalid loci)
3. biblRange_sync.py    dry-run, then --apply
```

## Step 1 — audit

```bash
python3 maintenance/ms-biblRange-update/biblRange_audit.py
```

Reports, per candidate join-bibl, what the sync would do and what needs a human.
Outputs: `biblRange_audit_report.tsv` (all), `biblRange_audit_summary.tsv`
(counts), `biblRange_to_review.tsv` (BLOCKER + REVIEW only).

| Severity | Codes | What the sync does |
|---|---|---|
| **BLOCKER** | `MISSING_PTR`, `EMPTY_OR_INVALID_TARGET`, `UNRESOLVABLE_TARGET`, `MULTIPLE_PTRS` | **skips** the bibl (can't resolve referenced ms) |
| **REVIEW** | `REF_LOCUS_INVALID` | **skips** (fix the referenced loci first) |
| **REVIEW** | `BIDIRECTIONAL_MISMATCH` | **still syncs** the existing A→B direction; creating the missing reverse bibl in B is deferred, so the flag persists for next audit |
| **REVIEW** | `NONDERIVABLE_CITEDRANGE`, `NONFOLIO_IN_JOINBIBL` | none today (count 0); the simple wipe **would remove** these — preserving them is deferred |
| **INFO** | `MULTI_ITEM_REF` | **syncs** — one citedRange per locus (flatten) |
| **INFO** | `REF_NO_LOCI` | **skips** — nothing to generate |

Anything unflagged is **OK** and syncs. The `to_review` shortlist still lists all
BLOCKER + REVIEW rows (e.g. `BIDIRECTIONAL_MISMATCH` stays listed because the
reverse bibl is still missing, even though A→B was synced).

## Step 2 — sync

```bash
python3 maintenance/ms-biblRange-update/biblRange_sync.py          # dry-run (default)
python3 maintenance/ms-biblRange-update/biblRange_sync.py --apply  # write
```

For each join-bibl pointing to **one resolvable** manuscript N: **remove all
`<citedRange>`** children and **regenerate** one per valid locus of N —
`@from`/`@to` and text **copied** from the locus, `unit="folios"` added, **no
other attribute** copied (no `xml:id`), inserted before `<ptr>`. Single-leaf loci
keep only `@from`. Text falls back to a generated `from–to` only if the locus has
none.

**Skipped — existing citedRanges left completely untouched, with a logged
reason:** no/empty/invalid `@target`, unresolvable ms id, multiple manuscript
targets, the referenced ms has a malformed locus (`REF_LOCUS_INVALID`), or it has
no usable loci (`REF_NO_LOCI`). The sync **never wipes a bibl unless it has valid
locus mirrors to put back** — so a host citedRange is removed only to be replaced.

**Safety:** dry-run by default; **idempotent** (a bibl already mirroring its loci
is `no_change`, not rewritten); only changed files are written; XML declaration
and trailing newline preserved; each modified file gets a dated
`<change source="…log">`.

Output: `biblRange_sync_log_<timestamp>.tsv` — one row per join-bibl
(`regenerated` / `no_change` / `skipped`, with reason and before/after).

## Deferred to future work

Reported by the audit, not yet acted on: auto-creating the missing reverse bibl
(`BIDIRECTIONAL_MISMATCH`); preserving hand-curated citedRanges instead of
wiping (`NONDERIVABLE`, needs provenance); paginated references
(`NONFOLIO_IN_JOINBIBL`).

## Files

| File | Role |
|---|---|
| `biblRange_audit.py` | audit + review shortlist (read-only) |
| `biblRange_sync.py` | (re)generate citedRanges (dry-run / `--apply`) |
| `biblRange_audit_*.tsv`, `biblRange_to_review.tsv`, `biblRange_sync_log_*.tsv` | outputs |
| `notes-resp-strategy.md` | background notes for the deferred add-and-keep model |
| `not-used/` | **deprecated** add-only scripts/outputs (see `not-used/README.md`) — not used |
```
