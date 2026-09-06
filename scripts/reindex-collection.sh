#!/usr/bin/env bash
set -uo pipefail
# Deliberately NOT using 'set -e' here -- a single transient curl hiccup
# (or `read` returning 1 on a no-trailing-newline file) should not kill
# the whole run.
#
# Reindexes one eXist-db collection, one document at a time, via the REST
# API. Written 2026-09-03 to route around a reverse-proxy timeout that a
# single blocking xmldb:reindex() call over a whole collection (or the
# whole data root) reliably hit -- each individual call here is small and
# fast, so none of them approach that timeout, and progress isn't lost
# between calls the way it is with one big blocking request.
#
# See ../facet-index-design-notes.md and ../runbook.md for the incident
# and design context this came out of.
#
# Usage:
#   REMOTE_EDB_SERVER_URL=https://... \
#   REMOTE_EDB_SERVER_USERNAME=... \
#   REMOTE_EDB_SERVER_PASSWORD=... \
#   ./reindex-collection.sh /db/apps/majlis-data/data/manuscripts [limit]
#
# The optional 2nd argument limits how many documents to process, for a
# quick test run before committing to reindexing an entire collection.

: "${REMOTE_EDB_SERVER_URL:?Set REMOTE_EDB_SERVER_URL first}"
: "${REMOTE_EDB_SERVER_USERNAME:?Set REMOTE_EDB_SERVER_USERNAME first}"
: "${REMOTE_EDB_SERVER_PASSWORD:?Set REMOTE_EDB_SERVER_PASSWORD first}"

COLLECTION="${1:-/db/apps/majlis-data/data/manuscripts}"
# Optional 2nd arg: limit how many docs to process (for a quick test run)
LIMIT="${2:-0}"

run_query() {
  curl --silent --show-error --max-time 90 --request POST --basic \
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

echo "Fetching document list from ${COLLECTION} ..."
DOCLIST_XQ="string-join(for \$d in collection('${COLLECTION}') return document-uri(\$d), '|')"
run_query "${DOCLIST_XQ}" > /tmp/reindex-docs.txt
echo "  listing call done (curl exit: $?)"

IFS='|' read -r -a DOCS < /tmp/reindex-docs.txt
TOTAL="${#DOCS[@]}"
echo "Found ${TOTAL} documents."

if [ "${LIMIT}" != "0" ] && [ "${LIMIT}" -lt "${TOTAL}" ]; then
  echo "Test mode: only processing first ${LIMIT} documents."
  TOTAL="${LIMIT}"
fi

for ((n=0; n<TOTAL; n++)); do
  doc="${DOCS[$n]}"
  echo "[$((n+1))/${TOTAL}] reindexing: ${doc}"
  result=$(run_query "xmldb:reindex('${doc}')")
  if echo "${result}" | grep -qi "exception"; then
    echo "  ERROR: ${result}"
  fi
done

echo "Done."
