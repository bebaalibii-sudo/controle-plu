# CELL 32 | Module 5 | Jury interface (Gradio), in French: project form -> preliminary compliance report with article, page and quote
import io, json, glob, os, re, contextlib, builtins
try: import gradio as gr
except ImportError:
    get_ipython().system("pip install -q gradio"); import gradio as gr

assert all(n in globals() for n in ("FORM", "EXTRACTED", "PROJECT")), "Run the runner (CELL 23) first: the interface uses its results."

# ---- the program's own cells (CELL 18 = which rules apply, CELL 29 = compliance report), read from the saved notebook ----
nb_path = max(glob.glob("/content/drive/MyDrive/Colab Notebooks/*.ipynb"), key=os.path.getmtime)
nb_code = ["".join(c["source"]) for c in json.load(open(nb_path, encoding="utf-8"))["cells"] if c["cell_type"] == "code"]
SRC18 = next((s for s in nb_code if "Which rules apply to MY project" in s[:400] and "Jury interface" not in s), None)
SRC29 = next((s for s in nb_code if "def pick(param" in s and "THE REPORT" in s and "Jury interface" not in s and "Scenario tests" not in s), None)
assert SRC18 and SRC29, "CELL 18 or CELL 29 was not found in the saved notebook (press Ctrl+S, then run this cell again)."

OK, NOK = "Conforme selon la règle structurée", "Non-conformité potentielle"
REVIEW, MISSING, NOTFOUND = "Interprétation requise", "Données insuffisantes", "Règle non retrouvée"
INFO = "Retenue, non comparée automatiquement"
ICON = {OK: "✅", NOK: "❌", REVIEW: "⚠️", MISSING: "⚠️", NOTFOUND: "⚠️", INFO: "ℹ️"}
PDF_OFFSET = 40            # this PLU: printed page = PDF page + 40
clean = lambda t: str(t).replace("|", "/").replace("\n", " ")

# ---------------- French labels of the form ----------------
SECTIONS_FR = {"GENERAL": "GÉNÉRAL", "UB.6  IMPLANTATION RELATIVE TO ROADS": "UB.6 — IMPLANTATION PAR RAPPORT AUX VOIES",
               "UB.7  NEIGHBOURING BOUNDARIES": "UB.7 — LIMITES SÉPARATIVES", "UB.9  FOOTPRINT AND OPEN GROUND": "UB.9 — EMPRISE AU SOL ET PLEINE TERRE",
               "UB.10 HEIGHT AND LEVELS": "UB.10 — HAUTEUR ET NIVEAUX", "UB.12 PARKING": "UB.12 — STATIONNEMENT",
               "UB.13 OPEN SPACES AND PLANTING": "UB.13 — ESPACES LIBRES ET PLANTATIONS"}
