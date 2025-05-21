#!/usr/bin/env python3
import os
import glob
from lxml import etree
import csv

# ——— CONFIGURATION —————————————————————————————————————————————————
TARGET_TITLE = (
    "MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World"
)

EDITION_TITLE = (
'Cataloging data from the ARCHES project re-used and prepared for electronic publication in the project: '
'MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World'
)
ADDITIONAL_NAMES = [
    "Ezra Stadler",
    "Jakob Shub-Oseledchik",
    "Sara Mattutat",
    "Jonathan Beise",
    "Masoumeh Seydi",
    "Nathan P. Gibson"
]
# Directory containing your XML files:
INPUT_GLOB = r"../../data/*/tei/*.xml"  # adjust as needed

# disable DTD loading & validation + relax ID checks
parser = etree.XMLParser(
    recover=True, ns_clean=False, remove_blank_text=False
)
# ————————————————————————————————————————————————————————————————

def process_file(path):
    tree = etree.parse(path, parser)
    root = tree.getroot()
    rows = []

    # 1) Try titleStmt/title[@level="m"]
    title_els = root.xpath(
        './/*[local-name()="teiHeader"]'
        '/*[local-name()="fileDesc"]'
        '/*[local-name()="titleStmt"]'
        '/*[local-name()="title"][@level="m"]'
    )
    # print("ttl:", title_els[0].text)
    # if not title_els:
    #     print("no titleStmt!!!")
    # else:
    #     ttl_txt = " ".join((title_els[0].text or "").split())

    if title_els and " ".join((title_els[0].text or "").split()) == TARGET_TITLE.strip():
        print("ttl:" , " ".join((title_els[0].text or "").split()))
        parent = title_els[0].getparent()
        rows.append({
            "filepath": path,
            "titleStmt_value": " ".join((title_els[0].text or "").split()),
            "editionStmt_value": "NA"
            # "xpath": rt.getpath(title_el)
        })

    else:
        # 2) Fallback: editionStmt/edition[1]
        edition_els = root.xpath(
            './/*[local-name()="teiHeader"]'
            '/*[local-name()="fileDesc"]'
            '/*[local-name()="editionStmt"]'
            '/*[local-name()="edition"]'
        )
        if not edition_els or " ".join((edition_els[0].text or "").split()) != EDITION_TITLE:
            # nothing to do
            return False
        if edition_els:
            print("edition ttl: ", edition_els[0].text)
            # rows.append({
            # "filepath": path,
            # "titleStmt_value": ttl_txt,
            # "editionStmt_value": " ".join((edition_els[0].text or "").split())
            # "xpath": rt.getpath(title_el)
            # })
        parent = edition_els[0].getparent()

    # Gather all <editor role="contributor"> children
    editors = [
        e for e in parent
        if e.tag.endswith("editor") and e.get("role") == "contributor"
    ]
    # Map existing name → element, and collect names
    existing_map = {}
    for e in editors:
        name = (e.text or "").strip()
        if name:
            existing_map[name] = e
    # print(existing_map)
    # Build full name set
    all_names = set(existing_map) | set(ADDITIONAL_NAMES)
    # print(all_names)
    # Sort alphabetically by last name
    sorted_names = sorted(all_names, key=lambda nm: nm.split()[-1])
    # print(sorted_names)

    # Remove old editor elements
    for e in editors:
        parent.remove(e)

    # Determine tag/namespace to use for new elements
    tag = editors[0].tag if editors else "editor"

    # Re‐append in sorted order
    for name in sorted_names:
        if name in existing_map:
            parent.append(existing_map[name])
        else:
            new_el = etree.Element(tag)
            new_el.set("role", "contributor")
            new_el.text = name
            parent.append(new_el)

    # Write back, preserving pretty-print
    tree.write(path,#.replace(".xml", "_new.xml"),
               encoding="utf-8",
               xml_declaration=True,
               pretty_print=True)
    # print(rows)
    # with open("titles.tsv", "w", encoding="utf-8", newline="") as f:
    #     w = csv.DictWriter(
    #         f,
    #         fieldnames=["filepath", "titleStmt_value", "editionStmt_value"],
    #         delimiter="\t"
    #     )
    #     w.writeheader()
    #     w.writerows(rows)
    return True

def main():
    all_xml = glob.glob(INPUT_GLOB)
    xml_files = [
        fn for fn in all_xml
        # fn = ../../data/<subdir>/tei/<file>
        if os.path.basename(os.path.dirname(os.path.dirname(fn))) != "bibl"
    ]
    for filepath in xml_files:
        print(filepath)
        updated = process_file(filepath)
        print(f"{'Updated' if updated else 'Skipped '} {filepath}")

if __name__ == "__main__":
    main()

