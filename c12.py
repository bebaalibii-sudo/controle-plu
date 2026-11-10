# CELL 12 | Milestone 5 | Guardrails: check any extracted rule against the PLU text (extract, number, unit, sector, pages)
import re, unicodedata
from difflib import SequenceMatcher

assert "chunks" in globals(), "Run the chunking cell (Cell 7) first, or restore with Cell 15."
assert "Rule" in globals(), "Run CELL 16 first (schema v1.1)."
chunk_by_id = {c["chunk_id"]: c for c in chunks}
GUARD_SECTORS = {s for c in chunks for s in c["sectors_mentioned"]} | {ZONE_PREFIX}

# ---------- Text helpers ----------
def squash(s):
    """Lower case, no accents, straight quotes, no spaces: so line breaks and OCR spacing do not matter."""
    s = s.replace("’", "'").replace("‘", "'").replace("´", "'").replace("«", '"').replace("»", '"')
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", "", s.lower())

def extract_match(extract, chunk_text):
    """exact / approx (>= 90% of the extract is a contiguous piece of the chunk) / missing."""
    e, t = squash(extract), squash(chunk_text)
    if e in t:
        return "exact", 1.0
    sm = SequenceMatcher(None, e, t, autojunk=False)
    cover = sm.find_longest_match(0, len(e), 0, len(t)).size / max(len(e), 1)
    return ("approx" if cover >= 0.9 else "missing"), round(cover, 2)

def numbers_in(text):
    return {float(m.replace(",", ".")) for m in re.findall(r"(?<![\w.,])(\d+(?:[.,]\d+)?)", text)}

UNIT_PATTERNS = {
    Unit.PERCENT: r"%|pour\s*cent",
    Unit.METRE: r"(?<![A-Za-z])m(?![A-Za-z0-9²])|m[eè]tres?",   # also matches "7m" written without a space
    Unit.M2: r"m2|m²|mètres?\s*carrés?",
    Unit.LEVELS: r"R\s*\+\s*\d|niveaux?|étages?|combles",
    Unit.SPACES: r"places?",
    Unit.SPACES_PER_DWELLING: r"places?",
    Unit.SPACES_PER_100M2: r"places?",
}

def mentions_sector(extract, sector):
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(sector)}(?![A-Za-z0-9])", extract))

# ---------- The guardrails ----------
def verify_rule(rule):
    """Returns a CHECKED COPY of the rule: provenance filled from the chunks, flags propagated, issues listed.
    ERROR = the rule cannot be trusted; WARNING = the architect must look."""
    r = rule.model_copy(deep=True)
    issues = []
    for i, src in enumerate(r.sources):
        ch = chunk_by_id.get(src.chunk_id)
        if ch is None:
            issues.append(f"ERROR source {i+1}: chunk '{src.chunk_id}' does not exist")
            src.verified = False
            continue
        # 1. provenance comes from the chunk, never from the model
        corrections = []
        for field, truth in [("article", f"UB.{ch['article_number']}" if ch["article_number"] else None),
                             ("sub_item", ch["sub_item"]), ("document", ch["document"]),
                             ("pdf_pages", ch["pdf_pages"]), ("printed_pages", ch["printed_pages"])]:
            if getattr(src, field) not in (None, [], truth) and getattr(src, field) != truth:
                corrections.append(field)
            setattr(src, field, truth if truth is not None else getattr(src, field))
        if corrections:
            issues.append(f"WARNING source {i+1}: {', '.join(corrections)} corrected from the chunk")
        # 2. the extract must really be in the chunk
        status, cover = extract_match(src.extract, ch["text"])
        ok = status != "missing"
        if status == "missing":
            issues.append(f"ERROR source {i+1}: extract not found in {src.chunk_id} (only {int(cover*100)}% matches)")
        elif status == "approx":
            issues.append(f"WARNING source {i+1}: extract only approximately found in {src.chunk_id} ({int(cover*100)}%)")
        # 3. flags that travel with the chunk
        if ch["possible_table"]:
            if "table_read_by_OCR_verify_on_pdf" not in r.ambiguity_flags:
                r.ambiguity_flags.append("table_read_by_OCR_verify_on_pdf")
            issues.append(f"WARNING source {i+1}: {src.chunk_id} is a table read by OCR (rows and columns can be mixed): verify on the PDF")
        for ref in ch["unresolved_cross_references"]:
            if ref not in r.unresolved_cross_references:
                r.unresolved_cross_references.append(ref)
        src.verified = ok
    # 4. the number and the unit must be in the extract
    if r.regulation_status == RegulationStatus.REGULATED and r.sources:
        joined = " ".join(src.extract for src in r.sources)
        for label, val in [("value", r.value), ("value_max", r.value_max)]:
            if val is not None and float(val) not in numbers_in(joined):
                issues.append(f"ERROR {label} {val:g} does not appear in the extract(s)")
        if r.unit and r.unit in UNIT_PATTERNS and not re.search(UNIT_PATTERNS[r.unit], joined, re.I):
            issues.append(f"WARNING unit '{r.unit.value}' not recognised in the extract(s)")
    # 5. 'non réglementé' must be written in the extract
    if r.regulation_status == RegulationStatus.EXPLICITLY_NOT_REGULATED:
        if not any(re.search(r"(?i)non\s*r[eèé]g[l]?ement|pas\s+de\s+r[eèé]gle|n'est\s+pas\s+fix", s.extract) for s in r.sources):
            issues.append("ERROR status 'non réglementé' but the extract does not say so")
    # 6. a declared sector must be named in the extract
    for sec in r.applies_to_sectors:
        if sec not in GUARD_SECTORS:
            issues.append(f"ERROR sector '{sec}' is not a sector of this document")
        elif sec != ZONE_PREFIX and not any(mentions_sector(s.extract, sec) for s in r.sources):
            issues.append(f"WARNING sector '{sec}' is not named in the extract(s)")
    r.guardrail_issues = issues
    return r

