#!/usr/bin/env python3
"""
Gather <date>/<origDate> elements that live inside <body> (i.e. not inside
<teiHeader>) across data/<entity>/tei/*.xml plus the standalone
data/tei/*.xml file, and write one row per occurrence to a TSV report.

The 'bibl' entity is skipped entirely -- its records aren't in scope for
this pass.

An element counts as "date-related" if:
  - its tag name is <date> or <origDate>, and
  - it is NOT inside <teiHeader> (teiHeader dates, e.g. publicationStmt/date
    or editor/date, aren't relevant here -- only dates that describe the
    manuscript/person/place/etc. itself, under <body>, are).

Usage:
    python3 maintenance/date/extract_dates.py [--out FILE.tsv]

Run from the repository root (paths are resolved relative to it).
"""
import argparse
import csv
import glob
import os
import xml.etree.ElementTree as ET

TEI_NS = "http://www.tei-c.org/ns/1.0"

ENTITY_GLOB = "data/*/tei/*.xml"
# 'bibl' records are out of scope for this pass -- leave the folder out.
EXCLUDED_ENTITY_DIRS = {"bibl"}
# data/tei/*.xml doesn't fit the data/<entity>/tei/ pattern (no entity
# subdirectory), so it's scanned separately under the "tei" entity label.
STANDALONE_GLOB = "data/tei/*.xml"
STANDALONE_ENTITY = "tei"

# Only these two tags are in scope now; see is_date_related() below.
DATE_ELEMENT_NAMES = {"date", "origDate"}

# --- Broader, attribute-based detection used by the previous pass ---
# This used to flag any element carrying an att.datable attribute
# (when/notBefore/notAfter/etc.), plus <floruit>, in addition to bare
# <date>/<origDate> tags. Commented out (not deleted) because this pass
# only needs <date> and <origDate> elements inside <body>; a later,
# broader pass may want this logic back.
# DATE_ELEMENT_NAMES = {"date", "origDate", "floruit"}
#
# # Attributes that unambiguously signal a date, on any element.
# DATE_ATTRS_ALWAYS = {
#     "when", "notBefore", "notAfter",
#     "when-iso", "notBefore-iso", "notAfter-iso",
#     "when-custom", "notBefore-custom", "notAfter-custom",
#     "datingPoint", "datingMethod", "calendar", "period",
# }
#
# # from/to are ambiguous: also used as non-date locators on some elements.
# DATE_ATTRS_CONTEXTUAL = {"from", "to", "from-iso", "to-iso", "from-custom", "to-custom"}
# NON_DATE_CONTEXT_ELEMENTS = {"locus", "citedRange"}
#
# # <change when="..."> (teiHeader/revisionDesc/change) timestamps a git-history
# # style revision entry, not a date fact about the entity itself, so it's
# # excluded here even though @when otherwise matches DATE_ATTRS_ALWAYS.
# EXCLUDED_ELEMENT_NAMES = {"change"}


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def is_date_related(tag: str, attrib: dict) -> bool:
    # --- Previous broader check (element name OR att.datable attributes) ---
    # if tag in EXCLUDED_ELEMENT_NAMES:
    #     return False
    # if tag in DATE_ELEMENT_NAMES:
    #     return True
    # if any(a in DATE_ATTRS_ALWAYS for a in attrib):
    #     return True
    # if tag not in NON_DATE_CONTEXT_ELEMENTS and any(a in DATE_ATTRS_CONTEXTUAL for a in attrib):
    #     return True
    # return False

    # Current scope: only bare <date>/<origDate> tags (attributes on them
    # don't matter here -- whether or not it's date/origDate is enough).
    # Whether it's inside <teiHeader> is checked separately by the caller
    # via the in_header flag from iter_element_paths().
    return tag in DATE_ELEMENT_NAMES


def build_xpath(ancestors_with_index):
    return "/" + "/".join(
        f"{tag}[{idx}]" if idx else tag for tag, idx in ancestors_with_index
    )


def iter_element_paths(root):
    """Yield (element, human_readable_xpath, in_header) for every element.

    in_header is True for <teiHeader> itself and everything under it, so
    callers can keep only elements that live under <text>/<body> instead.
    """
    # index among same-tag siblings under the same parent, 1-based, omitted when unique
    def walk(elem, path, in_header):
        children_by_tag = {}
        for child in elem:
            children_by_tag.setdefault(strip_ns(child.tag), []).append(child)
        counters = {}
        for child in elem:
            ctag = strip_ns(child.tag)
            siblings = children_by_tag[ctag]
            if len(siblings) > 1:
                counters[ctag] = counters.get(ctag, 0) + 1
                idx = counters[ctag]
            else:
                idx = None
            child_path = path + [(ctag, idx)]
            child_in_header = in_header or ctag == "teiHeader"
            yield child, build_xpath(child_path), child_in_header
            yield from walk(child, child_path, child_in_header)

    root_tag = strip_ns(root.tag)
    root_path = [(root_tag, None)]
    yield root, build_xpath(root_path), False
    yield from walk(root, root_path, False)


def find_entity_files():
    files = []
    for path in sorted(glob.glob(ENTITY_GLOB)):
        entity = path.split(os.sep)[1]
        if entity in EXCLUDED_ENTITY_DIRS:
            continue
        files.append((entity, path))
    for path in sorted(glob.glob(STANDALONE_GLOB)):
        files.append((STANDALONE_ENTITY, path))
    return files


def extract_rows(entity, filepath):
    rows = []
    try:
        tree = ET.parse(filepath)
    except ET.ParseError as e:
        print(f"WARNING: failed to parse {filepath}: {e}")
        return rows
    root = tree.getroot()

    for elem, xpath, in_header in iter_element_paths(root):
        # teiHeader dates (publicationStmt/date, editor/date, revisionDesc/
        # change, ...) aren't relevant -- only <body> dates are in scope.
        if in_header:
            continue
        tag = strip_ns(elem.tag)
        attrib = {strip_ns(k): v for k, v in elem.attrib.items()}
        if not is_date_related(tag, attrib):
            continue
        value = (elem.text or "").strip()
        attr_names = "; ".join(attrib.keys())
        attr_values = "; ".join(attrib.values())
        rows.append({
            "entity": entity,
            "file": os.path.basename(filepath),
            "value": value,
            "xpath": xpath,
            "attributes": attr_names,
            "attribute_values": attr_values,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="maintenance/date/date_values.tsv",
        help="output TSV path (default: maintenance/date/date_values.tsv)",
    )
    args = parser.parse_args()

    all_rows = []
    for entity, filepath in find_entity_files():
        all_rows.extend(extract_rows(entity, filepath))

    fieldnames = ["entity", "file", "value", "xpath", "attributes", "attribute_values"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
