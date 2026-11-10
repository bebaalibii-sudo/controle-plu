# CELL 13 | Milestone 5 | Build the extraction prompts (v6: housing table row + machine-readable applicability tests + more project facts)
import re, json

assert "all_results" in globals(), "Run CELL 13 first (retrieval)."
assert "FactTest" in globals(), "Run CELL 16 first (schema v1.2)."

PARAMS_TO_EXTRACT = ["implantation_voies", "emprise_au_sol", "hauteur_maximale", "nombre_de_niveaux", "limites_separatives","stationnement"]    # <- the parameters to do now (one or several)
PROMPT_CORE_RATIO = 0.85                 # top hits below 85% of the best score are left out of the prompt (noise)
DOWNLOAD_PROMPT_FILES = False            # True = also download each prompt as a .txt file to your computer

PARAM_DEFINITIONS = {
    "implantation_voies": "Building placement relative to roads and public spaces (recul, retrait, alignement, distance to the road).",
    "emprise_au_sol": "Building footprint / maximum ground coverage (emprise au sol, CES).",
    "hauteur_maximale": "Maximum building height (hauteur au faîtage, à l'égout, à l'acrotère), in metres.",
    "nombre_de_niveaux": "Number of permitted levels (R+1, R+2, combles, attique), where regulated.",
    "limites_separatives": "Placement relative to neighbouring plot boundaries (marges d'isolement, retrait, baies).",
    "stationnement": "Parking requirements (number of places, by dwelling or floor area, visitors, two-wheelers). Give ONE rule per distinct case (dwelling-size band, distance to a station, aided housing, visitors, motorised / non-motorised two-wheelers) and put the case in 'conditions'.",
    "espaces_verts_pleine_terre": "Green space / pleine terre / planted or permeable ground (espaces libres, plantations).",
}
for p in PARAMS_TO_EXTRACT:
    assert p in PARAM_DEFINITIONS, f"Unknown parameter name: {p}. Choose from {list(PARAM_DEFINITIONS)}"

# ---------------------------------------------------------------------------------------------
# PROJECT FACTS: the only facts a rule's conditions can be tested on (the form of the prototype).
# The model is given the NAMES and meanings, never the values of your project: CODE decides which rule applies (Cell 21).
# To add a question later (milestone 6), add a line here: the prompt, Cell 19 and Cell 21 all read this list.
# ---------------------------------------------------------------------------------------------
FACTS = {
    "within_500m_station":  {"type": "bool",   "meaning": "the plot is within 500 m of a railway station (true/false)",
                             "question": "Is the parcel within 500 m of a railway station (gare)?"},
    "avg_dwelling_sdp_m2":  {"type": "number", "meaning": "average floor area (SDP, surface de plancher) per dwelling of the project, in m2",
                             "question": "Average floor area (SDP) per dwelling, in m2"},
    "n_dwellings":          {"type": "number", "meaning": "number of dwellings (logements) in the project",
                             "question": "Number of dwellings (logements) in the project"},
    "total_sdp_m2":         {"type": "number", "meaning": "total floor area (SDP) of the whole operation, in m2",
                             "question": "Total floor area (SDP) of the whole operation, in m2"},
    "is_group_or_lotissement": {"type": "bool", "meaning": "the project is a group of constructions (groupe de constructions) or a lotissement (true/false)",
                             "question": "Is the project a group of constructions (groupe de constructions) or a lotissement?"},
    "multiple_uses":        {"type": "bool",   "meaning": "the construction has several uses, e.g. housing plus shops or activities (true/false)",
                             "question": "Does the construction have several uses (housing plus shops, offices or activities)?"},
    "n_f1_f2_dwellings":    {"type": "number", "meaning": "number of dwellings of type F1 or F2 in the project",
                             "question": "How many of the logements are of type F1 or F2?"},
    "n_larger_dwellings":   {"type": "number", "meaning": "number of dwellings larger than F2 (F3 and above) in the project",
                             "question": "How many of the logements are larger than F2 (F3 or more)?"},
    "required_places":      {"type": "number", "computed": True,
                             "meaning": "total number of parking places required for the project by the calculation (computed by the program, never asked)",
                             "question": "(computed by the program)"},
        "plot_area_m2":         {"type": "number", "meaning": "total area of the plot (parcelle), in m2",
                             "question": "Total area of the plot (parcelle), in m2"},
    "building_footprint_m2": {"type": "number", "meaning": "ground footprint of the buildings (emprise au sol), in m2",
                             "question": "Ground footprint of the buildings (emprise au sol), in m2"},
    "pleine_terre_m2":      {"type": "number", "meaning": "area of the plot kept as open ground (pleine terre), in m2",
                             "question": "Area kept as open ground (pleine terre), in m2"},
    "in_ecological_corridor": {"type": "bool", "meaning": "the plot is inside the protection perimeter of the Boulevard du Général de Gaulle ecological corridor (true/false)",
                             "question": "Is the plot inside the ecological corridor perimeter of the Boulevard du Général de Gaulle?"},
}
FACT_PARAMS = {"stationnement"}          # parameters whose rules depend on project facts (others later)

