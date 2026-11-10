"""Vérification préliminaire de conformité au PLU — application Streamlit (prototype MBA).

Parcours : 1. Document PLU  ->  2. Projet  ->  3. Règles  ->  4. Questionnaire  ->  5. Rapport
Mode hybride : le règlement de la zone UB d'Éragny-sur-Oise est reconnu par son empreinte et utilise les
règles vérifiées ; tout autre PDF passe par le pipeline complet (OCR, découpage, recherche sémantique, Gemini, garde-fous).
"""
import json, os
import streamlit as st

import engine
import fr

st.set_page_config(page_title="Conformité PLU – prototype", page_icon="🏠", layout="wide")

STEPS = ["1. Document PLU", "2. Projet", "3. Règles du PLU", "4. Questionnaire", "5. Rapport"]
S = st.session_state
for k, v in {"step": STEPS[0], "ans": {}, "overrides": {}}.items():
    S.setdefault(k, v)
if "_goto" in S:
    S.step = S.pop("_goto")

REF = engine.REFERENCE
TYPE_CODES = list(fr.TYPES_FR)


def go(step):
    S._goto = step            # appliqué au début de l'exécution suivante (le widget « step » existe déjà)


def reset_from(level):
    """Efface ce qui dépend d'une étape modifiée."""
    keys = {"doc": ["doc", "pages", "chunks", "rules", "rules_key", "results", "analysis", "final_project", "live_log", "live_failed"],
            "rules": ["rules", "rules_key", "results", "analysis", "final_project", "live_log", "live_failed"],
            "results": ["results", "analysis", "final_project"]}[level]
    for k in keys:
        S.pop(k, None)


def gemini_key():
    try:
        k = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        k = None
    return k or os.environ.get("GEMINI_API_KEY") or S.get("user_key")


def embedder():
    """bge-m3 si le serveur l'a installé (Colab, machine locale), sinon les plongements Gemini (Streamlit Community Cloud)."""
    try:
        import sentence_transformers  # noqa: F401
        return _bge()
    except ImportError:
        return engine.GeminiEmbedder(gemini_key())


@st.cache_resource(show_spinner="Chargement du modèle de plongements bge-m3 (environ 2 Go, la première fois seulement)…")
def _bge():
    return engine.load_embedder()


# ------------------------------------------------------------------------------------------------
# Barre latérale
# ------------------------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Vérification préliminaire de conformité au PLU")
    st.radio("Étapes", STEPS, key="step", label_visibility="collapsed")
    st.divider()
    doc = S.get("doc")
    if doc:
        st.caption(f"**Document :** {doc['name']}")
        st.caption(f"Zone {doc['zone']} · {doc['commune']}")
        st.caption("Règles vérifiées disponibles (secteur UB)" if doc["reference"] else "Nouveau document : règles extraites en direct, non vérifiées")
    if S.get("profile"):
        st.caption(f"**Secteur :** {S.profile['sector']} · {', '.join(fr.TYPES_FR[t] for t in S.profile['building_types'])}")
    if S.get("rules_key"):
        st.caption("**Règles :** " + ("vérifiées" if S.rules_key[0] == "verified" else "extraites en direct (à vérifier)"))
    st.divider()
    st.caption("Le modèle de langage lit le PLU et cite ses sources ; il ne décide jamais de la conformité. "
               "L'applicabilité et la conformité sont calculées par du code. Résultat préliminaire : à vérifier sur le PDF.")


