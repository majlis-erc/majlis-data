import csv
import os
import re
from lxml import etree

# The TSV file produced by the previous script
input_file = "xml_with_fols_in_values2.tsv"
# This will be our updated TSV file with a new column "Updated"
updated_input_file = "xml_with_fols_in_values2_updated.tsv"

# Regular expression to remove occurrences of whitespace, then "fol" or "fols", a dot, and whitespace.
remove_pattern = re.compile(r"\s*fols?\.\s*")


def find_element_by_readable_path(root, readable_path):
    """
    Given the root element and a human-readable path (e.g. /TEI/text/body/div[2]/measure[1]),
    traverse the tree by matching local tag names (ignoring namespaces) and using indices if present.
    Returns the found element or None if not found.
    """
    parts = readable_path.strip('/').split('/')
    current = root
    for part in parts:
        if '[' in part and part.endswith(']'):
            tag, idx_str = part[:-1].split('[')
            try:
                idx = int(idx_str) - 1  # convert to 0-indexed
            except ValueError:
                return None
        else:
            tag = part
            idx = 0
        # Filter children by comparing local names (ignoring namespace)
        children = [child for child in current if etree.QName(child).localname == tag]
        if idx < len(children):
            current = children[idx]
        else:
            return None
    return current

# Read the TSV file into a list of dictionaries, adding a new "Updated" column (default "No")
rows = []
with open(tsv_file, newline='', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter="\t")
    for row in reader:
        row["Updated"] = "No"  # default flag
        row["New Value"] = ""  # new column for storing the new element text after replacement
        rows.append(row)

# Group rows by the XML file path so that each XML file is processed only once.
files_to_rows = {}
for row in rows:
    file_path = row["File"]
    files_to_rows.setdefault(file_path, []).append(row)

# Process each XML file group.
for file_path, group_rows in files_to_rows.items():
    # We only process rows for which the Element tag is 'measure'
    measure_rows = [r for r in group_rows if r["Element tag"] == "measure"]
    if not measure_rows:
        continue

    try:
        # Use a parser that recovers from errors like invalid xml:id values.
        parser = etree.XMLParser(recover=True)
        tree = etree.parse(file_path, parser=parser)
        root = tree.getroot()
    except Exception as e:
        print(f"Error parsing file {file_path}: {e}")
        continue

    file_updated = False
    # Process each measure row
    for row in measure_rows:
        # Use the regenerated XPath from the TSV to locate the element
        regen_path = row["Readable Path"]
        found_elements = tree.xpath(regen_path)
        if found_elements:
            element = found_elements[0]
            if element.text:
                old_text = element.text
                # Remove the pattern occurrences; replace with a single space then trim.
                new_text = re.sub(remove_pattern, " ", old_text).strip()
                # Save the new value in the new column regardless of change.
                row["New Value"] = new_text
                if new_text != old_text:
                    element.text = new_text
                    row["Updated"] = "Yes"
                    file_updated = True
                else:
                    row["Updated"] = "No change"
            else:
                row["Updated"] = "No text"
                row["New Value"] = ""
        else:
            row["Updated"] = "Element not found"
            row["New Value"] = ""

    # Save changes to the XML file if any measure element was updated
    if file_updated:
        try:
            # Convert the tree to a byte string with an XML declaration and pretty print enabled.
            new_xml = etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=True)
            # Write the file in binary mode.
            with open(file_path, "wb") as f_out:
                print("updated xml file: ", file_path)
                f_out.write(new_xml)
            print(f"Updated file: {file_path}")
        except Exception as e:
            print(f"Error saving file {file_path}: {e}")

# Write out the updated TSV with the new "Updated" column.
if rows:
    fieldnames = list(rows[0].keys())
    with open(updated_tsv_file, "w", newline='', encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"Updated TSV file written to {updated_tsv_file}")
else:
    print("No rows found in the TSV file.")

