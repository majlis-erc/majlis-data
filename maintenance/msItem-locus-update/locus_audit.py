#!/usr/bin/env python3
"""
locus_audit.py — fetch and validate every <msItem>/<locus> in the manuscript
TEI corpus.

For each <locus> directly inside an <msItem>, the script records all of its
attributes (@from, @to, @unit, plus any others such as @target), its textual
content, and runs a set of validation checks to determine whether the element
is set up correctly to express a valid folio range.

Run from the repository root:

    python3 maintenance/msItem-locus-update/locus_audit.py

Outputs (written next to this script):
    locus_audit_report.tsv  — one row per <locus>, with parsed values + issues
    locus_audit_summary.tsv — count of loci per issue code

Read-only: this script never modifies the TEI files.
"""

import csv
import glob
import os
import re
from collections import Counter

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"

REPO_GLOB = "data/manuscripts/tei/*.xml"
HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "locus_audit_report.tsv")
SUMMARY = os.path.join(HERE, "locus_audit_summary.tsv")
TO_FIX = os.path.join(HERE, "locus_to_fix.tsv")

# Codes that need a human fix/decision, split by severity. Anything not listed
# here (BOTH_EMPTY, OPEN_ENDED, SELF_RANGE_OK) is valid/informational and is NOT
# put in the to-fix list.
ERROR_CODES = {
    "RANGE_PACKED_IN_FROM", "RANGE_PACKED_IN_TO", "BAD_FROM_FORMAT",
    "BAD_TO_FORMAT", "DESCENDING_RANGE", "TEXT_ONLY", "WHITESPACE",
    "UNIT_ON_LOCUS",
}
REVIEW_CODES = {"SIDE_INCONSISTENT", "TEXT_ATTR_MISMATCH", "MIXED_CONTENT"}

# Separators that, inside a single attribute, indicate a packed range.
RANGE_SEP = re.compile(r"[-–—,/]|(?<=[rv])\s*-\s*v")

# A single folio token: arabic number + optional side (r/v) + optional column letter.
FOLIO_TOKEN = re.compile(r"^\d+[rv]?[a-z]?$")
# Roman-numeral flyleaf token (i, ii, iii, iv, ...), optional side.
ROMAN_TOKEN = re.compile(r"^[ivxlcdm]+[rv]?$", re.IGNORECASE)

parser = etree.XMLParser(recover=True, remove_blank_text=False)


def ms_id(path):
    m = re.search(r"/(\d+)\.xml$", path)
    return m.group(1) if m else os.path.basename(path)


def readable_xpath(el):
    parts = []
    for a in reversed(list(el.iterancestors())):
        parts.append(etree.QName(a).localname)
    parts.append(etree.QName(el).localname)
    return "/".join(parts)


