# Runbook: browse pages return empty / facet counts look wrong

**Date:** 2026-09-03
**Background:** see `facet-index-design-notes.md` (this repo) and
`../../srophe/facet-index-design-notes.md` for the full incident writeup and design risks this
runbook exists because of.

This is a step-by-step guide for diagnosing and recovering from the specific failure mode hit on
2026-09-02/03: manuscript (or other collection) browse pages on staging return zero results, or a
facet shows a count that doesn't match reality. It also documents the REST-API technique used
throughout, since the eXide web UI proved unreliable (stuck sessions, stale output, a disabled
Run button) for long stretches during that incident.

## 0. Prerequisites

You need admin/dba credentials for the target eXist-db server. Set these in your shell once per
session:

```bash
export REMOTE_EDB_SERVER_URL="https://manuforma-staging.jalit.org"
export REMOTE_EDB_SERVER_USERNAME="your-username"
export REMOTE_EDB_SERVER_PASSWORD="your-password"
```

## 1. Run queries via REST instead of eXide

`srophe`'s own `src/main/deploy-resources/redeploy-xar-package.sh` already shows this pattern for
deploys; the same works for any ad-hoc XQuery. Define this helper once per shell session:

```bash
run_query() {
  curl --silent --show-error --request POST --basic \
    --user "${REMOTE_EDB_SERVER_USERNAME}:${REMOTE_EDB_SERVER_PASSWORD}" \
    --header "Content-Type: application/xml" \
    --data-binary @- \
    "${REMOTE_EDB_SERVER_URL}/exist/rest/db" <<EOF
<query xmlns="http://exist.sourceforge.net/NS/exist" cache="no" enclose="no" start="1" max="-1">
  <text><![CDATA[
$1
  ]]></text>
</query>
EOF
}
```

Then any query is just `run_query '...xquery here...'`. This is more reliable than eXide's web
UI for anything long-running or when the UI itself seems stuck — it's a plain synchronous HTTP
call, so the output you see is always the actual, current result.

**If a query might return an XQuery-parse error mentioning a specific error code but no useful
detail**, or if a whole *page* (not a query) is erroring, fetch the raw response body directly —
eXist-db's error pages usually include the real exception and stack trace, which a bare HTTP
status code does not show:

```bash
curl -s "${REMOTE_EDB_SERVER_URL}/exist/apps/majlis/manuscripts/index.html"
```

## 2. Diagnose: is this a text-index problem or a facet-index problem?

Check whether the core Lucene full-text index is healthy — this narrows things down fast:

```bash
run_query 'declare namespace tei="http://www.tei-c.org/ns/1.0";
count(collection("/db/apps/majlis-data/data/manuscripts")//tei:TEI[ft:query(descendant::tei:body, "manuscript")])'
```

- **Returns a healthy-looking count** (in the hundreds/thousands, not 0): the text index itself
  is fine. The problem is more likely in `collection.xconf`'s facet config, or in the browse-page
  query logic (`data:get-records()` in `srophe`'s `modules/lib/data.xqm`) not matching against the
  node type that actually carries a facet-capable `<text>` index block. See
  `../../srophe/facet-index-design-notes.md`.
- **Returns 0 or errors**: something more fundamental is broken (config missing entirely, wrong
  collection path, etc.) — check the next few steps before assuming it's a facet-only issue.

Also check the actual document count vs. what the UI shows, to rule out simple staleness:

```bash
run_query 'declare namespace tei="http://www.tei-c.org/ns/1.0";
(xmldb:collection-available("/db/apps/majlis-data/data/manuscripts"),
 count(collection("/db/apps/majlis-data/data/manuscripts")/tei:TEI))'
```

## 3. Check nothing is already running before triggering anything heavy

```bash
run_query 'system:get-running-xqueries()'
```

If a previous reindex attempt is still listed as running, **wait for it** rather than starting
another one — overlapping reindex attempts on the same collection is a likely way to make things
worse, not better.

## 4. If `collection.xconf` itself needs regenerating

This repo's `collection.xconf` (root of this repo) is the intended single source of truth (see
the design-notes doc) — deployed automatically by `pre-install.xql` whenever this package is
rebuilt and reinstalled. If you've just changed it, or changed the facet-related code in
`srophe`, and need to confirm the live server actually picked it up:

