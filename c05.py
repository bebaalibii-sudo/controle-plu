# CELL 5
import re, json

COMMUNE = "Éragny-sur-Oise"
DOCUMENT = "REGLEMENT ZONE UB.pdf"
ZONE_PREFIX = "UB"
MAX_CHARS_WARNING = 4500                # chunks longer than this are FLAGGED, never cut blindly

# ---- 0. Pages come from Cell 6 (cleaned) ----
assert "clean_text" in pages[0], "Run CELL 6 first (it creates the cleaned text)."

# ---- 1. Build a flat list of lines, each remembering its page ----
all_lines = []
for p in pages:
    for ln in p["clean_text"].splitlines():
        all_lines.append((ln, p["pdf_page"], p["printed_page"]))

def norm(line):
    return re.sub(r"\s+", " ", re.sub(r"_+", " ", line)).strip()

UP = "A-ZÉÈÀÂÊÎÔÛÇ"
SECTION_RE = re.compile(rf"^(\d)(?:[.,](\d))?[.,]?\s+([{UP}][{UP}0-9'’ ,\-–()/.]{{7,}})$")
HEADING_RE = re.compile(rf"^ARTICLE\s+{ZONE_PREFIX}\s*[.,]?\s*(\d{{1,2}})\s*[-–—=:]\s*(.*)$")
SUBITEM_RE = re.compile(r"^(\d{1,2}(?:[.,]\d{1,2}){1,3})[.,]?(?:\s+\S|\s*$)")

