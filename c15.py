# CELL 15 | Milestone 5 | Read the LLM's JSON answer, build the rules, run the guardrails, show the results (any parameter)
import re, json, os

assert "verify_rule" in globals(), "Run CELL 17 first (guardrails)."
assert "FactTest" in globals(), "Run CELL 16 first (schema v1.2)."
assert "register_manual_chunks" in globals(), "Run the new CELL 18 (v5) first: it defines the human-transcribed table row and the FACTS list."
register_manual_chunks()                      # makes sure the housing table row is known to the guardrails

# >>> The answers come from the LLM (CELL 18B). Earlier results are reloaded automatically. <<<
OVERWRITE_EXISTING = False   # False = a parameter already extracted and verified is NOT replaced by a new LLM answer (the new answer is saved apart, for comparison)
MANUAL_ANSWER = r'''
PASTE THE JSON HERE (only if you want to read an answer obtained another way; otherwise leave this line as it is)
'''
LLM_RAW = globals().get("LLM_RAW", {})
MODEL_ANSWER = "\n".join(LLM_RAW.values()) + ("" if "PASTE THE JSON HERE" in MANUAL_ANSWER else "\n" + MANUAL_ANSWER)

def parse_all_json(text):
    """Finds every JSON object in the pasted text (one per parameter), with or without code fences."""
    text = re.sub(r"```(?:json)?", "", text)
    dec, objs, i = json.JSONDecoder(), [], text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict) and "parameter" in obj:
                objs.append(obj)
            i = text.find("{", end)
        except json.JSONDecodeError:
            i = text.find("{", i + 1)
    if not objs:
        raise ValueError("No JSON answer found in the pasted text.")
    return objs

def to_source(chunk_id, extract):
    return SourceRef(chunk_id=str(chunk_id), extract=str(extract))

def check_condition_sources(rule):
    """Conditions and exceptions must also quote the PLU truthfully."""
    extra = []
    for kind, items in (("condition", rule.conditions), ("exception", rule.exceptions)):
        for n, cnd in enumerate(items, 1):
            if cnd.source is None:
                extra.append(f"WARNING {kind} {n}: no source given")
                continue
            ch = chunk_by_id.get(cnd.source.chunk_id)
            if ch is None:
                extra.append(f"ERROR {kind} {n}: chunk '{cnd.source.chunk_id}' does not exist"); cnd.source.verified = False; continue
            status, cover = extract_match(cnd.source.extract, ch["text"])
            cnd.source.verified = status != "missing"
            cnd.source.article = f"UB.{ch['article_number']}" if ch["article_number"] else None
            cnd.source.sub_item, cnd.source.pdf_pages, cnd.source.printed_pages = ch["sub_item"], ch["pdf_pages"], ch["printed_pages"]
            if status == "missing":
                extra.append(f"ERROR {kind} {n}: extract not found in {cnd.source.chunk_id} (only {int(cover*100)}% matches)")
            elif status == "approx":
                extra.append(f"WARNING {kind} {n}: extract only approximately found in {cnd.source.chunk_id}")
    rule.guardrail_issues = rule.guardrail_issues + extra
    return rule

VALID_OPS = {"==", "!=", "<", "<=", ">", ">=", "is_true", "is_false"}

def build_tests(rr, problems, n):
    """Machine-readable conditions: only known project facts and known operators are accepted. Anything else is kept as text for the architect."""
    tests, other = [], [str(x) for x in rr.get("needs_other_facts", []) or []]
    known = set(globals().get("FACTS", {}))
    for t in rr.get("applicability_tests", []) or []:
        fact, op, val = t.get("fact"), t.get("op"), t.get("value")
        bad = (known and fact not in known) or op not in VALID_OPS or (op not in ("is_true", "is_false") and (isinstance(val, bool) or not isinstance(val, (int, float))))
        if bad:
            problems.append(f"Rule {n}: test not usable ({fact} {op} {val}); kept as text for the architect")
            other.append(t.get("text") or f"{fact} {op} {val}")
            continue
        tests.append(FactTest(fact=fact, op=op, value=val, text=t.get("text")))
    return tests, other

def build_result(answer, sector, building_types):
    """Returns (ParameterResult or None, list of problems). Nothing is silently dropped."""
    problems, rules = [], []
    param = Parameter(answer["parameter"])
    status = RegulationStatus(answer["status"])
    for n, rr in enumerate(answer.get("rules", []), 1):
        try:
            tests, other_facts = build_tests(rr, problems, n)
            rule = Rule(
                parameter=param, regulation_status=status,
                kind=RuleKind(rr["kind"]) if rr.get("kind") else None,
                value=rr.get("value"), value_max=rr.get("value_max"),
                unit=Unit(rr["unit"]) if rr.get("unit") else None,
                formula_text=rr.get("formula_text"), summary=rr.get("summary"),
                applies_to_sectors=rr.get("applies_to_sectors") or [],
                applies_to_building_types=rr.get("applies_to_building_types") or [],
                conditions=[Condition(description=c.get("description", ""), source=to_source(c["chunk_id"], c["extract"])) if c.get("chunk_id") and c.get("extract") else Condition(description=c.get("description", "")) for c in rr.get("conditions", [])],
                exceptions=[Condition(description=c.get("description", ""), source=to_source(c["chunk_id"], c["extract"])) if c.get("chunk_id") and c.get("extract") else Condition(description=c.get("description", "")) for c in rr.get("exceptions", [])],
                ambiguity_flags=[str(a) for a in rr.get("ambiguities", [])],
                sources=[to_source(rr["chunk_id"], rr["extract"])] if rr.get("chunk_id") and rr.get("extract") else [],
                applicability_tests=tests, needs_other_facts=other_facts,
                applicability_logic=rr.get("applicability_logic") if rr.get("applicability_logic") in ("all", "any") else "all",
            )
            rule = verify_rule(rule)
            rule = check_condition_sources(rule)
            rules.append(rule)
        except Exception as e:
            problems.append(f"Rule {n} could not be built and was NOT kept: {str(e).splitlines()[0][:160]}")
    if status == RegulationStatus.NOT_FOUND:
        return ParameterResult(parameter=param, sector=sector, building_types=building_types, status=status,
                               notes=[str(x) for x in answer.get("notes", [])]), problems
    if not rules:
        problems.append("The model said the parameter is regulated but no usable rule came out: treat as 'interpretation required', NOT as 'not found'.")
        return None, problems
    return ParameterResult(parameter=param, sector=sector, building_types=building_types, status=status,
                           rules=rules, notes=[str(x) for x in answer.get("notes", [])]), problems