# ------------------------------------------------------------------------------------------------
# 1. Document
# ------------------------------------------------------------------------------------------------
def step_document():
    st.header("1. Importer le règlement du PLU")
    st.write("Importez le PDF du règlement de la zone (pièce écrite du PLU). Les données du projet ne sont jamais envoyées au modèle de langage : "
             "seul le texte du PLU l'est, et seulement pour un nouveau document.")
    up = st.file_uploader("Règlement du PLU (PDF)", type=["pdf"])
    if up is not None:
        data = up.getvalue()
        fp = engine.fingerprint(data)
        if not S.get("doc") or S.doc["sha256"] != fp:
            reset_from("doc")
            for k in [k for k in S.keys() if str(k).startswith("sectors_")]:
                del S[k]
            ref = fp == REF["sha256"]
            S.pdf = data
            S.doc = {"name": up.name, "sha256": fp, "reference": ref,
                     "zone": REF["zone"] if ref else None, "commune": REF["commune"] if ref else "à détecter",
                     "offset": REF["printed_page_offset"] if ref else None,
                     "sectors": REF["sectors"] if ref else None}
    doc = S.get("doc")
    if not doc:
        st.info("Aucun document pour l'instant.")
        return
    if doc["reference"]:
        st.success(f"**Document reconnu :** règlement de la zone UB d'{REF['commune']} ({REF['n_pages']} pages). "
                   "Les règles extraites et vérifiées pendant le projet sont disponibles pour le **secteur UB** : aucune attente, aucun appel au modèle.")
    else:
        st.warning("**Nouveau document.** Le pipeline complet sera lancé à l'étape 3 : lecture OCR, découpage par article, recherche sémantique "
                   "et extraction des 7 paramètres par Gemini avec garde-fous. Compter **5 à 10 minutes**. "
                   "Si le PDF contient plusieurs zones, vous choisirez la vôtre à l'étape 2. "
                   "Les règles obtenues **ne sont pas vérifiées par une personne**.")
        st.caption("Le prototype lit les règlements à articles numérotés (« ARTICLE UA.6 », « Article UBa 6 », « Art. UEV/ 6 »…). "
                   "Un PLU organisé autrement (chapitres, sections, sans articles 1 à 14) est signalé.")
    st.button("Continuer : le projet →", type="primary", on_click=go, args=(STEPS[1],))


# ------------------------------------------------------------------------------------------------
# 2. Projet (cellule 9)
# ------------------------------------------------------------------------------------------------
def step_project():
    st.header("2. Le projet")
    doc = S.get("doc")
    if not doc:
        st.info("Importez d'abord le règlement (étape 1)."); return
    if doc["reference"]:
        zone, sectors = doc["zone"], doc["sectors"]
    else:
        ensure_ocr()
        doc = S.doc
        zones = [z for z, _ in doc["zones"]]
        if len(zones) > 1:
            st.info(f"Ce règlement contient {len(zones)} zones. Choisissez celle de la parcelle.")
            zone = st.selectbox("Zone du PLU", zones, index=zones.index(doc["zone"]) if doc["zone"] in zones else 0,
                                format_func=lambda z: f"Zone {z} ({dict(doc['zones'])[z]} articles)")
            if zone != doc["zone"]:
                doc["zone"] = zone; S.doc = doc; S.pop("profile", None); reset_from("rules")
        zone = doc["zone"]
        with st.spinner(f"Découpage de la zone {zone}…"):
            sectors = zone_sectors(zone)
    old = S.get("profile") or {"sector": zone, "building_types": ["logement"]}
    opts = [zone] + [s for s in sectors if s != zone]
    with st.form("profile_form"):
        sector = st.selectbox(f"Secteur de la parcelle (zone {zone})", opts, index=opts.index(old["sector"]) if old["sector"] in opts else 0,
                              format_func=lambda s: f"{s} (pas de sous-secteur)" if s == zone else s)
        types = st.multiselect("Type(s) de construction", TYPE_CODES, default=old["building_types"], format_func=lambda c: fr.TYPES_FR[c])
        ok = st.form_submit_button("Enregistrer le projet", type="primary")
    if ok:
        types = types or ["logement"]
        new = {"sector": sector, "building_types": types, "building_labels": [fr.TYPES_FR[t] for t in types]}
        if new != S.get("profile"):
            S.profile = new
            reset_from("results")
        go(STEPS[2]); st.rerun()
    if S.get("profile"):
        st.caption(f"Projet enregistré : secteur {S.profile['sector']} · {', '.join(S.profile['building_labels'])}")