# ---------------------------------------------------------------------------------------------
# HUMAN TRANSCRIPTION of the housing row of the parking table (printed page 56), confirmed by the architect.
# The table is a drawn grid and the OCR mixes its rows and columns. The row is registered as a chunk of its own, so every
# guardrail works on it like on any other chunk, and it is always marked as a human transcription.
# ---------------------------------------------------------------------------------------------
MANUAL_ID = "UB.12#table_habitation_MANUAL"
MANUAL_TEXT = """TABLEAU DU STATIONNEMENT - ligne : Constructions destinées à l'habitation

Stationnement des véhicules motorisés (hors deux roues) :
Minimum 1 place pour un logement inférieur ou égal à 60m² de SDP, minimum 2 places pour un logement inférieur ou égal à 150 m² de SDP. Au-delà de 150 m² de SDP 1 place en plus pour chaque tranche entamée de 40 m² de SDP supplémentaire dans la limite de 3 places. 1 place par logement dans un périmètre de 500m autour d'une gare

Logements locatifs financés avec un prêt aidé par l'Etat : 1 place par logement. 0.5 place dans un périmètre de 500m autour d'une gare

Stationnement visiteur : Pour les immeubles comportant plus de 5 logements, les groupes de constructions et les lotissements, 1 place de stationnement doit être réalisé pour chaque tranche de 5 logements pour permettre le stationnement des visiteurs.

Stationnement des deux roues motorisées et non motorisées :
Pour les deux roues motorisées, les constructions de plus de 400 m² de SDP et plus de 6 logements : minimum 1% de la SDP ou 10 m² pour le remisage.

Pour les deux roues non motorisées, un espace doit leur être réservé : un minimum de 0,75m² par logement pour les logements de type F1 ou F2. Au-delà, un minimum de 1,5 m² par logement, avec un minimum de 3m². Lorsque la surface de plancher de l'opération est supérieure à 400m², cet espace doit avoir une superficie minimale de 10 m² et de 5 m² lorsque la SDP de l'opération est inférieure ou égale à 400m²"""
MANUAL_WARNING = ("HUMAN TRANSCRIPTION of one table row (housing), made from the PDF page image (printed page 56) and confirmed by the architect. "
                  "The table layout leaves open whether the line '1 place par logement dans un périmètre de 500m autour d'une gare' "
                  "belongs to general housing or to aided housing: it is read here as general housing, so flag it in 'ambiguities'")

def register_manual_chunks():
    """Add the manual chunk to chunk_by_id (not to 'chunks': the embeddings stay aligned with chunks)."""
    base = dict(chunk_by_id["UB.12#preamble"])
    base.update({
        "chunk_id": MANUAL_ID, "sub_item": "table, housing row", "text": MANUAL_TEXT, "n_chars": len(MANUAL_TEXT),
        "pdf_pages": [16], "printed_pages": [56], "possible_table": False, "manual_transcription": True,
        "unresolved_cross_references": [], "exception_cues": [],
    })
    chunk_by_id[MANUAL_ID] = base
    return base
register_manual_chunks()

order = {c["chunk_id"]: i for i, c in enumerate(chunks)}
order[MANUAL_ID] = order["UB.12#preamble"] + 0.5      # placed right after the table's place in the document
sector = PROJECT["sector"]
family = sorted(sector_family(sector))
HOUSING = {"logement", "logement_aide"}
only_housing = set(PROJECT["building_types"]) <= HOUSING

