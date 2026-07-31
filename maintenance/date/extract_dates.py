#!/usr/bin/env python3
"""
Gather every date-related element/attribute occurring anywhere in
data/<entity>/tei/*.xml (manuscripts, persons, places, works, relations,
bibl) plus the standalone data/tei/*.xml file, and write one row per
occurrence to a TSV report.

An element counts as "date-related" if either:
  - its tag name is one of DATE_ELEMENT_NAMES (date, origDate, floruit),
    regardless of whether it carries any attributes, or
  - it carries one of the TEI att.datable attributes (when, notBefore,
    notAfter, ...). "from"/"to" are treated as date attributes on any
    element EXCEPT those in NON_DATE_CONTEXT_ELEMENTS, since in this
    corpus <locus from="" to=""> and <citedRange from="" to=""> use
    from/to as folio/page locators rather than dates.

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
EXCLUDED_ENTITY_DIRS = set()
# data/tei/*.xml doesn't fit the data/<entity>/tei/ pattern (no entity
# subdirectory), so it's scanned separately under the "tei" entity label.
STANDALONE_GLOB = "data/tei/*.xml"
STANDALONE_ENTITY = "tei"

DATE_ELEMENT_NAMES = {"date", "origDate", "floruit"}

# Attributes that unambiguously signal a date, on any element.
DATE_ATTRS_ALWAYS = {
    "when", "notBefore", "notAfter",
    "when-iso", "notBefore-iso", "notAfter-iso",
    "when-custom", "notBefore-custom", "notAfter-custom",
    "datingPoint", "datingMethod", "calendar", "period",
}

# from/to are ambiguous: also used as non-date locators on some elements.
DATE_ATTRS_CONTEXTUAL = {"from", "to", "from-iso", "to-iso", "from-custom", "to-custom"}
NON_DATE_CONTEXT_ELEMENTS = {"locus", "citedRange"}

# <change when="..."> (teiHeader/revisionDesc/change) timestamps a git-history
# style revision entry, not a date fact about the entity itself, so it's
# excluded here even though @when otherwise matches DATE_ATTRS_ALWAYS.
EXCLUDED_ELEMENT_NAMES = {"change"}


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def is_date_related(tag: str, attrib: dict) -> bool:
    if tag in EXCLUDED_ELEMENT_NAMES:
        return False
    if tag in DATE_ELEMENT_NAMES:
        return True
    if any(a in DATE_ATTRS_ALWAYS for a in attrib):
        return True
    if tag not in NON_DATE_CONTEXT_ELEMENTS and any(a in DATE_ATTRS_CONTEXTUAL for a in attrib):
        return True
    return False


def build_xpath(ancestors_with_index):
    return "/" + "/".join(
        f"{tag}[{idx}]" if idx else tag for tag, idx in ancestors_with_index
    )


def iter_element_paths(root):
    """Yield (element, human_readable_xpath) for every element in the tree."""
    # index among same-tag siblings under the same parent, 1-based, omitted when unique
    def walk(elem, path):
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
            yield child, build_xpath(child_path)
            yield from walk(child, child_path)

    root_tag = strip_ns(root.tag)
    root_path = [(root_tag, None)]
    yield root, build_xpath(root_path)
    yield from walk(root, root_path)


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

    for elem, xpath in iter_element_paths(root):
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
