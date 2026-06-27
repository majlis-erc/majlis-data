#!/usr/bin/env python3
"""
biblRange_sync.py — (re)generate folio <citedRange> elements in manuscript-join
bibls by mirroring the referenced manuscript's <msItem>/<locus>.

SIMPLE MODEL (current): for each join-bibl that points (via <ptr target>) to a
single, resolvable manuscript N, REMOVE all of the bibl's <citedRange> children
and REGENERATE one per valid locus of N, mirroring the locus:

    referenced  <locus from="1r" to="8v">1r–8v</locus>
    ->  host     <citedRange unit="folios" from="1r" to="8v">1r–8v</citedRange>

  * @from / @to        — copied from the locus (single-leaf loci keep just @from)
  * text               — copied from the locus verbatim (falls back to a
                         generated "from–to" / "from" only if the locus has none)
  * unit="folios"      — added (standard on citedRange)
  * NO other attribute is copied (xml:id etc. are never carried over)
  * inserted immediately before <ptr>

A bibl is SKIPPED, untouched, when the referenced ms cannot be determined safely
— no manuscript <ptr>, an empty/invalid @target, an unresolvable manuscript id,
or more than one distinct manuscript target. Skips are logged.

Run `biblRange_audit.py` first; it reports scope and flags everything needing a
human decision (see README). This script does the writes.

Dry-run by default; pass --apply to write.

    python3 maintenance/ms-biblRange-update/biblRange_sync.py          # preview
    python3 maintenance/ms-biblRange-update/biblRange_sync.py --apply  # write

Outputs:
    biblRange_sync_log_<YYYYMMDD-HHMMSS>.tsv — one row per candidate join-bibl
        (regenerated / no_change / skipped, with before/after and reason)
    a dated <change source="..."> entry in each modified host file's revisionDesc
"""

import csv
import glob
import os
import re
import sys
from datetime import datetime

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
EN_DASH = "–"
REPO_GLOB = "data/manuscripts/tei/*.xml"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PREFIX = os.path.join(HERE, "biblRange_sync_log")

FOLIO_TOKEN = re.compile(r"^\d+[rv]?[a-z]?$")
ROMAN_TOKEN = re.compile(r"^[ivxlcdm]+[rv]?$", re.IGNORECASE)
RANGE_SEP = re.compile(r"[-–—,/]")
MANUSCRIPT_TARGET = re.compile(r"/manuscript/(\d+)")
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

parser = etree.XMLParser(recover=True, remove_blank_text=False)

LOG_COLS = ["host_ms", "file", "bibl_xml_id", "bibl_xpath", "bibl_xpath_readable",
            "ref_ms", "action", "changed", "reason",
            "n_before", "n_after", "citedRanges_before", "citedRanges_after"]


def ms_id(path):
    m = re.search(r"/(\d+)\.xml$", path)
    return m.group(1) if m else os.path.basename(path)


def token_ok(v):
    v = (v or "").strip()
    return bool(v) and bool(FOLIO_TOKEN.match(v) or ROMAN_TOKEN.match(v))


def readable_xpath(el):
    parts = [etree.QName(a).localname for a in reversed(list(el.iterancestors()))]
    parts.append(etree.QName(el).localname)
    return "/".join(parts)


def gen_text(frm, to):
    """Fallback display text from from/to (used only when a locus has no text)."""
    f, t = (frm or "").strip(), (to or "").strip()
    if t and t != f:
        return f"{f}{EN_DASH}{t}"
    return f


def ref_citedranges(root):
    """citedRanges to generate for a referenced ms, mirroring its msItem/locus.

    Returns (valid, has_invalid):
      valid       — list of (from, to_or_None, text) for usable loci
      has_invalid — True if any locus is malformed (bad/packed token). Empty
                    placeholders are ignored (neither valid nor invalid).
    """
    valid, has_invalid = [], False
    for loc in root.xpath('//*[local-name()="msItem"]/*[local-name()="locus"]'):
        frm = (loc.get("from") or "").strip()
        to_raw = (loc.get("to") or "").strip()
        text_raw = "".join(loc.itertext()).strip()
        if not frm and not to_raw and not text_raw:
            continue  # empty placeholder — ignore
        if (not token_ok(frm) or RANGE_SEP.search(frm)
                or (to_raw and not token_ok(to_raw))):
            has_invalid = True  # malformed -> REF_LOCUS_INVALID, fix at source
            continue
        to = to_raw if to_raw else None
        valid.append((frm, to, text_raw or gen_text(frm, to)))
    return valid, has_invalid


