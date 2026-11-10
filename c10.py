# CELL 10
import re, json
import numpy as np

# ---- 1. The project profile comes from Cell 12 ----
assert "PROJECT" in globals(), "Run CELL 12 first (it asks for the sector and the type of building)."
SECTOR = PROJECT["sector"]
BUILDING = PROJECT["building_types"]
TOP_K = 5
EXPAND_RATIO = 0.85    # an article is expanded if one of its chunks is in the top 3 with a score >= 85% of the best score
FORCE_BUILDING_RULES = []      # advanced, optional: force rules, e.g. ["emprise_au_sol"]. Normally leave empty: the program detects them.
BUILDING_DEPENDENT = set()      # filled below: the rules that take the building type into account
EXPANDED = {}                  # which articles were expanded for each parameter

# ---- 2. One search query per regulatory parameter (hypotheses: the evaluation will test them) ----
PARAM_QUERIES = {
    "implantation_voies": "implantation des constructions par rapport aux voies et emprises publiques : recul, retrait, alignement, distance minimale",
    "emprise_au_sol": "emprise au sol des constructions : coefficient d'emprise au sol (CES), emprise maximale",
    "hauteur_maximale": "hauteur maximum des constructions : hauteur au faîtage, à l'égout, à l'acrotère, en mètres",
    "nombre_de_niveaux": "nombre de niveaux des constructions : R+1, R+2, combles, attique, étages",
    "limites_separatives": "implantation des constructions par rapport aux limites séparatives : retrait, marges d'isolement, distance, baies",
    "stationnement": "stationnement des véhicules : nombre de places par logement, surface de plancher, deux roues, vélos",
    "espaces_verts_pleine_terre": "espaces libres, espaces verts, plantations, pleine terre, surface non imperméabilisée",
}

# ---- 3. Sector logic: never exclude a chunk, only LABEL it (a missed rule is worse than an extra chunk) ----
def sector_family(sector):
    """'UBc3' -> {'UBc3', 'UBc', 'UB'} : the sector and its parents."""
    fam = {sector, ZONE_PREFIX}
    m = re.fullmatch(rf"({ZONE_PREFIX}[a-z])(\d+)", sector)
    if m: fam.add(m.group(1))
    return fam

ITEM_START = re.compile(r"(?m)^(?=\s*\d{1,2}[.,]\d{1,2}(?:[.,]\d{1,2})*[.,]?(?:\s|$))")

def sector_relevance(chunk, sector):
    """Label the chunk by looking at each numbered item inside it (6.2.1, 6.2.5...), not at the chunk as a whole."""
    fam = sector_family(sector)
    yours = other = generic = 0
    for item in ITEM_START.split(chunk["text"]):
        if not item.strip():
            continue
        mentioned = {normalise_sector(c) for c in re.findall(rf"\b{ZONE_PREFIX}[a-z][a-z0-9]*\b", item)}
        base = bool(re.search(rf"(?i)\b(?:zone|secteur)\s+{ZONE_PREFIX}\b(?![a-z0-9])", item))
        if (mentioned & fam) or (base and ZONE_PREFIX in fam):
            yours += 1
        elif mentioned:
            other += 1
        else:
            generic += 1
    if yours:
        return "mentions YOUR sector" + (" + other sectors' variants" if other else "")
    if other and generic:
        return "MIXED: general text + other sectors' provisions"
    if other:
        return "OTHER sectors only - may not apply"
    return "general (no sector mentioned)"

def types_in(text):
    return {code for code, label, rx in BUILDING_TYPES.values() if re.search(rx, text, re.I)}

EXEMPTION_START = re.compile(r"(?i)ne s'appliquent? pas|n'est pas fix|aucune .{0,40}n'est impos|non r[eèé]g[l]?ement")

def is_exemption_chunk(chunk):
    """Blanket-exception blocks ('les prescriptions du present article ne s'appliquent pas aux ...') list exempted
    building types, but they are not rules that VARY by building type."""
    first = next((l for l in chunk["text"].splitlines() if l.strip()), "")
    return bool(EXEMPTION_START.search(first))

