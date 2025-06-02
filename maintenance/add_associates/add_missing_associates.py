#!/usr/bin/env python3
"""
fix_editors.py

For every XML file in the specified directory:
  - If teiHeader/fileDesc/titleStmt/title[@level="m"]
    == "MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World",
      then update the editors under titleStmt.
  - Else, if teiHeader/fileDesc/editionStmt/edition[1]
    == "MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World",
      then update the editors under editionStmt.

In either case:
  1. Gather all existing <editor role="contributor"> elements (keeping each node intact).
  2. Extract their names (element.text).
  3. Extend that set with the fixed list of 16 names.
  4. Sort alphabetically (case-insensitive).
  5. Remove all original <editor> nodes from the parent.
  6. Re-insert (in sorted order) the original elements where they belong,
     and create fresh <editor role="contributor">Name</editor> for any missing names.
  7. Write the file back (pretty-printed).
  8. Record, for each file, the existing contributor names before changes and the final contributor names after update.

At the end, write a TSV report (`editor_report.tsv`) in the same folder, with three columns:
    1. Path to the XML file
    2. Existing contributor names (before changes)
    3. Contributor names after update (alphabetically sorted, including any newly added)

Usage:
    python fix_editors.py /path/to/xml/folder
"""

import os
import sys
import glob
from lxml import etree

# The exact title/edition string to match:
TARGET_STRING = "MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World"

# The full list we want to end up with (16 names):
EXTRA_NAMES = [
    "Gregor Schwarb",
    "Maximilian de Molière",
    "Nadine Urbiczek",
    "Peter Tarras",
    "Annabelle Fuchs",
    "Lea Gzella",
    "Polina Lakteikina",
    "Maurizio Boehm",
    "Lea Poralla",
    "Lukas Froschmeier",
    "Ezra Stadler",
    "Jakob Shub-Oseledchik",
    "Sara Mattutat",
    "Jonathan Beise",
    "Masoumeh Seydi",
    "Nathan P. Gibson",
]

def sorted_names(all_names):
    """Return a list of all unique names, sorted case-insensitive."""
    return sorted(set(all_names), key=lambda s: s.lower())

def process_one_file(xml_path):
    """
    Parse the XML at xml_path, locate which parent (titleStmt vs. editionStmt)
    we need to modify, then reorder/add <editor role="contributor"> under that parent.

    Returns:
      changed (bool): True if the file was modified, False otherwise.
      existing_names (list of str): contributor names before modification.
      updated_names (list of str): contributor names after modification (sorted, including extras).
    """
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(xml_path, parser)
    root = tree.getroot()

    # XPath strings (no namespaces assumed). Adjust if your TEI uses a default namespace.
    title_path = ".//teiHeader/fileDesc/titleStmt/title[@level='m']"
    edition_path = ".//teiHeader/fileDesc/editionStmt/edition[1]"

    # Check titleStmt/title[@level='m']
    title_elem = root.find(title_path)
    parent_to_fix = None

    if title_elem is not None and (title_elem.text or "").strip() == TARGET_STRING:
        # Work on titleStmt
        parent_to_fix = root.find(".//teiHeader/fileDesc/titleStmt")
    else:
        # Else check editionStmt/edition[1]
        edition_elem = root.find(edition_path)
        if edition_elem is not None and (edition_elem.text or "").strip() == TARGET_STRING:
            parent_to_fix = root.find(".//teiHeader/fileDesc/editionStmt")

    if parent_to_fix is None:
        # Neither condition matched; no changes
        return False, [], []

    # 1) Collect existing <editor role="contributor"> elements under parent_to_fix
    xpath_editors = "editor[@role='contributor']"
    existing_editors = parent_to_fix.findall(xpath_editors)

    # 2) Extract their names (element.text)
    name_to_element = {}  # map from name -> element node
    existing_names = []
    for elem in existing_editors:
        name = (elem.text or "").strip()
        if name:
            existing_names.append(name)
            # Preserve the entire element node so we can reinsert it
            name_to_element[name] = elem

    # 3) Extend with EXTRA_NAMES (if not already present)
    all_names = existing_names + EXTRA_NAMES

    # 4) Compute sorted, unique list
    sorted_all = sorted_names(all_names)

    # 5) Remove all original <editor> nodes from parent_to_fix
    for elem in existing_editors:
        parent_to_fix.remove(elem)

    # 6) Re-insert in sorted order: use original element if name existed,
    #    else create a fresh one.
    for name in sorted_all:
        if name in name_to_element:
            parent_to_fix.append(name_to_element[name])
        else:
            new_editor = etree.Element("editor", role="contributor")
            new_editor.text = name
            parent_to_fix.append(new_editor)

    # 7) Write back to the same file (pretty-print with indentation)
    tree.write(xml_path.replace(".xml", "_new.xml"),
               encoding="UTF-8",
               xml_declaration=True,
               pretty_print=True)

    # Return existing_names and updated list
    return True, existing_names, sorted_all

def main(directory):
    all_xml = glob.glob(directory)
    xml_files = [
        fn for fn in all_xml
        # fn = ../../data/<subdir>/tei/<file>
        if os.path.basename(os.path.dirname(os.path.dirname(fn))) != "bibl"
    ]
    print(xml_files)
    if not xml_files:
        print("No XML files found in", directory)
        return

    print(f"Processing {len(xml_files)} file(s) in {directory}:")

    # if not os.path.isdir(folder_path):
    #     print(f"Error: '{folder_path}' is not a directory.")
    #     sys.exit(1)

    # xml_files = glob.glob(os.path.join(folder_path, "*.xml"))
    # if not xml_files:
    #     print(f"No .xml files found in {folder_path}.")
    #     return

    report_rows = []  # to collect (file_path, existing_names, updated_names)
    updated_count = 0

    for fpath in xml_files:
        try:
            changed, existing, updated = process_one_file(fpath)
            if changed:
                print(f"[UPDATED] {fpath}")
                updated_count += 1
            else:
                print(f"[SKIPPED] {fpath} (no matching title/edition)")

            # For skipped files, existing and updated are both []
            report_rows.append((fpath, existing, updated))
        except Exception as e:
            print(f"[ERROR] {fpath}: {e}")
            # In case of error, still append with empty lists
            report_rows.append((fpath, [], []))

    # 8) Write TSV report
    # report_path = os.path.join(folder_path, "editor_report.tsv")
    with open("./majlis_missing-assoc_report.tsv", "w", encoding="utf-8") as out:
        # Header
        out.write("file_path\texisting_contributors\tafter_contributors\n")
        for fpath, existing, updated in report_rows:
            existing_str = "; ".join(existing)
            updated_str = "; ".join(updated)
            out.write(f"{fpath}\t{existing_str}\t{updated_str}\n")

    print(f"\nDone. {updated_count} file(s) were modified.")
    print(f"Report written to: {report_path}")

if __name__ == "__main__":
    # if len(sys.argv) != 2:
    #     print("Usage: python fix_editors.py /path/to/xml/folder")
    #     sys.exit(1)
    # main(sys.argv[1])

    directory = r"../../data/*/tei/*.xml"
    main(directory)