# ------------------------------------------------------------------------------------------------
# 3. Règles : vérifiées ou extraites en direct
# ------------------------------------------------------------------------------------------------
def needs_live():
    p, doc = S.profile, S.doc
    return not (doc["reference"] and p["sector"] == REF["verified_sector"] and p["building_types"] == ["logement"])


def ensure_ocr():
    """OCR du nouveau document (une fois), détection des zones et du décalage de pages."""
    doc = S.doc
    if S.get("pages") is None:
        st.write("Le document doit d'abord être lu (OCR si nécessaire) pour connaître ses zones et ses secteurs.")
        if not st.button("Lire le document", type="primary"):
            st.stop()
        bar = st.progress(0.0, text="Lecture du document…")
        pages = engine.ocr_pdf(S.pdf, progress=lambda i, n: bar.progress(i / n, text=f"Lecture : page {i} / {n}"))
        S.pages = pages
        doc["zones"] = engine.detect_zones(pages)
        if not doc["reference"]:
            doc["commune"] = engine.detect_commune(pages)
            doc["offset"] = engine.detect_offset(pages)
        doc["zone"] = REF["zone"] if doc["reference"] else (doc["zones"][0][0] if doc["zones"] else None)
        S.doc = doc
        st.rerun()
    if not doc.get("zones") and not doc["reference"]:
        st.error("Aucun titre d'article numéroté n'a été trouvé (du type « ARTICLE UA.6 - … », « Article UBa 6 – … » ou « Art. UEV/ 6 - … »). "
                 "Ce règlement est organisé autrement (chapitres, sections) : il n'est pas encore pris en charge par le prototype.")
        st.stop()


def zone_sectors(zone):
    """Découpage de la zone choisie (une fois par zone) pour lire ses secteurs."""
    key = f"sectors_{zone}"
    if key not in S:
        try:
            chunks, _ = engine.chunk_pages([dict(p) for p in S.pages], zone, S.doc["offset"] or 0, S.doc["commune"], S.doc["name"])
        except engine.PipelineError as e:
            st.error(str(e)); st.stop()
        S[key] = sorted({x for c in chunks for x in c["sectors_mentioned"]})
    return S[key]


def step_rules():
    st.header("3. Les règles du PLU")
    if not S.get("doc") or not S.get("profile"):
        st.info("Complétez d'abord les étapes 1 et 2."); return
    doc, prof = S.doc, S.profile
    live = needs_live()
    key = ("live" if live else "verified", prof["sector"], tuple(prof["building_types"]))
    if S.get("rules_key") not in (None, key):
        reset_from("rules")
    if not live:
        if S.get("rules") is None:
            S.rules = engine.verified_rules(); S.rules_key = key
        st.success("Règles **vérifiées** du secteur UB (extraites par Gemini avec garde-fous, puis contrôlées pendant le projet).")
    else:
        if doc["reference"]:
            st.warning(f"Les règles vérifiées ne concernent que le **secteur UB** et le **logement**. Pour le secteur **{prof['sector']}** "
                       f"et/ou ces types de construction, une extraction en direct est nécessaire. Ses règles ne sont pas vérifiées par une personne.")
        if S.get("rules") is None:
            run_live(key)
            return
        st.warning("Règles **extraites en direct** : chaque citation a passé les garde-fous automatiques, mais aucune personne ne les a vérifiées.")
        failed = S.get("live_failed") or []
        for p, err in failed:
            st.error(f"{fr.PARAM_FR.get(p, p)} : extraction impossible ({err}). Ce paramètre sera « Règle non retrouvée ».")
        if failed:
            st.caption("Souvent dû au quota gratuit de Gemini (« 429 », « quota », « busy ») : attendez une minute ou deux, puis relancez.")
            if st.button("Relancer l'extraction des paramètres en échec", type="primary"):
                retry_failed([p for p, _ in failed]); st.rerun()
    show_rules(S.rules, doc["offset"])
    c1, c2 = st.columns([1, 3])
    c1.button("Continuer : le questionnaire →", type="primary", on_click=go, args=(STEPS[3],))
    c2.download_button("Télécharger les règles (JSON)", json.dumps(S.rules, ensure_ascii=False, indent=1), "regles_plu.json", "application/json")


