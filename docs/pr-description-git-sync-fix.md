# PR: Verify and retry git-sync webhook writes before reporting success

## Problem

The GitHub webhook that syncs `majlis-data` changes to the live staging server
(`modules/git-sync.xql` → `githubxq:execute-webhook()`) reports `status="okay"` for every
file it *attempts* to sync, without ever confirming the write actually succeeded. On
2026-09-04, a merge to `main` (PR #2341, "chore: regenerate relation JSON files") added 5
brand-new files that had never existed in the database before. The webhook fired, returned
HTTP 200, and reported `"okay"` for all 5 — but none of them were actually stored. This was
only discovered on 2026-09-05/06, while investigating why a person record's relationship
network diagram wasn't rendering; the diagram's data file was one of the 5 silently-missing
files.

Editing a file that already exists on the server has always worked reliably through this
same webhook (confirmed separately). Only creating a resource the server has never seen
before appears to be at risk.

## Root cause

`githubxq:do-update()` (in the separately-installed `githubxq` library, not this repo)
calls `xmldb:store()` and reports success purely based on that call not raising an
exception — it never checks whether the resource is actually retrievable afterward. Direct,
repeatable testing against the live server reproduced this exact behavior for a
hand-written test file (ruling out anything JSON- or content-specific): `xmldb:store()`
returned a success value, and the file was still not retrievable immediately after. The
most plausible explanation is a brief propagation delay on `raw.githubusercontent.com`
(the CDN the library fetches file content from) for content that had only existed for
seconds — plausible, not confirmed, since server-side logs weren't available to inspect.

## Fix

`git-sync.xql` no longer returns whatever `githubxq:execute-webhook()` returns, unexamined.
It now:
- Verifies each file githubxq reports as touched is actually retrievable
  (`util:binary-doc-available()` — not `doc-available()`, which always returns `false` for
  binary resources like `.json` regardless of whether they exist; this was a real mistake
  made and caught during this investigation).
- Retries the fetch-and-store once, after a short pause, if verification fails.
- Reports a genuine failure instead of a false `"okay"` if the retry also fails, so the
  problem is visible in GitHub's delivery log at the time it happens, not discovered later
  by chance.

A known, documented limitation: `githubxq:do-update()` has a second branch (creating a file
in a collection that doesn't exist yet) whose response format can't currently be parsed by
this fix — see the in-file comment for detail. The 2026-09-04 incident didn't go through
that branch, so it wasn't guessed at or half-fixed.

Full incident writeup and design discussion: `facet-index-design-notes.md` and
`runbook.md` at this repo's root.

## Verification

Tested against a local eXist-db instance for syntax/logic correctness, then verified live
end-to-end: redelivered the actual GitHub webhook event that originally failed silently
(the `main`-branch merge, not the source-branch commit — those are two different delivery
events), confirmed via direct database queries (`util:binary-doc-available()`) that all 5
previously-missing files are now genuinely present, and confirmed the live page renders the
previously-missing network diagram correctly.

## Note for whoever deploys this

The 5 config values at the top of the file (`$local:db-application-path`,
`$local:git-repo`, `$local:git-branch`, `$local:github-private-key`,
`$local:github-rate-limit-token`) are placeholder text in this commit, same as before this
fix — the real values must still be substituted locally, uncommitted, before deploying,
exactly as with every previous version of this file.