```bash
run_query 'doc-available("/db/system/config/db/apps/majlis-data/collection.xconf")'
```

**Do not** call `srophe`'s `sf:update-index()` to "refresh" this unless you specifically intend to
regenerate it *dynamically from srophe's code* — that overwrites this repo's static file, and is
exactly what caused the 2026-09-02/03 incident.

### Which deploy path does a given change actually need?

This repo reaches the live server through three different mechanisms, each covering different
ground — knowing which one a change needs avoids reaching for a full reinstall (and its
version-bump requirement, below) when it isn't necessary, or missing that it *is*:

- **git-sync webhook** (automatic, fires on every push to `main`): stores whatever files a push
  touches into `/db/apps/majlis-data` and below, via `xmldb:store()`. Covers ordinary data and
  code file changes on their own, with no manual step. Does **not** reach `collection.xconf`'s
  real, effective location (`/db/system/config/db/apps/majlis-data/collection.xconf`) — that
  path is outside `/db/apps/majlis-data` entirely. The webhook does still sync a copy of
  `collection.xconf` to `/db/apps/majlis-data/collection.xconf` (it's a file in the repo like
  any other), but nothing reads *that* copy for indexing — it's inert.
- **Direct store / `PUT`** (manual, one specific path — Option A below): the same effect as the
  webhook, run by hand for whatever path actually needs it, including the real
  `collection.xconf` location, as done 2026-09-08. Version-independent — no package-level
  machinery involved, just "put this exact content at this exact path."
- **Full package reinstall** (manual, requires a version bump — Option B below): the **only**
  path that re-executes `pre-install.xql`/`post-install.xql`, or picks up a change to
  `expath-pkg.xml` itself (dependencies, metadata). Required whenever a change needs
  install-time logic to actually *run* again — not just a file to exist somewhere. There is no
  direct-store equivalent for that; a `PUT` can place a file, but it can't re-run a script that
  only executes during install.

For `collection.xconf` specifically, direct store (Option A) is enough on its own — Lucene reads
it from its live location directly, with no install-time step in between. Reach for Option B
only when a change elsewhere in the package genuinely depends on install-time logic running.

### Option A: direct store (tested working 2026-09-08, no package rebuild needed)

For a `collection.xconf`-only change, this is the simplest path and doesn't need a rebuild at
all — just `PUT` the file straight to its live config path:

```bash
curl --http1.1 -u admin:$REMOTE_EDB_SERVER_PASSWORD -T collection.xconf \
  "$REMOTE_EDB_SERVER_URL/exist/rest/db/system/config/db/apps/majlis-data/collection.xconf"
```

Run from this repo's root, so `collection.xconf` resolves to the file there. Getting the target
path wrong risks another outage like 2026-09-02/03 — double check it against the `doc-available()`
check above before typing it from memory. Verify it landed:

```bash
curl -s "$REMOTE_EDB_SERVER_URL/exist/rest/db/system/config/db/apps/majlis-data/collection.xconf" \
  | grep 'dimension="repository"'   # or whatever line you just changed
```

An empty/no-output response from the `PUT` itself is normal on success — eXist's REST endpoint
returns an empty body; check the *effect* (the line above), not the absence of an error.

### Option B: full package rebuild + reinstall (needed for anything beyond collection.xconf)

Use this if the change also touches something only `pre-install.xql` applies (not just
`collection.xconf`). Tested end-to-end 2026-09-08:

