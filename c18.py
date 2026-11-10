# CELL 18 | Milestone 6 (prototype) | Which rules apply to MY project? The program checks the conditions and picks the rules, the architect verifies
import json, re, math

assert "EXTRACTED" in globals() and EXTRACTED, "Run CELL 19 first (extraction)."
assert "PROJECT" in globals() and "FACTS" in globals(), "Run CELL 12 and CELL 18 first (project profile and FACTS list)."

PARAMS_TO_CHECK = ["stationnement", "espaces_verts_pleine_terre"]       # <- the parameters whose rules depend on project facts

# DECISION RULE used when several "places per dwelling" rules apply at once (the PLU does not say whether they replace or add to each other):
#   "stricter"         = the rule requiring the MOST places is kept (prudent: never declares a project compliant too easily)
#   "station_replaces" = the rule tied to the 500 m station perimeter replaces the size-band rules
# The other rules stay visible as the alternative reading, and the architect verifies the choice.
CONFLICT_POLICY = "stricter"
OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b, "<": lambda a, b: a < b,
       "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
PLACES_UNITS = {Unit.SPACES, Unit.SPACES_PER_DWELLING, Unit.SPACES_PER_100M2}

def num(s):
    return float(s.strip().replace(",", "."))

# ---- 1. Which candidate rules exist for the building type of the project, and which facts do they need? ----
def type_ok(rule):
    return (not rule.applies_to_building_types) or bool(set(rule.applies_to_building_types) & set(PROJECT["building_types"]))

needed = []
for p in PARAMS_TO_CHECK:
    if p not in EXTRACTED:
        print(f"(parameter {p} is not extracted yet: skipped)"); continue
    for r in EXTRACTED[p].rules:
        if type_ok(r):
            for t in r.applicability_tests:
                if t.fact not in needed: needed.append(t.fact)

# ---- 2. Show the facts already known, let the architect correct them, and ask only for what is missing (Enter = keep / unknown) ----
ASK = {   # wording of the questions as shown in this cell
    "avg_dwelling_sdp_m2": "Average SDP (surface de plancher) PER LOGEMENT, in m2 (average of one logement)",
    "within_500m_station": "Is the parcel within 500 m of a gare (railway station)?",
    "n_dwellings":         "Number of logements in the project",
    "total_sdp_m2":        "TOTAL SDP of the whole operation, in m2 (all logements together)",
    "n_f1_f2_dwellings":   "How many of the logements are of type T1 or T2?",
    "n_larger_dwellings":  "How many of the logements are larger than T2 (T3 or more)?",
}
def q(f): return ASK.get(f, FACTS[f]["question"])

def show_fact(f):
    v = PROJECT.get(f)
    return "unknown" if v is None else ("yes" if v is True else "no" if v is False else f"{v:g}")

needed = [f for f in needed if not FACTS[f].get("computed")]      # computed facts (e.g. required_places) are never asked
known = [f for f in needed if PROJECT.get(f) is not None]
change_all = False
if known:
    print("Project facts used by the rules:")
    for f in needed: print(f"  - {q(f)}  ->  {show_fact(f)}")
    change_all = input("\nAre these answers correct?  Enter = yes | n = no, I want to change them: ").strip().lower() in ("n", "no", "non")
to_ask = needed if change_all else [f for f in needed if PROJECT.get(f) is None]
if to_ask:
    print("\nAnswer, or press Enter to keep the current value (unknown if none).\n")
for f in to_ask:
    spec, old = FACTS[f], PROJECT.get(f)
    if spec["type"] == "bool":
        a = input(f"{q(f)}  [y / n / Enter = keep: {show_fact(f)}]: ").strip().lower()
        PROJECT[f] = True if a in ("y", "yes", "o", "oui") else (False if a in ("n", "no", "non") else old)
    else:
        a = input(f"{q(f)}  [number / Enter = keep: {show_fact(f)}]: ").strip()
        try:    PROJECT[f] = num(a) if a else old
        except ValueError: print("  (not a number: kept the previous value)"); PROJECT[f] = old

