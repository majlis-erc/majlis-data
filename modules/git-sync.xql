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
 :  - modules/git-sync-config.xql must exist on the server (never committed to git - see
 :    modules/git-sync-config.xql.template and the .gitignore entry for the real file)
 :
 : @author Winona Salesky
 : @version 2.0
 :
 : Two incidents (2026-09-04/05: silent sync failures on brand-new files; 2026-09-07: the
 : webhook overwriting its own real config on every merge) shaped this file's current
 : design - the verification+retry wrapper below, and config values living in a separate,
 : never-committed module. Full narrative, root causes, and known limitations:
 : docs/git-sync-webhook-incidents.md at this repository's root. (Kept out of this comment
 : deliberately - a sufficiently large comment block here was found, 2026-09-07, to make
 : EXistServlet fail to execute this file directly via REST with a generic "Failed to read
 : query" error, even though the same content evaluates fine via util:eval(); keeping this
 : comment short avoids the problem regardless of its exact underlying cause.)
 :)

import module namespace githubxq="http://exist-db.org/lib/githubxq";
import module namespace http="http://expath.org/ns/http-client";
import module namespace git-sync-config="http://majlis-erc.github.io/majlis-data/git-sync-config" at "xmldb:exist:///db/apps/majlis-data/modules/git-sync-config.xql";

(: Re-aliased from git-sync-config.xql (never committed - see the file-level comment above
   and that file's own template) so the rest of this file can keep using the same $local:*
   names without further changes. :)
declare variable $local:db-application-path := $git-sync-config:db-application-path;
declare variable $local:git-repo := $git-sync-config:git-repo;
declare variable $local:git-branch := $git-sync-config:git-branch;
declare variable $local:github-private-key := $git-sync-config:github-private-key;
declare variable $local:github-rate-limit-token := $git-sync-config:github-rate-limit-token;

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
 : retrievable, and retries once (after a short pause) if not. See
 : docs/git-sync-webhook-incidents.md for the full background: this exists because
 : githubxq:execute-webhook() was found to report "okay" for files that had not actually
 : been stored.
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
                                    see docs/runbook.md at this repo's root.</message>
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
