"""Moteur du prototype PLU : reprend le code des cellules du notebook (PLU Prototype-Fin.ipynb) sans input().

Le code des cellules est exécuté tel quel depuis le dossier notebook_cells/, avec quelques adaptations
listées dans PATCHES (chemin du PDF, préfixe de zone, clé API, pas de fichiers rechargés en douce).
Le modèle de langage ne décide jamais de la conformité : il extrait des règles avec citation ;
l'applicabilité (cellule 18) et la conformité (cellule 29) sont calculées par du code.
"""
import builtins, contextlib, copy, hashlib, io, json, os, re, tempfile, threading
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
CELLS = HERE
DATA = HERE

# Document de référence : règlement de la zone UB d'Éragny-sur-Oise (règles vérifiées à la main)
REFERENCE = json.loads((DATA / "reference.json").read_text(encoding="utf-8"))
PARAMS = ["implantation_voies", "limites_separatives", "emprise_au_sol", "hauteur_maximale",
          "nombre_de_niveaux", "stationnement", "espaces_verts_pleine_terre"]

_LOCK = threading.Lock()          # le code des cellules utilise des fichiers et des variables globales


class PipelineError(Exception):
    """Erreur expliquée à l'utilisateur (en français)."""


# --------------------------------------------------------------------------------------------
# Lecture et adaptation du code des cellules
# --------------------------------------------------------------------------------------------
def _src(n):
    return (CELLS / f"c{n:02d}.py").read_text(encoding="utf-8")


def _patch(src, old, new, count=1):
    found = src.count(old)
    if found < count:
        raise RuntimeError(f"Adaptation impossible du code du notebook (motif introuvable) : {old[:70]!r}")
    return src.replace(old, new)


def _between(src, start, end=None, include_end_line=False):
    i = src.index(start)
    if end is None:
        return src[i:]
    j = src.index(end, i)
    if include_end_line:
        j = src.index("\n", j) + 1
    return src[i:j]


def _run(src, ns, name, inputs=None):
    """Exécute un bout de code de cellule dans ns. Le texte imprimé est renvoyé (journal technique)."""
    buf, old_input = io.StringIO(), builtins.input
    builtins.input = inputs or (lambda prompt="": "")
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(src, f"<{name}>", "exec"), ns)
    finally:
        builtins.input = old_input
    return buf.getvalue()


def _schema_ns():
    """Espace de noms de base : schéma v1.2 (cellule 11), FACTS (cellule 13), types de bâtiments (cellule 9)."""
    ns = {"__name__": "plu_cells"}
    _run(_src(11), ns, "cellule 11")
    _run(_between(_src(13), "FACTS = {", "FACT_PARAMS =", include_end_line=True), ns, "cellule 13 (FACTS)")
    _run(_between(_src(9), "BUILDING_TYPES = {", "HOUSING_TYPES", include_end_line=True), ns, "cellule 9 (types)")
    ns["has_errors"] = lambda rule: any(i.startswith("ERROR") for i in rule.guardrail_issues)   # = cellule 12
    return ns


def load_rules(data, ns):
    """dict JSON -> dict de ParameterResult (schéma de la cellule 11)."""
    return {k: ns["ParameterResult"].model_validate(v) for k, v in data.items()}


def dump_rules(extracted):
    return {k: v.model_dump(mode="json") for k, v in extracted.items()}


