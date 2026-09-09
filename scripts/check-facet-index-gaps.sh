#!/usr/bin/env bash
set -uo pipefail
# Compares a collection's true document count against how many documents a given facet
# dimension accounts for on the live browse page, for facets where every document is
# guaranteed to fall into exactly one bucket (e.g. a YES/NO existence check like
# "reproductions") - for those, any gap between the two numbers means the facet index is
# incomplete (e.g. an interrupted reindex), not a legitimate absence of data.
#
# Written 2026-09-09 after a real incident: a collection-level xmldb:reindex() call
# returned quickly, was mistaken for a completed run, and left 199 of 1533 manuscripts
# unaccounted for in both the "repository" and "reproductions" facets - only noticed by
# manually comparing counts. See docs/runbook.md section 5 for the full narrative.
#
# NOT reliable for a facet where a document can legitimately have no value at all (e.g.
# "repository" - some manuscripts genuinely lack one). Use this only for facets that
# partition every document into one of their buckets, with no legitimate "none of the
# above" case.
#
# Usage:
#   REMOTE_EDB_SERVER_URL=https://... \
#   REMOTE_EDB_SERVER_USERNAME=... \
#   REMOTE_EDB_SERVER_PASSWORD=... \
#   ./check-facet-index-gaps.sh <db-collection-path> <browse-page-url> <facet-param-name>
#
# Example (the exact case this script exists because of):
#   ./check-facet-index-gaps.sh /db/apps/majlis-data/data/manuscripts \
#     https://manuforma-staging.jalit.org/exist/apps/majlis/manuscripts/browse.html \
#     facet-reproductions
#
# Exit code 0: counts match, no gap. Exit code 1: a gap was found. Exit code 2: usage/setup
# error (missing credentials, bad arguments, or the page/query could not be read).

: "${REMOTE_EDB_SERVER_URL:?Set REMOTE_EDB_SERVER_URL first}"
: "${REMOTE_EDB_SERVER_USERNAME:?Set REMOTE_EDB_SERVER_USERNAME first}"
: "${REMOTE_EDB_SERVER_PASSWORD:?Set REMOTE_EDB_SERVER_PASSWORD first}"

if [ "$#" -ne 3 ]; then
  echo "Usage: $0 <db-collection-path> <browse-page-url> <facet-param-name>" >&2
  echo "Example: $0 /db/apps/majlis-data/data/manuscripts https://.../manuscripts/browse.html facet-reproductions" >&2
  exit 2
fi

COLLECTION="$1"
BROWSE_URL="$2"
FACET_PARAM="$3"

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

echo "Checking true document count for ${COLLECTION} ..."
DECLARE_TEI="declare namespace tei=\"http://www.tei-c.org/ns/1.0\";"
TOTAL=$(run_query "${DECLARE_TEI} count(collection('${COLLECTION}')//tei:TEI)")
if ! [[ "$TOTAL" =~ ^[0-9]+$ ]]; then
  echo "ERROR: could not get a document count - server returned: ${TOTAL}" >&2
  exit 2
fi
echo "  total documents: ${TOTAL}"

echo "Fetching ${BROWSE_URL} and summing ${FACET_PARAM} counts ..."
PAGE=$(curl --silent --max-time 60 "${BROWSE_URL}")
if [ -z "$PAGE" ]; then
  echo "ERROR: browse page returned no content" >&2
  exit 2
fi

# Extract every "(<number>)" that immediately follows this facet's links on the page.
COUNTS=$(echo "$PAGE" | grep -o "${FACET_PARAM}=[^\"]*\"[^<]*<span class=\"count\"> ([0-9]*) " \
  | grep -o '([0-9]*)' | tr -d '()')

if [ -z "$COUNTS" ]; then
  echo "ERROR: found no ${FACET_PARAM} counts on the page - check the facet-param-name argument" >&2
  exit 2
fi

SUM=0
for c in $COUNTS; do
  SUM=$((SUM + c))
done
echo "  ${FACET_PARAM} bucket count(s) found: $(echo "$COUNTS" | tr '\n' ' ')"
echo "  sum: ${SUM}"

GAP=$((TOTAL - SUM))
if [ "$GAP" -eq 0 ]; then
  echo "OK: ${FACET_PARAM} accounts for all ${TOTAL} documents, no gap."
  exit 0
else
  echo "GAP FOUND: ${FACET_PARAM} accounts for ${SUM} of ${TOTAL} documents (${GAP} missing)."
  echo "If this facet is meant to cover every document with no legitimate 'none' case (like a"
  echo "YES/NO existence check), this points at an incomplete reindex - see docs/runbook.md"
  echo "section 5 for how to re-run it and confirm completion properly this time."
  exit 1
fi
