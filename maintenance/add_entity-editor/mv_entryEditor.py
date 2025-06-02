#!/usr/bin/env python3
import os
from lxml import etree

def move_editor_in_file(file_path):
    parser = etree.XMLParser(recover=True, ns_clean=False, remove_blank_text=False)
    tree = etree.parse(file_path, parser)
    root = tree.getroot()

    # Handle default TEI namespace (if any)
    default_ns = root.nsmap.get(None)
    if default_ns:
        ns = {'tei': default_ns}
        title_xpath   = './/tei:teiHeader/tei:fileDesc/tei:titleStmt'
        edition_xpath = './/tei:teiHeader/tei:fileDesc/tei:editionStmt'
        editor_filter = 'tei:editor'
        role_expr     = '@role="entry-editor"'
    else:
        ns = {}
        title_xpath   = './/teiHeader/fileDesc/titleStmt'
        edition_xpath = './/teiHeader/fileDesc/editionStmt'
        editor_filter = 'editor'
        role_expr     = '@role="entry-editor"'

    # Skip files without an editionStmt
    editions = root.xpath(edition_xpath, namespaces=ns)
    if not editions:
        print(f"[↷] no editionStmt in {file_path} – skipped")
        return

    # Find and remove any <editor role="entry-editor"> under titleStmt
    title_stmts = root.xpath(title_xpath, namespaces=ns)
    moved = False
    for ts in title_stmts:
        editors = ts.xpath(f'.//{editor_filter}[{role_expr}]', namespaces=ns)
        for ed in editors:
            ts.remove(ed)
            moved = True

    if not moved:
        print(f"[→] no entry-editor found in titleStmt of {file_path}")
        return

    # Append a fresh <editor role="entry-editor"/> under each editionStmt
    for eds in editions:
        editor = etree.Element('editor')
        editor.set('role', 'entry-editor')
        eds.append(editor)

    # Write changes back to file
    tree.write(
        file_path.replace(".xml", "_new.xml"),
        encoding='utf-8',
        xml_declaration=True,
        pretty_print=True
    )
    print(f"[✔] moved entry-editor in {file_path}")


def main():
    directory = "../../data" #input("Enter path to directory containing XML files: ").strip()
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a valid directory.")
        return

    # Collect all .xml files, recursively, excluding any in a 'bibl' folder
    xml_files = []
    for root, dirs, files in os.walk(directory):
        # prevent descending into any 'bibl' subdirectory
        if 'bibl' in dirs:
            dirs.remove('bibl')
        for fname in files:
            if fname.lower().endswith('.xml'):
                xml_files.append(os.path.join(root, fname))

    if not xml_files:
        print(f"No XML files found in {directory} (excluding 'bibl').")
        return

    print(f"Processing {len(xml_files)} XML file(s) in {directory} (excluding 'bibl'):")
    for path in xml_files:
        move_editor_in_file(path)


if __name__ == '__main__':
    main()
