#!/usr/bin/env python3
import os
import re
from lxml import etree

def sanitize_text(text):
    """
    Normalize whitespace by collapsing consecutive whitespace
    (spaces, tabs, newlines) into a single space, then strip.
    """
    return re.sub(r'\s+', ' ', text).strip()

def move_or_remove_editor(file_path, report_rows):
    parser = etree.XMLParser(recover=True, ns_clean=False, remove_blank_text=False)
    tree = etree.parse(file_path, parser)
    root = tree.getroot()

    # Detect default TEI namespace (if any)
    default_ns = root.nsmap.get(None)
    if default_ns:
        ns = {'tei': default_ns}
        title_xpath   = './/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[@level="m"]'
        edition_xpath = './/tei:teiHeader/tei:fileDesc/tei:editionStmt/tei:edition'
        editor_title_xpath = './/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:editor[@role="entry-editor"]'
    else:
        ns = {}
        title_xpath   = './/teiHeader/fileDesc/titleStmt/title[@level="m"]'
        edition_xpath = './/teiHeader/fileDesc/editionStmt/edition'
        editor_title_xpath = './/teiHeader/fileDesc/titleStmt/editor[@role="entry-editor"]'

    # Extract and normalize title[@level="m"]
    title_elem = root.find(title_xpath, namespaces=ns)
    if title_elem is not None and title_elem.text:
        title_text = sanitize_text(title_elem.text)
    else:
        title_text = None

    # Extract and normalize edition text if available
    edition_elem = root.find(edition_xpath, namespaces=ns)
    if edition_elem is not None and edition_elem.text:
        edition_text = sanitize_text(edition_elem.text)
    else:
        edition_text = None

    # Find any <editor role="entry-editor"/> under titleStmt
    editor_title_elems = root.xpath(editor_title_xpath, namespaces=ns)
    before_xpath = "teiHeader/fileDesc/titleStmt/editor[@role='entry-editor']" if editor_title_elems else None

    # Initialize tagging and after_xpath
    tag = None
    after_xpath = None

    # Define the specific strings we compare against (also normalized)
    target_edition = sanitize_text(
        "Cataloging data from the ARCHES project re-used and prepared for electronic publication "
        "in the project: MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World"
    )
    target_title_for_move = sanitize_text(
        "Judeo-Arabic Bible Exegesis and Translations in the Firkovitch Manuscript Collections"
    )
    target_title_skip = sanitize_text(
        "MAJLIS: The Transformation of Jewish Literature in Arabic in the Islamicate World"
    )

    # Check conditions
    cond1 = (edition_text == target_edition and title_text == target_title_for_move)
    cond2 = (title_text == target_title_skip)

    if cond1:
        # Condition 1: move editor, tag as "updated"
        tag = "updated"
        if editor_title_elems:
            # Remove each editor under titleStmt
            for ed in editor_title_elems:
                parent = ed.getparent()
                parent.remove(ed)

            # Find editionStmt parent(s) and append new editor under each
            if default_ns:
                edition_stmt_xpath = './/tei:teiHeader/tei:fileDesc/tei:editionStmt'
            else:
                edition_stmt_xpath = './/teiHeader/fileDesc/editionStmt'
            edition_stmts = root.xpath(edition_stmt_xpath, namespaces=ns)
            for eds in edition_stmts:
                new_editor = etree.Element('editor')
                new_editor.set('role', 'entry-editor')
                eds.append(new_editor)
            after_xpath = "teiHeader/fileDesc/editionStmt/editor[@role='entry-editor']"
        else:
            # No editor to move, but still mark as updated
            after_xpath = None

        # Write changes back to file
        tree.write(
            file_path,
            encoding='utf-8',
            xml_declaration=True,
            pretty_print=True
        )

    elif cond2:
        # Condition 2: do nothing, tag as "not updated"
        tag = "not updated"
        after_xpath = None

    else:
        # Neither condition met: remove existing editor if present, tag as "error"
        tag = "error"
        if editor_title_elems:
            for ed in editor_title_elems:
                parent = ed.getparent()
                parent.remove(ed)
        # after_xpath remains None

        # Write changes back to file if we removed an editor
        tree.write(
            file_path.replace(".xml", "_new.xml"),
            encoding='utf-8',
            xml_declaration=True,
            pretty_print=True
        )

    # Append row to report
    report_rows.append([
        file_path,
        title_text or "None",
        edition_text or "None",
        tag,
        before_xpath or "None",
        after_xpath or "None"
    ])

def main():
    directory = "../../data"#input("Enter path to directory containing XML files: ").strip()
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory.")
        return

    report_rows = []
    # Walk directory recursively, excluding any 'bibl' subdirectory
    for root_dir, dirs, files in os.walk(directory):
        if 'bibl' in dirs:
            dirs.remove('bibl')
        for fname in files:
            if not fname.lower().endswith('.xml'):
                continue
            xml_path = os.path.join(root_dir, fname)
            move_or_remove_editor(xml_path, report_rows)

    # Write report to TSV in the input directory
    report_path = os.path.join(directory, "report.tsv")
    with open(report_path, 'w', encoding='utf-8') as out_f:
        # Header
        out_f.write(
            "file_path\ttitle_m\tedition\ttag\tbefore_xpath\tafter_xpath\n"
        )
        for row in report_rows:
            out_f.write("\t".join(row) + "\n")

    print(f"\nProcessing complete. Report written to:\n  {report_path}")

if __name__ == '__main__':
    main()
