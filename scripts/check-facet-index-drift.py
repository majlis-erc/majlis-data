#!/usr/bin/env python3
"""
Checks majlis-data's collection.xconf against every facet-def.xml declared in the
companion srophe repo, looking for two specific failure modes hit in practice:

1. A facet-definition with real content (not an empty placeholder) that has no
   matching <facet dimension="..."> entry in collection.xconf at all - e.g. the
   places/works/bibl/geo facets found missing on 2026-09-08, never added when
   collection.xconf was first written (it only ever covered manuscripts).
2. A facet-definition whose <group-by> has a @function attribute (meaning a
   dedicated sf:facet-<function>() implementation exists and is presumably doing
   something beyond a bare XPath lookup) where the matching collection.xconf entry
   is byte-identical to the raw <sub-path> text - i.e. nothing was done to it at
   all. Both real bugs found so far (repository's missing normalize-space(),
   reproductions' missing YES/NO check) were exactly this: the bare sub-path
   copied over unchanged. This deliberately does not try to verify an expression
   *matches* its function's actual logic - only that it isn't obviously still the
   untouched original.

This does not attempt to fully verify an expression is *correct* - only that it
looks like the two known-bad shapes above went unnoticed. A clean report is not a
guarantee nothing is wrong; it means these two specific, previously-hit mistakes
are not currently present.

Usage:
  python3 scripts/check-facet-index-drift.py [path-to-srophe-checkout]

Defaults to ../srophe relative to this repo's root, matching how the two repos
are laid out on disk everywhere else in this project's docs and scripts.
"""
import sys
import glob
import os
import re
import xml.etree.ElementTree as ET

FACET_NS = "{http://expath.org/ns/facet}"

# Facets that are genuinely declared in facet-def.xml but deliberately not wired into
# collection.xconf - a decision made 2026-09-08, not an oversight. collection.xconf was
# written to cover manuscripts only; extending it to these 9 (places/works/bibl/geo) was
# assessed as its own separate, larger task and set aside. Listed here as
# (collection-dir-name, facet-name) pairs so the MISSING check stays useful for genuinely
# new drift instead of reporting these same 9 every run. If any of these facets is ever
# actually implemented, remove its entry here - the check will then confirm it landed
# correctly instead of silently saying nothing about it.
KNOWN_ACCEPTED_GAPS = frozenset({
    ("places", "type"),
    ("works", "subjects"),
    ("works", "author"),
    ("works", "publicationDate"),
    ("bibl", "subjects"),
    ("bibl", "author"),
    ("bibl", "publicationDate"),
    ("geo", "type"),
    ("geo", "bibl"),
})


def load_facet_definitions(srophe_root):
    """Returns a list of (source_file, name, has_function, function_name, sub_path) for
    every non-empty facet-definition found under srophe's xar-resources. sub_path is the
    raw text of <group-by>/<sub-path>, or None if there isn't one (e.g. a <range> facet)."""
    definitions = []
    pattern = os.path.join(srophe_root, "src/main/xar-resources/*/facet-def.xml")
    for path in sorted(glob.glob(pattern)):
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            print(f"WARNING: could not parse {path}: {e}")
            continue
        root = tree.getroot()
        for fd in root.findall(f"{FACET_NS}facet-definition"):
            name = fd.get("name")
            group_by = fd.find(f"{FACET_NS}group-by")
            function_name = group_by.get("function") if group_by is not None else None
            sub_path_el = group_by.find(f"{FACET_NS}sub-path") if group_by is not None else None
            sub_path = sub_path_el.text.strip() if sub_path_el is not None and sub_path_el.text else None
            definitions.append((path, name, bool(function_name), function_name, sub_path))
    return definitions


def load_collection_xconf_facets(collection_xconf_path):
    """Returns {dimension_name: expression} from collection.xconf's <facet> entries."""
    tree = ET.parse(collection_xconf_path)
    facets = {}
    for facet in tree.getroot().iter():
        if facet.tag.endswith("}facet") or facet.tag == "facet":
            dim = facet.get("dimension")
            expr = facet.get("expression")
            if dim:
                facets[dim] = expr
    return facets


def main():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    srophe_root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(repo_root, "..", "srophe")
    collection_xconf_path = os.path.join(repo_root, "collection.xconf")

    if not os.path.isdir(srophe_root):
        print(f"ERROR: srophe checkout not found at {srophe_root}")
        print("Pass its path explicitly: python3 scripts/check-facet-index-drift.py /path/to/srophe")
        sys.exit(2)

    definitions = load_facet_definitions(srophe_root)
    configured = load_collection_xconf_facets(collection_xconf_path)

    missing = []
    suppressed = []
    unwrapped_function = []

    for source_file, name, has_function, function_name, sub_path in definitions:
        collection_dir = os.path.basename(os.path.dirname(source_file))
        if name not in configured:
            if (collection_dir, name) in KNOWN_ACCEPTED_GAPS:
                suppressed.append((source_file, name))
            else:
                missing.append((source_file, name))
        elif has_function and sub_path is not None:
            expr = (configured[name] or "").strip()
            # Don't hardcode which wrapper shapes are "acceptable" (normalize-space(),
            # a YES/NO check, an sf:facet() dispatch, ...) - there's no fixed list, and
            # both real bugs found so far were simply the bare sub-path copied over
            # completely unchanged. Flag only that exact case: something byte-identical
            # to the raw sub-path where a dedicated function implies it needs to not be.
            if expr == sub_path:
                unwrapped_function.append((source_file, name, function_name, expr))

    if suppressed:
        print(f"SUPPRESSED (known, accepted gap - not counted as a failure; see "
              f"KNOWN_ACCEPTED_GAPS in this script): {len(suppressed)} facet-definition(s):")
        for source_file, name in suppressed:
            print(f"  - {name}  (declared in {source_file})")
        print()

    if not missing and not unwrapped_function:
        print(f"OK: {len(definitions)} facet-definition(s) checked across {srophe_root}, "
              f"no missing or unwrapped-function entries found in {collection_xconf_path} "
              f"(beyond the {len(suppressed)} known, accepted gap(s) above).")
        return 0

    if missing:
        print(f"MISSING: facet-definition(s) with no matching <facet> in collection.xconf:")
        for source_file, name in missing:
            print(f"  - {name}  (declared in {source_file})")
        print()

    if unwrapped_function:
        print(f"POSSIBLY UNWRAPPED: facet-definition(s) with group-by/@function whose "
              f"collection.xconf entry looks like a bare, unwrapped sub-path:")
        for source_file, name, function_name, expr in unwrapped_function:
            print(f"  - {name}  (function=\"{function_name}\", declared in {source_file})")
            print(f"      current expression: {expr}")
        print()

    print("Neither finding above is necessarily wrong on its own - some facets may be "
          "deliberately manuscripts-only, or a function may not need special wrapping. "
          "This just surfaces drift for a human to judge; see "
          "docs/git-sync-webhook-incidents.md and docs/facet-index-design-notes.md for "
          "the incidents that motivated this check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
