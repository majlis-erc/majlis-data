#!/usr/bin/env python3
"""
biblRange_audit.py — read-only audit for the citedRange-from-locus sync.

For every manuscript-join <bibl> (a <bibl> in physDesc//listBibl that points to
another manuscript via <ptr target=".../manuscript/N"/>), this reports what a
scoped sync WOULD do — regenerate that bibl's folio <citedRange> elements from
the referenced manuscript N's <msItem>/<locus> — and flags everything that needs
a human decision before any write.

Read-only: never modifies TEI files.

Run from the repository root:

    python3 maintenance/ms-biblRange-update/biblRange_audit.py

Outputs (next to this script):
    biblRange_audit_report.tsv  — one row per candidate join-bibl
    biblRange_audit_summary.tsv — count per issue code
    biblRange_to_review.tsv     — shortlist: only rows needing human attention
"""

import csv
import glob
import os
import re
from collections import Counter, defaultdict

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}
REPO_GLOB = "data/manuscripts/tei/*.xml"
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "biblRange_audit_report.tsv")
SUMMARY = os.path.join(HERE, "biblRange_audit_summary.tsv")
TO_REVIEW = os.path.join(HERE, "biblRange_to_review.tsv")

FOLIO_TOKEN = re.compile(r"^\d+[rv]?[a-z]?$")
ROMAN_TOKEN = re.compile(r"^[ivxlcdm]+[rv]?$", re.IGNORECASE)
RANGE_SEP = re.compile(r"[-–—,/]")
MANUSCRIPT_TARGET = re.compile(r"/manuscript/(\d+)")

# issue codes by severity. BLOCKER + REVIEW go on the human-review shortlist;
# INFO is reported separately (not actionable per-join, just surfaced).
BLOCKER = {"MISSING_PTR", "EMPTY_OR_INVALID_TARGET", "UNRESOLVABLE_TARGET",
           "MULTIPLE_PTRS"}
REVIEW = {"NONDERIVABLE_CITEDRANGE", "NONFOLIO_IN_JOINBIBL",
          "REF_LOCUS_INVALID", "BIDIRECTIONAL_MISMATCH"}
# INFO = surfaced but handled automatically, not a per-join decision:
#   REF_NO_LOCI    -> referenced ms not foliated -> nothing to generate
#   MULTI_ITEM_REF -> referenced ms has several loci -> generate one citedRange
#                     per valid locus (flatten-all, by design)
INFO = {"REF_NO_LOCI", "MULTI_ITEM_REF"}

parser = etree.XMLParser(recover=True, remove_blank_text=False)


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


def load_corpus():
    """Return {ms_id: root}. Parses every file once."""
    roots = {}
    for f in sorted(glob.glob(REPO_GLOB)):
        try:
            r = etree.parse(f, parser).getroot()
        except Exception:
            r = None
        if r is not None:
            roots[ms_id(f)] = r
    return roots


def ref_loci(root):
    """Inspect a referenced ms's msItem/locus elements.

    Returns dict: usable=[(from,to)], n_items, n_loci, has_invalid_locus.
    A locus is 'usable' for a citedRange if @from is a valid token (to optional).
    """
    items = root.xpath('//*[local-name()="msItem"]')
    loci = root.xpath('//*[local-name()="msItem"]/*[local-name()="locus"]')
    usable, invalid = [], False
    items_with_loci = 0
    for it in items:
        if it.findall("t:locus", NS):
            items_with_loci += 1
    for l in loci:
        frm = (l.get("from") or "").strip()
        to = (l.get("to") or "").strip()
        if not frm and not to:
            continue  # empty placeholder — ignore, not invalid
        if not token_ok(frm) or RANGE_SEP.search(frm) or (to and not token_ok(to)):
            invalid = True
            continue
        usable.append((frm, to))
    return {
        "usable": usable,
        "n_items_with_loci": items_with_loci,
        "n_loci": len([l for l in loci if (l.get("from") or "").strip()
                       or (l.get("to") or "").strip()]),
        "has_invalid_locus": invalid,
    }


def existing_folio_cr(bibl):
    """List of (from,to) for folio citedRanges already in the bibl, plus a flag
    for any non-folio citedRange present."""
    folio, nonfolio = [], False
    for cr in bibl.findall("t:citedRange", NS):
        unit = (cr.get("unit") or "").strip()
        if unit in ("folios", "folio", ""):
            f = (cr.get("from") or "").strip()
            t = (cr.get("to") or "").strip()
            if f or t:
                folio.append((f, t))
        else:
            nonfolio = True
    return folio, nonfolio


