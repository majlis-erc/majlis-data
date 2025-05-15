#!/usr/bin/env python3
import os
import glob
from lxml import etree
import re

def find_specific_ref(xml_dir, output_tsv, target_ref):
    # set up a forgiving parser
    parser = etree.XMLParser(
        recover=True,
        ns_clean=True,
        huge_tree=True
    )

    rows = []
    xml_paths = glob.glob(os.path.join(xml_dir, '**', '*.xml'), recursive=True)

    for xml_file in xml_paths:
        try:
            tree = etree.parse(xml_file, parser)
        except (etree.XMLSyntaxError, OSError) as e:
            print(f"[Warning] Could not parse {xml_file}: {e}")
            continue

        # iterate over every element in the document
        for el in tree.iter():
            ref = el.get('ref')
            if ref == target_ref:
                # local name without namespace
                tag = etree.QName(el).localname
                # full text value
                text = ''.join(el.itertext()).strip()
                element_value = text if text else 'none'
                # raw absolute XPath
                xpath = el.getroottree().getpath(el)
                rows.append((xml_file, tag, xpath, ref, element_value))

    # write results
    with open(output_tsv, 'w', encoding='utf-8') as out:
        out.write('file_path\telement_name\txpath\tref_value\telement_value\n')
        for file_path, tag, xp, ref_val, val in rows:
            print("1:", val)
            val = re.sub("\n+|\t+", " ", val)
            val = re.sub(" +", " ", val)
            print("2:", val)
            out.write(f"{file_path}\t{tag}\t{xp}\t{ref_val}\t{val}\n")

if __name__ == "__main__":
    xml_dir = input("Enter the root directory containing your TEI XML files: ").strip()
    output_tsv = input("Enter the path for the output TSV file: ").strip()
    target_ref = "https://jalit.org/person/10"

    if not os.path.isdir(xml_dir):
        print(f"Error: '{xml_dir}' is not a valid directory.")
    else:
        find_specific_ref(xml_dir, output_tsv, target_ref)
        print(f"Done. All elements with ref='{target_ref}' have been written to {output_tsv}")

