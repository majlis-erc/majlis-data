import pandas as pd
from lxml import etree
import os
import re

# === CONFIGURATION ===
base_dir = '../..'
work_aut_info = "works_authors_info.tsv"         # path to your original TSV file
works_dir = "data/works/tei"                # folder containing work XML files
works_authors_updated = "works_authors_info_updated.tsv"  # name of the new TSV file


def load_and_clean_xml(path):
    """Loads an XML file and strips invalid xml:id attributes."""
    with open(path, "r", encoding="utf-8") as f:
        xml_data = f.read()
    parser = etree.XMLParser(huge_tree=True, recover=True)
    return etree.ElementTree(etree.fromstring(xml_data.encode("utf-8"), parser))


# === LOAD INPUT ===
df = pd.read_csv(work_aut_info, sep="\t", dtype=str).fillna("")

# Add new columns
updated_authors = []
updated_titles = []
statuses = []

for _, row in df.iterrows():
    work_file = row["work_file"]
    work_path = os.path.join(base_dir, works_dir, work_file)
    author_xpath = row["author_xpath"]
    title_xpath = row["title_xpath"]
    person_headword = str(row["person_headword"])
    author_ref = str(row["author_ref"]).strip()

    # Default values
    updated_author = "original value"
    updated_title = "original value"
    status = "not-updated"

    if not os.path.exists(work_path):
        updated_authors.append(updated_author)
        updated_titles.append(updated_title)
        statuses.append(status)
        continue

    try:
        tree = load_and_clean_xml(work_path)
    except Exception as e:
        print(f"Failed to parse {work_path}: {e}")
        updated_authors.append(updated_author)
        updated_titles.append(updated_title)
        statuses.append(status)
        continue

    # Do updates only if ref is present and non-empty
    if author_ref.strip():
        try:
            author_elem = tree.xpath(author_xpath)
            if author_elem:
                author_elem[0].text = person_headword
                updated_author = person_headword
        except Exception as e:
            print(f"Author update error in {work_file}: {e}")

        try:
            title_elem = tree.xpath(title_xpath)
            if title_elem and title_elem[0].text:
                original_text = title_elem[0].text.strip()
                new_text = re.sub(r"\([^()]*\)$", f"({person_headword})", original_text)
                title_elem[0].text = new_text
                updated_title = new_text
        except Exception as e:
            print(f"Title update error in {work_file}: {e}")

        # Save updated XML
        try:
            with open(work_path, "wb") as f:
                # xml_declaration=True adds <?xml version='1.0' encoding='utf-8'?> at the beginning of XML file
                # f.write(etree.tostring(tree, encoding="utf-8", pretty_print=True, xml_declaration=True))
                f.write(etree.tostring(tree, encoding="utf-8", pretty_print=True, xml_declaration=False))
            status = "updated"
        except Exception as e:
            print(f"Error writing {work_file}: {e}")

    updated_authors.append(updated_author)
    updated_titles.append(updated_title)
    statuses.append(status)

# Update DataFrame
df["updated_author_text"] = updated_authors
df["updated_title_text"] = updated_titles
df["status"] = statuses

# Save updated TSV
df.to_csv(works_authors_updated, sep="\t", index=False)
print(f"\n✅ Done! Updated TSV written to: {works_authors_updated}")