def item_type_hits(chunk):
    """For each numbered item: the building types named in its HEADING (2 first lines); a sub-item inherits its parent's."""
    parent_hit, hits = {}, []
    for item in ITEM_START.split(chunk["text"]):
        lines = [l for l in item.splitlines() if l.strip()]
        if not lines:
            continue
        heading = " ".join(lines[:2])
        own = types_in(heading)
        if len(own) >= 3 or re.search(r"(?i)plusieurs\s+(affectations|destinations|usages)|mixte", heading):
            own = set()          # a rule for mixed uses applies to every project
        m = re.match(r"^\s*([\d.,]+)", lines[0])
        parts = [p for p in re.split(r"[.,]", m.group(1)) if p] if m else []
        key = ".".join(parts[:2])
        if len(parts) == 2:
            parent_hit[key] = own
        hits.append(own or (parent_hit.get(key, set()) if len(parts) > 2 else set()))
    return hits

def has_type_headings(chunk):
    if chunk["possible_table"]:
        return bool(types_in(chunk["text"]))
    return any(item_type_hits(chunk))

def building_relevance(chunk, types):
    """Which building types does this chunk speak to?
    - only the HEADING of each numbered item is read; a sub-item inherits its parent's type;
    - general items next to type-specific items give a MIXED label, never 'OTHER types only'."""
    if chunk["possible_table"]:
        return "building: TABLE by destination - find YOUR row on the PDF" if types_in(chunk["text"]) else ""
    yours = other = generic = 0
    for hit in item_type_hits(chunk):
        if hit & set(types): yours += 1
        elif hit: other += 1
        else: generic += 1
    if yours: return "building: mentions YOUR type" + (" + others" if other else "")
    if other and generic: return "building: MIXED general text + other types' provisions"
    if other: return "building: OTHER types only"
    return ""

chunk_by_id = {c["chunk_id"]: c for c in chunks}
first_chunk_of_article = {}
for c in chunks:
    first_chunk_of_article.setdefault(c["article_number"], c["chunk_id"])

# ---- 4. Retrieval: top-K by meaning + the rest of the article (conditions and blanket exceptions live there) ----
chunks_by_article = {}
for c in chunks:
    chunks_by_article.setdefault(c["article_number"], []).append(c["chunk_id"])

def describe(c, rank, score, sector, kind, param):
    return {
        "rank": rank, "kind": kind, "chunk_id": c["chunk_id"], "score": score,
        "pdf_pages": c["pdf_pages"], "printed_pages": c["printed_pages"], "n_chars": c["n_chars"],
        "sector_relevance": sector_relevance(c, sector),
        "building_relevance": building_relevance(c, BUILDING) if param in BUILDING_DEPENDENT else "",
        "possible_table": c["possible_table"],
        "set_aside": param in BUILDING_DEPENDENT and building_relevance(c, BUILDING).startswith("building: OTHER types only"),
        "non_reglemente": bool(re.search(r"(?i)non r[eèé]g[l]?ement", c["text"])) and c["n_chars"] < 200,
        "exception_cues": c["exception_cues"],
        "see_also": sorted({first_chunk_of_article[r["target_article"]] for r in c["cross_refs_internal"]
                            if r["resolved"] and r["target_article"] != c["article_number"]}),
        "unresolved_cross_references": c["unresolved_cross_references"],
    }

def retrieve(param, sector, k=TOP_K):
    query = PARAM_QUERIES[param]
    if param in BUILDING_DEPENDENT:
        query += " ; pour : " + ", ".join(PROJECT["building_labels"])
    q = model_emb.encode([query], normalize_embeddings=True)[0]
    sims = E @ q
    order = list(np.argsort(-sims))
    best = float(sims[order[0]])
    results = [describe(chunks[i], n + 1, round(float(sims[i]), 3), sector, "core", param) for n, i in enumerate(order[:k])]
    have = {r["chunk_id"] for r in results}
    # expand the articles of the strongest hits: add their other sub-items, in article order
    articles_to_expand = []
    for i in order[:3]:
        a = chunks[i]["article_number"]
        if float(sims[i]) >= EXPAND_RATIO * best and a is not None and a not in articles_to_expand:
            articles_to_expand.append(a)
    EXPANDED[param] = articles_to_expand
    for a in articles_to_expand:
        for cid in chunks_by_article[a]:
            if cid not in have:
                results.append(describe(chunk_by_id[cid], "art", None, sector, "same_article", param))
                have.add(cid)
    return results

