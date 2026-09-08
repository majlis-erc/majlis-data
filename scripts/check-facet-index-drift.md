# `check-facet-index-drift.py`: what it is and how to use it

## Background

Two facet-related bugs shipped to the live manuscripts browse page before being caught:

- **`repository`** (found 2026-09-08): `collection.xconf`'s indexing expression for this
  facet was the raw, unwrapped `descendant::tei:msIdentifier/tei:repository` - but
  `facet-def.xml` marks this facet `function="repository"`, meaning `srophe`'s
  `sf:facet-repository()` is supposed to be the actual logic
  (`normalize-space(...)`). Because the index never applied that normalization, a
  manuscript record whose `<repository>` text happened to wrap across a line in the
  source XML (embedded whitespace) formed its own, separate facet bucket - two
  "National Library of Russia" entries instead of one.
- **`reproductions`** (found the same day, by this script's first run): identical shape.
  `facet-def.xml` marks it `function="reproductions"`; `sf:facet-reproductions()` computes
  a `YES`/`NO` existence check; `collection.xconf`'s expression was still the raw,
  unwrapped XPath.

Separately, the same investigation found that `places`, `works`, `bibl`, and `geo` each
declare real facets in their own `facet-def.xml` files that have **no** corresponding entry
in `collection.xconf` at all - `collection.xconf` was written to cover manuscripts only, and
was never extended. That's a real gap, but a much larger one (9 facets across 4
collections, each needing a correct expression and a reindex) - assessed 2026-09-08 as its
own separate task, deliberately not fixed alongside the two bugs above. This script treats
those 9 as **known, accepted** rather than flagging them every run - see
`KNOWN_ACCEPTED_GAPS` in the script itself.

Full incident narrative: `docs/git-sync-webhook-incidents.md` and
`docs/facet-index-design-notes.md`.

## What the relationship actually is

`facet-def.xml` (one per collection, in the `srophe` repo) is a **declaration**: "this
collection has a facet named X, grouped by this XPath (optionally via a dedicated
function)." `collection.xconf` (in this repo, `majlis-data`) is the **actual Lucene index
config** - a facet only works if it independently has a matching `<facet
dimension="...">` entry there. Nothing keeps the two in sync automatically; that link has
always lived only in a human's head, which is exactly how both bugs above happened. This
script is a mechanical check standing in for that missing link.

## What it checks

1. **Missing entirely**: a facet declared in some `facet-def.xml` with no matching
   `dimension` in `collection.xconf` at all - excluding the 9 known, accepted gaps above.
2. **Possibly unwrapped**: a facet with `group-by/@function="..."` whose
   `collection.xconf` expression is byte-identical to the raw `<sub-path>` text - i.e.
   nothing was done to it, the same shape as both real bugs found so far.

It does **not** try to verify an expression is fully *correct* - only that it isn't
obviously still the untouched original. A clean run is not a guarantee nothing is wrong;
it means these two specific, previously-hit mistakes aren't currently present.

## Exact steps to run it

```bash
cd /path/to/majlis-data
python3 scripts/check-facet-index-drift.py /path/to/srophe
```

- The second argument is the path to a local `srophe` checkout. If omitted, it defaults to
  `../srophe` relative to this repo (i.e. the two repos checked out as siblings, the layout
  used everywhere else in this project).
- No dependencies beyond Python 3's standard library - nothing to install.
- **Exit code `0`**: clean (possibly with known, accepted gaps listed - that's expected,
  not a failure). **Exit code `1`**: something to review, printed by facet name and source
  file. **Exit code `2`**: couldn't find the `srophe` checkout at the given/default path.

## When to run it

Any time a commit touches `srophe`'s `*/facet-def.xml` files or this repo's
`collection.xconf` - in either repo, on any branch - run this locally against your working
copies of both repos **before merging** that change. It is a manual pre-merge check;
nothing runs it automatically (there is no CI pipeline for `majlis-data` yet - see
`~/Desktop/ci-automation-design.md`, which proposes adding this script as an automated
pre-deploy step once that pipeline exists).

## If it reports a "possibly unwrapped" finding

1. Open the named function (`sf:facet-<name>()`) in `srophe`'s
   `src/main/xar-resources/modules/lib/facets.xql` and read exactly what it computes.
2. Update the matching `<facet dimension="...">` expression in `collection.xconf` so it
   computes the identical thing - e.g. wrap in `normalize-space(...)`, or replicate an
   `if(...) then ... else ...` check, whatever that function actually does. There's no
   fixed list of "correct" wrappers; match the function, not a template.
