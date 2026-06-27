#!/usr/bin/env python3
"""
ms_biblRange_update.py
======================
Populates <citedRange> elements in manuscript TEI XML files based on locus
ranges found in referenced ("joined") manuscripts.

Background
----------
Each manuscript may reference one or more related manuscripts via:

    physDesc/ab/listBibl/bibl/ptr[@target]

where @target is a URL of the form https://jalit.org/manuscript/<id>.

The referenced manuscript records the folio range of its content at:

    body/listBibl/msDesc/msContents/msItem/locus[@from][@to]

This script reads those locus values and writes them back into the
referencing manuscript as:

    <citedRange unit="folios" from="..." to="..."/>

inserted inside the <bibl> element, immediately before the <ptr>.

The relationship can be bidirectional: if ms A references ms B, ms B
typically also references ms A. Processing all files in one pass handles
both directions automatically.

Idempotency / non-destructive behaviour
----------------------------------------
Existing <citedRange> elements are NEVER removed or modified. For each locus
in the referenced manuscript, the script checks whether a <citedRange> with
the same @from/@to already exists in the <bibl>. Only missing ones are added.
Re-running the script on already-updated files is safe and produces no changes.

Note on bibl_xml_id in the report
----------------------------------
The report column bibl_xml_id records the existing xml:id attribute of the
<bibl> element for identification only. The script does NOT modify xml:id
or any other attribute of <bibl> — it only adds/replaces <citedRange> children.

Text-only loci
--------------
If a <locus> element in the referenced manuscript has text content (e.g.
"1r-8v") but no @from attribute, the script skips it and logs a warning to
ms_biblRange_warnings.tsv. These cases should be fixed at the source by
adding proper @from/@to attributes to the <locus> element.

Output
------
- Updated XML files in data/manuscripts/tei/
- ms_biblRange_report.tsv — one row per citedRange (added or existing)
- ms_biblRange_warnings.tsv — one row per skipped text-only locus

Usage
-----
Run from the repository root:

    python3 maintenance/ms-biblRange-update/ms_biblRange_update.py
"""

import os
import re
import glob
import csv
from lxml import etree

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.abspath(os.path.join(SCRIPT_DIR, '../../data/manuscripts/tei'))
REPORT_PATH   = os.path.join(SCRIPT_DIR, 'ms_biblRange_report.tsv')
WARNINGS_PATH = os.path.join(SCRIPT_DIR, 'ms_biblRange_warnings.tsv')

TEI_NS = 'http://www.tei-c.org/ns/1.0'
XML_NS = 'http://www.w3.org/XML/1998/namespace'

# Matches https://jalit.org/manuscript/<id> (with optional trailing slash)
MS_URL_RE = re.compile(r'/manuscript/(\d+)/?$')

parser = etree.XMLParser(recover=True, remove_blank_text=False)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ms_id_from_url(url):
    """Extract the numeric manuscript ID from a jalit.org manuscript URL."""
    m = MS_URL_RE.search(url)
    return m.group(1) if m else None


def readable_xpath(element):
    """
    Build a human-readable XPath using local element names, e.g.:
        TEI/text/body/listBibl/msDesc/msContents/msItem/locus
    Positional indices are omitted for readability.
    """
    parts = []
    el = element
    while el is not None:
        tag = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        parts.append(tag)
        el = el.getparent()
    return '/'.join(reversed(parts))


