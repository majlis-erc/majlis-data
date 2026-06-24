#!/usr/bin/env python3
"""
apply_locus_fixes.py — fix malformed <msItem>/<locus> elements and normalise
their textual content.

Two phases:

  Part A — apply the reviewed fixes from locus_to_fix_reviewed.tsv.
           The reviewer's "final_fix" column holds the COMPLETE replacement: one
           or more literal <locus ...>...</locus> elements that wholly replace
           the target locus (so a single locus may be split into several). The
           whole element is replaced — attributes and text both come from
           final_fix; any other attribute on the original not restated there is
           carried over. Rows with an empty final_fix are skipped (un-reviewed).
           Targets are matched by (ms_id, raw @from, raw @to).

  Part B — make every well-formed <msItem>/<locus>'s text agree with @from/@to:
             from="2r" to="10v"  -> "2r–10v"   (en dash)
             from="2r" (no @to)  -> "2r"        (single leaf, per TEI)
             from="1r" to="1r"   -> "1r"        (single leaf)
           Behaviour designed to stay safe and idempotent as the corpus evolves:
             * adds text where none exists;
             * re-syncs text that is in the script's own canonical format
               (a folio token, or token–token / token-token) but no longer
               matches the attributes (e.g. normalises a hyphen to an en dash,
               or refreshes a stale range);
             * PRESERVES human-authored text — anything containing words,
               prefixes or punctuation such as "ff. 2r–10v" or "11r, top" — so
               re-runs never destroy editorial labels;
             * SKIPS empty placeholders (from="" to=""), mixed content, invalid
               ranges (where @from sorts after @to) and unrecognised tokens,
               reporting them for review instead of guessing.

Every change written to an XML file is recorded, one row per element, in
locus_change_log.tsv (full before/after).

Run from the repository root. Dry-run by default; pass --apply to write changes.

    python3 maintenance/msItem-locus-update/apply_locus_fixes.py          # preview
    python3 maintenance/msItem-locus-update/apply_locus_fixes.py --apply  # write
"""

import csv
import glob
import os
import re
import sys
from datetime import datetime

from lxml import etree

TEI = "http://www.tei-c.org/ns/1.0"
EN_DASH = "–"

HERE = os.path.dirname(os.path.abspath(__file__))
FIX_TSV = os.path.join(HERE, "locus_to_fix_reviewed.tsv")
# change log filename gets a generation timestamp appended at run time
CHANGE_LOG_PREFIX = os.path.join(HERE, "locus_change_log")
REPO_GLOB = "data/manuscripts/tei/*.xml"
# reviewer's column: the complete replacement <locus> element(s) for each row
DECISION_COL = "final_fix"

FOLIO_TOKEN = re.compile(r"^\d+[rv]?[a-z]?$")
ROMAN_TOKEN = re.compile(r"^[ivxlcdm]+[rv]?$", re.IGNORECASE)
# Text that the script itself produces / owns: a single token, or two tokens
# joined by an em dash, en dash or hyphen, optionally surrounded by spaces.
MACHINE_TEXT = re.compile(
    r"^\s*(\d+[rv]?[a-z]?|[ivxlcdm]+[rv]?)"
    r"(\s*[—–-]\s*(\d+[rv]?[a-z]?|[ivxlcdm]+[rv]?))?\s*$",
    re.IGNORECASE,
)

parser = etree.XMLParser(recover=True, remove_blank_text=False)


def token_ok(value):
    if not value:
        return False
    s = value.strip()
    return bool(FOLIO_TOKEN.match(s) or ROMAN_TOKEN.match(s))


def parse_folio(value):
    """Sortable key for a folio token, or None if unparseable.
    side rank: recto(0) < verso(1) < none(2)."""
    if not value:
        return None
    m = re.match(r"^(\d+)([rv])?([a-z])?$", value.strip())
    if not m:
        return None
    return (int(m.group(1)), {"r": 0, "v": 1, None: 2}[m.group(2)], m.group(3) or "")


