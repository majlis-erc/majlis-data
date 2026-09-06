xquery version "3.1";

(:~
 : Webhook endpoint for Srophe Web Application
 : XQuery endpoint to respond to Github webhook requests.
 :
 : Requirements
 :  - githubxq library : http://exist-db.org/lib/githubxq
 :  - EXPath Crypto library : http://expath.org/spec/crypto
 :  - eXist-db 3.0 or greater
 :  - Must be run with elevated privileges: sm:chmod(xs:anyURI('/db/apps/srophe/modules/git-sync.xql'), "rwsr-xr-x")
 :
 : @author Winona Salesky
 : @version 2.0
 :
 : ------------------------------------------------------------------------------------
 : ADDENDUM (added 2026-09-05) - verification + one retry wrapped around
 : githubxq:execute-webhook(). Read this section if a webhook
 : delivery in GitHub's log shows status="okay" for a file that turns out not to actually
 : be on the server, or if you are extending or replacing this sync mechanism later.
 :
 : BACKGROUND INCIDENT (2026-09-04): a push to this repo's main branch added 5 brand-new
 : files that had never existed in the database before - data/persons/rel/46.json and 4
 : sibling files under data/persons/rel/ and data/manuscripts/rel/, auto-committed by the
 : generate-relations.yml GitHub Action (not a human edit). GitHub's webhook delivery log
 : showed the request reaching this endpoint, getting HTTP 200 back, with a response body
 : reporting status="okay" for all 5 files individually. Despite that, none of the 5 files
 : were actually retrievable on the live server - confirmed directly, by querying the
 : database itself (xmldb:get-child-resources() did not list them; util:binary-doc-available()
 : and doc-available() both returned false for every one of them). This was traced down on
 : 2026-09-04/05 as part of investigating why a person record's ("person 46") relationship
 : network diagram was not appearing on its page: the diagram's data file was one of the 5
 : missing files.
 :
 : What was already known to work, checked separately during that same investigation: an
 : EDIT to a file that already exists on the server (e.g. a person record's biography text
 : being updated) syncs through this exact same webhook reliably. Only creating a resource
 : that the server has never seen before appears to be at risk.
 :
 : ROOT CAUSE, established by direct, repeatable testing against the live server on
 : 2026-09-05 (see githubxq:do-update() and githubxq:get-file-data() in the githubxq
 : library itself - installed separately on the server, not part of this repository):
 : githubxq:do-update() calls xmldb:store() and reports status="okay" purely based on
 : that call not raising an XQuery exception - it never checks whether the stored resource
 : is actually retrievable afterward. Manually repeating the exact same fetch-from-GitHub-
 : then-store-in-eXist steps the library performs, live against the server, reproduced the
 : same outcome: xmldb:store() returned a success value, and the resulting file was still
 : not retrievable immediately after. This was confirmed to happen even for a plain
 : hand-written test string stored under a new filename (not real GitHub content at all),
 : ruling out a JSON-specific or content-specific cause - the bug is in the store/retrieval
 : path itself, not in what is being stored. The 5 real, unresolvable-at-the-time failures
 : were not reproduced a second time by that manual replication (fetching and storing the
 : same real files by hand succeeded), which points to the original failure having been a
 : one-off, non-reproducible condition on 2026-09-04 rather than a deterministic bug - most
 : plausibly a brief propagation delay on raw.githubusercontent.com (the CDN githubxq
 : fetches file content from) for content that had only existed for seconds. That specific
 : explanation is a plausible theory, not confirmed - the server's own request/error logs
 : were not available for inspection while diagnosing this. What IS confirmed, independent
 : of the exact cause, is the underlying defect this addendum fixes: githubxq never
 : verifies a store actually succeeded before reporting it as "okay", so any transient
 : failure of this kind - whatever triggers it - passes through completely silently.
 :
 : WHAT THIS ADDENDUM CHANGES: this file no longer returns whatever
 : githubxq:execute-webhook() returns, unexamined. It now checks each file githubxq reports
 : as touched (local:verify-and-retry(), below) to confirm the file is actually retrievable
 : afterward, and if not, pauses briefly and retries the fetch-and-store once directly
 : (local:retry-store(), below), long enough to ride out a brief transient failure of the
 : kind described above. If the retry also fails, the response now reports a genuine
 : failure instead of a false "okay", so the problem is visible in GitHub's webhook
 : delivery log at the time it happens, instead of only being discoverable later by
 : someone noticing a specific piece of missing content (as happened here).
 :
 : WHAT THIS ADDENDUM DOES NOT CHANGE: the 5 values below
 : ($local:db-application-path / $local:git-repo / $local:git-branch /
 : $local:github-private-key / $local:github-rate-limit-token) are unmodified from before
 : this addendum - they are placeholder text in this committed source file, not the real
 : values the live server uses. (Confirmed 2026-09-04 by comparing this file against a
 : backup taken from the live server: the deployed copy has real values in their place.
 : Whatever process is responsible for substituting the real values before this file
 : reaches the server needs to keep doing so for this version exactly as before - this
 : addendum does not touch or replace that process, and does not address the risk that the
 : live server's real values could silently drift from whatever this repository expects,
 : the same way this project's collection.xconf drifted and caused a separate, unrelated
 : incident on 2026-09-02/03 - see facet-index-design-notes.md at this repository's root
 : for that incident's writeup.)
 :
 : ALSO NOT ADDRESSED BY THIS ADDENDUM: this webhook can only write into the application's
 : data collection (/db/apps/majlis-data and below). It has no ability to deploy changes to
 : collection.xconf or other index/schema configuration, which can only reach the server
 : through a full package install (pre-install.xql, triggered by rebuilding and uploading
 : the whole package) - a separate, structural limitation, not a bug this addendum could
 : fix. See facet-index-design-notes.md and runbook.md at this repository's root for the
 : fuller design discussion this addendum came out of.
 :
 : KNOWN LIMITATION OF THIS ADDENDUM ITSELF: githubxq:do-update() has two internal
 : branches. One handles a file going into a collection that already exists on the server,
 : and wraps its result in a <message> child element - this is the branch the 2026-09-04
 : incident went through (data/persons/rel and data/manuscripts/rel already existed), and
 : it is the branch local:verify-and-retry() below is able to check. The other branch
 : handles a file whose collection does not exist yet and needs creating first; it does
 : NOT wrap its result in <message> - it mixes xmldb:create-collection()'s and
 : xmldb:store()'s raw return values directly into the <response> element, with no
 : reliable child element to read a file path back out of. local:verify-and-retry() cannot
 : currently identify or retry a failure in that second branch, because it cannot
 : determine which file the response even refers to. If a future problem involves the
 : FIRST file ever added to a brand-new collection under this application (rather than an
 : addition to an existing collection, as in the 2026-09-04 incident), start your
 : investigation here.
 : ------------------------------------------------------------------------------------
 :)

import module namespace githubxq="http://exist-db.org/lib/githubxq";
import module namespace http="http://expath.org/ns/http-client";

(: These 5 values are exactly what this file had before this update - unchanged
   placeholder text, not a real path/repo/branch/key. See the file-level comment above:
   whatever process substitutes the real values before this reaches the server needs to
   keep doing that here, same as before. :)
declare variable $local:db-application-path := 'srophe-repo';
declare variable $local:git-repo := 'git-repo';
declare variable $local:git-branch := 'branch';
declare variable $local:github-private-key := '';
declare variable $local:github-rate-limit-token := '';

(:~
 : Re-fetches one file directly from GitHub's raw-content host and re-stores it, bypassing
 : githubxq entirely (its execute-webhook() needs the original signed payload, which has
 : already been consumed by the time we know a retry is needed).
 :
 : @param $resource-path full database path githubxq reported storing, e.g.
 :        "/db/apps/majlis-data/data/persons/rel/46.json"
 : @return a short human-readable outcome string, folded into the response message so a
 :         retry that still fails is diagnosable from the webhook delivery log alone
 :)
declare function local:retry-store($resource-path as xs:string) as xs:string {
    try {
        let $file-path := substring-after($resource-path, concat($local:db-application-path, '/'))
        let $raw-url := concat(
                            replace($local:git-repo, 'https://github.com/', 'https://raw.githubusercontent.com/'),
                            '/', $local:git-branch, '/', $file-path)
        let $response := http:send-request(
                            <http:request http-version="1.1" href="{xs:anyURI($raw-url)}" method="get">
                                {if($local:github-rate-limit-token != '') then
                                    <http:header name="Authorization" value="{concat('token ',$local:github-rate-limit-token)}"/>
                                else ()}
                                <http:header name="Connection" value="close"/>
                            </http:request>)
        let $status := string($response[1]/@status)
        let $body := $response[2]
        return
            if(starts-with($status, '2') and string-length(string($body)) gt 0) then
                let $file-name := tokenize($resource-path, '/')[last()]
                let $collection := substring($resource-path, 1, string-length($resource-path) - string-length($file-name) - 1)
                return concat('retry re-stored: ', xmldb:store($collection, $file-name, $body))
            else
                concat('retry fetch did not return usable content (HTTP ', $status, ')')
    } catch * {
        concat('retry itself errored: ', $err:code, ': ', $err:description)
    }
};

(:~
 : Confirms each file githubxq:execute-webhook() reported as "okay" is actually
 : retrievable, and retries once (after a short pause) if not. See the ADDENDUM comment
 : at the top of this file for the full background: this exists because
 : githubxq:execute-webhook() was found to report "okay" for files that had not actually
 : been stored (see the 2026-09-04 incident described there).
 :
 : @param $webhook-result whatever githubxq:execute-webhook() returned
 : @return the same responses, but any that were falsely "okay" are now either genuinely
 :         fixed (still "okay") or honestly reported as failed
 :)
declare function local:verify-and-retry($webhook-result as item()*) as item()* {
    for $response in $webhook-result
    return
        if($response/self::response[@status = 'okay'][matches(message, concat('^', $local:db-application-path, '/'))]) then
            let $resource-path := $response/message/text()
            (: doc-available() always returns false for a binary resource (e.g. .json)
               even when the resource genuinely exists - using doc-available() alone here
               would silently miss every JSON file, which is a mistake this same
               investigation made before it was caught (2026-09-04/05). util:binary-doc-
               available() is the correct check for anything that is not XML; this line
               tries both so the check works for either kind of file. :)
            let $exists := util:binary-doc-available(xs:anyURI($resource-path)) or doc-available($resource-path)
            return
                if($exists) then
                    $response
                else
                    let $wait := util:wait(2000)
                    let $retry-outcome := local:retry-store($resource-path)
                    let $exists-after-retry := util:binary-doc-available(xs:anyURI($resource-path)) or doc-available($resource-path)
                    return
                        if($exists-after-retry) then
                            <response status="okay">
                                <message>{$resource-path} - reported okay on first attempt but was not actually
                                    stored; recovered after one retry. See git-sync.xql comments (2026-09-05).</message>
                            </response>
                        else
                            (response:set-status-code(500),
                            <response status="fail">
                                <message>{$resource-path} - githubxq reported okay but the file does not exist,
                                    and a retry did not fix it either ({$retry-outcome}). Needs manual attention -
                                    see runbook.md at this repo's root.</message>
                            </response>)
        else
            $response
};

let $data := request:get-data()
return
    local:verify-and-retry(
        githubxq:execute-webhook($data,
            $local:db-application-path,
            $local:git-repo,
            $local:git-branch,
            $local:github-private-key,
            $local:github-rate-limit-token))