def is_mostly_upper(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8

# ---- 2. Walk through the document once, grouping lines by article ----
blocks, cur, pending_section, skip_next = [], None, None, False
front = {"number": None, "title": "Introduction de la zone", "section": None, "lines": []}
cur = front; blocks.append(front)
for i, (raw, pdf_p, prt_p) in enumerate(all_lines):
    line = norm(raw)
    if skip_next:
        skip_next = False
        if line and is_mostly_upper(line) and not line.startswith("ARTICLE"):
            cur["title"] += " " + line
            continue
    m = HEADING_RE.match(line)
    if m:
        cur = {"number": int(m.group(1)), "title": m.group(2).strip(), "section": pending_section, "lines": []}
        blocks.append(cur); skip_next = True
        continue
    if SECTION_RE.match(line):
        pending_section = line               # section headings are metadata, not rule text
        continue
    cur["lines"].append((raw.rstrip(), pdf_p, prt_p))

# ---- 3. Split each article at its numbered sub-items (level N.M keeps all deeper levels inside) ----
EXC_CUES = r"(?i)\b(sauf|à l'exception|a l'exception|ne s'appliquent pas|ne s'applique pas|sous réserve|toutefois|excepté|dérogation|dérogations|lorsque|dans le cas)\b"
INT_REF = re.compile(rf"(?i)\barticles?\s+(?:{ZONE_PREFIX}\s*[.,]?\s*)?(\d{{1,2}})(?:[.,]\d{{1,2}})*(?!\d)")
EXT_CODE_REF = re.compile(r"(?i)\barticles?\s+([LRD])\s*[.]?\s*(\d{2,3}[-–]\d+(?:[-–]\d+)*)")
EXT_DOC_KW = re.compile(r"(?i)(document graphique|plan de zonage|plan de masse|annexes?\b|servitudes?|PPRI|OAP|orientations? d'aménagement|plan de pr[ée]vention|cahier des charges)")
valid_articles = {b["number"] for b in blocks if b["number"]}

def looks_like_table(text):
    """Heuristic: OCR column marks '|' on several lines, or many very short lines = a table."""
    ls = [l.strip() for l in text.splitlines() if l.strip()]
    if sum("|" in l for l in ls) >= 3: return True
    if len(ls) < 15: return False
    lengths = sorted(len(l) for l in ls)
    return lengths[len(lengths) // 2] < 30 and sum(lengths) / len(lengths) < 35

def normalise_sector(code):
    """OCR often reads the digit 1 as the letter i in sector codes (UBci -> UBc1). Metadata only: the stored text is never changed."""
    m = re.fullmatch(rf"({ZONE_PREFIX}[a-z])i", code)
    if m: return m.group(1) + "1"
    m = re.fullmatch(rf"({ZONE_PREFIX}[a-z]\d)i", code)
    if m: return m.group(1)
    return code

def make_chunk(block, sub, lines):
    text = "\n".join(l for l, _, _ in lines).strip()
    pdf_pages = sorted({p for _, p, _ in lines}); prt_pages = sorted({q for _, _, q in lines})
    internal = []
    for m in INT_REF.finditer(text):
        n = int(m.group(1))
        internal.append({"text": re.sub(r"\s+", " ", m.group(0)), "target_article": n, "resolved": n in valid_articles})
    external = [re.sub(r"\s+", " ", m.group(0)) for m in EXT_CODE_REF.finditer(text)]
    docs = sorted({m.group(0).lower() for m in EXT_DOC_KW.finditer(text)})
    raw_sectors = set(re.findall(rf"\b{ZONE_PREFIX}[a-z][a-z0-9]*\b", text))      # UBa, UBb, UBb1, UBc2... read from the text
    sectors = sorted({normalise_sector(c) for c in raw_sectors})
    sector_ocr_fixes = sorted(f"{c}->{normalise_sector(c)}" for c in raw_sectors if normalise_sector(c) != c)
    art = f"{ZONE_PREFIX}.{block['number']}" if block["number"] else f"{ZONE_PREFIX}.intro"
    return {
        "chunk_id": f"{art}#{sub}" if sub else art,
        "document": DOCUMENT, "commune": COMMUNE, "zone_document": ZONE_PREFIX,
        "article_number": block["number"], "article_title": block["title"], "section": block["section"],
        "sub_item": sub, "pdf_pages": pdf_pages, "printed_pages": prt_pages,
        "sectors_mentioned": sectors, "sector_ocr_fixes": sector_ocr_fixes, "text": text, "n_chars": len(text),
        "cross_refs_internal": internal,
        "cross_refs_external_code": external,
        "mentions_other_documents": docs,
        "unresolved_cross_references": [r["text"] for r in internal if not r["resolved"]] + external,
        "possible_table": looks_like_table(text),
        "exception_cues": sorted({c.lower() for c in re.findall(EXC_CUES, text)}),
        "text_for_embedding": f"ARTICLE {art} - {block['title']}\n{text}",
    }

chunks, gaps = [], []
for b in blocks:
    n = b["number"]; groups, cur_sub, cur_lines = [], "preamble", []
    for ln, pdf_p, prt_p in b["lines"]:
        m = SUBITEM_RE.match(norm(ln))
        if n and m:
            num = m.group(1).replace(",", ".")
            parts = num.split(".")
            if int(parts[0]) == n:                       # numbering must belong to this article
                if cur_lines: groups.append((cur_sub, cur_lines))
                cur_sub, cur_lines = ".".join(parts[:2]), []   # keep levels N.M.x inside N.M
                if groups and groups[-1][0] == cur_sub:        # same N.M continues (e.g. 6.2.1 after 6.2)
                    cur_lines = groups.pop()[1]
        cur_lines.append((ln, pdf_p, prt_p))
    if cur_lines: groups.append((cur_sub, cur_lines))
    pre = next((g for g in groups if g[0] == "preamble"), None)
    pre_text = "\n".join(l for l, _, _ in pre[1]).strip() if pre else ""
    for sub, lines in groups:
        if not "".join(l for l, _, _ in lines).strip():
            continue
        ch = make_chunk(b, None if sub == "preamble" and len(groups) == 1 else sub, lines)
        if sub != "preamble" and pre_text:
            ch["preamble_chunk_id"] = f"{ch['chunk_id'].split('#')[0]}#preamble"
            if len(pre_text) <= 600:      # short lead-in sentence: keep it with every rule it introduces
                ch["text_for_embedding"] = ch["text_for_embedding"].replace("\n", "\n[Article lead-in: " + pre_text.replace("\n", " ") + "]\n", 1)
        chunks.append(ch)
    subs = sorted({int(s.split(".")[1]) for s, _ in groups if s != "preamble"})
    if n and subs and subs != list(range(1, max(subs) + 1)):
        gaps.append((n, [k for k in range(1, max(subs) + 1) if k not in subs]))

# ---- 4. Report ----
print("==== CHUNKS ====")
print(f"{'chunk_id':<14}{'pdf p.':<10}{'chars':>6}  sectors / refs / cues")
for c in chunks:
    pp = f"{c['pdf_pages'][0]}-{c['pdf_pages'][-1]}" if len(c["pdf_pages"]) > 1 else str(c["pdf_pages"][0])
    flags = []
    if c["sectors_mentioned"]: flags.append("sectors:" + ",".join(c["sectors_mentioned"]))
    if re.search(r"(?i)non r[eèé]g[l]?ement", c["text"]): flags.append("NON-REGLEMENTE")
    if c["cross_refs_internal"]: flags.append("int-refs:" + str(len(c["cross_refs_internal"])))
    if c["cross_refs_external_code"]: flags.append("code-refs:" + str(len(c["cross_refs_external_code"])))
    if c["mentions_other_documents"]: flags.append("docs:" + "/".join(c["mentions_other_documents"])[:30])
    if c["exception_cues"]: flags.append("cues:" + ",".join(c["exception_cues"])[:40])
    if c["possible_table"]: flags.append("TABLE?-verify on PDF")
    if c["n_chars"] > MAX_CHARS_WARNING: flags.append("LONG")
    print(f"{c['chunk_id']:<14}{pp:<10}{c['n_chars']:>6}  " + " | ".join(flags))

print("\n==== CHECKS ====")
print("Total chunks:", len(chunks))
ids = [c["chunk_id"] for c in chunks]
print("Duplicate chunk ids (must be none):", sorted({i for i in ids if ids.count(i) > 1}) or "none")
print("Longest chunk (chars):", max(c["n_chars"] for c in chunks))
print("Chunks flagged LONG:", [c["chunk_id"] for c in chunks if c["n_chars"] > MAX_CHARS_WARNING] or "none")
print("Chunks that look like tables (OCR loses rows/columns):", [c["chunk_id"] for c in chunks if c["possible_table"]] or "none")
print("Chunks stating 'Non réglementé':", [c["chunk_id"] for c in chunks if re.search(r"(?i)non r[eèé]g[l]?ement", c["text"]) and c["n_chars"] < 200] or "none")
print("Sector codes normalised (OCR 1/i confusion) - VERIFY on the PDF:", sorted({f for c in chunks for f in c["sector_ocr_fixes"]}) or "none")
print("All sector codes found:", sorted({x for c in chunks for x in c["sectors_mentioned"]}))
print("Possible missed sub-items (gaps in numbering):", gaps or "none")
print("Unresolved cross-references:", {c["chunk_id"]: c["unresolved_cross_references"] for c in chunks if c["unresolved_cross_references"]} or "none")

with open("chunks.json", "w", encoding="utf-8") as f:
    json.dump(chunks, f, ensure_ascii=False, indent=1)
print("\nSaved chunks.json")

def show_chunk(chunk_id, n=1500):
    c = next(x for x in chunks if x["chunk_id"] == chunk_id)
    print(f"--- {c['chunk_id']} | {c['article_title']} | section: {c['section']}")
    print(f"PDF pages {c['pdf_pages']} | printed pages {c['printed_pages']} | sectors: {c['sectors_mentioned']}")
    print(c["text"][:n])