# ---- 5. Run for the 7 parameters and display ----
def pages_text(r):
    p, q = r["pdf_pages"], r["printed_pages"]
    return f"PDF p.{p[0]}" + (f"-{p[-1]}" if len(p) > 1 else "") + f" (printed {q[0]}" + (f"-{q[-1]}" if len(q) > 1 else "") + ")"

def flags_text(r):
    flags = []
    if r["possible_table"]: flags.append("TABLE?-verify on PDF")
    if r["non_reglemente"]: flags.append("NON-REGLEMENTE")
    if r["exception_cues"]: flags.append("exception cues: " + ",".join(r["exception_cues"])[:35])
    if r["see_also"]: flags.append("see also " + ",".join(r["see_also"]))
    if r["building_relevance"]: flags.insert(0, r["building_relevance"])
    return (" | " + " | ".join(flags)) if flags else ""

# ---- 5b. Which rules depend on the building type in THIS PLU? (automatic: nobody has to say) ----
detected = {}
for param in PARAM_QUERIES:
    retrieve(param, SECTOR)                       # neutral search (no building type yet) to find the article(s) concerned
    arts = set(EXPANDED.get(param, []))
    hit_chunks = [c["chunk_id"] for c in chunks
                  if c["article_number"] in arts and not is_exemption_chunk(c) and has_type_headings(c)]
    if hit_chunks:
        detected[param] = hit_chunks
        BUILDING_DEPENDENT.add(param)
BUILDING_DEPENDENT.update(FORCE_BUILDING_RULES)
print("==== AUTOMATIC DETECTION: rules whose article has sub-items by building type ====")
for param in PARAM_QUERIES:
    forced = " (forced)" if param in FORCE_BUILDING_RULES else ""
    print(f"  {param:<28} -> " + (("YES (" + ", ".join(detected.get(param, ["forced"])[:4]) + (" ..." if len(detected.get(param, [])) > 4 else "") + ")" + forced) if param in BUILDING_DEPENDENT else "no"))

all_results = {}
for param in PARAM_QUERIES:
    res = retrieve(param, SECTOR)
    all_results[param] = res
    kept = [r for r in res if not r["set_aside"]]
    aside = [r for r in res if r["set_aside"]]
    core = [r for r in kept if r["kind"] == "core"]
    extra = [r for r in kept if r["kind"] == "same_article"]
    btxt = (" | building: " + ", ".join(PROJECT["building_labels"])) if param in BUILDING_DEPENDENT else ""
    print(f"\n=== {param}  (sector: {SECTOR}{btxt}) ===")
    for r in core:
        print(f"{str(r['rank']):>3} | {r['chunk_id']:<14} | {r['score']:.3f} | {pages_text(r):<26} | {r['sector_relevance']}{flags_text(r)}")
    if extra:
        print("    + added from the same article (conditions / exceptions can be here):")
        for r in extra:
            print(f"    + {r['chunk_id']:<14} | {pages_text(r):<26} | {r['sector_relevance']}{flags_text(r)}")
    if aside:
        print("    - SET ASIDE (about other building types only; not deleted, saved in the results file):")
        for r in aside:
            rk = f"rank {r['rank']}" if r["kind"] == "core" else "same article"
            print(f"    - {r['chunk_id']:<14} | {pages_text(r):<26} | {rk}")
    print(f"    context size for this parameter (kept only): {sum(r['n_chars'] for r in kept)} characters")

with open("retrieval_results.json", "w", encoding="utf-8") as f:
    json.dump({"project": PROJECT, "embedding_model": EMB_MODEL, "top_k": TOP_K, "expand_ratio": EXPAND_RATIO, "results": all_results}, f, ensure_ascii=False, indent=1)
print("\nSaved retrieval_results.json")