def run_live(key):
    doc, prof = S.doc, S.profile
    if S.get("pages") is None:
        ensure_ocr()
    st.subheader("Extraction en direct")
    c1, c2 = st.columns(2)
    zone = c1.text_input("Préfixe de zone lu dans les titres d'articles", doc["zone"], disabled=True)
    offset = c2.number_input("Décalage de pagination (page imprimée − page PDF)", value=int(doc["offset"] or 0), step=1,
                             help="Sert à donner la page imprimée du règlement. Pour Éragny UB : 40 (page PDF 11 = page 51).")
    if not gemini_key():
        st.text_input("Clé API Gemini (Google AI Studio)", type="password", key="user_key",
                      help="Gardée en mémoire pendant la session seulement. Le texte du PLU est envoyé à Gemini, jamais les données du projet.")
    if not st.button("Extraire les règles (5 à 10 minutes)", type="primary", disabled=not gemini_key()):
        return
    try:
        with st.status("Analyse du document…", expanded=True) as box:
            st.write("Découpage par article et sous-article…")
            chunks, _ = engine.chunk_pages([dict(p) for p in S.pages], zone, int(offset), doc["commune"], doc["name"])
            doc["offset"] = int(offset); S.doc = doc
            st.write(f"{len(chunks)} passages, {len({c['article_number'] for c in chunks if c['article_number']})} articles.")
            st.write("Recherche sémantique : calcul des plongements des passages…")
            model = embedder()
            try:
                E = engine.embed_chunks(model, chunks)
            except engine.PipelineError as e:
                st.warning("Plongements Gemini indisponibles (" + str(e)[:120] + "). La recherche se fait par mots-clés "
                           "(TF-IDF) : moins fine, mais l'extraction peut continuer.")
                model = engine.KeywordEmbedder()
                E = engine.embed_chunks(model, chunks)
            S.search_mode = getattr(model, "name", "")
            st.write("Extraction des 7 paramètres par Gemini (le service gratuit est parfois saturé : l'application patiente et réessaie)…")
            bar = st.progress(0.0)
            use_manual = doc["reference"] and any(c["chunk_id"] == "UB.12#preamble" for c in chunks)
            rules, log, failed = engine.extract_live(
                chunks, E, model, zone, prof, gemini_key(), use_manual,
                progress=lambda i, n, p: bar.progress(i / n, text=(f"Paramètre {i + 1} / {n} : {fr.PARAM_FR.get(p, p)}" if p else "Terminé")))
            box.update(label="Analyse terminée", state="complete")
    except engine.PipelineError as e:
        st.error(str(e)); return
    S.rules, S.rules_key, S.live_log, S.live_failed = rules, key, log, failed
    reset_from("results")
    st.rerun()


def retry_failed(params):
    """Relance Gemini seulement pour les paramètres en échec ; les autres règles sont gardées."""
    doc, prof = S.doc, S.profile
    with st.status("Nouvel essai d'extraction…", expanded=True) as box:
        chunks, _ = engine.chunk_pages([dict(p) for p in S.pages], doc["zone"], int(doc["offset"] or 0), doc["commune"], doc["name"])
        model = embedder()
        try:
            E = engine.embed_chunks(model, chunks)
        except engine.PipelineError:
            model = engine.KeywordEmbedder(); E = engine.embed_chunks(model, chunks)
        bar = st.progress(0.0)
        use_manual = doc["reference"] and any(c["chunk_id"] == "UB.12#preamble" for c in chunks)
        rules, log, failed = engine.extract_live(chunks, E, model, doc["zone"], prof, gemini_key(), use_manual, params=params,
            progress=lambda i, n, p: bar.progress(i / n, text=(f"Paramètre {i + 1} / {n} : {fr.PARAM_FR.get(p, p)}" if p else "Terminé")))
        box.update(label="Essai terminé", state="complete")
    merged = dict(S.rules); merged.update(rules)
    S.rules, S.live_failed = merged, failed
    reset_from("results")


