#CELL 29 COMPLIANCE REPORT | Milestone 7 | All parameters checked together, in the order of the PLU articles
import json, re

g = PROJECT.get
new = g("new_construction")
OK, NOK = "Conforme selon la règle structurée", "Non-conformité potentielle"
REVIEW, MISSING, NOTFOUND = "Interprétation requise", "Données insuffisantes", "Règle non retrouvée"
RESULTS = []

def pick(param, *tokens, value=False):
    if param not in EXTRACTED: return None, None
    for k, r in enumerate(EXTRACTED[param].rules, 1):
        text = ((r.summary or "") + " " + (r.formula_text or "")).lower()
        if has_errors(r) or (value and r.value is None): continue
        if not tokens or any(t.lower() in text for t in tokens): return k, r
    return None, None

def verdict(ok):
    return OK if ok else (NOK if new else REVIEW)

def add(article, name, status, detail="", rule=None, rule_no=None, notes=()):
    s = rule.sources[0] if rule is not None and rule.sources else None
    where = f"{s.article} sub-item {s.sub_item}, printed p.{s.printed_pages}" if s else article
    exc = [e.description[:120] for e in rule.exceptions[:3]] if rule is not None and status in (NOK, REVIEW) else []
    RESULTS.append({"article": article, "name": name, "status": status, "detail": detail, "where": where,
                    "quote": s.extract[:160] if s else "", "notes": list(notes) + exc, "rule": rule_no})

def notfound(article, name):
    add(article, name, NOTFOUND, "no usable rule in the extraction")

# ---------------- UB.6 implantation ----------------
for word, cond, dfact, name in [("public roads", None, "dist_road_m", "Setback from public/private roads"),
                                ("halage", "borders_halage", "dist_halage_m", "Setback from the chemin de Halage"),
                                ("stream", "borders_ru", "dist_ru_m", "Setback from the stream (ru)"),
                                ("railway", "near_railway", "dist_rail_m", "Distance from the railway")]:
    k, r = pick("implantation_voies", word, value=True)
    if r is None: notfound("UB.6", name); continue
    if cond is not None and g(cond) is False: continue
    d = g(dfact)
    if (cond is not None and g(cond) is None) or d is None or new is None:
        add("UB.6", name, MISSING, f"required at least {r.value:g} m | project: {d if d is not None else 'unknown'}", r, k)
    else:
        add("UB.6", name, verdict(d >= r.value), f"required at least {r.value:g} m | project: {d:g} m", r, k)

# ---------------- UB.7 boundaries ----------------
k1, r1 = pick("limites_separatives", "lateral")
k2, r2 = pick("limites_separatives", "rear")
k3, r3 = pick("limites_separatives", "HT/2")
f3 = (r3.formula_text or "") if r3 else ""
mins = {("no" if gr else "yes"): float(n.replace(",", ".")) for n, gr in
        re.findall(r"minimum\s+(\d+(?:[.,]\d+)?)\s*m\s+if\s+the\s+\w+\s+has\s+(no\s+)?openings", f3, flags=re.I)}
formula_ok = r3 is not None and "HT/2" in f3.replace(" ", "") and len(mins) == 2
for name, kind in [("lateral boundary 1", "lateral"), ("lateral boundary 2", "lateral"), ("rear boundary", "rear")]:
    t = name.replace(" ", "_")
    if g(f"{t}_exists") is not True: continue
    label, (kk, rule) = f"Position relative to the {name}", ((k1, r1) if kind == "lateral" else (k2, r2))
    on, op, L, ht = g(f"{t}_on"), g(f"{t}_openings"), g(f"{t}_L"), g(f"{t}_HT")
    if rule is None: notfound("UB.7", label); continue
    if on is None or op is None or new is None or (on is False and (L is None or ht is None)):
        add("UB.7", label, MISSING, "a value is missing", rule, kk); continue
    if on is True:
        if kind == "lateral": add("UB.7", label, verdict(op is False), "building on the boundary: allowed only if the facade has no openings", rule, kk)
        else: add("UB.7", label, verdict(False), "building on the rear boundary: the margins d'isolement must be respected", rule, kk)
    elif not formula_ok:
        add("UB.7", label, REVIEW, "the margin formula could not be read from the rule", r3, k3)
    else:
        m = mins["yes" if op else "no"]; need = max(ht / 2, m)
        add("UB.7", label, verdict(L >= need), f"required margin L = max(HT/2 = {ht/2:g}, minimum {m:g}) = {need:g} m | project L = {L:g} m", r3, k3)

