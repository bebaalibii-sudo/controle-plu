# CELL 14 | Milestone 5 | Call the LLM by API: send each prompt, get the JSON answer back (no more copy-paste)
import os, re, json, time, getpass

assert "built" in globals() or any(os.path.exists(f) for f in os.listdir(".") if f.startswith("prompt_")), "Run CELL 18 first (it builds the prompts)."

# ------------------------------- SETTINGS (the only lines you may change) -------------------------------
PROVIDER = "gemini"                       # "gemini" (free key from Google AI Studio)  or  "claude" (paid key from the Anthropic console)
PARAMS_TO_CALL = list(PARAMS_TO_EXTRACT)  # the parameters set in CELL 18 (change here only to call fewer)
GEMINI_MODEL = "auto"                     # "auto" = the newest Gemini 'flash' model your key can use; or type a model name
CLAUDE_MODEL = "claude-sonnet-5-5"
GEMINI_SECRET = "Gemini_API_key"         # the NAME of your secret in Colab Secrets (key icon, left menu)
CLAUDE_SECRET = "ANTHROPIC_API_KEY"
MAX_TRIES = 18                            # tries per parameter: the free service is often busy, so the cell waits 20 s between tries and cycles through the models
# ----------------------------------------------------------------------------------------------------------

def get_key(secret_name):
    """Colab Secrets first (left menu, key icon). If not found, asks once, hidden. The key is never printed or saved."""
    try:
        from google.colab import userdata
        k = userdata.get(secret_name)
        if k: return k.strip()
    except Exception:
        pass
    print(f"No secret named {secret_name} found in Colab Secrets (key icon in the left menu).")
    return getpass.getpass(f"Paste your {PROVIDER} API key here (hidden, kept in memory only): ").strip()

def clean_json_text(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    return text

def valid_json(text):
    try:
        obj = json.loads(clean_json_text(text))
        return isinstance(obj, dict) and "parameter" in obj and "status" in obj
    except Exception:
        return False

def gemini_candidates(names):
    """Gemini 'flash' models, best first: stable before preview, then the highest version. Lite / image / audio / experimental variants are left out."""
    bad = ("lite", "image", "tts", "live", "audio", "exp", "embedding", "vision", "robotics", "computer", "thinking", "latest", "omni")
    out = []
    for n in names:
        short = n.replace("models/", "")
        if "gemini" not in short or "flash" not in short or any(b in short for b in bad): continue
        nums = tuple(int(x) for x in re.findall(r"\d+", short.split("flash")[0]))
        out.append((("preview" not in short, nums), short))
    out.sort(reverse=True)
    return [n for _, n in out] or ["gemini-2.5-flash"]

class Caller:
    def __init__(self):
        if PROVIDER == "gemini":
            try: from google import genai
            except ImportError:
                get_ipython().system("pip install -q google-genai"); from google import genai
            from google.genai import types, errors
            self.genai, self.types, self.errors = genai, types, errors
            self.client = genai.Client(api_key=get_key(GEMINI_SECRET))
            if GEMINI_MODEL == "auto":
                names = [m.name for m in self.client.models.list() if "generateContent" in (m.supported_actions or [])]
                self.candidates = gemini_candidates(names)
            else:
                self.candidates = [GEMINI_MODEL]
            self.model = self.candidates[0]
        elif PROVIDER == "claude":
            try: import anthropic
            except ImportError:
                get_ipython().system("pip install -q anthropic"); import anthropic
            self.anthropic = anthropic
            self.client = anthropic.Anthropic(api_key=get_key(CLAUDE_SECRET))
            self.candidates = [CLAUDE_MODEL]
            self.model = CLAUDE_MODEL
        else:
            raise ValueError("PROVIDER must be 'gemini' or 'claude'")

    def next_model(self):
        """Switch to the next candidate model. Returns False if there is only one."""
        i = self.candidates.index(self.model)
        if len(self.candidates) > 1:
            self.model = self.candidates[(i + 1) % len(self.candidates)]     # after the last model, starts again from the first
            print(f"   switching to model: {self.model}")
            return True
        return False

    def ask(self, prompt, temperature=0.0):
        """One call. Returns (text, input_tokens, output_tokens)."""
        if PROVIDER == "gemini":
            r = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=self.types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json", max_output_tokens=32000))
            u = r.usage_metadata
            return r.text, getattr(u, "prompt_token_count", None), getattr(u, "response_token_count", None)
        r = self.client.messages.create(model=self.model, max_tokens=16000, temperature=temperature,
                                        messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, r.usage.input_tokens, r.usage.output_tokens

def status_code(e):
    return getattr(e, "code", None) or getattr(e, "status_code", None)

def call_with_retries(caller, prompt):
    """Retries when the service is busy (429 / 5xx) or when the answer is not valid JSON. Switches to the next model when one is refused (404) or stays busy."""
    last, busy = "", 0
    for attempt in range(1, MAX_TRIES + 1):
        try:
            text, t_in, t_out = caller.ask(prompt, temperature=0.0 if attempt == 1 else 0.3)
        except Exception as e:
            code = status_code(e)
            if code in (401, 403):
                raise RuntimeError("The key was refused (401/403). Check the key and that the API is enabled for it.") from e
            if code == 404:
                print(f"   model {caller.model} is not available for this key")
                if caller.next_model(): continue
                raise RuntimeError("No usable model left. Set GEMINI_MODEL to a name from your model list.") from e
            if code == 429 or (isinstance(code, int) and code >= 500) or "overloaded" in str(e).lower():
                busy += 1
                print(f"   {caller.model} is busy or the quota is reached (code {code}), try {attempt}/{MAX_TRIES}; waiting 20 s")
                time.sleep(20)
                if busy >= 2 and caller.next_model():
                    busy = 0
                continue
            raise
        last = text
        if valid_json(text): return clean_json_text(text), t_in, t_out
        print(f"   the answer was not valid JSON (try {attempt}/{MAX_TRIES}); asking again")
    raise RuntimeError("No valid answer after several tries. Last answer began with: " + (last or "")[:200])

LLM_RAW = globals().setdefault("LLM_RAW", {})
LLM_META = globals().setdefault("LLM_META", {})
caller = Caller()
print(f"Provider: {PROVIDER} | model: {caller.model}\n(The prompts contain the PLU text only: no project values and no personal data are sent.)\n")

for param in PARAMS_TO_CALL:
    if "built" in globals() and param in built: prompt = built[param][0]
    elif os.path.exists(f"prompt_{param}.txt"): prompt = open(f"prompt_{param}.txt", encoding="utf-8").read()
    else: print(f"{param}: no prompt found, run CELL 18 for it first"); continue
    t0 = time.time()
    print(f"{param}: sending {len(prompt)} characters ...")
    try:
        text, t_in, t_out = call_with_retries(caller, prompt)
    except Exception as e:
        print(f"{param}: FAILED -> {e}"); continue
    LLM_RAW[param] = text
    LLM_META[param] = {"provider": PROVIDER, "model": caller.model, "tokens_in": t_in, "tokens_out": t_out, "seconds": round(time.time() - t0, 1)}
    fname = f"llm_raw_{param}_{PROVIDER}.txt"
    with open(fname, "w", encoding="utf-8") as f: f.write(text)
    n_rules = len(json.loads(text).get("rules", []))
    print(f"{param}: OK | {n_rules} rule(s) in the answer | tokens in/out: {t_in}/{t_out} | {LLM_META[param]['seconds']} s | saved as {fname}")

print("\nNext: run CELL 19. It reads these answers, checks every quote against the PDF text and shows the result.")