# ---- 2b. Consistency check of the answers ----
_n, _t, _a = PROJECT.get("n_dwellings"), PROJECT.get("total_sdp_m2"), PROJECT.get("avg_dwelling_sdp_m2")
if _n and _t and _a and abs(_n * _a - _t) > 0.3 * _t:
    print(f"\n!! CHECK YOUR ANSWERS: {_n:g} dwellings x {_a:g} m2 = {_n*_a:g} m2, but the total SDP is {_t:g} m2 (about {_t/_n:.0f} m2 per dwelling). One of the three numbers is probably wrong.")

_f, _g = PROJECT.get("n_f1_f2_dwellings"), PROJECT.get("n_larger_dwellings")
if _n and _f is not None and _g is not None and _f + _g != _n:
    print(f"\n!! CHECK YOUR ANSWERS: {_f:g} logements T1/T2 + {_g:g} larger = {_f+_g:g}, but the project has {_n:g} logements.")

# ---- 3. The program tests every condition against the project (the language model is NOT involved) ----
def eval_test(t):
    v = PROJECT.get(t.fact)
    if v is None: return None
    if t.op == "is_true":  return v is True
    if t.op == "is_false": return v is False
    if t.value is None or isinstance(v, bool): return None
    return OPS[t.op](float(v), float(t.value))

def check_rule(rule):
    """Returns (status, list of lines explaining it). status: applies / to_confirm / not_for_project."""
    if not type_ok(rule):
        return "not_for_project", ["other building type: " + ", ".join(rule.applies_to_building_types)]
    if has_errors(rule):                  # a rule that failed the guardrails is never proposed by the program
        return "to_confirm", ["[?? ] this rule FAILED the guardrails (a quote or number is not in the PDF text): check it against the PDF before using it"]
    lines, vals = [], []
    for t in rule.applicability_tests:
        r = eval_test(t)
        vals.append(r)
        mark = "yes" if r else ("NO " if r is False else "?? ")
        shown = PROJECT.get(t.fact)
        lines.append(f"[{mark}] {t.text or t.fact}  ({t.fact} {t.op} {t.value if t.value is not None else ''} | your project: {shown if shown is not None else 'unknown'})")
    for o in rule.needs_other_facts:
        lines.append(f"[?? ] needs something not collected yet: {o}")
    untested = []
    if not rule.applicability_tests and not rule.needs_other_facts:      # conditions written in the PLU that no test covers
        untested = [c.description for c in rule.conditions]
        for c in untested:
            lines.append(f"[?? ] condition the program cannot test: {c[:110]}")
    unknown = (None in vals) or bool(rule.needs_other_facts) or bool(untested)
    if rule.applicability_logic == "any" and vals:
        if True in vals:   return "applies", lines
        if unknown:        return "to_confirm", lines
        return "not_for_project", lines
    if False in vals:      return "not_for_project", lines
    if unknown:            return "to_confirm", lines
    return "applies", lines

LABEL = {"applies": "APPLIES", "to_confirm": "TO CONFIRM", "not_for_project": "not for your project"}

def evaluate():
    out = {}                                  # parameter -> list of (rule number, rule, status, lines)
    for p in PARAMS_TO_CHECK:
        if p not in EXTRACTED: continue
        out[p] = []
        for k, r in enumerate(EXTRACTED[p].rules, 1):
            status, lines = check_rule(r)
            r.applicable_to_project = status
            out[p].append((k, r, status, lines))
    return out

# the program picks between "places per dwelling" rules that apply at once (the architect only verifies)
def pdw(r): return r.value if (r.unit == Unit.SPACES_PER_DWELLING and r.value is not None) else None
def is_station_rule(r): return any(t.fact == "within_500m_station" for t in r.applicability_tests)