def is_machine_text(s):
    """True if `s` is in the script's own canonical/auto format (tokens + dash),
    i.e. text the script may safely re-sync. Human prose/labels return False."""
    return bool(MACHINE_TEXT.match(s))


def machine_tokens(s):
    """Lowercased token list of canonical machine text ('1r–5v' -> ['1r','5v']),
    or None if `s` is not machine format."""
    if not is_machine_text(s):
        return None
    return [p.strip().lower() for p in re.split(r"[—–-]", s.strip())]


def norm_quotes(s):
    """Normalise smart quotes to straight double quotes."""
    return (s.replace("“", '"').replace("”", '"')
             .replace("„", '"').replace("‟", '"')
             .replace("‘", "'").replace("’", "'"))


def tsv_to_attr(value):
    """'(absent)' -> None ; '' stays '' ; otherwise the literal string."""
    return None if value == "(absent)" else value


def load_fixes():
    """Return dict: ms_id -> list of fix dicts (only rows with a final_fix)."""
    fixes = {}
    with open(FIX_TSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            final = (row.get(DECISION_COL) or "").strip()
            if not final:
                continue  # un-reviewed row
            fixes.setdefault(row["ms_id"], []).append({
                "from": tsv_to_attr(row["from"]),
                "to": tsv_to_attr(row["to"]),
                "final_fix": final,
            })
    return fixes


def parse_replacement(decision):
    """Parse a final_fix string of one or more <locus> elements into a list of
    new lxml elements in the TEI namespace."""
    xml = norm_quotes(decision)
    wrapped = f'<root xmlns="{TEI}">{xml}</root>'
    root = etree.fromstring(wrapped)
    return list(root)


def find_locus(root, frm, to):
    """Find the msItem/locus whose raw @from/@to match frm/to."""
    for loc in root.xpath('//*[local-name()="msItem"]/*[local-name()="locus"]'):
        if loc.get("from") == frm and loc.get("to") == to:
            return loc
    return None


def gen_text(frm, to):
    """Dash-separated (or single) text from from/to, or None if not derivable
    (unrecognised token, or an invalid range where @from sorts after @to)."""
    f = (frm or "").strip()
    t = (to or "").strip()
    if not token_ok(f):
        return None
    if t and token_ok(t) and t != f:
        pf, pt = parse_folio(f), parse_folio(t)
        if pf and pt and pf > pt:
            return None  # invalid descending range — refuse, report for review
        return f"{f}{EN_DASH}{t}"
    # single leaf: no @to, empty @to, or to == from
    return f


def readable_xpath(el):
    parts = [etree.QName(a).localname for a in reversed(list(el.iterancestors()))]
    parts.append(etree.QName(el).localname)
    return "/".join(parts)


def compact(el):
    """Compact serialisation of a locus for the change log (no namespace, no
    internal marker attribute)."""
    tag = etree.QName(el).localname
    attrs = " ".join(f'{etree.QName(k).localname}="{v}"'
                     for k, v in el.attrib.items() if k != PART_A_MARKER)
    head = f"{tag} {attrs}".strip()
    txt = "".join(el.itertext())
    return f"<{head}>{txt}</{tag}>" if txt else f"<{head}/>"


CHANGE_COLS = [
    "ms_id", "file", "locus_xpath", "locus_xpath_readable", "part", "action",
    "changed", "from_before", "to_before", "text_before", "other_attrs_before",
    "from_after", "to_after", "text_after", "other_attrs_after",
    "element_before", "element_after", "note",
]


def other_attrs(el):
    return "; ".join(f"{etree.QName(k).localname}={v}"
                     for k, v in el.attrib.items()
                     if k != PART_A_MARKER
                     and etree.QName(k).localname not in ("from", "to"))


XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
# Temporary marker flagging elements authored by Part A, so Part B leaves their
# text alone. lxml element identity (id()) is unstable across xpath queries, so
# we mark on the node itself and strip the marker before writing.
PART_A_MARKER = "__partA_authored"


def carry_attrs(original, new_elem, first, log):
    """Copy auxiliary attributes of `original` that the replacement does not
    define onto `new_elem` (e.g. xml:id, @n, @target, @scheme). @from/@to are
    the core attributes the reviewer fully specifies in final_fix, so they are
    NEVER carried over — otherwise the original's @to would leak onto a
    replacement that deliberately omits it (single-leaf). xml:id is unique, so on
    a 1->N split it is carried only to the first new element."""
    for k, v in original.attrib.items():
        if k in ("from", "to"):
            continue  # fully owned by the reviewer's replacement element
        if k in new_elem.attrib:
            continue  # reviewed value wins
        if k == XML_ID and not first:
            log.append(f"  [Part A] WARNING: dropped xml:id={v!r} on a split "
                       f"element (would duplicate the id); set it manually if needed")
            continue
        new_elem.set(k, v)


def apply_part_a(root, ms_fixes, log, changes, mid, path, tree):
    """Apply Part A fixes to a parsed tree. Returns the number of changes.

    Replacement elements are flagged with PART_A_MARKER so Part B leaves their
    (human-reviewed) text untouched; the marker is stripped before writing.
    Every change is appended to `changes`.
    """
    changed = 0
    for fx in ms_fixes:
        loc = find_locus(root, fx["from"], fx["to"])
        if loc is None:
            log.append(f"  [Part A] ms target NOT FOUND: from={fx['from']!r} to={fx['to']!r}")
            continue
        final = fx["final_fix"]
        if not norm_quotes(final).lstrip().startswith("<locus"):
            log.append(f"  [Part A] SKIP: final_fix is not <locus> element(s): {final!r}")
            continue

        parent = loc.getparent()
        idx = parent.index(loc)
        tail = loc.tail
        xpath_r = readable_xpath(loc)
        b_from, b_to = loc.get("from"), loc.get("to")
        b_text = "".join(loc.itertext())
        b_other = other_attrs(loc)
        b_elem = compact(loc)

        # the whole locus is replaced by the reviewer's element(s)
        news = parse_replacement(final)
        parent.remove(loc)
        for i, ne in enumerate(news):
            carry_attrs(loc, ne, first=(i == 0), log=log)
            ne.set(PART_A_MARKER, "1")  # Part A content is authoritative
            ne.tail = tail
            parent.insert(idx + i, ne)
            changes.append({
                "ms_id": mid, "file": path, "locus_xpath": tree.getpath(ne),
                "locus_xpath_readable": readable_xpath(ne), "part": "A",
                "action": "replace_element", "changed": "yes",
                "from_before": b_from, "to_before": b_to, "text_before": b_text,
                "other_attrs_before": b_other,
                "from_after": ne.get("from"), "to_after": ne.get("to"),
                "text_after": "".join(ne.itertext()), "other_attrs_after": other_attrs(ne),
                "element_before": b_elem, "element_after": compact(ne),
                "note": f"reviewed final_fix: element {i + 1} of {len(news)}",
            })
        log.append(f"  [Part A] replaced 1 locus (from={fx['from']!r}) "
                   f"with {len(news)} element(s)")
        changed += 1
    return changed


def apply_part_b(root, log, changes, mid, path, tree):
    """Make well-formed loci's text agree with @from/@to (see module docstring).

    Returns (added, fixed, other, preserved, mismatched) where:
      other      = (frm, to) left untouched & needing review (bad range, unknown
                   token, mixed content);
      preserved  = (frm, to, text) human-authored prose/label deliberately kept;
      mismatched = (frm, to, text) canonical-format text whose folios DIFFER from
                   the attributes — never overwritten, left for human review.
    """
    added = fixed = 0
    other, preserved, mismatched = [], [], []
    for loc in root.xpath('//*[local-name()="msItem"]/*[local-name()="locus"]'):
        if loc.get(PART_A_MARKER):
            continue  # already logged by Part A
        frm = loc.get("from")
        to = loc.get("to")
        f = (frm or "").strip()
        t = (to or "").strip()
        existing = "".join(loc.itertext()).strip()
        b_other = other_attrs(loc)
        b_elem = compact(loc)

        def rec(action, changed, note, text_after=None):
            changes.append({
                "ms_id": mid, "file": path, "locus_xpath": tree.getpath(loc),
                "locus_xpath_readable": readable_xpath(loc), "part": "B",
                "action": action, "changed": "yes" if changed else "no",
                "from_before": frm, "to_before": to, "text_before": existing,
                "other_attrs_before": b_other,
                "from_after": frm, "to_after": to,
                "text_after": text_after if text_after is not None else existing,
                "other_attrs_after": b_other,
                "element_before": b_elem,
                "element_after": compact(loc) if changed else b_elem,
                "note": note,
            })

        if not f and not t:
            rec("skip_empty", False, "empty placeholder (no @from/@to) — nothing to render")
            continue
        expected = gen_text(frm, to)
        if expected is None:
            other.append((frm, to))
            rec("review_invalid", False,
                "invalid range (@from after @to) or unrecognised token — needs review")
            continue
        # expected folios as tokens: single leaf, or [from, to]
        exp_tokens = [f.lower()] if expected == f else [f.lower(), t.lower()]

        if not existing:
            loc.text = expected
            added += 1
            rec("add_text", True, "added text from @from/@to", expected)
        elif existing == expected:
            rec("no_change", False, "text already matches @from/@to")
        elif len(loc):
            other.append((frm, to))
            rec("review_mixed", False, "mixed content (child elements) — left untouched, review")
        elif not is_machine_text(existing):
            preserved.append((frm, to, existing))
            rec("preserve_human", False, "human prose/label — preserved")
        elif machine_tokens(existing) == exp_tokens:
            loc.text = expected
            fixed += 1
            log.append(f"  [Part B] FIX text {existing!r} -> {expected!r}")
            rec("fix_text_cosmetic", True, "normalised separator/spacing (same folios)", expected)
        else:
            mismatched.append((frm, to, existing))
            rec("review_mismatch", False,
                "canonical text disagrees with @from/@to — left untouched, review")
    return added, fixed, other, preserved, mismatched


def add_revision_change(root, summary, when, source=None):
    """Prepend a <change when=... source=...> to teiHeader/revisionDesc recording
    this run's edits. `source` is the change-log filename (basename). Returns True
    if a change element was added."""
    ns = f"{{{TEI}}}"
    header = root.find(f"{ns}teiHeader")
    if header is None:
        return False
    rev = header.find(f"{ns}revisionDesc")
    created = rev is None
    if created:
        rev = etree.SubElement(header, f"{ns}revisionDesc")

    change = etree.Element(f"{ns}change")
    change.set("when", when)
    if source:
        change.set("source", source)  # the detailed change-log file for this run
    change.text = summary

    if len(rev):
        # match the whitespace indentation of the existing first child
        indent = rev.text if (rev.text and not rev.text.strip()) else "\n            "
        change.tail = indent
        rev.text = indent
        rev.insert(0, change)
    else:
        rev.text = "\n            "
        change.tail = "\n        "
        rev.append(change)
        if created:
            rev.tail = "\n    "
    return True


def write_preserving_decl(path, tree):
    """Write the tree but keep the file's original XML declaration line, so the
    only diff is the actual content change (lxml otherwise rewrites "1.0" with
    single quotes)."""
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    first, _, _ = original.partition("\n")
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
    fixes = load_fixes()
    files = sorted(glob.glob(REPO_GLOB))

    total_a = total_b_add = total_b_fix = 0
    other_all, preserved_all, mismatched_all = [], [], []
    changes = []
    touched_files = 0

    # name this run's change log up front so each <change> can cite it via @source
    run_dt = datetime.now()
    when = run_dt.strftime("%Y-%m-%d")
    change_log = f"{CHANGE_LOG_PREFIX}_{run_dt.strftime('%Y%m%d-%H%M%S')}.tsv"
    log_basename = os.path.basename(change_log)

    for path in files:
        mid = re.search(r"/(\d+)\.xml$", path)
        mid = mid.group(1) if mid else None
        tree = etree.parse(path, parser)
        root = tree.getroot()
        if root is None:
            continue
        log = []

        a = (apply_part_a(root, fixes[mid], log, changes, mid, path, tree)
             if mid in fixes else 0)
        added, fixed, other, preserved, mismatched = apply_part_b(
            root, log, changes, mid, path, tree)
        for frm, to in other:
            other_all.append((mid, frm, to))
        for frm, to, txt in preserved:
            preserved_all.append((mid, frm, to, txt))
        for frm, to, txt in mismatched:
            mismatched_all.append((mid, frm, to, txt))

        # strip the temporary Part A marker before serialising
        for el in root.iter():
            if el.get(PART_A_MARKER) is not None:
                el.attrib.pop(PART_A_MARKER, None)

        if a or added or fixed:
            touched_files += 1
            total_a += a
            total_b_add += added
            total_b_fix += fixed
            # record this run's edits in the file's revisionDesc
            parts = []
            if a:
                parts.append(f"{a} reviewed locus fix(es)")
            if added:
                parts.append(f"{added} locus text value(s) added from @from/@to")
            if fixed:
                parts.append(f"{fixed} locus text value(s) re-synced to @from/@to")
            summary = ("Locus folio data updated (apply_locus_fixes.py): "
                       + "; ".join(parts) + ".")
            add_revision_change(root, summary, when, source=log_basename)
            print(f"{path}: Part A={a}, Part B added={added}, fixed={fixed}")
            for line in log:
                print(line)
            if apply:
                write_preserving_decl(path, tree)

    # always write the change log (covers exactly what was/would be written);
    # its basename is what each modified file's <change source="..."> cites
    with open(change_log, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CHANGE_COLS, delimiter="\t")
        w.writeheader()
        w.writerows(changes)

    print("\n" + "=" * 60)
    print(f"{'APPLIED' if apply else 'DRY-RUN (no files written)'}")
    print(f"Files touched:                {touched_files}")
    print(f"Part A fixes applied:         {total_a}")
    print(f"Part B text values added:     {total_b_add}")
    print(f"Part B text values re-synced: {total_b_fix}")
    n_changed = sum(1 for c in changes if c["changed"] == "yes")
    print(f"Detailed log rows (incl. no-change): {len(changes)} "
          f"({n_changed} changed) -> {change_log}")
    if preserved_all:
        print(f"\nHuman-authored text preserved (prose/label, left untouched): "
              f"{len(preserved_all)}")
        for mid, frm, to, txt in preserved_all[:20]:
            print(f"   ms {mid}: from={frm!r} to={to!r} text={txt!r}")
    if mismatched_all:
        print(f"\nCanonical text DISAGREES with attributes — NOT overwritten, "
              f"review (audit flags TEXT_ATTR_MISMATCH): {len(mismatched_all)}")
        for mid, frm, to, txt in mismatched_all[:20]:
            print(f"   ms {mid}: from={frm!r} to={to!r} text={txt!r}")
    if other_all:
        print(f"\nPart 3 — loci NOT classifiable (left untouched, please review): {len(other_all)}")
        for mid, frm, to in other_all:
            print(f"   ms {mid}: from={frm!r} to={to!r}")
    else:
        print("\nPart 3 — no unclassifiable loci; nothing left needing a decision.")
    if not apply:
        print("\nRe-run with --apply to write these changes.")


if __name__ == "__main__":
    main()
