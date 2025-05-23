#!/usr/bin/env python3
import os
import glob
from lxml import etree

def add_editor_to_file(file_path):
    parser = etree.XMLParser(recover=True, ns_clean=False, remove_blank_text=False)
    tree = etree.parse(file_path, parser)
    root = tree.getroot()

    # detect default namespace (if any)
    default_ns = root.nsmap.get(None)
    if default_ns:
        ns = {'tei': default_ns}
        xpath = './/tei:teiHeader/tei:fileDesc/tei:titleStmt'
    else:
        ns = {}
        xpath = './/teiHeader/fileDesc/titleStmt'

    title_stmts = root.xpath(xpath, namespaces=ns)
    if not title_stmts:
        print(f"  [!] no titleStmt found in {os.path.basename(file_path)}")
        return

    for ts in title_stmts:
        exists = ts.xpath('.//editor[@role="entry-editor"]', namespaces=ns)
        if exists:
            print(f"  [→] already has entry-editor in {os.path.basename(file_path)}")
            continue
        editor = etree.Element('editor')
        editor.set('role', 'entry-editor')
        ts.append(editor)

    tree.write(file_path.replace(".xml", "_new.xml"),
               encoding='utf-8',
               xml_declaration=True,
               pretty_print=True)
    print(f"  [+] updated {os.path.basename(file_path)}")


def main():
    directory = r"../../data/*/tei/*.xml"#input("Enter path to directory containing XML files: ").strip()
    # if not directory:
    #     print("No directory entered. Exiting.")
    #     return
    # if not os.path.isdir(directory):
    #     print(f"Error: '{directory}' is not a valid directory.")
    #     return

    # xml_files = glob.glob(os.path.join(directory, '*.xml'))
    # all_xml = glob.glob(os.path.join(directory, '*.xml'))
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
    for f in xml_files:
        add_editor_to_file(f)


if __name__ == '__main__':
    main()