def resolve(checked):
    resolved, proposal, info = {}, {}, {}
    for p, items in checked.items():
        cands = [(k, r) for k, r, s, _ in items if s == "applies" and pdw(r) is not None]
        best, why = None, None
        if len(cands) > 1:
            if CONFLICT_POLICY == "station_replaces" and any(is_station_rule(r) for _, r in cands):
                best = max([(k, r) for k, r in cands if is_station_rule(r)], key=lambda kr: pdw(kr[1]))
                why = "policy 'station_replaces': the rule tied to the station perimeter replaces the size-band rules"
            else:
                best = max(cands, key=lambda kr: pdw(kr[1]))
                why = "policy 'stricter': among the rules that apply at once, the one requiring the most places is kept"
            for k, r in cands:
                if k != best[0]: resolved[(p, k)] = f"set aside: {why} (kept [{best[0]}])"
        elif len(cands) == 1:
            best = cands[0]
        info[p] = {"cands": cands, "best": best, "why": why}
        proposal[p] = [k for k, r, s, _ in items if s == "applies" and (p, k) not in resolved]
    return resolved, proposal, info

# pass 1: rules that do not depend on the computed number of places
checked = evaluate()
RESOLVED, PROPOSAL, INFO = resolve(checked)

# the number of required places is COMPUTED by the program (chosen rule x dwellings, plus visitor places if that rule applies)
PROJECT["required_places"], REQ_DETAIL = None, None
if "stationnement" in checked and PROJECT.get("n_dwellings") and INFO["stationnement"]["best"]:
    _n = PROJECT["n_dwellings"]
    _kb, _rb = INFO["stationnement"]["best"]
    cars = math.ceil(pdw(_rb) * _n)
    vis = 0
    for k, r, s, _ in checked["stationnement"]:
        if s == "applies" and "visitor" in (r.formula_text or r.summary or "").lower(): vis = math.ceil(_n / 5)
    PROJECT["required_places"] = float(cars + vis)
    REQ_DETAIL = f"{cars + vis} places = {cars} for the logements (rule [{_kb}]) + {vis} for visitors" + (" (visitor rule applies; an incomplete slice of 5 is counted: stricter reading)" if vis else "")

# pass 2: now the rules that depend on the number of places (e.g. the 5% reduced-mobility rule at 20 places or more)
checked = evaluate()
RESOLVED, PROPOSAL, INFO = resolve(checked)

# ---- 4. Show the result: first the rules that matter, then the others in one line each ----
print("\n==== PROJECT FACTS USED ====")
print("Sector:", PROJECT["sector"], "| building type(s):", "; ".join(PROJECT["building_labels"]))
for f in FACTS:
    print(f"  {f:<22} = {PROJECT.get(f) if PROJECT.get(f) is not None else 'unknown'}")

for p, items in checked.items():
    print(f"\n==== {p}: rules checked against your project ====")
    for k, r, status, lines in items:
        if status == "not_for_project": continue
        val = f"{r.value:g} {r.unit.value}" if r.value is not None and r.unit else (r.formula_text or "-")
        print(f"\n[{k}] {LABEL[status]} | {r.kind.value if r.kind else '-'} | {val}")
        print(f"    {r.summary}")
        for ln in lines: print("    ", ln)
        src = r.sources[0] if r.sources else None
        if src: print(f"     Source: {src.article} sub-item {src.sub_item} | printed p.{src.printed_pages}")
        for e in r.exceptions: print(f"     Possible exception: {e.description[:120]}")
        for a in r.ambiguity_flags: print("     Ambiguity:", a[:220])
    print("\n---- Not for your project (shown so that nothing disappears silently) ----")
    for k, r, status, lines in items:
        if status == "not_for_project":
            why = next((ln for ln in lines if ln.startswith("[NO") or ln.startswith("other building")), lines[0] if lines else "")
            print(f"  [{k}] {r.summary[:95]}  <- {why[:90]}")