def show_rules(rules, offset):
    rows = []
    for p in engine.PARAMS:
        v = rules.get(p)
        n_err = sum(any(i.startswith("ERROR") for i in r["guardrail_issues"]) for r in v["rules"]) if v else 0
        rows.append({"Paramètre": fr.PARAM_FR[p], "Statut": {"reglemente": "réglementé", "non_reglemente": "non réglementé",
                     "non_retrouve": "non retrouvé"}.get(v["status"], v["status"]) if v else "non extrait",
                     "Règles": len(v["rules"]) if v else 0, "Règles écartées (garde-fous)": n_err})
    st.dataframe(rows, hide_index=True, width="stretch")
    with st.expander("Voir chaque règle avec sa citation"):
        for p in engine.PARAMS:
            v = rules.get(p)
            if not v:
                continue
            st.markdown(f"**{fr.PARAM_FR[p]}**")
            for k, r in enumerate(v["rules"], 1):
                s = (r.get("sources") or [{}])[0]
                bad = any(i.startswith("ERROR") for i in r["guardrail_issues"])
                pages = s.get("printed_pages") or []
                st.markdown(f"{k}. {'⛔ ' if bad else ''}« {s.get('extract', '')} »  \n"
                            f"   *{s.get('article', '?')}" + (f", alinéa {s['sub_item']}" if str(s.get('sub_item') or '')[:1].isdigit() else "")
                            + f", page(s) imprimée(s) {', '.join(map(str, pages)) or '?'}*")
                if bad:
                    st.caption("   Écartée par les garde-fous : une citation ou un nombre n'a pas été retrouvé dans le texte du PDF.")


# ------------------------------------------------------------------------------------------------
# 4. Questionnaire (cellule 28) + vérification de l'applicabilité (cellule 18)
# ------------------------------------------------------------------------------------------------
TEST_PROJECT = dict(  # projet de test « tout conforme » de la cellule 31 (3 logements de 58 m²)
    new_construction=True, dist_road_m=5.0, borders_halage=False, borders_ru=False, near_railway=False,
    lateral_boundary_1_exists=True, lateral_boundary_1_on=True, lateral_boundary_1_openings=False, lateral_boundary_2_exists=False,
    rear_boundary_exists=True, rear_boundary_on=False, rear_boundary_openings=True, rear_boundary_L=5.0, rear_boundary_HT=6.0,
    plot_area_m2=1000.0, building_footprint_m2=400.0, pleine_terre_m2=400.0, slope_facing_oise=False, roof_pitched=False,
    roof_flat=True, height_acroterion_m=7.0, floors_above_ground_roof_flat=1, avg_dwelling_sdp_m2=58.0, within_500m_station=True,
    n_dwellings=3, is_group_or_lotissement=False, total_sdp_m2=174.0, n_f1_f2_dwellings=1, n_larger_dwellings=2,
    multiple_uses=False, places_provided=3, in_ecological_corridor=False)


def fill_test():
    for f, v in TEST_PROJECT.items():
        S[f"f_{f}"] = {True: "oui", False: "non"}.get(v, v) if isinstance(v, bool) else v
    reset_from("results")


def clear_form():
    for k in [k for k in S.keys() if str(k).startswith("f_")]:
        del S[k]
    reset_from("results")


def value_of(fact, kind):
    v = S.get(f"f_{fact}")
    if kind == "yn":
        return {"oui": True, "non": False}.get(v)
    return None if v is None else float(v)


