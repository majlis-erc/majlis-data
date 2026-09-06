# Data-deploy and index design: risks and possible improvements

**Date:** 2026-09-03 (incident occurred 2026-09-02 through 2026-09-03)
**Companion file:** see `../../srophe/facet-index-design-notes.md` for the app-repo side of this —
the two are meant to be read together, since the 2026-09-02/03 incident described below spans
both repos.

## What happened (short version)

This repo carries its own checked-in `collection.xconf` (repo root), including a hand-written
`tei:TEI` facet block whose own comment records that it was already added once before, to fix the
exact same "manuscript browse page facet sidebar renders empty" problem this 2026-09-02/03
incident revisited.
That file is deployed automatically to `/db/system/config/db/apps/majlis-data` by
`pre-install.xql` whenever the `majlis-data` package is rebuilt and (re)installed — the "rebuild
and upload" step done manually on 2026-09-02.

Separately, the `srophe` app repo has its *own*, independent, dynamically-generated version of
the same config (`sf:build-index()` in `modules/lib/facets.xql`), writable to the exact same live
path via `sf:update-index()`. Running that on 2026-09-02/03 (in an attempt to fix an unrelated
cosmetic bug) silently overwrote this repo's already-correct, already-fixed `collection.xconf`
with an incomplete one, breaking browse-page results across every collection on staging.

## Risks in the current design

1. **No CI/CD for this repo's own deploys.** Unlike `srophe` (which has `ci.yml` auto-building
   and redeploying on push to `master`), `majlis-data`'s two GitHub Actions workflows
   (`fix-xmlns.yml`, `generate-relations.yml`) are data-hygiene only — nothing here rebuilds or
   redeploys the package automatically. Any change to `collection.xconf`, `post-install.xql`,
   `pre-install.xql`, or anything else package-level requires a manual local `mvn`/build step,
   then a manual `curl` upload + redeploy against the staging server. That's slower, undocumented
   as a repeatable procedure, and easy to get wrong — during the 2026-09-02/03 incident described
   above, the equivalent manual reindex step on the `srophe` side (a full-collection
   `xmldb:reindex()` call) repeatedly hit the staging proxy's request timeout (`504 Gateway
   Time-out`) and had to be reworked into a slower one-document-at-a-time script instead; see
   `../../srophe/facet-index-design-notes.md` for that side of it.
2. **`collection.xconf` here is a second, competing source of truth.** It duplicates facet
   definitions that also exist, differently expressed, as `facet-def.xml` files + dynamic
   generation logic in `srophe`. Nothing keeps the two in sync, and nothing detects drift between
   them — this repo's copy silently "just worked" for a long time specifically *because* nobody
   had triggered `srophe`'s generator recently enough to clobber it.
3. **Two different, poorly-documented paths get data/config to the live server.** Per
   `online-deploy.md` (in `srophe`): individual data-file edits likely reach staging within
   minutes via a GitHub webhook calling `srophe`'s `git-sync.xql`, which writes files directly
   into the live collection — bypassing this repo's own build/package/pre-install pipeline
   entirely. Package-level changes (like `collection.xconf`) need the full manual rebuild+upload
   instead. Which path applies to which kind of change is inferred, not written down reliably,
   and the webhook mechanism itself is explicitly flagged in that doc as "not directly confirmed"
   from either repo's contents alone.
4. **No validation on data before/as it reaches the live collection.** Whether via the webhook
   path or a package rebuild, nothing checks that changed TEI files are well-formed or
   schema-valid before they land in the running collection.
5. **No post-deploy check that indexing/search still works.** Same gap as the `srophe` side —
   nothing here verifies, after a package deploy, that browse/facet results are still non-empty.

## Possible improvements

- **Add a CI workflow that builds and redeploys this package automatically on push to the
  default branch**, mirroring `srophe`'s `ci.yml` `deploy-staging` job (same
  upload/redeploy/cleanup script pattern would work here too, pointed at this repo's own
  package). Removes the manual rebuild+upload step as a routine task.
- **Make this repo's `collection.xconf` the single authoritative source**, per the companion
  doc's recommendation, and have `srophe` stop being able to silently overwrite it — either by
  removing/disabling `srophe`'s dynamic generator's write path, or turning it into a checker that
  flags drift against this file instead of overwriting it.
- **Document the actual data-flow to staging, and confirm it.** Get the webhook configuration
  (repo Settings → Webhooks) and the server-side `access-config.xml` actually inspected once
  (both currently undocumented/unconfirmed per `online-deploy.md`), then write down plainly: which
  kinds of changes sync automatically within minutes, and which require a manual/CI package
  deploy.
- **Add basic validation on data changes** — e.g., a GitHub Actions job that checks changed
  `data/**/*.xml` files are well-formed (and ideally schema-valid against the TEI ODD this project
  uses) before they can reach `main`, catching a malformed record before it ever syncs live.
- **Add a post-deploy smoke test** here too, same idea as the companion doc: after any package
  redeploy, hit a known browse URL and confirm non-empty results.

## Resuming this work

Start by re-reading, in order:
1. This file and `../../srophe/facet-index-design-notes.md`.
2. `collection.xconf` (this repo's root) — note its own inline comments documenting a prior fix
   for the same underlying problem.
3. `pre-install.xql` — the `xdb:store-files-from-pattern(..., "*.xconf")` call that deploys
   `collection.xconf` automatically on package install.
4. `post-install.xql`, `repo.xml`, `expath-pkg.xml` — the rest of this package's install
   lifecycle.
5. `../../srophe/online-deploy.md` — what's confirmed vs. assumed about how changes here actually
   reach the live/staging server.

The open design decision to make first (shared with the companion doc) is the "single source of
truth for `collection.xconf`" question — most other improvements here depend on that being
settled first.
