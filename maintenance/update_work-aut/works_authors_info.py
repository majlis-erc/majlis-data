import os
import re
import csv
import glob
from lxml import etree

# Directories containing the TEI XML files
base_dir = '../../majlis-data'
works_dir = 'data/works/tei'
persons_dir = 'data/persons/tei'
# Output TSV file
output_file = 'works_authors_info.tsv'


# helper function to generate named XPath
def get_named_xpath(elem):
    path_parts = []
    while elem is not None and not isinstance(elem, etree._ElementTree):
        tag = etree.QName(elem).localname
        attrib_parts = []
        if "type" in elem.attrib:
            attrib_parts.append(f"@type='{elem.attrib['type']}'")
        if "level" in elem.attrib:
            attrib_parts.append(f"@level='{elem.attrib['level']}'")
        if "ref" in elem.attrib:
            attrib_parts.append(f"@ref='{elem.attrib['ref']}'")
        if "xml:lang" in elem.attrib:
            attrib_parts.append(f"@xml:lang='{elem.attrib['xml:lang']}'")
        if attrib_parts:
            tag_expr = f"{tag}[{' and '.join(attrib_parts)}]"
        else:
            tag_expr = tag
        path_parts.insert(0, tag_expr)
        elem = elem.getparent()
    return "/" + "/".join(path_parts)


# 1. A helper to read & clean XML (drops any xml:id="…" so lxml never trips on invalid NCNames)
def load_clean_tree(path):
    text = open(path, encoding="utf‑8").read()
    # remove any xml:id attributes
    cleaned = re.sub(r'\s+xml:id="[^"]*"', "", text)
    # parse with a permissive parser
    parser = etree.XMLParser(huge_tree=True)
    return etree.fromstring(cleaned.encode("utf‑8"), parser)

# 2. TEI namespace shortcut
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace"
}

# 3. Walk through every work file
rows = []
for work_path in sorted(glob.glob(os.path.join(base_dir, works_dir, '*.xml'))):
    print(work_path)
    work_fname = os.path.basename(work_path)
    w_root = load_clean_tree(work_path)

    # --- extract <author>/@ref, text, and its XPath
    author_elem = w_root.find(".//tei:text/tei:body/tei:bibl/tei:author", NS)
    ref = author_elem.get("ref") if author_elem is not None else ""
    author_text = (author_elem.text or "").strip()
    author_xpath = w_root.getroottree().getpath(author_elem) if author_elem is not None else ""
    author_named_xpath = get_named_xpath(author_elem) if author_elem is not None else ""

    # --- extract <title level="a"> from the header
    title_elem = w_root.find(
        ".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[@level='a']",
        NS
    )
    title_text = (title_elem.text or "").strip()
    title_xpath = w_root.getroottree().getpath(title_elem)
    title_named_xpath = get_named_xpath(title_elem) if title_elem is not None else ""

    # --- follow the ref to the person file
    pers_name = "NA"
    pers_xpath = ""
    if ref:
        print(ref)
        # pid = ref[1:] + ".xml"
        pid = ref.split("/")[-1].lstrip("#") + ".xml"
        p_path = os.path.join(base_dir, persons_dir, pid)
        if os.path.exists(p_path):
            p_root = load_clean_tree(p_path)

            # try Hebrew‑Latin majlis-headword first
            q = ".//tei:text/tei:body/tei:listPerson/tei:person/tei:persName"
            he_names = p_root.xpath(
                ".//tei:persName[@type='majlis-headword' and @xml:lang='he-Latn']/tei:name",
                namespaces=NS
            )
            ar_names = p_root.xpath(
                ".//tei:persName[@type='majlis-headword' and @xml:lang='ar-Latn']/tei:name",
                namespaces=NS
            )
            pick = he_names or ar_names

            if pick:
                # pick[0] is the <perName> element, so .text is the actual string
                pers_name = pick[0].text.strip()
                pers_xpath = p_root.getroottree().getpath(pick[0])
                person_named_xpath = get_named_xpath(pick[0])

            else:
                pers_name, pers_xpath, person_named_xpath = "NA", "", ""

    # --- collect the row
    rows.append([
        work_fname,
        ref,
        author_text, author_xpath, author_named_xpath,
        title_text, title_xpath, title_named_xpath,
        pers_name, pers_xpath, person_named_xpath
    ])

    # 4. Dump to TSV
with open(output_file, "w", encoding="utf‑8", newline="") as out:
    w = csv.writer(out, delimiter="\t")
    w.writerow([
        "work_file",
        "author_ref",
        "author_text", "author_xpath", "author_named_xpath",
        "title_text", "title_xpath", "title_named_xpath",
        "person_headword", "person_headword_xpath", "person_named_xpath"
    ])
    w.writerows(rows)

print("✓ Wrote", len(rows), "rows to works_persons.tsv")