3. Deploy the change (see `docs/runbook.md` - a direct `PUT` to
   `/exist/rest/db/system/config/db/apps/majlis-data/collection.xconf` has worked without
   needing a full package reinstall).
4. **Reindex the affected collection** - the config change alone does not retroactively
   recompute facets for documents already indexed. Use a collection-level `xmldb:reindex()`
   call, not `scripts/reindex-collection.sh`'s per-document approach - the latter was found
   2026-09-08 to not actually fix a facet-grouping problem even run across every affected
   collection (see `docs/runbook.md` section 5 for the full finding and why the
   collection-level call's expected client-side timeout is not a failure):
   ```bash
   run_query 'xmldb:reindex("/db/apps/majlis-data/data/<collection>")'
   ```
5. Re-run this script to confirm the finding is gone, and check the actual browse page.

## If it reports a "missing" finding for a facet that should now be implemented

Add the matching `<facet dimension="...">` entry to `collection.xconf` (matching the
`sub-path` in `facet-def.xml`, or the relevant `sf:facet-<name>()` function's logic if
`group-by` has a `@function`), then follow steps 3-5 above. If the facet in question is one
of the 9 currently listed in `KNOWN_ACCEPTED_GAPS` in the script, remove its entry from
that set once implemented - the check will then confirm it's wired correctly on future
runs, instead of staying silent about it.

## How to reduce the risk of facet/index issues recurring

Lessons from the incidents this script exists because of (`docs/git-sync-webhook-incidents.md`,
`docs/facet-index-design-notes.md`), collected here since none of them are enforced
automatically yet - each one is currently a discipline a person has to remember, not a
guarantee.

- **Never patch `collection.xconf` (or any config) directly on the live server without
  committing the same change back to git.** This is the single root cause behind more than
  one incident: a manual, uncommitted live fix looks like it worked, then silently vanishes
  the next time anything gets redeployed, because a redeploy always installs from git, not
  from whatever is currently live. If a change is worth applying live, it is worth a commit
  first - or immediately after, at the very latest.
- **A `collection.xconf` change does not deploy itself.** Neither the git-sync webhook's
  ordinary file sync nor a merge to `main` makes it live on its own. Two ways to actually
  deploy it: a direct `PUT` to
  `/exist/rest/db/system/config/db/apps/majlis-data/collection.xconf` (confirmed working,
  no package reinstall needed), or a full package reinstall - which only takes effect if
  `expath-pkg.xml`'s version number differs from what's already installed. eXist's package
  installer silently no-ops a same-version reinstall - it returns success without deploying
  anything, which is easy to mistake for "it worked."
- **A config/index change never retroactively applies to already-indexed documents.**
  Reindex the affected collection every time, with a collection-level `xmldb:reindex(...)`
  call - expect it to time out the client connection while it keeps running server-side;
  that's normal, not a failure. `scripts/reindex-collection.sh`'s per-document approach
  avoids that timeout but was found 2026-09-08 to not actually fix a facet-grouping problem
  even run across every affected collection - see `docs/runbook.md` section 5 for the full
  finding. Use the collection-level call for facet fixes.
- **Run `check-facet-index-drift.py` before merging any change to `facet-def.xml` or
  `collection.xconf`.** It catches the two specific mistakes already made once each
  (missing entry, unwrapped function) - it will not catch anything else, so it's a floor,
  not a full correctness check.
- **When a facet has `group-by/@function="..."` in `facet-def.xml`, always match
  `collection.xconf`'s expression to what that named `sf:facet-<name>()` function actually
  computes** - never just copy the `<sub-path>` text verbatim. There is no fixed list of
  "correct" wrapper shapes; read the function.
- **Don't trust an HTTP status code alone as proof a deploy step worked.** More than one
  step in this project's own recovery looked successful by its status code while doing
  nothing: a `200` from a same-version package reinstall that silently no-op'd, and an empty
  response body that was actually a normal, successful `PUT` (curl prints nothing on success
  without an explicit `-w` flag). Confirm the *effect* directly - re-fetch the config, re-run
  the validator, check the actual browse page or facet counts - rather than stopping at "the
  command didn't show an error."
- **None of this is automated yet.** There is no CI pipeline for `majlis-data`, no
  automatic reindex-trigger on a config change, and no post-deploy smoke test confirming a
  browse page actually returns results and correct facet counts after a deploy - all
  proposed in `docs/facet-index-design-notes.md`'s "Possible improvements" and
  `~/Desktop/ci-automation-design.md`, none built. Until that exists, treat every facet/index
  change with the full manual sequence above, every time - there is no safety net catching a
  skipped step.