def step_form():
    st.header("4. Questionnaire du projet")
    if S.get("rules") is None:
        st.info("Les règles du PLU doivent d'abord être disponibles (étape 3)."); return
    zone = S.doc["zone"]
    form = engine.form_definition()
    drop = engine.relevant_facts(S.rules, S.doc["reference"]) or set()
    c1, c2, _ = st.columns([1, 1, 2])
    c1.button("Remplir avec le projet test", on_click=fill_test, help="Le projet « tout conforme » des tests de scénarios (3 logements de 58 m²).")
    c2.button("Tout effacer", on_click=clear_form)
    st.caption("Laissez « inconnu » ou le champ vide si vous ne savez pas : le rapport indiquera « Données insuffisantes » au lieu de deviner.")
    get = lambda f: value_of(f, next((k for _, ff, k, _, _ in form if ff == f), "m"))
    last = None
    for section, fact, kind, label, cond in form:
        if fact in drop or (cond is not None and not cond(get)):
            continue
        if section != last:
            st.subheader(fr.section_fr(section, zone)); last = section
        text = fr.LABELS_FR.get(fact, label.strip())
        k = f"f_{fact}"
        if kind == "yn":
            S.setdefault(k, "inconnu")
            st.radio(text, ["inconnu", "oui", "non"], key=k, horizontal=True)
        else:
            unit = {"m": "m", "m2": "m²", "n": ""}[kind]
            if k in S and S[k] is not None:
                S[k] = float(S[k])
            extra = {} if k in S else {"value": None}
            st.number_input(text + (f" ({unit})" if unit else ""), min_value=0.0, step=1.0 if kind == "n" else 0.5,
                            format="%g" if kind != "n" else "%.0f", key=k, **extra)
    st.divider()
    if st.button("Lancer la vérification de conformité", type="primary"):
        S.overrides = {}
        run_check()
        go(STEPS[4]); st.rerun()


def project_values():
    form = engine.form_definition()
    drop = engine.relevant_facts(S.rules, S.doc["reference"]) or set()
    P = dict(S.profile)
    get = lambda f: value_of(f, next((k for _, ff, k, _, _ in form if ff == f), "m"))
    for section, fact, kind, label, cond in form:
        visible = fact not in drop and (cond is None or cond(get))
        P[fact] = get(fact) if visible else None
    if "n_dwellings" in P and P.get("n_dwellings") is not None:
        P["n_dwellings"] = float(P["n_dwellings"])
    return P


def run_check():
    P = project_values()
    results, analysis, log, final = engine.check_compliance(S.rules, P, S.doc["zone"], S.overrides, reference=S.doc["reference"])
    S.results, S.analysis, S.final_project, S.check_log = results, analysis, final, log


