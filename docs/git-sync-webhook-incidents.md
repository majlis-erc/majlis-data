# git-sync.xql webhook: incident history

**Purpose:** detailed narrative for the two incidents referenced briefly in
`modules/git-sync.xql`'s own file-level comment. Kept here, rather than growing indefinitely
inside the code file itself, both for readability and because very large comment blocks in
that file were found (2026-09-07) to cause `EXistServlet` to fail to execute it directly via
REST with a generic "Failed to read query" error, even though the exact same content
evaluates correctly via `util:eval()` - the underlying limit was not pinned down further once
this was identified as the likely cause, since keeping the file's own comment short avoids
the problem regardless of the precise mechanism.

## Incident 1 (2026-09-04/05): silent sync failures on brand-new files

A push to this repo's `main` branch on 2026-09-04 added 5 brand-new files that had never
existed in the database before - `data/persons/rel/46.json` and 4 sibling files under
`data/persons/rel/` and `data/manuscripts/rel/`, auto-committed by the
`generate-relations.yml` GitHub Action (not a human edit). GitHub's webhook delivery log
showed the request reaching this endpoint, getting HTTP 200 back, with a response body
reporting `status="okay"` for all 5 files individually. Despite that, none of the 5 files
were actually retrievable on the live server - confirmed directly, by querying the database
itself (`xmldb:get-child-resources()` did not list them; `util:binary-doc-available()` and
`doc-available()` both returned `false` for every one of them). This was traced down on
2026-09-04/05 as part of investigating why a person record's ("person 46") relationship
network diagram was not appearing on its page: the diagram's data file was one of the 5
missing files.

What was already known to work, checked separately during that same investigation: an edit
to a file that already exists on the server (e.g. a person record's biography text being
updated) syncs through this exact same webhook reliably. Only creating a resource that the
server has never seen before appeared to be at risk.

**Root cause**, established by direct, repeatable testing against the live server on
2026-09-05 (see `githubxq:do-update()` and `githubxq:get-file-data()` in the `githubxq`
library itself - installed separately on the server, not part of this repository):
`githubxq:do-update()` calls `xmldb:store()` and reports `status="okay"` purely based on that
call not raising an XQuery exception - it never checks whether the stored resource is
actually retrievable afterward. Manually repeating the exact same fetch-from-GitHub-then-
store-in-eXist steps the library performs, live against the server, reproduced the same
outcome: `xmldb:store()` returned a success value, and the resulting file was still not
retrievable immediately after. This was confirmed to happen even for a plain hand-written
test string stored under a new filename (not real GitHub content at all), ruling out a
JSON-specific or content-specific cause - the bug is in the store/retrieval path itself, not
in what is being stored. The 5 real, unresolvable-at-the-time failures were not reproduced a
second time by that manual replication (fetching and storing the same real files by hand
succeeded), which points to the original failure having been a one-off, non-reproducible
condition on 2026-09-04 rather than a deterministic bug - most plausibly a brief propagation
delay on `raw.githubusercontent.com` (the CDN `githubxq` fetches file content from) for
content that had only existed for seconds. That specific explanation is a plausible theory,
not confirmed - the server's own request/error logs were not available for inspection while
diagnosing this. What IS confirmed, independent of the exact cause, is the underlying defect
this fixed: `githubxq` never verifies a store actually succeeded before reporting it as
`"okay"`, so any transient failure of this kind - whatever triggers it - passes through
completely silently.

**Fix**: `git-sync.xql` no longer returns whatever `githubxq:execute-webhook()` returns,
unexamined. It checks each file `githubxq` reports as touched (`local:verify-and-retry()`) to
confirm the file is actually retrievable afterward, and if not, pauses briefly and retries
the fetch-and-store once directly (`local:retry-store()`), long enough to ride out a brief
transient failure of the kind described above. If the retry also fails, the response reports
a genuine failure instead of a false `"okay"`, so the problem is visible in GitHub's webhook
delivery log at the time it happens, instead of only being discoverable later by someone
noticing a specific piece of missing content (as happened here).

**Not addressed by this fix**: this webhook can only write into the application's data
collection (`/db/apps/majlis-data` and below). It has no ability to deploy changes to
`collection.xconf` or other index/schema configuration, which can only reach the server
through a full package install (`pre-install.xql`, triggered by rebuilding and uploading the
whole package) - a separate, structural limitation. See `facet-index-design-notes.md` and
`runbook.md` in this same `docs/` folder for the fuller design discussion this fix came out
of.

**Known limitation of this fix itself**: `githubxq:do-update()` has two internal branches.
One handles a file going into a collection that already exists on the server, and wraps its
result in a `<message>` child element - this is the branch the incident above went through
(`data/persons/rel` and `data/manuscripts/rel` already existed), and it is the branch
`local:verify-and-retry()` is able to check. The other branch handles a file whose collection
does not exist yet and needs creating first; it does **not** wrap its result in `<message>`
- it mixes `xmldb:create-collection()`'s and `xmldb:store()`'s raw return values directly
into the `<response>` element, with no reliable child element to read a file path back out
of. `local:verify-and-retry()` cannot currently identify or retry a failure in that second
branch, because it cannot determine which file the response even refers to. If a future
problem involves the first file ever added to a brand-new collection under this application
(rather than an addition to an existing collection, as in this incident), start
investigation there.

## Incident 2 (2026-09-07): the webhook overwrote its own real config, again

~24 hours after Incident 1's fix was deployed to the live server with its real config values
substituted in, the live file was found reset back to placeholder values - for the second
time. Nobody had manually rebuilt or re-uploaded the package (confirmed by asking directly).

The actual cause: merging Incident 1's fix as a pull request into `main` was itself a push to
`main`, which this webhook correctly received and processed - and `modules/git-sync.xql` was
one of the files that merge changed. So the webhook, doing exactly what it's supposed to do,
synced its own source file from git and overwrote the live, real-valued copy with the
placeholder text committed in this repository. This is not a one-off fluke: it happens every
single time any future change to this file is merged to `main`, for as long as the file
holds both the sync logic and the real secret in the same place.

**Fix**: the 5 config values now live in `modules/git-sync-config.xql` - a file that is never
committed to this repository (see the `.gitignore` entry for it, and
`modules/git-sync-config.xql.template` for the committed, secret-free template documenting
its structure). Create the real file once, by hand, directly on the server, from that
template. Because it is never in git, no future merge - to `git-sync.xql` or anything else in
the repository - can ever cause the webhook to sync over it and reset it again.

## Resuming this work

Start by re-reading this file, then `modules/git-sync.xql`'s own (now short) file-level
comment, `modules/git-sync-config.xql.template`, and the `.gitignore` entry for
`modules/git-sync-config.xql`. The open, not-yet-fixed items are the "known limitation" in
Incident 1 (new-collection case) and the broader CI-automation design work (a separate,
not-yet-merged draft as of this writing).