def main():
    roots = load_corpus()

    # join graph: ms -> set(referenced ms) for bidirectional check
    join_map = defaultdict(set)
    for mid, root in roots.items():
        for bibl in root.iterfind(".//t:physDesc//t:listBibl/t:bibl", NS):
            for ptr in bibl.findall("t:ptr", NS):
                m = MANUSCRIPT_TARGET.search(ptr.get("target") or "")
                if m:
                    join_map[mid].add(m.group(1))

    rows = []
    counter = Counter()

    for mid in sorted(roots, key=lambda x: int(x) if x.isdigit() else 0):
        root = roots[mid]
        tree = root.getroottree()
        for bibl in root.iterfind(".//t:physDesc//t:listBibl/t:bibl", NS):
            xid = bibl.get("{http://www.w3.org/XML/1998/namespace}id") or ""
            ptrs = bibl.findall("t:ptr", NS)
            targets = [p.get("target") or "" for p in ptrs]
            ms_targets = [MANUSCRIPT_TARGET.search(t) for t in targets]
            ms_hits = [m.group(1) for m in ms_targets if m]
            is_candidate = ("manuscript" in xid.lower()) or bool(ms_hits)
            if not is_candidate:
                continue  # not a manuscript-join bibl — out of scope

            issues = []
            ref = ms_hits[0] if ms_hits else ""

            # --- A. join validity ---
            if len(ptrs) == 0:
                issues.append("MISSING_PTR")
            elif len(ptrs) > 1 and len(set(ms_hits)) > 1:
                issues.append("MULTIPLE_PTRS")
            if ptrs and not ms_hits:
                issues.append("EMPTY_OR_INVALID_TARGET")
            if ms_hits and ref not in roots:
                issues.append("UNRESOLVABLE_TARGET")

            folio_cr, has_nonfolio = existing_folio_cr(bibl)
            n_add = n_remove = n_keep = ""

            resolvable = bool(ms_hits) and ref in roots and "MULTIPLE_PTRS" not in issues
            if resolvable:
                info = ref_loci(roots[ref])
                gen = set(info["usable"])
                cur = set(folio_cr)
                add = gen - cur
                remove = cur - gen
                keep = cur & gen
                n_add, n_remove, n_keep = len(add), len(remove), len(keep)

                # --- B. removal-safety ---
                if remove:
                    issues.append("NONDERIVABLE_CITEDRANGE")
                if has_nonfolio:
                    issues.append("NONFOLIO_IN_JOINBIBL")
                # --- C. referenced-side ---
                if not info["usable"]:
                    issues.append("REF_NO_LOCI")
                if info["has_invalid_locus"]:
                    issues.append("REF_LOCUS_INVALID")
                # --- D. editorial ---
                if info["n_items_with_loci"] > 1 or info["n_loci"] > 1:
                    issues.append("MULTI_ITEM_REF")
                if mid not in join_map.get(ref, set()):
                    issues.append("BIDIRECTIONAL_MISMATCH")

            for code in issues:
                counter[code] += 1

            iset = set(issues)
            sev = ("BLOCKER" if iset & BLOCKER
                   else "REVIEW" if iset & REVIEW
                   else "INFO" if iset & INFO else "OK")
            rows.append({
                "host_ms": mid,
                "bibl_xml_id": xid,
                "bibl_xpath_readable": readable_xpath(bibl),
                "ref_ms": ref,
                "target": targets[0] if targets else "",
                "ref_resolvable": "yes" if resolvable else "no",
                "would_add": n_add,
                "would_remove": n_remove,
                "would_keep": n_keep,
                "severity": sev,
                "issues": ";".join(issues),
            })

    cols = ["host_ms", "bibl_xml_id", "bibl_xpath_readable", "ref_ms", "target",
            "ref_resolvable", "would_add", "would_remove", "would_keep",
            "severity", "issues"]
    with open(REPORT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    with open(SUMMARY, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["issue_code", "count"])
        for code, n in counter.most_common():
            w.writerow([code, n])

    review = [r for r in rows if r["severity"] in ("BLOCKER", "REVIEW")]
    review.sort(key=lambda r: (r["severity"] != "BLOCKER",
                               int(r["host_ms"]) if r["host_ms"].isdigit() else 0))
    with open(TO_REVIEW, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(review)

    total = len(rows)
    sev_count = Counter(r["severity"] for r in rows)
    # what the syncable joins would generate
    syncable = [r for r in rows if r["ref_resolvable"] == "yes"
                and r["severity"] != "BLOCKER"]
    total_add = sum(int(r["would_add"]) for r in syncable if r["would_add"] != "")
    total_remove = sum(int(r["would_remove"]) for r in syncable if r["would_remove"] != "")
    add_some = sum(1 for r in syncable if r["would_add"] not in ("", 0, "0"))

    print(f"Candidate join-bibls: {total}")
    print(f"  OK (clean, will sync):        {sev_count['OK']}")
    print(f"  REVIEW/BLOCKER (-> to_review): {len(review)}")
    print(f"  INFO (auto-handled):          {sev_count['INFO']}")
    print()
    print("Generation scope (resolvable, non-blocked joins):")
    print(f"  citedRanges that would be ADDED:   {total_add}")
    print(f"  existing folio CR to be REMOVED:   {total_remove}")
    print(f"  join-bibls that gain >=1 citedRange: {add_some}")
    print()
    print("Issue frequency:")
    for code, n in counter.most_common():
        tag = "BLOCKER" if code in BLOCKER else "INFO" if code in INFO else "REVIEW"
        print(f"  {n:5}  {code}  [{tag}]")
    print(f"\nWrote {REPORT}")
    print(f"Wrote {SUMMARY}")
    print(f"Wrote {TO_REVIEW}  ({len(review)} rows)")


if __name__ == "__main__":
    main()
