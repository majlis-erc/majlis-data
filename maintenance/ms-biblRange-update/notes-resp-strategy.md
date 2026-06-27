# Strategy: make `citedRange` updates self-correcting with `@resp`

## Problem

The current `ms_biblRange_update.py` is **add-only**: it never removes existing
`citedRange` elements. That is not self-correcting:

1. If a source `<locus>` is **fixed** (e.g. `5r-v` -> `5r`/`5v`), the next run
   adds the corrected `citedRange`, but the stale `5r-v` one stays -> duplicate /
   wrong data.
2. If a source `<locus>` is **deleted or changed**, the orphaned `citedRange`
   lingers forever.

## Why "remove all citedRanges and regenerate" is wrong

`citedRange` is used **all over the corpus**, not just in manuscript-join bibls:

- ~977 `unit="p"`, plus `unit="page"`, `unit="section"`, and ~1415 empty
  `unit="folios"` -> page/section citations to secondary literature and other
  references, unrelated to the join mechanism.
- Only ~193 carry `unit="folios" from=... to=...` (plus 3 malformed `from`-only).

A blanket wipe would destroy thousands of unrelated, hand-entered citations.
Critically, there is currently **no marker** distinguishing a script-generated
`citedRange` from a human-entered one — they are byte-identical.

## Recommended strategy: scoped, provenance-marked *sync* (not wipe)

Make the script **own** only the citedRanges it creates, identified by `@resp`,
and reconcile them each run.

### What is `@resp`?

`@resp` ("responsibility") is a standard TEI attribute (from
`att.global.responsibility`) that records *who or what is responsible for* a
piece of markup. Its value is a pointer — typically a `#`-reference to an element
that identifies the agent.

## 1. Declare the responsible agent once per file

In the `teiHeader`'s `<titleStmt>` — next to the existing `<respStmt>` — add one
with an `xml:id`:

```xml
<respStmt xml:id="jalit-join">
  <resp>citedRange for manuscript joins generated automatically from the folio range (locus) of the referenced manuscript</resp>
  <name>ms_biblRange_update.py</name>
</respStmt>
```

The `xml:id` is what the `@resp` pointer resolves to. It must be unique within
each file, and the script should add it idempotently (insert only if absent).

## 2. Tag every generated `citedRange` with `resp="#jalit-join"`

```xml
<citedRange unit="folios" from="2r" to="4v" resp="#jalit-join"/>
<ptr target="https://jalit.org/manuscript/1319"/>
```

The leading `#` means "the element with `xml:id="jalit-join"` in this document."

## 3. New script algorithm: "own-and-sync"

Per run, for each **join-bibl** (a `<bibl>` containing
`<ptr target=".../manuscript/N"/>`):

1. **Remove** every `<citedRange>` in that bibl where `@resp="#jalit-join"` —
   the script's own, possibly-stale entries.
2. **Regenerate** the full current set from the referenced ms's `<locus>`
   values, each written *with* `resp="#jalit-join"`.
3. **Never touch** any `citedRange` that lacks `resp="#jalit-join"` — the safety
   guarantee for hand-entered ranges, page citations, everything else.
4. Ensure the `<respStmt xml:id="jalit-join">` exists in the header.

This makes the script self-correcting: fix a source `locus`, re-run, and the old
`5r-v` disappears while the corrected `5r`/`5v` is written — no duplicates, no
orphans. It stays idempotent (a clean run produces zero diffs).

## Two things to confirm before coding

1. **Schema validation.** `@resp` is normally available on every element
   (via `att.global`), including `<citedRange>`. But this project may use a
   customized ODD/RNG. Validate one tagged file before committing the batch.
2. **First-run diff.** The ~196 ranges already written are *unmarked*. The first
   marked run will rewrite them to add `resp="#jalit-join"` — a one-time,
   expected diff. After that it is stable.
