# !/usr/bin/env python3
import os
import csv
import re
from lxml import etree


def get_unique_xpath(el):
    parts = []
    while el is not None and isinstance(el, etree._Element):
        parent = el.getparent()
        tag = etree.QName(el).localname
        pref = f"tei:{tag}"
        if parent is not None:
            siblings = [sib for sib in parent if etree.QName(sib).localname == tag]
            if len(siblings) > 1:
                idx = siblings.index(el) + 1
                parts.append(f"/{pref}[{idx}]")
            else:
                parts.append(f"/{pref}")
        else:
            parts.append(f"/{pref}")
        el = parent
    return "".join(reversed(parts))


def extract_funders(data_dir, output_tsv):
    # whitespace *before* '(' only when preceded by a letter
    re_before = re.compile(r'(?<=[A-Za-z])\s+(?=\()')
    # whitespace *after* '(' only when followed by a letter
    re_after = re.compile(r'(?<=\()\s+(?=[A-Za-z])')

    parser = etree.XMLParser(recover=True, ns_clean=False, remove_blank_text=False)

    with open(output_tsv, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow([
            "file_path",
            "xpath",
            "value",
            "space_before_paren",  # True if ' ('
            "space_after_paren"  # True if '( '
        ])

        for root, _, files in os.walk(data_dir):
            for fn in files:
                if not fn.lower().endswith(".xml"):
                    continue
                fullpath = os.path.join(root, fn)
                try:
                    tree = etree.parse(fullpath, parser)
                except Exception as e:
                    print(f"⚠️  Skipping {fullpath}: parse error ({e})")
                    continue

                funders = tree.xpath(
                    '//*[local-name()="teiHeader"]'
                    '/*[local-name()="fileDesc"]'
                    '/*[local-name()="titleStmt"]'
                    '/*[local-name()="funder"]'
                )
                for funder in funders:
                    # 1) build unique XPath
                    xp = get_unique_xpath(funder)

                    # 2) concatenate orgName texts *without* extra spaces
                    orgs = funder.xpath('.//*[local-name()="orgName"]')
                    # val = "".join(
                    #     "".join(o.itertext())
                    #     for o in orgs
                    # )
                    fragments = []
                    for o in funder.xpath('.//*[local-name()="orgName"]'):
                        # 1. get all text inside the tag
                        fragments.append("".join(o.itertext()))
                        # 2. then grab any text _after_ it (this is where your "(" or ")" lives)
                        if o.tail:
                            fragments.append(o.tail)

                    # join everything, strip only leading/trailing whitespace
                    val = "".join(fragments).strip()

                    # 3) detect whitespace issues around "("
                    space_before = bool(re_before.search(val))
                    space_after = bool(re_after.search(val))

                    # 4) write TSV row
                    writer.writerow([fullpath, xp, val, space_before, space_after])


if __name__ == "__main__":
    extract_funders("../../data", "funder_info.tsv")
    print("✅ Done: output.tsv written with space_before_paren and space_after_paren flags.")