def has_errors(rule):
    return any(i.startswith("ERROR") for i in rule.guardrail_issues)

# ---------- Tests built from YOUR chunks (nothing typed by hand: the extracts are cut from the real text) ----------
print("==== GUARDRAIL TESTS ====")
c91 = chunk_by_id["UB.9#9.1"]
m = re.search(r"secteur UB,[^\n]*\n[^\n]*?(\d+)\s*%\s*maximum", c91["text"])
assert m, "Could not find the UB line in UB.9#9.1: send me the text of that chunk."
good_extract, good_value = m.group(0), float(m.group(1))
print(f"(Test material, cut from UB.9#9.1: value {good_value:g}% | extract: {good_extract!r})")

def make(**kw):
    base = dict(parameter=Parameter.EMPRISE_SOL, regulation_status=RegulationStatus.REGULATED, kind=RuleKind.MAXIMUM,
                value=good_value, unit=Unit.PERCENT, applies_to_sectors=["UB"],
                sources=[SourceRef(chunk_id="UB.9#9.1", extract=good_extract)])
    base.update(kw); return Rule(**base)

def report(name, rule, expect):
    v = verify_rule(rule)
    got = "ERROR" if has_errors(v) else ("WARNING" if v.guardrail_issues else "OK")
    print(f"{'PASS' if got == expect else 'FAIL'} | {name:<52} -> {got:<7} | auto_comparable={v.auto_comparable()}")
    for i in v.guardrail_issues: print("        ", i)
    return v

v = report("T1 correct rule", make(), "OK")
report("T2 wrong number (value changed)", make(value=good_value + 10), "ERROR")
report("T3 invented extract", make(sources=[SourceRef(chunk_id="UB.9#9.1", extract="Le coefficient est de 55% pour toutes les constructions.")]), "ERROR")
report("T4 chunk that does not exist", make(sources=[SourceRef(chunk_id="UB.99#1", extract=good_extract)]), "ERROR")
report("T5 wrong sector label (UBa for the UB line)", make(applies_to_sectors=["UBa"]), "WARNING")
report("T6 wrong page given by the 'model'", make(sources=[SourceRef(chunk_id="UB.9#9.1", extract=good_extract, pdf_pages=[3], printed_pages=[43], article="UB.2")]), "WARNING")
report("T7 wrong unit (m instead of %)", make(unit=Unit.METRE), "WARNING")

nr_chunk = next(c for c in chunks if re.search(r"(?i)non r[eèé]g[l]?ement", c["text"]) and c["n_chars"] < 200)
report(f"T8 explicit 'non réglementé' ({nr_chunk['chunk_id']})",
       Rule(parameter=Parameter.NB_NIVEAUX, regulation_status=RegulationStatus.EXPLICITLY_NOT_REGULATED,
            sources=[SourceRef(chunk_id=nr_chunk["chunk_id"], extract=nr_chunk["text"].strip())]), "OK")
report("T9 claims 'non réglementé' on a chunk that has a rule",
       Rule(parameter=Parameter.EMPRISE_SOL, regulation_status=RegulationStatus.EXPLICITLY_NOT_REGULATED,
            sources=[SourceRef(chunk_id="UB.9#9.1", extract=good_extract)]), "ERROR")

tbl = next((c for c in chunks if c["possible_table"]), None)
if tbl:
    report(f"T10 rule taken from the parking table ({tbl['chunk_id']})",
           Rule(parameter=Parameter.STATIONNEMENT, regulation_status=RegulationStatus.REGULATED, kind=RuleKind.TEXTUAL,
                summary="test", sources=[SourceRef(chunk_id=tbl["chunk_id"], extract=" ".join(tbl["text"].split()[:12]))]), "WARNING")