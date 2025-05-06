#!/usr/bin/env python3
import os
import csv
import re
from lxml import etree

# ——— Regex patterns ———
# remove whitespace after '(' when followed by a letter: '( A' → '(A'
RE_REMOVE = re.compile(r'\(\s+(?=[A-Za-z])')
# add a single space before '(' when preceded by a letter: 'A(' → 'A ('
RE_ADD    = re.compile(r'(?<=[A-Za-z])\(')

# ——— TEI namespace for your XPaths ———
NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# ——— Input and output TSVs ———
INPUT_TSV  = "funder_info.tsv"
OUTPUT_TSV = "funder_info_updated.tsv"

# ——— 1) Load the old TSV ———
with open(INPUT_TSV, newline="", encoding="utf-8") as f:
    reader     = csv.DictReader(f, delimiter="\t")
    rows       = list(reader)
    fieldnames = reader.fieldnames + ["updated_value"]

# ——— 2) Group rows by file_path ———
by_file = {}
for row in rows:
    by_file.setdefault(row["file_path"], []).append(row)

# ——— Helper to apply the same fixes to any text node ———
def fix_text(txt: str) -> str:
    if txt is None:
        return None
    out = RE_REMOVE.sub("(", txt)
    out = RE_ADD.sub(" (", out)
    return out

def patch_element(el: etree._Element):
    """Recursively fix el.text and all child.tail values."""
    el.text = fix_text(el.text)
    for child in el:
        patch_element(child)
        child.tail = fix_text(child.tail)

# ——— 3) Process each XML file ———
for xml_file, file_rows in by_file.items():
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree   = etree.parse(xml_file, parser)
    updated_any = False

    for row in file_rows:
        orig_val  = row["value"]
        fixed_val = fix_text(orig_val)

        if fixed_val != orig_val:
            # mark for TSV
            row["updated_value"] = fixed_val

            # locate the exact element
            elems = tree.xpath(row["xpath"], namespaces=NS)
            if not elems:
                print(f"Warning: XPath {row['xpath']} not found in {xml_file}")
                continue

            # patch it in-memory
            patch_element(elems[0])
            updated_any = True
        else:
            row["updated_value"] = "not updated"

    # ——— write new XML only if something changed ———
    if updated_any:
        base, ext    = os.path.splitext(xml_file)
        updated_file = f"{base}_updated{ext}"
        tree.write(
            updated_file,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=False,    # minimize unrelated formatting changes
        )
        print(f"Wrote updated XML to: {updated_file}")

# ——— 4) Write the new TSV ———
with open(OUTPUT_TSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

print(f"Done. Updated TSV written to {OUTPUT_TSV}")