```bash
# 1. Rebuild the .xar (temporarily move out the local backup folder so it isn't bundled in -
#    see "Possible improvements" in facet-index-design-notes.md re: build.xml's lack of excludes)
mv LIVE-BACKUP_manuforma-staging_majlis-data_2026-09-02 /tmp/LIVE-BACKUP-temp-hold
ant xar
mv /tmp/LIVE-BACKUP-temp-hold LIVE-BACKUP_manuforma-staging_majlis-data_2026-09-02

# 2. Before uploading anything, confirm the LOCAL build actually has your change -
#    cheap to check, saves discovering an install "succeeded" on stale content later
unzip -p build/majlis-data-0.01.xar collection.xconf | grep 'dimension="repository"'

# 3. Upload it, overwriting whatever was there before (including any stale .xar left from an
#    earlier, abandoned attempt - this is the same target path every time)
curl --http1.1 -u admin:$REMOTE_EDB_SERVER_PASSWORD -T build/majlis-data-0.01.xar \
  "$REMOTE_EDB_SERVER_URL/exist/rest/db/system/repo/majlis-data-0.01.xar"

# 4. Confirm the uploaded copy in the DB actually has the change too, before installing it
curl -s --http1.1 -u admin:$REMOTE_EDB_SERVER_PASSWORD \
  "$REMOTE_EDB_SERVER_URL/exist/rest/db/system/repo/majlis-data-0.01.xar" -o /tmp/uploaded-check.xar
unzip -p /tmp/uploaded-check.xar collection.xconf | grep 'dimension="repository"'

# 5. Install it
cat > /tmp/reinstall-majlis-data.xml <<'EOF'
<query xmlns="http://exist.sourceforge.net/NS/exist" cache="no" enclose="no" start="1" max="-1">
  <text><![CDATA[
import module namespace repo="http://exist-db.org/xquery/repo";
repo:install-and-deploy-from-db("/db/system/repo/majlis-data-0.01.xar")
  ]]></text>
</query>
EOF
curl -s -o /dev/null -w "install HTTP status: %{http_code}\n" \
  --http1.1 -u admin:$REMOTE_EDB_SERVER_PASSWORD -X POST -H "Content-Type: application/xml" \
  --data-binary @/tmp/reinstall-majlis-data.xml \
  "$REMOTE_EDB_SERVER_URL/exist/rest/db"

# 6. Verify the LIVE config actually changed - a 200 in step 5 is not proof by itself, see below
curl -s "$REMOTE_EDB_SERVER_URL/exist/rest/db/system/config/db/apps/majlis-data/collection.xconf" \
  | grep 'dimension="repository"'
```

**Gotcha hit twice on 2026-09-08, easy to lose an hour to**: `expath-pkg.xml`'s version number
has never been bumped (still `"0.01"` since the file was created). eXist's package installer
silently no-ops a reinstall at the *same* version - step 5 returns `200` as if it worked, but
step 6 still shows the old content, because nothing was actually redeployed. If step 6 doesn't
show your change after a genuine `200` in step 5, this is the first thing to check - bump the
version in `expath-pkg.xml` (e.g. `"0.01"` → `"0.02"`) and repeat steps 1-6. A version bump is
**only** needed for this full-reinstall path - Option A (direct store) is unaffected by it.

### Either way: reindex after

Neither option retroactively recomputes facets for documents already indexed under the old
config - see section 5 below ("Reindexing a collection") for that, and
`scripts/check-facet-index-drift.py` (this repo's `scripts/` folder) for a pre-merge check that
would have caught the two specific mistakes this whole section exists because of.

## 5. Reindexing a collection (route around the proxy timeout)

A single `xmldb:reindex()` call over a whole collection (or the whole data root) reliably exceeds
the reverse proxy's request timeout at current data volumes — you'll see a `504 Gateway Time-out`
after roughly a minute, regardless of whether you call it from eXide or directly via `curl`. Use
`scripts/reindex-collection.sh` instead, which reindexes one document at a time so no single
request is ever slow enough to time out. Run these from the repository root (not from `docs/`,
where this file lives):

```bash
scripts/reindex-collection.sh /db/apps/majlis-data/data/manuscripts        # full run
scripts/reindex-collection.sh /db/apps/majlis-data/data/manuscripts 5      # test run, first 5 docs only
```

Run it once per affected collection (`manuscripts`, `places`, `persons`, `works`, `relations`,
`texts`, `bibl`, ...). It can take a while for a large collection (tens of minutes) — that's
expected; let it finish rather than interrupting it.

**Found 2026-09-08: this per-document approach did not actually fix a facet-grouping problem**
(the `repository` facet-duplication bug — see `facet-index-design-notes.md` and
`scripts/check-facet-index-drift.md`), even run across every affected collection. The browse
page still showed the old, split facet counts afterward. What did work was a single
collection-level `xmldb:reindex()` call — the exact thing this section exists to route around,
because it hits the same proxy timeout below:

```bash
run_query 'xmldb:reindex("/db/apps/majlis-data/data/manuscripts")'
```

Expect a client-side timeout or connection error after roughly a minute — that is just the
reverse proxy giving up on the response, not the server stopping. The reindex keeps running
server-side regardless of whether the client is still connected to see it finish. Fire it, then
wait (roughly 10-15 minutes for the manuscripts collection at current volumes) before checking
results — don't mistake the client-side timeout for a failure and retry repeatedly.

Net effect: **for a facet-related fix, use the collection-level call above, accepting the
timeout, rather than the per-document script.** The per-document script's value (documented
above) is avoiding the timeout entirely — but if it doesn't actually recompute what needs fixing
per-document, that trade isn't worth it for facets specifically. The per-document script may
still be the right tool for other reindex needs (e.g. recovering a broken text index, its
original 2026-09-02/03 use case) - this distinction wasn't tested either way and is worth
confirming before assuming.