# ---------------- UB.9 footprint ----------------
plot, foot, green = g("plot_area_m2"), g("building_footprint_m2"), g("pleine_terre_m2")
k, r = next(((k, r) for k, r in enumerate(EXTRACTED["emprise_au_sol"].rules, 1)
             if r.kind and r.kind.value == "maximum" and r.unit and r.unit.value == "%" and r.value is not None and not has_errors(r)), (None, None))
if r is None: notfound("UB.9", "Building footprint (CES)")
elif None in (plot, foot) or plot <= 0 or new is None: add("UB.9", "Building footprint (CES)", MISSING, "plot area or footprint missing", r, k)
else:
    ces = foot / plot * 100
    add("UB.9", "Building footprint (CES)", verdict(ces <= r.value), f"required at most {r.value:g} % | project: {ces:.1f} % (footprint / plot area)", r, k,
        ["Assumption: the extract does not state the denominator; taken as the total plot area."])

# ---------------- UB.10 height and levels ----------------
slope = g("slope_facing_oise")
for label, tokens, hasf, hf, nf in [("pitched roof", ("faîtage", "faitage", "pitched"), "roof_pitched", "height_ridge_m", "floors_above_ground_roof_pitched"),
                                    ("flat roof", ("acrotère", "acrotere", "flat roof"), "roof_flat", "height_acroterion_m", "floors_above_ground_roof_flat")]:
    if g(hasf) is not True: continue
    k, r = pick("hauteur_maximale", *tokens, value=True)
    h = g(hf)
    if r is None: notfound("UB.10", f"Maximum height ({label})")
    elif h is None or new is None or slope is None: add("UB.10", f"Maximum height ({label})", MISSING, f"required at most {r.value:g} m | project: unknown", r, k)
    elif slope: add("UB.10", f"Maximum height ({label})", REVIEW, f"required at most {r.value:g} m | project: {h:g} m", r, k,
                    ["Sloping land facing the Oise: heights are set from a median point defined in an annex that is not in the document."])
    else: add("UB.10", f"Maximum height ({label})", verdict(h <= r.value), f"required at most {r.value:g} m | project: {h:g} m", r, k,
              [c.description[:120] for c in r.conditions[:2]])
    k, r = pick("nombre_de_niveaux", *tokens)
    n, attic = g(nf), g("attic_roof_pitched") if label == "pitched roof" else False
    m = re.search(r"R\s*\+\s*(\d+)", ((r.formula_text or "") + " " + (r.summary or ""))) if r else None
    if r is None: notfound("UB.10", f"Number of levels ({label})")
    elif m is None: add("UB.10", f"Number of levels ({label})", REVIEW, "the number of levels could not be read from the rule", r, k)
    elif n is None or new is None: add("UB.10", f"Number of levels ({label})", MISSING, f"allowed: R+{m.group(1)} | project: unknown", r, k)
    else: add("UB.10", f"Number of levels ({label})", verdict(n <= int(m.group(1))),
              f"project: R+{n:g}" + (" + combles/attique" if attic else "") + f" | allowed: R+{m.group(1)}", r, k,
              [a[:140] for a in r.ambiguity_flags[:1]])