LABELS_FR = {
 "new_construction": "Les travaux constituent-ils une CONSTRUCTION NEUVE (et non la modification d'un bâtiment existant, une amélioration thermique, une reconstruction après sinistre, des travaux techniques ou un bâtiment de service public) ?",
 "dist_road_m": "Distance entre la construction et l'alignement de la voie (ou la limite de la voie privée)",
 "borders_halage": "Le terrain borde-t-il le chemin de Halage ?", "dist_halage_m": "Distance entre la construction et l'alignement du chemin de Halage",
 "borders_ru": "Le terrain borde-t-il le ru ?", "dist_ru_m": "Distance entre la construction et les berges du ru",
 "near_railway": "Le terrain est-il proche d'une voie ferrée ?", "dist_rail_m": "Distance entre la construction et le rail le plus proche",
 "plot_area_m2": "Surface totale du terrain (parcelle)", "building_footprint_m2": "Emprise au sol des constructions",
 "pleine_terre_m2": "Surface conservée en pleine terre", "slope_facing_oise": "Le terrain est-il en pente face à l'Oise ?",
 "roof_pitched": "La construction a-t-elle une TOITURE À PENTES ?", "height_ridge_m": "Hauteur au faîtage",
 "floors_above_ground_roof_pitched": "Outre le rez-de-chaussée (R), combien d'autres niveaux complets (le n de R+n) ? Ne pas compter le dernier niveau situé dans la toiture",
 "attic_roof_pitched": "Le dernier niveau est-il des combles ou un attique ?",
 "roof_flat": "La construction a-t-elle une TOITURE-TERRASSE ?", "height_acroterion_m": "Hauteur à l'acrotère",
 "floors_above_ground_roof_flat": "Outre le rez-de-chaussée (R), combien d'autres niveaux complets (le n de R+n) ?",
 "avg_dwelling_sdp_m2": "Surface de plancher moyenne PAR LOGEMENT", "within_500m_station": "Le terrain est-il à moins de 500 m d'une gare ?",
 "n_dwellings": "Nombre de logements du projet", "is_group_or_lotissement": "Le projet est-il un groupe de constructions ou un lotissement ?",
 "total_sdp_m2": "Surface de plancher TOTALE de l'opération (tous les logements)", "n_f1_f2_dwellings": "Combien de logements sont de type T1 ou T2 ?",
 "n_larger_dwellings": "Combien de logements sont plus grands que T2 (T3 ou plus) ?",
 "multiple_uses": "La construction a-t-elle plusieurs usages (logement avec commerces, bureaux ou activités) ?",
 "places_provided": "Nombre de places de stationnement prévues par le projet", "bicycle_space_m2": "Surface réservée aux deux-roues non motorisés (local vélos)",
 "in_ecological_corridor": "Le terrain est-il dans le périmètre du corridor écologique du boulevard du Général de Gaulle ?",
 "corridor_strip_kept": "Une bande de 5 m depuis la limite parcellaire est-elle conservée en pleine terre et plantée d'espèces locales ?"}
for _t, _n in (("lateral_boundary_1", "LIMITE LATÉRALE 1"), ("lateral_boundary_2", "LIMITE LATÉRALE 2"), ("rear_boundary", "LIMITE DE FOND")):
    LABELS_FR.update({f"{_t}_exists": f"{_n} : y a-t-il une limite séparative à vérifier ici ?",
                      f"{_t}_on": "La construction est-elle SUR cette limite (en contact) ?",
                      f"{_t}_openings": "La façade face à cette limite comporte-t-elle des ouvertures (baies) ?",
                      f"{_t}_L": "Distance entre la construction et cette limite (L)",
                      f"{_t}_HT": "Hauteur de la construction sur cette limite, depuis le terrain naturel (HT)"})

# ---------------- French wording of the report ----------------
NAMES_FR = {"Setback from public/private roads": "Recul par rapport aux voies publiques ou privées", "Setback from the chemin de Halage": "Recul par rapport au chemin de Halage",
            "Setback from the stream (ru)": "Recul par rapport au ru", "Distance from the railway": "Distance par rapport à la voie ferrée",
            "Building footprint (CES)": "Emprise au sol (CES)", "Number of parking places": "Nombre de places de stationnement",
            "Open ground (pleine terre)": "Espaces de pleine terre", "5 m strip along the ecological corridor": "Bande de 5 m le long du corridor écologique"}
def name_fr(x):
    n = x["name"]
    if n in NAMES_FR: return NAMES_FR[n]
    m = re.match(r"Position relative to the (lateral boundary (\d)|rear boundary)", n)
    if m: return f"Position par rapport à la limite séparative latérale {m.group(2)}" if m.group(2) else "Position par rapport à la limite séparative de fond"
    m = re.match(r"(Maximum height|Number of levels) \((flat|pitched) roof\)", n)
    if m: return ("Hauteur maximale" if m.group(1) == "Maximum height" else "Nombre de niveaux") + (" (toiture-terrasse)" if m.group(2) == "flat" else " (toiture à pentes)")
    if n.startswith("Other parking rule"): return "Autre règle de stationnement : « " + " ".join(str(x["quote"]).split())[:70] + "… »"
    return n