# ------------------------------------------------------------------------------------------------
# 5. Rapport (cellule 29) + choix des règles applicables (cellule 18)
# ------------------------------------------------------------------------------------------------
def step_report():
    st.header("5. Rapport préliminaire de conformité")
    if S.get("results") is None:
        st.info("Remplissez le questionnaire puis lancez la vérification (étape 4)."); return
    R, off, doc, prof = S.results, S.doc["offset"] or 0, S.doc, S.profile
    st.caption(f"{doc['commune']} · zone {doc['zone']} · secteur {prof['sector']} · {', '.join(prof['building_labels'])} · "
               + ("règles vérifiées" if S.rules_key[0] == "verified" else "règles extraites en direct, non vérifiées"))
    n = lambda sts: sum(x["status"] in sts for x in R)
    c1, c2, c3 = st.columns(3)
    c1.metric("✅ Conforme(s)", n([fr.OK]))
    c2.metric("❌ Non-conformité(s) potentielle(s)", n([fr.NOK]))
    c3.metric("⚠️ À vérifier", n([fr.REVIEW, fr.MISSING, fr.NOTFOUND]))
    st.dataframe([{"#": i, "Article": x["article"], "Vérification": fr.name_fr(x), "Résultat": f"{fr.ICON.get(x['status'], '')} {x['status']}"}
                  for i, x in enumerate(R, 1)], hide_index=True, width="stretch")
    groups = [("❌ Non-conformités potentielles", [fr.NOK]), ("⚠️ À vérifier", [fr.REVIEW, fr.MISSING, fr.NOTFOUND]), ("✅ Conformes selon la règle structurée", [fr.OK])]
    for title, sts in groups:
        items = [x for x in R if x["status"] in sts]
        if not items:
            continue
        st.subheader(title)
        for x in items:
            with st.expander(f"{x['article']} — {fr.name_fr(x)} : {x['status']}", expanded=x["status"] == fr.NOK):
                if x["detail"]:
                    st.markdown(f"**Calcul :** {fr.detail_fr(x['detail'])}")
                st.markdown(f"**Où vérifier :** {fr.where_fr(x['where'], off)}")
                if x["quote"]:
                    st.markdown(f"> {x['quote']}")
                for note in fr.notes_fr(x["notes"]):
                    st.markdown(f"- {note}")
    show_applicability()
    st.divider()
    head = (f"# Vérification préliminaire de conformité au PLU\n{doc['commune']}, zone {doc['zone']}, secteur {prof['sector']} — "
            f"{', '.join(prof['building_labels'])}\n\nRègles : " + ("vérifiées" if S.rules_key[0] == "verified" else "extraites en direct, non vérifiées"))
    c1, c2 = st.columns(2)
    c1.download_button("Télécharger le rapport (Markdown)", fr.render_markdown(R, off, head), "rapport_conformite.md", "text/markdown")
    c2.download_button("Télécharger le rapport (JSON)", json.dumps({"projet": S.final_project, "resultats": R}, ensure_ascii=False, indent=1),
                       "rapport_conformite.json", "application/json")
    st.caption("Vérification préliminaire uniquement. Le modèle de langage ne décide jamais de la conformité : les règles sont extraites du texte du PLU "
               "avec des citations mot pour mot, et la comparaison est faite par du code. Vérifiez chaque point sur le PDF.")


def show_applicability():
    """Cellule 18 : quelles règles conditionnelles s'appliquent ? L'architecte peut corriger le choix du programme."""
    A = S.analysis
    params = [p for p in ("stationnement", "espaces_verts_pleine_terre") if p in A]
    if not params:
        return
    st.subheader("Règles conditionnelles : le choix du programme, à vérifier")
    if A.get("required_detail"):
        st.info("Stationnement : " + fr.required_fr(A["required_detail"]))
    with st.form("applicability_form"):
        new = {}
        for p in params:
            st.markdown(f"**{fr.PARAM_FR[p]}**")
            for r in A[p]["rules"]:
                if r["status"] == "not_for_project" and r["kept"] is not True:
                    continue
                default = r["kept"] is True or (r["kept"] is None and r["status"] == "applies")
                lab = f"Règle {r['n']} — {fr.APPLIES_FR[r['status']]} : {fr.quote_label(r)}"
                chk = st.checkbox(lab, value=default, key=f"ap_{p}_{r['n']}")
                det = fr.rule_lines_fr(r)
                if det:
                    st.caption("  \n".join(det))
                if chk != default or S.overrides.get(p, {}).get(r["n"]) is not None:
                    new.setdefault(p, {})[r["n"]] = chk
            hidden = [r for r in A[p]["rules"] if r["status"] == "not_for_project" and r["kept"] is not True]
            if hidden:
                with st.expander(f"{len(hidden)} règle(s) ne concernent pas ce projet"):
                    for r in hidden:
                        st.caption(f"Règle {r['n']} : {fr.quote_label(r, 160)}  \n" + "  \n".join(fr.rule_lines_fr(r)))
        st.caption("Décocher = écarter la règle ; cocher une règle « À confirmer » = la retenir. Le nombre de places exigé est calculé "
                   "à partir des règles « places par logement » et visiteurs avant votre vérification.")
        if st.form_submit_button("Recalculer le rapport avec ces choix"):
            S.overrides = new
            run_check()
            st.rerun()


PAGES = {STEPS[0]: step_document, STEPS[1]: step_project, STEPS[2]: step_rules, STEPS[3]: step_form, STEPS[4]: step_report}
PAGES[S.step]()