def parse_folio(value):
    """Parse a single folio token into a sortable key, or None if unparseable.

    Returns (number, side_rank, raw_suffix). side rank: recto(0) < verso(1) <
    none(2 -> treated as a whole leaf, sorts after verso for safety).
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    m = re.match(r"^(\d+)([rv])?([a-z])?$", s)
    if not m:
        return None
    num = int(m.group(1))
    side = m.group(2)
    side_rank = {"r": 0, "v": 1, None: 2}[side]
    col = m.group(3) or ""
    return (num, side_rank, col)


def token_ok(value):
    """True if value is a single, well-formed folio/leaf token."""
    if value is None:
        return False
    s = value.strip()
    if not s:
        return False
    return bool(FOLIO_TOKEN.match(s) or ROMAN_TOKEN.match(s))


def has_side(value):
    return bool(re.search(r"[rv]$", (value or "").strip()))


def suggest_fix(frm, to, codes):
    """An obvious mechanical fix where one exists, else '' (needs human input)."""
    f = (frm or "").strip()
    # combined recto/verso packed in @from, e.g. "5r-v" -> from="5r" to="5v"
    m = re.match(r"^(\d+)r-v$", f)
    if "RANGE_PACKED_IN_FROM" in codes and m:
        return f'from="{m.group(1)}r" to="{m.group(1)}v"'
    # leading/trailing whitespace only -> trimmed values
    if codes == {"WHITESPACE"}:
        return f'from="{f}" to="{(to or "").strip()}"'
    return ""


def check_locus(frm, to, unit, text, has_children=False):
    """Return a list of (code, message) issues for one locus."""
    issues = []
    frm_s = (frm or "").strip()
    to_s = (to or "").strip()
    text_s = (text or "").strip()
    unit_raw = unit  # None means attribute absent

    # --- A. structural / presence ---
    if has_children:
        issues.append(("MIXED_CONTENT",
                       "locus contains child element(s); the auto text-sync skips "
                       "it — verify @from/@to and that the markup is intended"))
    if not frm_s and not to_s and not text_s:
        issues.append(("BOTH_EMPTY", "no @from, @to or text content"))
        return issues  # nothing else meaningful to check
    if not frm_s and text_s:
        issues.append(("TEXT_ONLY", f"text {text_s!r} but no @from; add @from/@to"))
    if frm_s and not to_s:
        issues.append(("OPEN_ENDED", "has @from but empty/absent @to (confirm single folio)"))

    # --- B. packed range / token format ---
    if frm_s and RANGE_SEP.search(frm_s):
        issues.append(("RANGE_PACKED_IN_FROM",
                       f'@from {frm_s!r} looks like a range; split into @from/@to'))
    if to_s and RANGE_SEP.search(to_s):
        issues.append(("RANGE_PACKED_IN_TO",
                       f'@to {to_s!r} looks like a range; split into @from/@to'))
    if frm_s and not RANGE_SEP.search(frm_s) and not token_ok(frm_s):
        issues.append(("BAD_FROM_FORMAT", f'@from {frm_s!r} is not a recognised folio token'))
    if to_s and not RANGE_SEP.search(to_s) and not token_ok(to_s):
        issues.append(("BAD_TO_FORMAT", f'@to {to_s!r} is not a recognised folio token'))
    if frm is not None and frm != frm.strip():
        issues.append(("WHITESPACE", "@from has leading/trailing whitespace"))
    if to is not None and to != to.strip():
        issues.append(("WHITESPACE", "@to has leading/trailing whitespace"))

    # --- C. unit on locus ---
    # @unit is NOT a standard attribute of <locus> (it belongs on <citedRange>);
    # a <locus> is folios by nature, and the foliation system, if it must be
    # recorded, is expressed via @scheme. So flag @unit only when wrongly present.
    if unit_raw is not None:
        issues.append(("UNIT_ON_LOCUS",
                       f'@unit={unit_raw.strip()!r} is non-standard on <locus>; '
                       'unit belongs on <citedRange>, use @scheme for foliation system'))

    # --- D. range logic ---
    pf, pt = parse_folio(frm_s), parse_folio(to_s)
    if pf and pt:
        if pf > pt:
            issues.append(("DESCENDING_RANGE", f"@from {frm_s} sorts after @to {to_s}"))
        elif pf == pt:
            issues.append(("SELF_RANGE_OK", f"@from == @to ({frm_s})"))
        # one endpoint carries an r/v side and the other does not
        if has_side(frm_s) != has_side(to_s):
            issues.append(("SIDE_INCONSISTENT",
                           f"endpoints mix sided/unsided refs ({frm_s}/{to_s}); "
                           "normalise both (e.g. 1 -> 1r)"))

    # --- E. text vs attributes ---
    if text_s and (frm_s or to_s):
        # normalise away whitespace and dash style (en/em dash vs hyphen) so the
        # generated "1r–4v" text is not falsely flagged against @from/@to "1r"/"4v"
        def _norm(s):
            s = re.sub(r"\s+", "", s.lower())
            return s.replace("–", "-").replace("—", "-")
        norm_text = _norm(text_s)
        norm_attr = _norm(f"{frm_s}-{to_s}").strip("-")
        # only flag obvious disagreement when text contains folio-ish tokens
        if re.search(r"\d", norm_text) and norm_attr and norm_attr not in norm_text \
                and norm_text not in norm_attr:
            issues.append(("TEXT_ATTR_MISMATCH",
                           f"text {text_s!r} disagrees with @from/@to ({frm_s}/{to_s})"))

    return issues


def main():
    files = sorted(glob.glob(REPO_GLOB))
    rows = []
    issue_counter = Counter()
    locus_total = 0

    for path in files:
        try:
            tree = etree.parse(path, parser)
        except Exception as e:  # noqa: BLE001
            rows.append({"ms_id": ms_id(path), "locus_xpath": "", "unit": "",
                         "from": "", "to": "", "text": "",
                         "other_attrs": "", "n_issues": "1",
                         "issues": f"PARSE_ERROR: {e}"})
            issue_counter["PARSE_ERROR"] += 1
            continue
        root = tree.getroot()
        if root is None:
            continue
        for locus in root.xpath('//*[local-name()="msItem"]/*[local-name()="locus"]'):
            locus_total += 1
            frm = locus.get("from")
            to = locus.get("to")
            unit = locus.get("unit")
            # full text content (handles mixed content / child elements), not
            # just the leading text node, so text-only loci are never under-read
            text = "".join(locus.itertext())
            other = {k: v for k, v in locus.attrib.items()
                     if etree.QName(k).localname not in ("from", "to", "unit")}
            other_str = "; ".join(f"{etree.QName(k).localname}={v}" for k, v in other.items())

            has_children = any(isinstance(c.tag, str) for c in locus)
            issues = check_locus(frm, to, unit, text, has_children=has_children)
            for code, _ in issues:
                issue_counter[code] += 1

            rows.append({
                "ms_id": ms_id(path),
                "locus_xpath": tree.getpath(locus),
                "locus_xpath_readable": readable_xpath(locus),
                "unit": unit if unit is not None else "(absent)",
                "from": frm if frm is not None else "(absent)",
                "to": to if to is not None else "(absent)",
                "text": text.strip(),
                "other_attrs": other_str,
                "n_issues": str(len(issues)),
                "issues": " | ".join(f"{c}: {m}" for c, m in issues),
                "_codes": {c for c, _ in issues},
            })

    cols = ["ms_id", "locus_xpath", "locus_xpath_readable", "unit", "from", "to",
            "text", "other_attrs", "n_issues", "issues"]
    with open(REPORT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    with open(SUMMARY, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["issue_code", "count"])
        for code, n in issue_counter.most_common():
            w.writerow([code, n])

    # --- to-fix shortlist: every locus needing a human fix/decision ---
    fix_cols = ["severity", "ms_id", "locus_xpath", "locus_xpath_readable",
                "from", "to", "text", "issue", "suggested_fix",
                "final_fix"]
    fix_rows = []
    for r in rows:
        codes = r.get("_codes", set())
        actionable = codes & (ERROR_CODES | REVIEW_CODES)
        if not actionable:
            continue
        fix_rows.append({
            "severity": "ERROR" if codes & ERROR_CODES else "REVIEW",
            "ms_id": r["ms_id"], "locus_xpath": r["locus_xpath"],
            "locus_xpath_readable": r["locus_xpath_readable"],
            "from": r["from"], "to": r["to"], "text": r["text"],
            "issue": ";".join(sorted(actionable)),
            "suggested_fix": suggest_fix(
                None if r["from"] == "(absent)" else r["from"],
                None if r["to"] == "(absent)" else r["to"], actionable),
            "final_fix": "",  # to be filled in by the reviewer
        })
    fix_rows.sort(key=lambda x: (x["severity"] != "ERROR",
                                 int(x["ms_id"]) if x["ms_id"].isdigit() else 0))
    with open(TO_FIX, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fix_cols, delimiter="\t")
        w.writeheader()
        w.writerows(fix_rows)

    flagged = sum(1 for r in rows if r["issues"])
    print(f"Scanned {len(files)} files, {locus_total} <msItem>/<locus> elements.")
    print(f"{flagged} loci have at least one issue.\n")
    print("Issue frequency:")
    for code, n in issue_counter.most_common():
        print(f"  {n:5}  {code}")
    print(f"\n{len(fix_rows)} loci need a fix/decision -> {TO_FIX}")
    print(f"Wrote {REPORT}")
    print(f"Wrote {SUMMARY}")


if __name__ == "__main__":
    main()