def verified_rules():
    return json.loads((DATA / "extractions_verified.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# 1. Empreinte du PDF (mode hybride)
# --------------------------------------------------------------------------------------------
def fingerprint(pdf_bytes):
    return hashlib.sha256(pdf_bytes).hexdigest()


def is_reference(pdf_bytes):
    return fingerprint(pdf_bytes) == REFERENCE["sha256"]


# --------------------------------------------------------------------------------------------
# 2. OCR (même méthode que la cellule 3 : couche texte si elle existe, sinon Tesseract fra, --psm 4, 300 dpi)
# --------------------------------------------------------------------------------------------
def ocr_pdf(pdf_bytes, progress=None, dpi=300):
    import pymupdf, pytesseract
    from PIL import Image
    pages = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        n = doc.page_count
        if n == 0:
            raise PipelineError("Le PDF ne contient aucune page.")
        for i, page in enumerate(doc, start=1):
            native = page.get_text()
            if len(native.strip()) >= 50:
                text, method = native, "text_layer"
            else:
                pix = page.get_pixmap(dpi=dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text, method = pytesseract.image_to_string(img, lang="fra", config="--psm 4"), "ocr"
            pages.append({"pdf_page": i, "text": text, "method": method})
            if progress:
                progress(i, n)
    return pages


def detect_offset(pages):
    """Page imprimée = page PDF + décalage. On cherche un numéro seul en haut ou en bas de page."""
    votes = Counter()
    for p in pages:
        lines = [l.strip() for l in p["text"].splitlines() if l.strip()]
        for l in lines[:3] + lines[-3:]:
            m = re.fullmatch(r"(?:page\s*)?(\d{1,4})(?:\s*/\s*\d{1,4})?", l, re.I)
            if m and int(m.group(1)) >= p["pdf_page"]:
                votes[int(m.group(1)) - p["pdf_page"]] += 1
    if votes:
        off, n = votes.most_common(1)[0]
        if n >= max(3, len(pages) // 4):
            return off
    return 0


def detect_zone(pages):
    """Préfixe de zone lu dans les titres d'articles (« ARTICLE UB.6 - ... »)."""
    rx = re.compile(r"^\s*ARTICLE\s+[—–\-]*\s*([A-Z]{1,4}[a-z]?)\s*[.,]?\s*(\d{1,2})\s*[-–—=:]", re.M)
    found = Counter()
    for p in pages:
        for m in rx.finditer(re.sub(r"_+", " ", p["text"])):
            found[m.group(1)] += 1
    if not found:
        return None, 0
    zone, n = found.most_common(1)[0]
    return zone, n


def detect_commune(pages):
    text = " ".join(p["text"][:3000] for p in pages[:3])
    m = re.search(r"(?i)\b(?:commune|ville)\s+d[e'’]\s*([A-ZÉÈ][\w\-’' ]{2,40})", text)
    if re.search(r"(?i)eragny", text):
        return "Éragny-sur-Oise"
    return m.group(1).strip() if m else "commune non détectée"


# --------------------------------------------------------------------------------------------
# 3. Nettoyage + découpage (cellules 4 et 5)
# --------------------------------------------------------------------------------------------
def chunk_pages(pages, zone, offset, commune, document):
    for p in pages:
        p["printed_page"] = p["pdf_page"] + offset
    # lignes répétées sur au moins la moitié des pages = en-têtes / pieds de page (généralise le filtre d'Éragny)
    per_page = [set(l.strip() for l in p["text"].splitlines() if l.strip()) for p in pages]
    cnt = Counter(l for s in per_page for l in s)
    repeated = {l for l, c in cnt.items() if len(pages) >= 4 and c >= len(pages) / 2 and not l.upper().startswith("ARTICLE")}
    ns = {"pages": pages, "REPEATED_LINES": repeated}
    s4 = _patch(_src(4), 'ZONE_PREFIX = "UB"', f"ZONE_PREFIX = {zone!r}")
    s4 = _patch(s4, 'rf"^ARTICLE\\s+{ZONE_PREFIX}', 'rf"^ARTICLE\\s+[—–\\-]*\\s*{ZONE_PREFIX}')   # OCR : « ARTICLE —UB.6 »
    s4 = _patch(s4, "if FOOTER_RE.match(line) or HEADER_RE.match(line):",
                "if FOOTER_RE.match(line) or HEADER_RE.match(line) or line.strip() in REPEATED_LINES:")
    s4 = _patch(s4, 'print("Example of removed lines:", pages[1]["removed_lines"])', "pass")
    s4 = s4.split("# ---- 4. Save ----")[0]
    log = _run(s4, ns, "cellule 4")
    s5 = _patch(_src(5), 'COMMUNE = "Éragny-sur-Oise"', f"COMMUNE = {commune!r}")
    s5 = _patch(s5, 'DOCUMENT = "REGLEMENT ZONE UB.pdf"', f"DOCUMENT = {document!r}")
    s5 = _patch(s5, 'ZONE_PREFIX = "UB"', f"ZONE_PREFIX = {zone!r}")
    s5 = _patch(s5, 'rf"^ARTICLE\\s+{ZONE_PREFIX}', 'rf"^ARTICLE\\s+[—–\\-]*\\s*{ZONE_PREFIX}')
    s5 = _patch(s5, 'with open("chunks.json", "w", encoding="utf-8") as f:\n    json.dump(chunks, f, ensure_ascii=False, indent=1)', "pass")
    log += _run(s5, ns, "cellule 5")
    chunks = ns["chunks"]
    n_articles = len({c["article_number"] for c in chunks if c["article_number"]})
    if n_articles < 3:
        raise PipelineError(f"Seulement {n_articles} article(s) reconnu(s) : la structure de ce règlement n'est pas prise en charge "
                            "(le prototype attend des articles numérotés « ARTICLE {zone}.1 », « ARTICLE {zone}.2 »…).")
    return chunks, log


# --------------------------------------------------------------------------------------------
# 4. Plongements (cellule 8) et recherche (cellule 10)
# --------------------------------------------------------------------------------------------
class GeminiEmbedder:
    """Plongements par l'API Gemini (remplace bge-m3 quand le serveur n'a pas assez de mémoire pour le modèle local).
    Même interface que SentenceTransformer.encode pour que la cellule 10 reste inchangée."""
    MODELS = ["gemini-embedding-001", "text-embedding-004"]

    def __init__(self, api_key, dim=768):
        from google import genai
        from google.genai import types
        self.types, self.dim = types, dim
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120000))
        self.model = self.MODELS[0]
        self.name = self.model

    def _call(self, texts, task):
        import time
        last = None
        for attempt in range(5):
            try:
                r = self.client.models.embed_content(model=self.model, contents=texts,
                        config=self.types.EmbedContentConfig(task_type=task, output_dimensionality=self.dim))
                return [e.values for e in r.embeddings]
            except Exception as e:
                last, code = e, getattr(e, "code", None) or getattr(e, "status_code", None)
                msg = str(e)
                if code in (401, 403):
                    raise PipelineError("La clé Gemini est refusée pour les plongements (401/403).")
                if code == 404 and self.model != self.MODELS[-1]:
                    self.model = self.MODELS[self.MODELS.index(self.model) + 1]; self.name = self.model; continue
                if code == 429 and re.search(r"limit:\s*0\b", msg):
                    break                                   # aucun quota gratuit pour ce modèle : inutile d'attendre
                if code == 429 or (isinstance(code, int) and code >= 500):
                    m = re.search(r"retry(?:Delay)?['\"]?\s*[:=]\s*['\"]?(\d+)", msg, re.I) or re.search(r"retry in (\d+)", msg, re.I)
                    time.sleep(min(int(m.group(1)) + 2, 65) if m else 20)
                    continue
                raise
        raise PipelineError(f"Quota Gemini atteint pour les plongements : {str(last)[:160]}")

    def encode(self, texts, normalize_embeddings=True, batch_size=8, task="RETRIEVAL_QUERY", **kw):
        import numpy as np, time
        out = []
        for i in range(0, len(texts), batch_size):
            out += self._call(list(texts[i:i + batch_size]), task)
            if i + batch_size < len(texts):
                time.sleep(1.0)                              # rester sous la limite par minute du forfait gratuit
        E = np.asarray(out, dtype="float32")
        if normalize_embeddings:
            E = E / np.clip(np.linalg.norm(E, axis=1, keepdims=True), 1e-12, None)
        return E


class KeywordEmbedder:
    """Solution de repli sans modèle ni API : vecteurs TF-IDF des mots (sans accents ni mots vides).
    Moins fin que des plongements sémantiques, mais la recherche reste possible quand le quota Gemini est épuisé."""
    name = "tfidf-mots-cles"
    STOP = set("les des une dans pour par sur aux avec sont est qui que leur leurs ces cette ainsi elle ils doit doivent etre peut peuvent "
               "plus moins entre lorsque dont tout tous toute toutes article zone pas non ont".split())

    def __init__(self):
        self.vocab, self.idf = {}, None

    def _tokens(self, t):
        import unicodedata
        t = unicodedata.normalize("NFKD", t.lower())
        t = "".join(ch for ch in t if not unicodedata.combining(ch))
        return [w for w in re.findall(r"[a-z0-9]{3,}", t) if w not in self.STOP]

    def fit(self, texts):
        import numpy as np
        docs = [set(self._tokens(t)) for t in texts]
        for d in docs:
            for w in d:
                self.vocab.setdefault(w, len(self.vocab))
        df = np.zeros(len(self.vocab))
        for d in docs:
            for w in d:
                df[self.vocab[w]] += 1
        self.idf = np.log((1 + len(docs)) / (1 + df)) + 1
        return self

    def encode(self, texts, normalize_embeddings=True, **kw):
        import numpy as np
        E = np.zeros((len(texts), len(self.vocab)), dtype="float32")
        for i, t in enumerate(texts):
            for w in self._tokens(t):
                j = self.vocab.get(w)
                if j is not None:
                    E[i, j] += 1
        E = np.log1p(E) * self.idf
        if normalize_embeddings:
            E = E / np.clip(np.linalg.norm(E, axis=1, keepdims=True), 1e-12, None)
        return E


def load_embedder(name="BAAI/bge-m3"):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer(name, device="cpu")
    m.max_seq_length = 1024
    return m


def embed_chunks(model_emb, chunks):
    import numpy as np
    texts = [c["text_for_embedding"] for c in chunks]
    if isinstance(model_emb, KeywordEmbedder):
        E = model_emb.fit(texts).encode(texts)
    elif isinstance(model_emb, GeminiEmbedder):
        E = model_emb.encode(texts, normalize_embeddings=True, task="RETRIEVAL_DOCUMENT")
    else:
        E = model_emb.encode(texts, batch_size=8, normalize_embeddings=True)
    return np.asarray(E)


def _profile_ns(ns, profile):
    ns["PROJECT"] = dict(profile)
    return ns


# --------------------------------------------------------------------------------------------
# 5. Extraction en direct : recherche + prompts + Gemini + garde-fous (cellules 10, 12, 13, 14, 15)
# --------------------------------------------------------------------------------------------
def extract_live(chunks, E, model_emb, zone, profile, api_key, use_manual_table, progress=None, params=None, fake_llm=None):
    """Renvoie (dict JSON des règles, journal, liste des paramètres en échec)."""
    params = params or PARAMS
    ns = _schema_ns()
    ns.update(chunks=chunks, E=E, model_emb=model_emb, ZONE_PREFIX=zone, EMB_MODEL=getattr(model_emb, "name", "BAAI/bge-m3"),
              USE_MANUAL=use_manual_table)
    _profile_ns(ns, profile)
    ns["normalise_sector"] = _normalise_sector_fn(zone)
    log = ""
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd(); os.chdir(tmp)
        try:
            # cellule 10 : recherche (une requête par paramètre + extension à tout l'article)
            log += _run(_src(10), ns, "cellule 10")
            # cellule 12 : garde-fous (sans les tests propres à UB.9)
            s12 = _src(12).split("# ---------- Tests built from YOUR chunks")[0]
            s12 = _patch(s12, 'f"UB.{ch[\'article_number\']}"', 'f"{ZONE_PREFIX}.{ch[\'article_number\']}"')
            log += _run(s12, ns, "cellule 12")
            # cellule 13 : prompts (le tableau du stationnement transcrit à la main ne vaut que pour Éragny UB)
            s13 = _patch(_src(13), 'PARAMS_TO_EXTRACT = ["implantation_voies", "emprise_au_sol", "hauteur_maximale", "nombre_de_niveaux", "limites_separatives","stationnement"]',
                         f"PARAMS_TO_EXTRACT = {params!r}")
            s13 = _patch(s13, "register_manual_chunks()\n\norder", "if USE_MANUAL: register_manual_chunks()\n\norder")
            s13 = _patch(s13, 'order[MANUAL_ID] = order["UB.12#preamble"] + 0.5', 'if USE_MANUAL: order[MANUAL_ID] = order["UB.12#preamble"] + 0.5')
            s13 = _patch(s13, 'if param == "stationnement" and (set(PROJECT["building_types"]) & HOUSING):',
                         'if USE_MANUAL and param == "stationnement" and (set(PROJECT["building_types"]) & HOUSING):')
            s13 = s13.split("for n, (param, (text, pchunks, aside_ids, superseded, notes, fname)) in enumerate(built.items(), 1):")[0]
            log += _run(s13, ns, "cellule 13")
            # cellule 14 : appel du modèle (définitions seulement ; la boucle est refaite ici pour suivre l'avancement)
            s14 = _between(_src(14), "def get_key(secret_name):", "LLM_RAW = globals()")
            s14 = _patch(s14, "self.client = genai.Client(api_key=get_key(GEMINI_SECRET))",
                         "self.client = genai.Client(api_key=get_key(GEMINI_SECRET), http_options=types.HttpOptions(timeout=120000))")
            ns.update(PROVIDER="gemini", GEMINI_MODEL="auto", CLAUDE_MODEL="", GEMINI_SECRET="", CLAUDE_SECRET="", MAX_TRIES=8)
            log += _run(s14, ns, "cellule 14")
            ns["get_key"] = lambda name: api_key
            try:
                caller = None if fake_llm else ns["Caller"]()
            except Exception as e:
                raise PipelineError(f"La clé Gemini est refusée ou le service est inaccessible : {str(e)[:200]}")
            raw, failed = {}, []
            for i, param in enumerate(params, 1):
                if progress:
                    progress(i - 1, len(params), param)
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        text, _, _ = (fake_llm(param, ns["built"][param][0]) if fake_llm
                                      else ns["call_with_retries"](caller, ns["built"][param][0]))
                    raw[param] = text
                except Exception as e:
                    failed.append((param, str(e)[:200]))
                log += f"\n[Gemini] {param}\n" + buf.getvalue()
            if progress:
                progress(len(params), len(params), "")
            # cellule 15 : lecture des réponses + garde-fous ; aucun ancien fichier n'est rechargé
            ns["LLM_RAW"] = raw
            ns["EXTRACTED"] = {}
            s15 = _patch(_src(15), "register_manual_chunks()                      # makes sure",
                         "if USE_MANUAL: register_manual_chunks()                      # makes sure")
            s15 = _patch(s15, "    if not EXTRACTED:                                   # new session",
                         "    if False:                                   # new session")
            s15 = _patch(s15, 'cnd.source.article = f"UB.{ch[\'article_number\']}"', 'cnd.source.article = f"{ZONE_PREFIX}.{ch[\'article_number\']}"')
            if raw:
                log += _run(s15, ns, "cellule 15")
            extracted = dump_rules(ns["EXTRACTED"])
        finally:
            os.chdir(cwd)
    return extracted, log, failed


def _normalise_sector_fn(zone):
    def normalise_sector(code):
        m = re.fullmatch(rf"({zone}[a-z])i", code)
        if m: return m.group(1) + "1"
        m = re.fullmatch(rf"({zone}[a-z]\d)i", code)
        if m: return m.group(1)
        return code
    return normalise_sector


# --------------------------------------------------------------------------------------------
# 6. Questionnaire (cellule 28)
# --------------------------------------------------------------------------------------------
def form_definition():
    """FORM de la cellule 28 : liste de (section, fait, type yn/m/m2/n, libellé, condition)."""
    ns = {"PROJECT": {}}
    _run(_src(28).split('print("Answer each question.')[0], ns, "cellule 28")
    return ns["FORM"]


def relevant_facts(rules_json, reference):
    """Questions propres à Éragny (Halage, ru, Oise, corridor) : posées seulement si une règle en parle."""
    if reference:
        return None                                    # document de référence : toutes les questions
    txt = lambda p: " ".join(((r.get("summary") or "") + " " + (r.get("formula_text") or "") + " " +
                              " ".join(c.get("description", "") for c in r.get("conditions", []))).lower()
                             for r in rules_json.get(p, {}).get("rules", []))
    imp, hau, esp = txt("implantation_voies"), txt("hauteur_maximale"), txt("espaces_verts_pleine_terre")
    drop = set()
    if "halage" not in imp: drop |= {"borders_halage", "dist_halage_m"}
    if "stream" not in imp and " ru" not in imp: drop |= {"borders_ru", "dist_ru_m"}
    if "railway" not in imp: drop |= {"near_railway", "dist_rail_m"}
    if "oise" not in hau: drop |= {"slope_facing_oise"}
    if "strip" not in esp and "corridor" not in esp: drop |= {"in_ecological_corridor", "corridor_strip_kept"}
    return drop


# --------------------------------------------------------------------------------------------
# 7. Applicabilité (cellule 18) et rapport de conformité (cellule 29)
# --------------------------------------------------------------------------------------------
def _c18():
    return _src(18)


def _c29(zone):
    s = _src(29)
    s = re.sub(r'"UB\.(\d+)"', lambda m: f'"{zone}.{m.group(1)}"', s)
    # la décision de l'architecte (cellule 18) est prise en compte : True = retenue, False = écartée
    s = _patch(s, 'status_of = lambda r: getattr(r, "applicable_to_project", None)',
               'status_of = lambda r: ("applies" if r.applicability_confirmed is True else "not_for_project" if r.applicability_confirmed is False else getattr(r, "applicable_to_project", None))')
    s = _patch(s, 'enumerate(EXTRACTED["emprise_au_sol"].rules, 1)',
               'enumerate(EXTRACTED["emprise_au_sol"].rules if "emprise_au_sol" in EXTRACTED else [], 1)')
    s = _patch(s, 'enumerate(EXTRACTED["espaces_verts_pleine_terre"].rules, 1)',
               'enumerate(EXTRACTED["espaces_verts_pleine_terre"].rules if "espaces_verts_pleine_terre" in EXTRACTED else [], 1)')
    s = s.split("# ---------------- THE REPORT ----------------")[0]
    return s


def check_compliance(rules_json, project, zone="UB", overrides=None, reference=True):
    """Cellule 18 puis cellule 29, sans input().
    overrides = {paramètre: {numéro de règle: True (retenir) | False (écarter)}} : la vérification de l'architecte.
    Renvoie (RESULTS de la cellule 29, analyse de la cellule 18, journal, PROJECT complété)."""
    overrides = overrides or {}
    ns = _schema_ns()
    ns["EXTRACTED"] = load_rules(copy.deepcopy(rules_json), ns)
    ns["PROJECT"] = dict(project)
    order = [p for p in ["stationnement", "espaces_verts_pleine_terre"] if p in ns["EXTRACTED"]]
    queue = list(order)
    state = {"p": None}

    def answer(prompt=""):
        if "Do you accept the program's proposal" in prompt:
            state["p"] = queue.pop(0) if queue else None
            return "n" if overrides.get(state["p"]) else ""
        o = overrides.get(state["p"]) or {}
        if "Rules to RETAIN" in prompt:
            return ",".join(str(k) for k, v in sorted(o.items()) if v is True)
        if "Rules to REJECT" in prompt:
            return ",".join(str(k) for k, v in sorted(o.items()) if v is False)
        return ""                                       # « Entrée » : garder la valeur / accepter

    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd(); os.chdir(tmp)
        try:
            log = _run(_c18(), ns, "cellule 18", inputs=answer)
            log += _run(_c29(zone), ns, "cellule 29")
        finally:
            os.chdir(cwd)
    results = ns["RESULTS"]
    if not reference:      # contrôles propres à Éragny (Halage, ru, voie ferrée) : pas de « non retrouvée » pour un autre PLU
        local = {"Setback from the chemin de Halage", "Setback from the stream (ru)", "Distance from the railway"}
        results = [x for x in results if not (x["name"] in local and x["status"] == "Règle non retrouvée")]
    analysis = {}
    for p, items in ns.get("checked", {}).items():
        analysis[p] = {
            "rules": [{"n": k, "summary": r.summary, "status": s, "lines": lines,
                       "tests": [{"fact": t.fact, "op": t.op, "value": t.value, "result": ns["eval_test"](t),
                                  "project": ns["PROJECT"].get(t.fact)} for t in r.applicability_tests],
                       "other_facts": list(r.needs_other_facts), "guard_fail": ns["has_errors"](r),
                       "untested": bool(not r.applicability_tests and not r.needs_other_facts and r.conditions),
                       "kept": r.applicability_confirmed, "note": ns["RESOLVED"].get((p, k)),
                       "source": (r.sources[0].model_dump(mode="json") if r.sources else None)}
                      for k, r, s, lines in items],
            "proposal": ns["PROPOSAL"].get(p, []),
        }
    analysis["required_detail"] = ns.get("REQ_DETAIL")
    return results, analysis, log, ns["PROJECT"]
