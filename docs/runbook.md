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
exactly what caused the 2026-09-02/03 incident. If you need to reapply this repo's static file
without a full package rebuild+redeploy, that's a manual store of this exact file's content to
the path above — ask before improvising here; getting the target path wrong risks another outage.

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
