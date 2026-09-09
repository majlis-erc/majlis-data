# `check-facet-index-gaps.sh`: what it is and how to use it

## Background

Deploying the `reproductions` facet fix on 2026-09-08, a collection-level `xmldb:reindex()`
call returned quickly and was mistaken for a completed run. Checking the live counts
afterward showed it wasn't: `repository`'s previously-confirmed "National Library of Russia"
bucket had dropped from `1392` to `1193`, and `reproductions`' `NO` bucket covered only `1334`
of the collection's `1533` total manuscripts - both short by exactly the same `199`, even
though the two facets share no code. This was only found by manually comparing numbers. Full
narrative: `docs/runbook.md` section 5.

`check-facet-index-gaps.sh` (written 2026-09-09) automates that comparison, so a future
incomplete reindex is caught by running a script instead of a human noticing a suspicious
number.

## What it checks

For a given collection and a given facet, it compares:

1. The collection's **true document count** - a live, authenticated query
   (`count(collection(...)//tei:TEI)`).
2. The **sum of that facet's bucket counts** on the actual live browse page - read publicly,
   no credentials needed for this half.

If the two don't match, it reports the gap.

**This is only reliable for a facet where every document is guaranteed to fall into exactly
one bucket, with no legitimate "none of the above" case** - e.g. `reproductions`, a plain
`YES`/`NO` existence check. For a facet like `repository`, where a document can legitimately
have no value at all, a gap doesn't necessarily mean anything is wrong - don't use this script
for that kind of facet, or treat its output there as informational at most, not a failure.

## Exact steps to run it

```bash
REMOTE_EDB_SERVER_URL=https://... \
REMOTE_EDB_SERVER_USERNAME=... \
REMOTE_EDB_SERVER_PASSWORD=... \
scripts/check-facet-index-gaps.sh <db-collection-path> <browse-page-url> <facet-param-name>
```

Concrete example (the exact case this script exists because of):

```bash
scripts/check-facet-index-gaps.sh /db/apps/majlis-data/data/manuscripts \
  https://manuforma-staging.jalit.org/exist/apps/majlis/manuscripts/browse.html \
  facet-reproductions
```

- All three positional arguments are required - the script exits with usage instructions if
  any are missing.
- Credentials are read from the same three environment variables `docs/runbook.md` and
  `scripts/reindex-collection.sh` already use (`REMOTE_EDB_SERVER_URL`,
  `REMOTE_EDB_SERVER_USERNAME`, `REMOTE_EDB_SERVER_PASSWORD`) - set once per terminal session,
  not passed as arguments.
- No dependencies beyond `bash` and `curl` - nothing to install.
- **Exit code `0`**: counts match, no gap. **Exit code `1`**: a gap was found, printed with
  both numbers and the size of the gap. **Exit code `2`**: a usage or setup problem (missing
  credentials, wrong number of arguments, or the page/query couldn't be read at all) - not the
  same as a real gap, check the printed error.

## When to run it

After **any** reindex of a collection whose facets matter - not just after a deploy that
changed `collection.xconf`. A reindex's completion is not reliably signaled by how quickly the
triggering request returns (`docs/runbook.md` section 5) - this script is the actual
confirmation step, run once the reindex has had time to finish, in place of eyeballing numbers
on the browse page by hand.

## If it reports a gap

1. The reindex most likely did not actually complete. Re-run the collection-level
   `xmldb:reindex(...)` call (not the per-document `scripts/reindex-collection.sh` - confirmed
   2026-09-08 not to fix facet grouping even run across every affected collection) and this
   time genuinely wait before checking again, rather than trusting a fast return.
2. Re-run this script. If the gap is now `0`, done.
3. If the gap persists after a second full reindex, this points at something beyond a
   one-off incomplete run - worth investigating which specific documents are missing (e.g. a
   direct query comparing document URIs against what the facet actually covers) rather than
   just repeating the reindex indefinitely.
