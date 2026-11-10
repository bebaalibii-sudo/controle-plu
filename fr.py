"""Textes en français de l'interface : repris de la cellule 32 (interface du jury), sans Gradio."""
import re
from pathlib import Path

_src = (Path(__file__).parent / "c32.py").read_text(encoding="utf-8")
_part = _src[_src.index('OK, NOK = "Conforme'):_src.index("def run_check(")]
# généralisation : n'importe quel préfixe de zone (UB, UA, UC...) dans « Où vérifier »
_part = _part.replace(r're.match(r"(UB\.\d+)(?: sub-item', r're.match(r"([A-Z]{1,4}[a-z]?\.\d+)(?: sub-item')
NS = {"re": re}
exec(compile(_part, "<cellule 32 : textes FR>", "exec"), NS)

OK, NOK, REVIEW, MISSING, NOTFOUND = NS["OK"], NS["NOK"], NS["REVIEW"], NS["MISSING"], NS["NOTFOUND"]
ICON, SECTIONS_FR, LABELS_FR = NS["ICON"], NS["SECTIONS_FR"], NS["LABELS_FR"]
name_fr, detail_fr, notes_fr = NS["name_fr"], NS["detail_fr"], NS["notes_fr"]


def where_fr(where, offset):
    NS["PDF_OFFSET"] = offset
    return NS["where_fr"](where)


def render_markdown(results, offset, header=""):
    NS["PDF_OFFSET"] = offset
    return (header + "\n\n" if header else "") + NS["render"](results)


def section_fr(section, zone):
    s = SECTIONS_FR.get(section, section)
    return s.replace("UB.", f"{zone}.") if zone != "UB" else s


PARAM_FR = {
    "implantation_voies": "Implantation par rapport aux voies",
    "limites_separatives": "Limites séparatives",
    "emprise_au_sol": "Emprise au sol",
    "hauteur_maximale": "Hauteur maximale",
    "nombre_de_niveaux": "Nombre de niveaux",
    "stationnement": "Stationnement",
    "espaces_verts_pleine_terre": "Espaces verts et pleine terre",
}
APPLIES_FR = {"applies": "S'applique au projet", "to_confirm": "À confirmer", "not_for_project": "Ne concerne pas le projet"}
TYPES_FR = {  # libellés de la cellule 9
    "logement": "Logement (habitation)",
    "logement_aide": "Logement locatif financé avec un prêt aidé par l'État",
    "hebergement_hotelier": "Hébergement hôtelier (hôtel, foyer, résidence…)",
    "commerce_services": "Commerce et activités de service",
    "bureaux": "Bureaux",
    "equipement_public": "Équipement public ou d'intérêt collectif",
    "autre": "Autre construction ou installation",
}


def line_fr(line):
    """Lignes d'explication de la cellule 18 (« [yes] ... ») en français."""
    t = str(line)
    t = t.replace("[yes]", "[oui]").replace("[NO ]", "[non]").replace("[?? ]", "[ ? ]")
    for en, fr in [("your project:", "votre projet :"), ("unknown", "inconnu"),
                   ("needs something not collected yet:", "demande une donnée non collectée :"),
                   ("condition the program cannot test:", "condition que le programme ne peut pas tester :"),
                   ("other building type:", "autre type de construction :"),
                   ("this rule FAILED the guardrails (a quote or number is not in the PDF text): check it against the PDF before using it",
                    "cette règle n'a PAS passé les garde-fous (citation ou nombre absent du texte du PDF) : à vérifier sur le PDF")]:
        t = t.replace(en, fr)
    return t


def note_fr(note):
    if not note:
        return ""
    if "stricter" in note:
        m = re.search(r"kept \[(\d+)\]", note)
        return ("Écartée par la lecture la plus stricte : parmi les règles « places par logement » qui s'appliquent en même temps, "
                f"celle qui exige le plus de places est retenue (règle {m.group(1) if m else '?'}).")
    return note


def required_fr(detail):
    if not detail:
        return ""
    m = re.match(r"(\d+) places = (\d+) for the logements \(rule \[(\d+)\]\) \+ (\d+) for visitors", detail)
    if not m:
        return detail
    tot, cars, k, vis = m.groups()
    s = f"{tot} place(s) exigée(s) = {cars} pour les logements (règle {k}) + {vis} pour les visiteurs"
    if "incomplete slice" in detail:
        s += " (une tranche de 5 logements entamée est comptée : lecture la plus stricte)"
    return s


FACT_SHORT = {
    "within_500m_station": "terrain à moins de 500 m d'une gare", "avg_dwelling_sdp_m2": "surface de plancher moyenne par logement (m²)",
    "n_dwellings": "nombre de logements", "total_sdp_m2": "surface de plancher totale (m²)",
    "is_group_or_lotissement": "groupe de constructions ou lotissement", "multiple_uses": "plusieurs usages",
    "n_f1_f2_dwellings": "nombre de logements T1/T2", "n_larger_dwellings": "nombre de logements T3 ou plus",
    "required_places": "nombre de places exigé", "plot_area_m2": "surface du terrain (m²)",
    "building_footprint_m2": "emprise au sol (m²)", "pleine_terre_m2": "surface de pleine terre (m²)",
    "in_ecological_corridor": "terrain dans le corridor écologique",
}
OP_FR = {"==": "=", "!=": "≠", "<": "<", "<=": "≤", ">": ">", ">=": "≥"}


def _val(v):
    if v is True: return "oui"
    if v is False: return "non"
    if v is None: return "inconnu"
    return f"{v:g}".replace(".", ",") if isinstance(v, (int, float)) else str(v)


def rule_lines_fr(r):
    """Explication de la cellule 18 en français, reconstruite à partir des tests (pas du texte anglais du modèle)."""
    out = []
    if r.get("guard_fail"):
        out.append("⛔ cette règle n'a pas passé les garde-fous (citation ou nombre absent du texte du PDF) : à vérifier sur le PDF")
    for t in r.get("tests", []):
        name = FACT_SHORT.get(t["fact"], t["fact"])
        cond = f"{name} = oui" if t["op"] == "is_true" else f"{name} = non" if t["op"] == "is_false" else f"{name} {OP_FR.get(t['op'], t['op'])} {_val(t['value'])}"
        mark = {True: "✓", False: "✗", None: "?"}[t["result"]]
        out.append(f"{mark} condition : {cond} — votre projet : {_val(t['project'])}")
    for _ in r.get("other_facts", []):
        out.append("? condition qui demande une donnée que le questionnaire ne collecte pas : voir la citation")
    if r.get("untested"):
        out.append("? condition écrite dans le PLU que le programme ne peut pas tester : voir la citation")
    if r.get("note"):
        out.append(note_fr(r["note"]))
    return out


def quote_label(r, n=110):
    q = " ".join(((r.get("source") or {}).get("extract") or r.get("summary") or "").split())
    return f"« {q[:n]}{'…' if len(q) > n else ''} »"
