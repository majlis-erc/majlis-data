#!/usr/bin/env python3
import os
import glob
import re
from lxml import etree

def make_readable(xpath):
    # Remove namespace URIs in {…}, strip any prefix before “:”, drop [n] indices
    parts = xpath.split('/')
    clean = []
    for part in parts:
        if not part:
            continue
        # strip Clark notation {uri}
        p = re.sub(r'^\{[^}]+\}', '', part)
        # strip any prefix like tei:
        p = p.split(':')[-1]
        # remove numeric index
        p = re.sub(r'\[\d+\]', '', p)
        clean.append(p)
    return '/' + '/'.join(clean)

def extract_person_info(xml_dir, output_tsv):
    person_tags = ['author', 'editor', 'resp', 'persName']
    ns = {'tei': 'http://www.tei-c.org/ns/1.0'}
    parser = etree.XMLParser(recover=True, ns_clean=True, huge_tree=True)

    rows = []
    xml_paths = glob.glob(os.path.join(xml_dir, '**', '*.xml'), recursive=True)

    for xml_file in xml_paths:
        try:
            tree = etree.parse(xml_file, parser)
        except (etree.XMLSyntaxError, OSError) as e:
            print(f"[Warning] Could not parse {xml_file}: {e}")
            continue

        for tag in person_tags:
            for el in tree.findall(f'.//tei:{tag}', namespaces=ns):
                ref = el.get('ref')
                ref_value = ref.strip() if ref and ref.strip() else 'none'

                text = ''.join(el.itertext()).strip()
                element_value = text if text else 'none'

                raw_xpath = el.getroottree().getpath(el)
                readable = make_readable(raw_xpath)

                rows.append((
                    xml_file,
                    tag,
                    raw_xpath,
                    readable,
                    ref_value,
                    element_value
                ))

    with open(output_tsv, 'w', encoding='utf-8') as out:
        out.write('file_path\telement_name\txpath\treadable_xpath\tref_value\telement_value\n')
        for file_path, tag, xp, rp, ref_val, val in rows:
            out.write(f"{file_path}\t{tag}\t{xp}\t{rp}\t{ref_val}\t{val}\n")

if __name__ == "__main__":
    xml_dir = input("Enter the root directory containing your TEI XML files: ").strip()
    output_tsv = input("Enter the path for the output TSV file: ").strip()

    if not os.path.isdir(xml_dir):
        print(f"Error: '{xml_dir}' is not a valid directory.")
    else:
        extract_person_info(xml_dir, output_tsv)
        print(f"Done. Extracted data written to {output_tsv}")