def existing_citedranges(bibl):
    """Existing citedRange children as (unit, from, to_or_None, text) tuples."""
    out = []
    for cr in bibl.findall("t:citedRange", NS):
        to = (cr.get("to") or "").strip() or None
        out.append((cr.get("unit"), (cr.get("from") or "").strip() or None,
                    to, "".join(cr.itertext()).strip()))
    return out


def make_citedrange(frm, to, text):
    cr = etree.Element(f"{{{TEI}}}citedRange")
    cr.set("unit", "folios")
    cr.set("from", frm)
    if to:
        cr.set("to", to)
    cr.text = text
    return cr


def compact_crs(crs_elems):
    return " ".join(etree.tostring(c, encoding="unicode").strip() for c in crs_elems) \
        if crs_elems else ""


def sync_bibl(bibl, roots, host_mid, tree, changes):
    """Returns 'regenerated' | 'no_change' | 'skipped'. Records a log row."""
    xid = bibl.get(XML_ID) or ""
    ptrs = bibl.findall("t:ptr", NS)
    targets = [p.get("target") or "" for p in ptrs]
    hits = [MANUSCRIPT_TARGET.search(t) for t in targets]
    ms_hits = [m.group(1) for m in hits if m]
    is_candidate = ("manuscript" in xid.lower()) or bool(ms_hits)
    if not is_candidate:
        return None  # not a manuscript-join bibl

    before_elems = bibl.findall("t:citedRange", NS)
    before = compact_crs(before_elems)
    n_before = len(before_elems)

    def log(action, changed, reason, after="", n_after=""):
        changes.append({
            "host_ms": host_mid, "file": "",  # filled in by caller
            "bibl_xml_id": xid, "bibl_xpath": tree.getpath(bibl),
            "bibl_xpath_readable": readable_xpath(bibl),
            "ref_ms": ms_hits[0] if ms_hits else "", "action": action,
            "changed": "yes" if changed else "no", "reason": reason,
            "n_before": n_before, "n_after": n_after if n_after != "" else n_before,
            "citedRanges_before": before, "citedRanges_after": after or before,
        })

    # --- skip conditions (left untouched) ---
    if not ms_hits:
        log("skipped", False, "no/empty/invalid manuscript @target")
        return "skipped"
    if len(set(ms_hits)) > 1:
        log("skipped", False, f"multiple manuscript targets: {sorted(set(ms_hits))}")
        return "skipped"
    ref = ms_hits[0]
    if ref not in roots:
        log("skipped", False, f"referenced ms {ref} not found in corpus")
        return "skipped"

    # --- build the mirror set; never wipe unless we have valid mirrors to add ---
    new, has_invalid = ref_citedranges(roots[ref])
    if has_invalid:
        log("skipped", False,
            f"referenced ms {ref} has a malformed locus (REF_LOCUS_INVALID); "
            "fix loci first — existing citedRanges left untouched")
        return "skipped"
    if not new:
        log("skipped", False,
            f"referenced ms {ref} has no usable loci (REF_NO_LOCI); "
            "nothing to generate — existing citedRanges left untouched")
        return "skipped"

    new_tuples = [("folios", f, t, txt) for (f, t, txt) in new]
    if existing_citedranges(bibl) == new_tuples:
        log("no_change", False, "existing citedRanges already mirror referenced loci")
        return "no_change"

    # --- regenerate: remove all citedRange children, insert mirrors before <ptr> ---
    ptr = bibl.find("t:ptr", NS)
    indent = None
    if ptr is not None:
        prev = ptr.getprevious()
        indent = prev.tail if prev is not None else bibl.text
    if not (indent and indent.strip() == ""):
        indent = "\n                                "  # sensible default
    for cr in before_elems:
        bibl.remove(cr)
    new_elems = [make_citedrange(f, t, txt) for (f, t, txt) in new]
    for cr in new_elems:
        cr.tail = indent
        if ptr is not None:
            ptr.addprevious(cr)
        else:
            bibl.append(cr)
    log("regenerated", True, "removed all citedRanges, regenerated from referenced loci",
        after=compact_crs(new_elems), n_after=len(new_elems))
    return "regenerated"