DETAIL_FR = [("required at least", "exigé : au moins"), ("required at most", "exigé : au plus"), ("required margin", "marge exigée"), ("required:", "exigé :"),
             ("minimum ", "minimum "), ("project L", "projet L"), ("project:", "projet :"), ("provided:", "prévu :"), ("allowed:", "autorisé :"),
             ("unknown", "inconnu"), ("of the unbuilt area", "de la surface non bâtie"), ("(footprint / plot area)", "(emprise / surface du terrain)"),
             ("(calculated from the retained rules)", "(calculé à partir des règles retenues)"), ("combles/attique", "combles/attique"),
             ("building on the boundary: allowed only if the facade has no openings", "construction sur la limite : autorisée seulement si la façade n'a pas d'ouvertures (baies)"),
             ("building on the rear boundary: the margins d'isolement must be respected", "construction sur la limite de fond : les marges d'isolement doivent être respectées"),
             ("the margin formula could not be read from the rule", "la formule de la marge n'a pas pu être lue dans la règle"),
             ("the number of levels could not be read from the rule", "le nombre de niveaux n'a pas pu être lu dans la règle"),
             ("a value is missing", "une valeur manque"), ("plot area or footprint missing", "surface du terrain ou emprise manquante"),
             ("plot area, footprint or pleine terre area missing", "surface du terrain, emprise ou pleine terre manquante"),
             ("inconsistent areas: check the numbers", "surfaces incohérentes : vérifier les chiffres"),
             ("required places not calculated (run the Fact-Test Evaluator) or places provided missing", "nombre de places exigé non calculé ou nombre de places prévu manquant"),
             ("retained for your project but not compared automatically: check on the drawings", "retenue pour votre projet mais non comparée automatiquement : à vérifier sur les plans"),
             ("retained for your project but not compared automatically", "retenue pour votre projet mais non comparée automatiquement"),
             ("no usable rule in the extraction", "aucune règle exploitable dans l'extraction"),
             ("applies only inside the ecological corridor perimeter", "s'applique seulement dans le périmètre du corridor écologique")]
def detail_fr(t):
    t = str(t).replace(" | ", " ; ").replace("|", ";").replace("\n", " ")
    for en, fr in DETAIL_FR: t = t.replace(en, fr)
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    return t

NOTES_FR = [("Assumption: the extract does not state the denominator", "Hypothèse : l'extrait ne précise pas le dénominateur ; la surface totale du terrain est utilisée."),
            ("Assumption: unbuilt area", "Hypothèse : surface non bâtie = surface du terrain − emprise (accès et terrasses non déduits)."),
            ("Required places follow the 'stricter' policy", "Le nombre de places suit la lecture la plus stricte (arrondi supérieur, tranche de visiteurs incomplète comptée)."),
            ("Sloping land facing the Oise", "Terrain en pente face à l'Oise : les hauteurs se mesurent depuis un point médian défini dans une annexe absente du document."),
            ("The regulatory heights must be respected", "Les hauteurs réglementaires doivent être respectées en tout point de la construction."),
            ("New buildings on a shared boundary", "Une construction neuve sur limite mitoyenne doit s'inscrire dans l'épannelage des bâtiments existants."),
            ("No rules fixed for technical structures", "Pas de règle fixée pour certains ouvrages techniques, équipements d'intérêt collectif, reconstructions après sinistre et extensions (voir l'article 9.3).")]
GENERIC_NOTE = "Autres exceptions ou conditions signalées dans l'article cité : à vérifier dans le PDF."
def notes_fr(notes):
    out = []
    for n in notes:
        m = re.match(r"Rules (\[.*?\]) are still undecided", n)
        if m: fr = f"Les règles {m.group(1)} restent à décider et pourraient augmenter le nombre de places exigé."
        else: fr = next((f for k, f in NOTES_FR if n.startswith(k)), GENERIC_NOTE)
        if fr not in out: out.append(fr)
    return out

def where_fr(w):
    m = re.match(r"(UB\.\d+)(?: sub-item (.+?), printed p\.\[(.*?)\])?$", str(w))
    if not m: return clean(w)
    art, sub, pg = m.groups()
    if not sub: return f"Article {art}"
    sub = sub.replace("table, housing row", "tableau, ligne « logement »").replace("preamble", "préambule")
    nums = sorted({int(p) for p in re.findall(r"\d+", pg or "")})
    span = lambda L: f"{L[0]}" if L[0] == L[-1] else f"{L[0]}–{L[-1]}"
    pages = f", page(s) imprimée(s) {span(nums)} (page(s) PDF {span([p - PDF_OFFSET for p in nums])})" if nums else ""
    return f"Article {art}, alinéa {sub}{pages}"

