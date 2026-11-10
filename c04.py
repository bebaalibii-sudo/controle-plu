# CELL 4
import re, json, os

ZONE_PREFIX = "UB"          # prefix used in the article headings of this PLU
EXPECTED_ARTICLES = list(range(1, 17))   # UB.1 ... UB.16 (this PLU's numbering)

# ---- 0. Get the pages (from memory, or from the saved file) ----
try:
    pages
except NameError:
    with open("pages_extracted.json", encoding="utf-8") as f:
        pages = json.load(f)["pages"]

# ---- 1. Cleaning: remove ONLY the running footer and the lone zone label in the header ----
FOOTER_RE = re.compile(r"(?i)(^\s*verdi\b|r[eé]vision du plu d.{0,2}\s*eragny)")   # running footer, tolerant to OCR noise
HEADER_RE = re.compile(rf"^\s*{ZONE_PREFIX}\s*$")

def clean_page(text):
    kept, removed = [], []
    for line in text.splitlines():
        if FOOTER_RE.match(line) or HEADER_RE.match(line):
            removed.append(line.strip())
        else:
            kept.append(line.rstrip())
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, removed

for p in pages:
    p["clean_text"], p["removed_lines"] = clean_page(p["text"])

# ---- 2. Heading detection (tolerates OCR noise: underscores, '=' for '-', ',' for '.') ----
def normalise_heading_line(line):
    line = re.sub(r"_+", " ", line)          # OCR turned wide letter-spacing into underscores
    return re.sub(r"\s+", " ", line).strip()

HEADING_RE = re.compile(rf"^ARTICLE\s+{ZONE_PREFIX}\s*[.,]?\s*(\d{{1,2}})\s*[-–—=:]\s*(.*)$")

def is_mostly_upper(s):
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8

articles = []
for p in pages:
    lines = p["clean_text"].splitlines()
    for idx, raw in enumerate(lines):
        line = normalise_heading_line(raw)
        m = HEADING_RE.match(line)
        if not m:
            continue
        number, title = int(m.group(1)), m.group(2).strip()
        # the title may continue on the next line (only if it directly follows and is uppercase)
        if idx + 1 < len(lines):
            nxt = normalise_heading_line(lines[idx + 1])
            if nxt and is_mostly_upper(nxt) and not nxt.startswith("ARTICLE"):
                title = (title + " " + nxt).strip()
        articles.append({"number": number, "title": title,
                         "start_pdf_page": p["pdf_page"], "start_printed_page": p["printed_page"]})

# ---- 3. Checks ----
found = [a["number"] for a in articles]
missing = [n for n in EXPECTED_ARTICLES if n not in found]
duplicates = sorted({n for n in found if found.count(n) > 1})
out_of_order = found != sorted(found)

print("==== ARTICLE INDEX ====")
for a in articles:
    print(f"{ZONE_PREFIX}.{a['number']:<2} | PDF p.{a['start_pdf_page']:<2} (printed {a['start_printed_page']}) | {a['title'][:80]}")

print("\n==== CHECKS ====")
print("Articles found:", len(articles), "of", len(EXPECTED_ARTICLES))
print("Missing:", missing or "none")
print("Duplicates:", duplicates or "none")
print("Order correct:", not out_of_order)
print("Lines removed by cleaning (all pages):", sum(len(p["removed_lines"]) for p in pages))
print("Example of removed lines:", pages[1]["removed_lines"])

# ---- 4. Save ----
with open("articles_index.json", "w", encoding="utf-8") as f:
    json.dump(articles, f, ensure_ascii=False, indent=1)