def add_revision_change(root, summary, when, source):
    ns = f"{{{TEI}}}"
    header = root.find(f"{ns}teiHeader")
    if header is None:
        return
    rev = header.find(f"{ns}revisionDesc")
    if rev is None:
        rev = etree.SubElement(header, f"{ns}revisionDesc")
    change = etree.Element(f"{ns}change")
    change.set("when", when)
    change.set("source", source)
    change.text = summary
    if len(rev):
        indent = rev.text if (rev.text and not rev.text.strip()) else "\n            "
        change.tail = indent
        rev.text = indent
        rev.insert(0, change)
    else:
        rev.text = "\n            "
        change.tail = "\n        "
        rev.append(change)


def write_preserving_decl(path, tree):
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    first = original.partition("\n")[0]
    trailing_nl = original.endswith("\n")
    body = etree.tostring(tree, encoding="unicode")
    out = []
    if first.lstrip().startswith("<?xml"):
        out.append(first + "\n")
    else:
        out.append('<?xml version="1.0" encoding="UTF-8"?>\n')
        body = first + body
    out.append(body.rstrip("\n"))
    if trailing_nl:
        out.append("\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("".join(out))


def main():
    apply = "--apply" in sys.argv
    files = sorted(glob.glob(REPO_GLOB))
    roots = {}
    for f in files:
        r = etree.parse(f, parser).getroot()
        if r is not None:
            roots[ms_id(f)] = r

    when = datetime.now().strftime("%Y-%m-%d")
    log_path = f"{LOG_PREFIX}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.tsv"
    log_basename = os.path.basename(log_path)

    changes = []
    counts = {"regenerated": 0, "no_change": 0, "skipped": 0}
    files_changed = 0
    total_cr = 0

    for f in files:
        mid = ms_id(f)
        root = roots.get(mid)
        if root is None:
            continue
        tree = root.getroottree()
        file_rows_before = len(changes)
        n_regen = 0
        for bibl in root.iterfind(".//t:physDesc//t:listBibl/t:bibl", NS):
            res = sync_bibl(bibl, roots, mid, tree, changes)
            if res in counts:
                counts[res] += 1
            if res == "regenerated":
                n_regen += 1
        # fill in the file column for this file's rows
        for row in changes[file_rows_before:]:
            row["file"] = f

        if n_regen:
            files_changed += 1
            n_cr = sum(int(r["n_after"]) for r in changes[file_rows_before:]
                       if r["action"] == "regenerated")
            total_cr += n_cr
            summary = (f"citedRange sync (biblRange_sync.py): regenerated {n_regen} "
                       f"join-bibl(s) ({n_cr} citedRange element(s)) from referenced loci.")
            add_revision_change(root, summary, when, log_basename)
            print(f"{f}: regenerated {n_regen} bibl(s)")
            if apply:
                write_preserving_decl(f, tree)

    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(changes)

    print("\n" + "=" * 60)
    print(f"{'APPLIED' if apply else 'DRY-RUN (no files written)'}")
    print(f"Candidate join-bibls processed: {sum(counts.values())}")
    print(f"  regenerated: {counts['regenerated']}  ({total_cr} citedRange elements)")
    print(f"  no_change:   {counts['no_change']}")
    print(f"  skipped:     {counts['skipped']}")
    print(f"Host files changed: {files_changed}")
    print(f"Log: {log_path}")
    if not apply:
        print("\nRe-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