# ---- 4b. Show the program's choice ----
for p, items in checked.items():
    print(f"\n==== {p}: THE PROGRAM'S CHOICE ====")
    cands, best, why = INFO[p]["cands"], INFO[p]["best"], INFO[p]["why"]
    n = PROJECT.get("n_dwellings")
    if len(cands) > 1:
        print(f"Several rules on places per dwelling apply at once: {[k for k, _ in cands]}. The PLU does not say whether they replace or add to each other.")
        print(f"Program's choice: rule [{best[0]}] ({pdw(best[1]):g} place(s) per dwelling). Reason: {why}.")
        if n:
            for k, r in cands:
                tag = "CHOSEN     " if k == best[0] else "alternative "
                print(f"   {tag}[{k}] {pdw(r):g} per dwelling x {n:g} dwellings = {math.ceil(pdw(r) * n)} places")
            print("   (number of dwellings x places per dwelling, rounded up; this is the program's arithmetic, to be verified)")
            if len({pdw(r) for _, r in cands}) == 1:
                print("   The competing rules give the same number here, so the choice between them does not change the result.")
    elif len(cands) == 1:
        k, r = cands[0]
        print(f"One rule on places per dwelling applies: [{k}] {pdw(r):g} per dwelling" + (f" x {n:g} dwellings." if n else "."))
    else:
        print("No rule on places per dwelling applies with the facts given.")
    if p == "stationnement" and REQ_DETAIL:
        print("Required parking places (program's calculation):", REQ_DETAIL)
    print("Proposed rules to retain:", PROPOSAL[p])
    asked = [k for k, r, s, _ in items if s == "to_confirm"]
    if asked: print("Rules the program cannot decide alone (a needed fact is missing or not collected yet):", asked)

# ---- 5. Human verification: nothing is final until the architect says so ----
def parse_numbers(s, valid):
    out = []
    for x in re.split(r"[,\s;]+", s.strip()):
        if x.isdigit() and int(x) in valid: out.append(int(x))
        elif x: print(f"  (ignored: '{x}')")
    return out

DECISIONS = {}
for p, items in checked.items():
    valid = {k for k, *_ in items}
    proposal = PROPOSAL[p]
    print(f"\n==== YOUR VERIFICATION for {p} ====")
    print("The program proposes to retain:", proposal or "none")
    a = input("Do you accept the program's proposal?  Enter = yes | n = no, I want to change it: ").strip().lower()
    if a in ("n", "no", "non"):
        c = input("Rules to RETAIN (numbers separated by commas | Enter = keep the proposal): ").strip()
        confirmed = parse_numbers(c, valid) if c else proposal
        d = input("Rules to REJECT (numbers separated by commas | Enter = none): ").strip()
        rejected = parse_numbers(d, valid)
        who = "architect changed the proposal"
    else:
        confirmed, rejected, who = proposal, [], "architect accepted the program's proposal"
    for k, r, s, _ in items:
        if k in rejected:    r.applicability_confirmed = False
        elif k in confirmed: r.applicability_confirmed = True
        else:                r.applicability_confirmed = None
    DECISIONS[p] = [{"rule": k, "summary": r.summary, "code_says": s, "program_note": RESOLVED.get((p, k)), "architect": r.applicability_confirmed, "how": who} for k, r, s, _ in items]

# ---- 6. Save and summarise ----
with open("extractions_all.json", "w", encoding="utf-8") as f:
    json.dump({k: v.model_dump(mode="json") for k, v in EXTRACTED.items()}, f, ensure_ascii=False, indent=1)
with open("applicability_decisions.json", "w", encoding="utf-8") as f:
    json.dump({"project": PROJECT, "conflict_policy": CONFLICT_POLICY, "decisions": DECISIONS}, f, ensure_ascii=False, indent=1)

print("\n==== RULES RETAINED FOR YOUR PROJECT (verified by the architect) ====")
for p, items in checked.items():
    kept = [(k, r) for k, r, *_ in items if r.applicability_confirmed is True]
    undecided = [k for k, r, s, _ in items if s != "not_for_project" and r.applicability_confirmed is None and (p, k) not in RESOLVED]
    aside = [k for (pp, k) in RESOLVED if pp == p]
    for k, r in kept: print(f"  [{k}] {r.summary}")
    if not kept: print("  none confirmed yet")
    if undecided: print("  still undecided:", undecided)
    if aside: print("  set aside by the program (alternative reading):", aside)
print("\nSaved extractions_all.json and applicability_decisions.json")