def chunk_block(c):
    warn = []
    if c.get("manual_transcription"): warn.append(MANUAL_WARNING)
    if c["possible_table"]: warn.append("TABLE read by OCR: rows and columns may be mixed")
    if c["unresolved_cross_references"]: warn.append("refers to texts outside this document: " + "; ".join(c["unresolved_cross_references"]))
    pp = c["printed_pages"]
    head = (f"=== CHUNK {c['chunk_id']} | {c['article_title']} | sub-item {c['sub_item'] or '-'} | "
            f"printed pages {pp[0]}" + (f"-{pp[-1]}" if len(pp) > 1 else "") + " ===")
    return head + ("\nWARNING: " + " / ".join(warn) if warn else "") + "\n" + c["text"]

def build_prompt(param):
    # 1. Which chunks go into the prompt: the kept ones, without the noise, in document order
    res = all_results[param]
    best = max(r["score"] for r in res if r["kind"] == "core")
    expanded_articles = set(EXPANDED.get(param, []))
    keep_ids = {r["chunk_id"] for r in res
                if not r["set_aside"] and (r["kind"] == "same_article"
                                           or r["score"] >= PROMPT_CORE_RATIO * best
                                           or chunk_by_id[r["chunk_id"]]["article_number"] in expanded_articles)}
    aside_ids = [r["chunk_id"] for r in res if r["set_aside"]]
    # 1b. Parking, housing only: the human transcription replaces the garbled OCR table (the OCR chunk is kept in the files, not deleted)
    superseded, notes = [], []
    if param == "stationnement" and (set(PROJECT["building_types"]) & HOUSING):
        keep_ids.add(MANUAL_ID)
        if only_housing and "UB.12#preamble" in keep_ids:
            keep_ids.discard("UB.12#preamble")
            superseded.append("UB.12#preamble")
        elif not only_housing:
            notes.append("Your project has other building types than housing. Only the HOUSING row of the table is transcribed; "
                         "the OCR table chunk is kept for the others and must be checked on the PDF.")
    prompt_chunks = sorted((chunk_by_id[cid] for cid in keep_ids), key=lambda c: order[c["chunk_id"]])
    building = (", ".join(PROJECT["building_labels"]) if param in BUILDING_DEPENDENT
                else "not relevant for this rule (ignore the type of building)")
    # 1c. Rules that must be written so that CODE can test them against the project (the model never sees your values)
    extra_rule = ""
    if any(c.get("manual_transcription") for c in prompt_chunks):
        extra_rule += ("\n10. A chunk marked HUMAN TRANSCRIPTION is a table row typed by a person: treat it like any other chunk, quote it verbatim, "
                       "and use kind \"minimum\" or \"per_unit\" (with value and unit) when the number is written, or \"textual\" when it is not a simple number. "
                       "Each different case (size band, distance to a station, aided housing, visitors, two-wheelers) is its own rule.")
    facts_block, tests_json = "", ""
    if param in FACT_PARAMS:
        facts_block = ("\nPROJECT FACTS YOU MAY USE IN \"applicability_tests\" (names and meanings only: you are NOT given the values of the project and you must not guess them)\n"
                       + "\n".join(f"- {k}: {v['meaning']}" for k, v in FACTS.items()) + "\n")
        extra_rule += ("\n11. For every rule whose condition can be written with the project facts above, add machine-readable \"applicability_tests\": "
                       "{\"fact\": a name from the list, \"op\": one of \"==\" \"!=\" \"<\" \"<=\" \">\" \">=\" \"is_true\" \"is_false\", \"value\": number or null, \"text\": the condition in words}. "
                       "Write each test EXACTLY as the text states it: do not adjust a band to avoid an overlap with another rule, do not decide which rule applies, and do not use any value of the project. "
                       "A condition that needs something that is not in the list (for example the number of floors of the building) goes into \"needs_other_facts\" as a short phrase. "
                       "Use \"applicability_logic\": \"any\" only when the text offers alternatives joined by 'ou', otherwise \"all\". "
                       "The type of building is NOT a test: use \"applies_to_building_types\" (\"logement\" or \"logement_aide\").")
        tests_json = (',\n      "applicability_tests": [{"fact": "...", "op": "...", "value": number or null, "text": "..."}],'
                      '\n      "needs_other_facts": ["..."],\n      "applicability_logic": "all" | "any"')
    # 2. The prompt
    text = f"""You are helping an architect with a PRELIMINARY reading of a French PLU (local urban plan). You do not decide compliance.
Use ONLY the chunks given below. Never use outside knowledge. Never invent a number, an article or a page.

PARAMETER: {param}: {PARAM_DEFINITIONS[param]}
PARCEL SECTOR (entered by the architect): {sector}   (applicable sector family: {", ".join(family)})
BUILDING TYPE: {building}
{facts_block}
WHAT TO DO
1. Find the rule(s) for this parameter that apply to the parcel sector. If the text gives a different value for another sector, do NOT output it as a rule: mention it in "notes".
2. For every rule, copy the exact words that support it into "extract" (verbatim, from ONE chunk, even if the OCR has typos), and give that chunk's id in "chunk_id". Do not translate, correct or shorten inside the quote.
3. "value" and "unit" only if the number is written in the extract. If the rule is a formula (for example a fraction of the height), use kind "formula" and write the formula in "formula_text"; leave value null.
4. List every condition and every exception that limits the rule in "conditions" / "exceptions", each with its own chunk_id and verbatim extract. Include blanket exceptions such as "les prescriptions du présent article ne s'appliquent pas" or "il n'est pas fixé de règle pour".
5. If a chunk is marked TABLE (read by OCR), do not guess which row or column applies: use kind "textual", say so in "ambiguities".
6. If the chunk says the parameter is "Non réglementé" (not regulated), return status "non_reglemente" with that chunk's id and extract.
7. If nothing in the chunks concerns this parameter, return status "non_retrouve" and an empty list of rules.
8. Do not calculate anything and do not say whether a project complies.
9. Several rules are allowed (different cases, building types or sectors of the same family). Each one stands alone.{extra_rule}

ANSWER WITH ONE JSON OBJECT AND NOTHING ELSE, in exactly this shape:
{{
  "parameter": "{param}",
  "status": "reglemente" | "non_reglemente" | "non_retrouve",
  "rules": [
    {{
      "kind": "minimum" | "maximum" | "exact" | "range" | "formula" | "per_unit" | "textual",
      "value": number or null,
      "value_max": number or null,
      "unit": "m" | "m2" | "%" | "niveaux" | "places" | "places_par_logement" | "places_par_100m2_surface_plancher" | "aucune" | null,
      "formula_text": string or null,
      "summary": "one short sentence in English, keeping the French PLU terms",
      "applies_to_sectors": ["{sector}"],
      "applies_to_building_types": [],
      "chunk_id": "the chunk id",
      "extract": "verbatim words copied from that chunk",
      "conditions": [{{"description": "...", "chunk_id": "...", "extract": "verbatim"}}],
      "exceptions": [{{"description": "...", "chunk_id": "...", "extract": "verbatim"}}],
      "ambiguities": ["anything unclear, missing or needing the architect's interpretation"]{tests_json}
    }}
  ],
  "notes": ["other sectors with different values, cross-references to other articles, anything the architect should know"]
}}

CHUNKS
""" + "\n\n".join(chunk_block(c) for c in prompt_chunks)
    return text, prompt_chunks, aside_ids, superseded, notes