def show_result(result, problems):
    print(f"\n=== {result.parameter.value if result else '???'} | sector {PROJECT['sector']} | status: {result.status.value if result else 'EXTRACTION FAILED'} ===")
    for p in problems: print("  PROBLEM:", p)
    if not result: return
    for k, r in enumerate(result.rules, 1):
        src = r.sources[0] if r.sources else None
        val = f"{r.value:g} {r.unit.value}" if r.value is not None and r.unit else (r.formula_text or "-")
        print(f"\n  Rule {k}: {r.kind.value if r.kind else '-'} | {val} | sectors: {r.applies_to_sectors or 'not stated'}")
        print(f"    {r.summary}")
        if src:
            print(f"    Source: {src.article} sub-item {src.sub_item} | printed p.{src.printed_pages} | verified: {src.verified}")
            print(f"    Extract: {src.extract[:220]!r}")
        for label, items in (("Condition", r.conditions), ("Exception", r.exceptions)):
            for c in items:
                s = c.source
                print(f"    {label}: {c.description[:110]} [{s.chunk_id if s else 'no source'} | verified: {s.verified if s else '-'}]")
        for tt in r.applicability_tests: print(f"    Test ({r.applicability_logic}): {tt.fact} {tt.op} {tt.value if tt.value is not None else ''}  [{tt.text}]")
        for o in r.needs_other_facts: print("    Needs another fact:", o)
        for a in r.ambiguity_flags: print("    Ambiguity:", a)
        for i in r.guardrail_issues: print("    GUARDRAIL:", i)
        if has_errors(r):
            print("    >>> FAILED THE GUARDRAILS: do not rely on this rule until it is checked against the PDF <<<")
        print(f"    auto_comparable: {r.auto_comparable()}  |  review: {r.review_status.value}")
    for n in result.notes: print("  Note:", n)

if True:
    EXTRACTED = globals().setdefault("EXTRACTED", {})
    if not EXTRACTED:                                   # new session: reload the earlier results saved by this cell
        for path in ["extractions_all.json", "/content/drive/MyDrive/PLU_project/prototype_UB/extractions_all.json"]:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        EXTRACTED[k] = ParameterResult.model_validate(v)
                print(f"Loaded {len(EXTRACTED)} earlier result(s) from {path}: {sorted(EXTRACTED)}")
                break
    for k in list(EXTRACTED):                           # bring results made with an older schema up to the current one
        EXTRACTED[k] = ParameterResult.model_validate(EXTRACTED[k].model_dump(mode="json"))
    try:
        answers = parse_all_json(MODEL_ANSWER) if MODEL_ANSWER.strip() else []
        if not answers: print("\nNo new LLM answer in memory (run CELL 18B to get one). Showing the results already stored.")
    except Exception as e:
        answers = []; print("The answer could not be read:", e)
    for answer in answers:
        try:
            result, problems = build_result(answer, PROJECT["sector"], PROJECT["building_types"])
            show_result(result, problems)
            if result:
                pname = result.parameter.value
                if pname in EXTRACTED and not OVERWRITE_EXISTING:
                    print(f"\n  >>> {pname} was already extracted and verified: it is KEPT ({len(EXTRACTED[pname].rules)} rules). This new answer has {len(result.rules)} rule(s) and is saved apart as extractions_llm_{pname}.json for comparison. Set OVERWRITE_EXISTING = True to replace.")
                    with open(f"extractions_llm_{pname}.json", "w", encoding="utf-8") as f:
                        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=1)
                else:
                    EXTRACTED[pname] = result
        except Exception as e:
            print(f"\n=== {answer.get('parameter', '???')} === could not be read:", e)
    if EXTRACTED:
        with open("extractions_all.json", "w", encoding="utf-8") as f:
            json.dump({k: v.model_dump(mode="json") for k, v in EXTRACTED.items()}, f, ensure_ascii=False, indent=1)
        print("\n==== SUMMARY: parameters extracted so far ====")
        for k in PARAM_DEFINITIONS if "PARAM_DEFINITIONS" in globals() else EXTRACTED:
            if k in EXTRACTED:
                v = EXTRACTED[k]
                n_err = sum(has_errors(r) for r in v.rules)
                print(f"  {k:<28} {v.status.value:<16} rules: {len(v.rules)} | auto_comparable: {sum(r.auto_comparable() for r in v.rules)} | failed guardrails: {n_err}")
            else:
                print(f"  {k:<28} (not extracted yet)")
        print("Saved extractions_all.json")