#!/usr/bin/env python3
"""
test_biblRange.py
=================
Tests that bidirectional manuscript references have correct <citedRange>
elements in both directions.

For every pair (ms A, ms B) where:
  - ms A's physDesc/ab/listBibl/bibl has a <ptr> to ms B, AND
  - ms B's physDesc/ab/listBibl/bibl has a <ptr> to ms A

the test verifies that each side's <bibl> contains a <citedRange> matching
every <msItem>/<locus> found in the referenced manuscript's <body>.

Usage
-----
Run from the repository root:

    python3 maintenance/ms-biblRange-update/test_biblRange.py

Exit code is 0 if all checks pass, 1 if any fail.
"""

import os
import re
import glob
import sys
from lxml import etree

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.abspath(os.path.join(SCRIPT_DIR, '../../data/manuscripts/tei'))

MS_URL_RE = re.compile(r'/manuscript/(\d+)/?$')
parser    = etree.XMLParser(recover=True, remove_blank_text=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ms_id_from_url(url):
    m = MS_URL_RE.search(url.strip())
    return m.group(1) if m else None


def parse_ms(ms_id):
    path = os.path.join(DATA_DIR, f'{ms_id}.xml')
    if not os.path.exists(path):
        return None
    return etree.parse(path, parser)


def get_physdesc_refs(tree):
    """
    Return a dict of { ref_ms_id: bibl_element } for all <bibl> entries in
    physDesc/ab/listBibl that have a <ptr @target> pointing to another ms.
    """
    bibls = tree.getroot().xpath(
        './/*[local-name()="physDesc"]'
        '//*[local-name()="ab"]'
        '//*[local-name()="listBibl"]'
        '/*[local-name()="bibl"]'
    )
    refs = {}
    for bibl in bibls:
        ptrs = bibl.xpath('./*[local-name()="ptr"][@target and string-length(@target)>0]')
        if not ptrs:
            continue
        ref_id = ms_id_from_url(ptrs[0].get('target', ''))
        if ref_id:
            refs[ref_id] = bibl
    return refs


def get_msitem_loci(tree):
    """
    Return a list of (from, to) tuples from direct <locus> children of
    <msItem> elements anywhere in <body>.
    """
    loci = tree.getroot().xpath(
        './/*[local-name()="body"]'
        '//*[local-name()="msItem"]'
        '/*[local-name()="locus"]'
    )
    result = []
    for l in loci:
        from_val = l.get('from', '').strip()
        to_val   = l.get('to',   '').strip()
        if from_val:
            result.append((from_val, to_val))
    return result


def get_cited_ranges(bibl):
    """
    Return a set of (from, to) tuples from all <citedRange> children of a bibl.
    """
    return {
        (cr.get('from', '').strip(), cr.get('to', '').strip())
        for cr in bibl.xpath('./*[local-name()="citedRange"]')
    }


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests():
    ms_files = sorted(glob.glob(os.path.join(DATA_DIR, '*.xml')))

    # Build the full reference map: ms_id -> { ref_id -> bibl_element }
    print('Loading manuscripts...')
    trees   = {}
    ref_map = {}
    for path in ms_files:
        ms_id = os.path.splitext(os.path.basename(path))[0]
        tree  = etree.parse(path, parser)
        trees[ms_id]   = tree
        ref_map[ms_id] = get_physdesc_refs(tree)

    # Find all bidirectional pairs (each pair stored once, A < B lexicographically)
    bidir_pairs = set()
    for ms_id, refs in ref_map.items():
        for ref_id in refs:
            if ref_id in ref_map and ms_id in ref_map.get(ref_id, {}):
                pair = tuple(sorted([ms_id, ref_id], key=lambda x: int(x)))
                bidir_pairs.add(pair)

    print(f'Found {len(bidir_pairs)} bidirectional pair(s) to check.\n')

    passes = 0
    failures = 0
    failure_lines = []

    for ms_a, ms_b in sorted(bidir_pairs, key=lambda p: int(p[0])):
        for current_id, ref_id in [(ms_a, ms_b), (ms_b, ms_a)]:
            # The bibl in current_id that points to ref_id
            bibl       = ref_map[current_id][ref_id]
            cited      = get_cited_ranges(bibl)

            # The loci we expect to find in that bibl's citedRanges
            if ref_id not in trees:
                failure_lines.append(
                    f'  FAIL  ms {current_id} -> ms {ref_id}: file not found'
                )
                failures += 1
                continue

            expected_loci = get_msitem_loci(trees[ref_id])
            if not expected_loci:
                # Nothing to check — referenced ms has no loci yet
                continue

            missing = [loc for loc in expected_loci if loc not in cited]

            if missing:
                failures += 1
                failure_lines.append(
                    f'  FAIL  ms {current_id} -> ms {ref_id}: '
                    f'missing citedRange(s): {missing}'
                )
            else:
                passes += 1

    # Summary
    total = passes + failures
    print(f'Results: {passes}/{total} checks passed, {failures} failed.\n')

    if failure_lines:
        print('Failures:')
        for line in failure_lines:
            print(line)
    else:
        print('All bidirectional citedRange checks passed.')

    return failures


if __name__ == '__main__':
    failures = run_tests()
    sys.exit(1 if failures else 0)