def get_msitem_loci(ms_path, ref_tree, warning_rows):
    """
    Return all direct locus children of msItem elements found inside <body>.

    Returns a list of dicts with keys: from, to, xpath, xpath_readable.
    Only loci with a non-empty @from attribute are included.

    Loci that have text content but no @from attribute are skipped and
    appended to warning_rows for review.
    ref_tree is the already-parsed ElementTree of the referenced ms file.
    """
    root  = ref_tree.getroot()
    ms_id = os.path.splitext(os.path.basename(ms_path))[0]

    loci = root.xpath(
        './/*[local-name()="body"]'
        '//*[local-name()="msItem"]'
        '/*[local-name()="locus"]'
    )

    # Detects a combined range packed into @from, e.g. "5r-v" or "110r-v"
    COMBINED_RE = re.compile(r'^.+-[a-z]$', re.IGNORECASE)

    result = []
    for locus in loci:
        from_val = locus.get('from', '').strip()
        to_val   = locus.get('to',   '').strip()
        text_val = (locus.text or '').strip()

        locus_xpath          = ref_tree.getpath(locus)
        locus_xpath_readable = readable_xpath(locus)

        if not from_val:
            if text_val:
                # Text-only locus — cannot safely split into from/to; skip and warn
                warning_rows.append({
                    'ref_ms_id':            ms_id,
                    'locus_xpath':          locus_xpath,
                    'locus_xpath_readable': locus_xpath_readable,
                    'locus_text':           text_val,
                    'issue': (
                        'locus has text content but no @from/@to attributes; '
                        'add @from/@to to the <locus> element'
                    ),
                })
            continue

        # @from present — include in results, but warn about data quality issues
        result.append({
            'from':           from_val,
            'to':             to_val,
            'xpath':          locus_xpath,
            'xpath_readable': locus_xpath_readable,
        })

        if COMBINED_RE.match(from_val):
            # @from encodes both start and end, e.g. "5r-v" — should be split
            warning_rows.append({
                'ref_ms_id':            ms_id,
                'locus_xpath':          locus_xpath,
                'locus_xpath_readable': locus_xpath_readable,
                'locus_text':           f'from="{from_val}"',
                'issue': (
                    f'@from contains a combined range ("{from_val}"); '
                    'split into separate @from and @to attributes'
                ),
            })
        elif not to_val:
            # @to is absent or empty — open-ended reference, may be intentional
            warning_rows.append({
                'ref_ms_id':            ms_id,
                'locus_xpath':          locus_xpath,
                'locus_xpath_readable': locus_xpath_readable,
                'locus_text':           f'from="{from_val}" to=""',
                'issue': (
                    f'@to is empty (open-ended from "{from_val}"); '
                    'add @to if this is a range, or confirm it is a single-folio reference'
                ),
            })

    return result


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_file(path, report_rows, warning_rows):
    """
    Update <citedRange> elements in a single manuscript file.

    For each <bibl> in physDesc/ab/listBibl whose <ptr @target> points to
    another manuscript, the locus ranges from that manuscript are written as
    <citedRange unit="folios" from="..." to="..."/> immediately before <ptr>.

    Appends one dict per citedRange to report_rows.
    Appends one dict per skipped text-only locus to warning_rows.
    Returns True if the file was modified.
    """
    tree = etree.parse(path, parser)
    root = tree.getroot()
    modified = False

    ms_id = os.path.splitext(os.path.basename(path))[0]

    bibls = root.xpath(
        './/*[local-name()="physDesc"]'
        '//*[local-name()="ab"]'
        '//*[local-name()="listBibl"]'
        '/*[local-name()="bibl"]'
    )

    for bibl in bibls:
        ptrs = bibl.xpath(
            './*[local-name()="ptr"]'
            '[@target and string-length(@target)>0]'
        )
        if not ptrs:
            continue

        target_url = ptrs[0].get('target', '').strip()
        ref_id = ms_id_from_url(target_url)
        if not ref_id:
            continue

        ref_path = os.path.join(DATA_DIR, f'{ref_id}.xml')
        if not os.path.exists(ref_path):
            continue

        ref_tree = etree.parse(ref_path, parser)
        loci = get_msitem_loci(ref_path, ref_tree, warning_rows)
        if not loci:
            continue

        # Collect existing citedRange (from, to) pairs — these are never removed
        existing_crs = bibl.xpath('./*[local-name()="citedRange"]')
        already_covered = {
            (cr.get('from', '').strip(), cr.get('to', '').strip())
            for cr in existing_crs
        }

        # Insertion point: after the last existing citedRange, or before <ptr> if none
        ptr_el = ptrs[0]
        if existing_crs:
            insert_idx = list(bibl).index(existing_crs[-1]) + 1
        else:
            insert_idx = list(bibl).index(ptr_el)

        added = 0
        for locus in loci:
            key = (locus['from'], locus['to'])
            already_present = key in already_covered

            if not already_present:
                cr = etree.Element(f'{{{TEI_NS}}}citedRange')
                cr.set('unit', 'folios')
                cr.set('from', locus['from'])
                if locus['to']:
                    cr.set('to', locus['to'])
                bibl.insert(insert_idx + added, cr)
                added += 1

            # Report ALL loci (existing and newly added) for a complete picture
            # bibl_xml_id: existing xml:id of the <bibl>, read-only — NOT modified by this script
            report_rows.append({
                'ms_id':                    ms_id,
                'bibl_xml_id':              bibl.get(f'{{{XML_NS}}}id', ''),
                'bibl_xpath':               tree.getpath(bibl),
                'bibl_xpath_readable':      readable_xpath(bibl),
                'citedRange_from':          locus['from'],
                'citedRange_to':            locus['to'],
                'status':                   'existing' if already_present else 'added',
                'ref_ms_id':                ref_id,
                'ref_locus_xpath':          locus['xpath'],
                'ref_locus_xpath_readable': locus['xpath_readable'],
                'ref_locus_from':           locus['from'],
                'ref_locus_to':             locus['to'],
            })

        if added > 0:
            modified = True

    if modified:
        # Preserve the original XML declaration quote style (double quotes)
        xml_bytes = etree.tostring(
            root,
            encoding='UTF-8',
            xml_declaration=True,
            pretty_print=True,
        ).replace(b"<?xml version='1.0' encoding='UTF-8'?>",
                  b'<?xml version="1.0" encoding="UTF-8"?>')
        with open(path, 'wb') as f:
            f.write(xml_bytes)

    return modified


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

REPORT_FIELDS = [
    'ms_id',
    'bibl_xml_id',
    'bibl_xpath',
    'bibl_xpath_readable',
    'citedRange_from',
    'citedRange_to',
    'status',
    'ref_ms_id',
    'ref_locus_xpath',
    'ref_locus_xpath_readable',
    'ref_locus_from',
    'ref_locus_to',
]


WARNING_FIELDS = [
    'ref_ms_id',
    'locus_xpath',
    'locus_xpath_readable',
    'locus_text',
    'issue',
]


def write_report(report_rows):
    with open(REPORT_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, delimiter='\t')
        writer.writeheader()
        writer.writerows(report_rows)
    print(f'Report written to:   {REPORT_PATH}')


def write_warnings(warning_rows):
    with open(WARNINGS_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=WARNING_FIELDS, delimiter='\t')
        writer.writeheader()
        writer.writerows(warning_rows)
    if warning_rows:
        print(f'Warnings written to: {WARNINGS_PATH} ({len(warning_rows)} issue(s))')
    else:
        print(f'No warnings.')


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    ms_files = sorted(glob.glob(os.path.join(DATA_DIR, '*.xml')))
    report_rows  = []
    warning_rows = []
    updated = 0

    for path in ms_files:
        try:
            if process_file(path, report_rows, warning_rows):
                print(f'[UPDATED] {path}')
                updated += 1
        except Exception as e:
            print(f'[ERROR]   {path}: {e}')

    write_report(report_rows)
    write_warnings(warning_rows)
    print(f'\nDone. {updated} file(s) updated, {len(report_rows)} citedRange(s) written.')


if __name__ == '__main__':
    main()
