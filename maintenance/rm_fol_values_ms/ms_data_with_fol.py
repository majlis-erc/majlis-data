import os
import re
import csv
from lxml import etree

# Regular expression to match " fol." or " fols." (with a word boundary)
pattern = re.compile(r'\bfols?\.')


def get_xpath_with_localname(element):
    """
    Generate an absolute XPath expression that uses local-name() predicates.
    This expression is robust in recovered trees and can be used with tree.xpath().
    For example, it will produce a path like:
      / *[local-name()='TEI'][1]/*[local-name()='text'][1]/*[local-name()='body'][1]/*[local-name()='div'][2]/*[local-name()='measure'][1]
    """
    path_parts = []
    current = element
    while current is not None:
        tag = etree.QName(current).localname
        parent = current.getparent()
        # Count siblings (with the same local name) to determine the index
        if parent is not None:
            siblings = [child for child in parent if etree.QName(child).localname == tag]
            index = siblings.index(current) + 1  # XPath is 1-indexed
        else:
            index = 1
        path_parts.append("*[local-name()='%s'][%d]" % (tag, index))
        current = parent
    # Reverse the list so that it starts at the root element
    xpath_expr = "/" + "/".join(reversed(path_parts))
    return xpath_expr

# Change this to the local path where your TEI XML files are stored
tei_directory = "../../majlis-data/data/manuscripts/tei"


# Name of the output file (TSV format)
output_file = "xml_with_fols_in_values2.tsv"

with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile, delimiter="\t")
    # Write header row
    writer.writerow(["File", "Readable Path", "Element tag", "Value"])

    # Iterate over all files in the directory and its subdirectories
    parser = etree.XMLParser(recover=True)
    for root_dir, _, files in os.walk(tei_directory):
        for file in files:
            if file.endswith('.xml'):
                file_path = os.path.join(root_dir, file)
                try:
                    tree = etree.parse(file_path, parser)
                except Exception as e:
                    print(f"Error parsing file {file_path}: {e}")
                    continue

                # Search all elements in the XML tree
                for element in tree.iter():
                    # Ensure element.text exists and search for the pattern
                    if element.text and pattern.search(element.text):
                        # Get the XPath to the element
                        xpath = tree.getpath(element)
                        readable_path = get_xpath_with_localname(element)
                        # Remove namespace from the element tag for a cleaner output
                        tag_without_ns = etree.QName(element).localname
                        value = element.text.strip()
                        writer.writerow([file_path, readable_path, tag_without_ns, value])
                        # print(f"File: {file_path}")
                        # print(f"Element path: {xpath}")
                        # print(f"Element tag: {element.tag}")
                        # print(f"Readable Path: {readable_path}")
                        # print(f"Element tag: {tag_without_ns}")
                        # print(f"Value: {element.text.strip()}")
                        # print("-" * 40)