# ---- Build, save, show a SHORT summary first, then the prompt between two clear markers ----
built = {}
for param in PARAMS_TO_EXTRACT:
    text, pchunks, aside_ids, superseded, notes = build_prompt(param)
    fname = f"prompt_{param}.txt"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(text)
    built[param] = (text, pchunks, aside_ids, superseded, notes, fname)

print("==== SUMMARY ====")
for param, (text, pchunks, aside_ids, superseded, notes, fname) in built.items():
    print(f"\n{param} | sector {sector} | {len(text)} characters | saved as {fname}")
    print("  chunks in the prompt:", [c["chunk_id"] for c in pchunks])
    if aside_ids:   print("  left out (other building types, not deleted):", aside_ids)
    if superseded:  print("  replaced by the human transcription (not deleted):", superseded)
    if param in FACT_PARAMS: print("  project facts the model may test:", list(FACTS), "(names only, no values)")
    for n_ in notes: print("  NOTE:", n_)

for n, (param, (text, pchunks, aside_ids, superseded, notes, fname)) in enumerate(built.items(), 1):
    print("\n" + "=" * 20, f"COPY FROM THE NEXT LINE  (prompt {n} of {len(built)}: {param})", "=" * 20)
    print(text)
    print("=" * 20, f"END OF PROMPT {n}", "=" * 20)

if DOWNLOAD_PROMPT_FILES:
    try:
        from google.colab import files
        for param, (*_, fname) in built.items():
            files.download(fname)
    except Exception as e:
        print("(download skipped:", e, ")")