def render(results):
    n = lambda sts: sum(x["status"] in sts for x in results)
    md = [f"## Rapport préliminaire de conformité\n**{n([OK])} conforme(s) · {n([NOK])} non-conformité(s) potentielle(s) · {n([REVIEW, MISSING, NOTFOUND])} à vérifier**\n",
          "| # | Article | Vérification | Résultat |", "|---|---|---|---|"]
    for i, x in enumerate(results, 1):
        md.append(f"| {i} | {x['article']} | {clean(name_fr(x))[:90]} | {ICON.get(x['status'], '')} {x['status']} |")
    groups = [("❌ Non-conformité potentielle", [NOK]), ("⚠️ À vérifier (interprétation requise, donnée manquante ou règle non retrouvée)", [REVIEW, MISSING, NOTFOUND]),
              ("✅ Conforme selon la règle structurée", [OK]), ("ℹ️ Règles retenues mais non comparées automatiquement", [INFO])]
    for title, sts in groups:
        items = [x for x in results if x["status"] in sts]
        if not items: continue
        md.append(f"\n### {title}")
        for x in items:
            md.append(f"\n**{x['article']} — {clean(name_fr(x))}**  \n{x['status']}" + (f" · {detail_fr(x['detail'])}" if x["detail"] else ""))
            md.append(f"  \n*Où vérifier :* {where_fr(x['where'])}")
            if x["status"] != OK and x["quote"]: md.append(f"  \n> {clean(x['quote'])}")
            for note in notes_fr(x["notes"]): md.append(f"  \n- À vérifier : {note}")
    md.append("\n---\n*Vérification préliminaire uniquement. Le modèle de langage ne décide jamais de la conformité : les règles sont extraites du texte du PLU avec des citations mot pour mot, et la comparaison est faite par du code. Vérifiez chaque point sur le PDF.*")
    return "\n".join(md)

def run_check(*values):
    for (section, fact, kind, label, cond), v in zip(FORM, values):
        if kind == "yn": PROJECT[fact] = {"oui": True, "non": False}.get(v)
        else: PROJECT[fact] = None if v in (None, "") else float(v)
    log, old_input = io.StringIO(), builtins.input
    builtins.input = lambda prompt="": ""                      # Enter = accept the program's proposal
    try:
        with contextlib.redirect_stdout(log):
            exec(SRC18, globals())
            exec(SRC29, globals())
    except Exception as e:
        return f"**Erreur pendant la vérification :** {e}", None
    finally:
        builtins.input = old_input
    return render(RESULTS), "compliance_report.json"

# ---- the page ----
with gr.Blocks(title="Vérification préliminaire de conformité au PLU") as demo:
    gr.Markdown(f"# Vérification préliminaire de conformité au PLU — Éragny-sur-Oise, zone {PROJECT.get('sector', 'UB')}\n"
                f"Type de construction : {'; '.join(PROJECT.get('building_labels', []))}. Renseignez le projet puis appuyez sur le bouton. Laissez « inconnu » ou le champ vide si vous ne savez pas.")
    with gr.Tabs() as tabs:
        with gr.Tab("1. Données du projet", id="form"):
            fields, last = [], None
            for section, fact, kind, label, cond in FORM:
                if section != last:
                    gr.Markdown(f"### {SECTIONS_FR.get(section, section)}"); last = section
                text = LABELS_FR.get(fact, label.strip()) + (" (seulement si applicable)" if cond is not None else "")
                cur = PROJECT.get(fact)
                if kind == "yn":
                    fields.append(gr.Radio(["inconnu", "oui", "non"], value={True: "oui", False: "non"}.get(cur, "inconnu"), label=text))
                else:
                    fields.append(gr.Number(value=cur, label=text + {"m": " [m]", "m2": " [m²]", "n": ""}[kind]))
            go = gr.Button("Lancer la vérification de conformité", variant="primary")
        with gr.Tab("2. Rapport de conformité", id="report"):
            report = gr.Markdown("Renseignez le formulaire puis appuyez sur *Lancer la vérification de conformité*.")
            file_out = gr.File(label="Télécharger le rapport (JSON)")
    ev = go.click(run_check, inputs=fields, outputs=[report, file_out])
    try: ev.then(lambda: gr.Tabs(selected="report"), None, tabs)
    except Exception: pass

demo.launch(share=True, debug=False)