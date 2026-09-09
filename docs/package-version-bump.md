# The package version (`expath-pkg.xml`): what it is, when it matters, and what it doesn't fix

**Status as of 2026-09-09: not yet done.** `expath-pkg.xml`'s version has been `"0.01"` since
the file was created (confirmed via full git history) and has never been bumped. Decided
2026-09-09 not to bump it as part of the facet-index work, since that work never actually
needed it (see "Why this came up during facet/index work" below).

## What a package version even is, in this project

`majlis-data` isn't just loose files eXist-db reads off disk - it's installed as a package
(the `.xar` file), and `expath-pkg.xml` is that package's manifest: it declares the package's
identity and, critically, a version string. eXist's package manager uses that version to track
which release of the app is currently installed.

## What `pre-install.xql` / `post-install.xql` actually are

Special scripts that eXist's package manager runs automatically - but **only** during an
actual install/reinstall operation, never at any other time:

- `pre-install.xql` runs *before* the package's files are unpacked. In this project, this is
  what deploys the static `collection.xconf` into its real, effective location
  (`/db/system/config/db/apps/majlis-data`).
- `post-install.xql` runs *after*. `srophe`'s copy has a commented-out call to rebuild the
  dynamic facet index (`sf:update-index()`) - deliberately disabled; see
  `git-sync-webhook-incidents.md` and `facet-index-design-notes.md` for why calling that
  function live is dangerous.

Neither of these ever runs just because its file exists somewhere in the database via the
webhook's ordinary file sync - they only run as part of the install process itself.

## Why the version number matters

When you ask the package manager to install a `.xar`, it checks: is a package with this same
name already installed at this exact same version? If yes, it treats the request as
already-satisfied and does nothing - no re-running `pre-install.xql`, no re-copying files -
even though the request explicitly asked it to install.

**This is exactly what happened on 2026-09-08**, deploying the `repository` facet fix: the
first reinstall attempt returned a `200` HTTP status (looking like success) while the live
`collection.xconf` remained completely unchanged, because the version was still `"0.01"` -
identical to what was already installed - and the package manager correctly, by its own
design, treated the reinstall as a no-op. This cost real diagnostic time before the cause was
found; see `docs/runbook.md` section 4, Option B, for the full narrative.

## What bumping the version actually does

Nothing more than changing that one string (e.g. `"0.01"` → `"0.02"`) so the package manager
sees the new `.xar` as genuinely different from what's installed - which is what makes it
actually proceed: unpack files, run `pre-install.xql`, run `post-install.xql`.

## When it would actually be needed - concrete cases

- **`pre-install.xql` or `post-install.xql`'s own script logic changes.** The updated file can
  sync into the database fine via the ordinary webhook, but it will never *execute* its new
  logic until an actual install runs it - and that install will silently no-op without a
  version bump. Example: if the still-unbuilt "trigger a reindex automatically when
  `collection.xconf` changes" idea (flagged as an open gap in `facet-index-design-notes.md`)
  were ever implemented as install-time logic, deploying it would need this.
- **`expath-pkg.xml` itself changes** - e.g. a new dependency requirement. That declaration is
  only checked by the package manager during install.
- **Any one-time setup meant to happen specifically "when this app is (re)installed"**, as
  opposed to "whenever this file happens to exist in the database."

## What it prevents

Exactly the false-positive above: a reinstall that reports success while silently changing
nothing, because the package manager already considers the requested version done. It does
**not** prevent, or fix, anything for changes deployable through the webhook or a direct `PUT`
to a specific path (like `collection.xconf`, both times this was actually needed) - those never
touch this mechanism at all.

## What it does NOT do (answering two questions raised 2026-09-09)

**Does bumping the version, after changing `collection.xconf`, mean the manual
build+upload+reindex sequence becomes unnecessary?** No. A version bump only changes whether a
*manually-triggered* full reinstall (Option B in `docs/runbook.md`) actually takes effect once
run - it automates nothing about triggering that reinstall in the first place. You would still
rebuild the `.xar` by hand, still upload it by hand, still fire the install call by hand. And
reindexing is **never** automatic regardless of version or deploy path - it is always a
separate, manual step (`docs/runbook.md` section 5).

**Why was this raised at all during facet/index work, if it has nothing to do with facet or
index correctness?** Because it caused real, concrete confusion *during* that work, not
because facet fixes depend on it. The first attempt to deploy the `repository` facet fix went
through Option B (full reinstall) before Option A (direct store to `collection.xconf`'s live
path) was found to work better and require none of this. Both `repository` and `reproductions`
were ultimately deployed via Option A, which is entirely version-independent. This document's
content is general `majlis-data` package-deployment knowledge that happened to surface while
doing facet work - it is not itself a facet-correctness fix, and nothing about
`scripts/check-facet-index-drift.py` or the facet fixes depends on it.

## Resuming this work

Not currently planned as active work - revisit only if a future change genuinely needs
`pre-install.xql`/`post-install.xql` logic to run again, or `expath-pkg.xml` itself changes.
See `docs/runbook.md` section 4 ("Which deploy path does a given change actually need?") for
the fuller decision guide this fits into.