**Found 2026-09-08, deploying the `reproductions` fix: a fast return from the collection-level
call is not proof it finished.** After firing the same `xmldb:reindex(...)` call above, it
returned in about a minute - consistent with the timeout above, but mistaken at the time for a
genuine, fast completion (a plausible mistake, since an earlier reindex for the `repository` fix
had also returned quickly and *had* genuinely completed - see the "possibly unwrapped" narrative
in `scripts/check-facet-index-drift.md`). Checking the live counts afterward showed otherwise:
`repository`'s "National Library of Russia" bucket, previously confirmed at `1392`, had dropped
to `1193`; `reproductions`' `NO` bucket covered only `1334` of the collection's `1533` total
manuscripts. Both were short by exactly the same number - `199` - even though the two facets
share no code or expression, which is what confirmed this was a collection-wide reindex gap, not
something wrong with the `reproductions` fix itself. Re-running the identical `xmldb:reindex(...)`
call a second time, and this time waiting roughly 15 minutes before checking (rather than
checking immediately, since it had returned within a minute again), gave the correct, stable
result: `repository` back to `1392`, `reproductions` `NO` at the full `1533`, confirmed unchanged
across several checks a couple of minutes apart. What made the difference between the two
attempts was never confirmed - most likely explanation is that the request happened to complete
in one case and got cut short (client and server both stopping together, rather than the server
surviving past the client's timeout as assumed above) in the other, but this was not verified
against server-side logs, which were not available.

**Practical rule going forward: never treat how quickly this call returns as evidence of whether
it finished, in either direction.** A fast return does not mean it failed (it may have completed
that quickly, as happened once) and does not mean it succeeded (it may have been cut short, as
happened once). The only real confirmation is checking actual facet counts against a known-correct
total afterward - ideally more than once a few minutes apart, since a single reading can still
catch it mid-update.

## 6. Verify

After reindexing, re-check the document count query from step 2, then load the actual browse
page and confirm:

```bash
curl -s -o /dev/null -w "%{http_code}\n" "${REMOTE_EDB_SERVER_URL}/exist/apps/majlis/manuscripts/index.html"
curl -s "${REMOTE_EDB_SERVER_URL}/exist/apps/majlis/manuscripts/index.html?lang=&alpha-filter=ALL" | grep -c "class=\"summary"
```
(Adjust the second check's marker to whatever the current template actually renders per result —
the goal is just confirming the results area isn't empty.)

## Obstacles hit while diagnosing the 2026-09-02/03 incident, in case they recur

- The eXide web UI got into a stuck state (frozen output, disabled Run button) that even a hard
  refresh and a fresh private-browsing tab didn't clear. If that happens again, don't keep
  retrying in the browser — switch to the `run_query` REST approach in step 1 immediately.
- A `bash` script using `set -e` combined with `read -a` reading a file with no trailing newline
  will silently die right after a successful step, with no error message — because `read` returns
  a non-zero exit status at EOF even when it read the data correctly. `scripts/reindex-collection.sh`
  deliberately does not use `set -e` for this reason.
- Testing a URL shape that isn't actually what the app links to (e.g. a bare trailing-slash
  collection root) can surface an unrelated, pre-existing bug and send troubleshooting down the
  wrong path. Always get the *exact* URL from the browser's address bar rather than guessing one.