# ---------------- UB.12 parking ----------------
PU = globals().get("PLACES_UNITS") or {Unit.SPACES, Unit.SPACES_PER_DWELLING, Unit.SPACES_PER_100M2}
status_of = lambda r: getattr(r, "applicable_to_project", None)
rules12 = list(enumerate(EXTRACTED["stationnement"].rules, 1)) if "stationnement" in EXTRACTED else []
is_places = lambda r: r.unit in PU or "visitor" in (r.summary or "").lower()
basis = [(k, r) for k, r in rules12 if status_of(r) == "applies" and is_places(r) and not has_errors(r)]
unsure = [k for k, r in rules12 if status_of(r) == "to_confirm" and is_places(r)]
need, have = g("required_places"), g("places_provided")
if not basis: notfound("UB.12", "Number of parking places")
elif need is None or have is None: add("UB.12", "Number of parking places", MISSING, "required places not calculated (run the Fact-Test Evaluator) or places provided missing", basis[0][1], basis[0][0])
else:
    st = (MISSING if unsure else OK) if have >= need else NOK
    add("UB.12", "Number of parking places", st, f"required: {need:g} (calculated from the retained rules) | provided: {have:g}", basis[0][1], basis[0][0],
        ([f"Rules {unsure} are still undecided and could raise the requirement."] if unsure else []) +
        ["Required places follow the 'stricter' policy (rounded up, incomplete visitor slice counted)."])
for k, r in rules12:
    if status_of(r) == "applies" and not is_places(r) and not has_errors(r):
        add("UB.12", "Other parking rule: " + (r.summary or "")[:80], REVIEW, "retained for your project but not compared automatically: check on the drawings", r, k)

# ---------------- UB.13 open ground ----------------
kg, rg = next(((k, r) for k, r in enumerate(EXTRACTED["espaces_verts_pleine_terre"].rules, 1)
               if status_of(r) == "applies" and r.unit and r.unit.value == "%" and r.value is not None and not has_errors(r)), (None, None))
if rg is None: notfound("UB.13", "Open ground (pleine terre)")
elif None in (plot, foot, green) or new is None: add("UB.13", "Open ground (pleine terre)", MISSING, "plot area, footprint or pleine terre area missing", rg, kg)
elif not (0 <= foot < plot) or green > plot - foot + 1e-9: add("UB.13", "Open ground (pleine terre)", MISSING, "inconsistent areas: check the numbers", rg, kg)
else:
    share = green / (plot - foot) * 100
    add("UB.13", "Open ground (pleine terre)", verdict(share >= rg.value), f"required at least {rg.value:g} % of the unbuilt area | project: {share:.1f} %", rg, kg,
        ["Assumption: unbuilt area = plot area - footprint (driveways and terraces not subtracted)."])
kc, rc = pick("espaces_verts_pleine_terre", "5-meter", "5 m", "strip", value=True)
if rc is not None and g("in_ecological_corridor") is not False:
    st = MISSING if g("in_ecological_corridor") is None or (g("in_ecological_corridor") and g("corridor_strip_kept") is None) else verdict(g("corridor_strip_kept") is True)
    add("UB.13", "5 m strip along the ecological corridor", st, "applies only inside the ecological corridor perimeter", rc, kc)

# ---------------- THE REPORT ----------------
print("=" * 78 + "\nCOMPLIANCE REPORT (in the order of the PLU articles)\n" + "=" * 78)
for i, x in enumerate(RESULTS, 1):
    print(f"{i:>2}. {x['article']:<6} {x['name'][:52]:<52} {x['status']}")
groups = [("CONFIRMED (conforme according to the structured rule)", [OK]), ("NOT COMPLIANT (potential non-conformity)", [NOK]),
          ("TO CHECK (interpretation required, data missing, or rule not found)", [REVIEW, MISSING, NOTFOUND])]
for title, sts in groups:
    items = [x for x in RESULTS if x["status"] in sts]
    print(f"\n{'-' * 78}\n{title}: {len(items)}\n{'-' * 78}")
    for x in items:
        print(f"* {x['article']} | {x['name']}\n    {x['status']}" + (f" | {x['detail']}" if x["detail"] else ""))
        print(f"    Where to check: {x['where']}")
        if x["status"] != OK and x["quote"]: print(f"    Quote: {x['quote']!r}")
        for n_ in x["notes"]: print(f"    Check: {n_}")
json.dump(RESULTS, open("compliance_report.json", "w"), ensure_ascii=False, indent=1)
print("\nSaved compliance_report.json")