# CELL 9 | Milestone 4 | Project profile: sub-sector, type of building, 500 m from a station, average dwelling area
import re

known_sectors = {s for c in chunks for s in c["sectors_mentioned"]} | {ZONE_PREFIX}

# Building types = the categories this PLU uses in its parking article (UB.12), in the usual French wording
BUILDING_TYPES = {
    "1": ("logement",              "Logement (habitation)",                                      r"logements?|habitat(?:ion)?"),
    "2": ("logement_aide",         "Logement locatif financé avec un prêt aidé par l'État",      r"pr[êe]t aid[ée]|logements? locatifs? financ[ée]s?"),
    "3": ("hebergement_hotelier",  "Hébergement hôtelier (hôtel, foyer, résidence...)",          r"h[ée]bergement|h[ôo]tel|touristique|chambres?"),
    "4": ("commerce_services",     "Commerce et activités de service",                           r"commerc|artisanat|restauration|activit[ée]s? de service"),
    "5": ("bureaux",               "Bureaux",                                                    r"bureaux?|tertiaire"),
    "6": ("equipement_public",     "Équipement public ou d'intérêt collectif",                   r"services? publics?|int[ée]r[êe]t collectif|[ée]quipements?"),
    "7": ("autre",                 "Autre construction ou installation",                         r"autres constructions|entrep[ôo]ts?|industri|agricol"),
}
HOUSING_TYPES = {"logement", "logement_aide"}   # types for which the average dwelling area is asked

# ---- 1. Zone (read from the document) and sub-sector (chosen by the architect) ----
print(f"Zone: {ZONE_PREFIX}  (read from the document, nothing to type)")
sub_sectors = sorted(s for s in known_sectors if s != ZONE_PREFIX)
SECTOR = ZONE_PREFIX
if sub_sectors:
    print(f"\nDoes the parcel lie in a sub-sector of {ZONE_PREFIX}?")
    print(f"  0. No sub-sector (plain {ZONE_PREFIX})")
    for i, s in enumerate(sub_sectors, 1):
        print(f"  {i}. {s}")
    _sub = input("Your choice [Enter = 0]: ").strip()
    if _sub.isdigit() and 1 <= int(_sub) <= len(sub_sectors):
        SECTOR = sub_sectors[int(_sub) - 1]
    elif _sub not in ("", "0"):
        print(f"  (ignored: '{_sub}' is not in the list, plain {ZONE_PREFIX} is used)")

# ---- 2. Type(s) of building ----
print("\nType of building (several allowed: separate the numbers with commas, e.g. 1,4):")
for k, (_, label, _) in BUILDING_TYPES.items():
    print(f"  {k}. {label}")
_choice = input("Your choice [default 1]: ").strip() or "1"
chosen = []
for part in re.split(r"[,\s;]+", _choice):
    if part in BUILDING_TYPES and part not in chosen:
        chosen.append(part)
    elif part:
        print(f"  (ignored: '{part}' is not in the list)")
if not chosen:
    chosen = ["1"]
types = [BUILDING_TYPES[k][0] for k in chosen]

# ---- 3. Is the parcel within 500 m of a railway station? (the parking rule changes near a station) ----
print("\nIs the parcel within 500 m of a railway station (gare)?")
_st = input("  y = yes, n = no, Enter = I don't know yet: ").strip().lower()
if _st in ("y", "yes", "o", "oui"):
    WITHIN_500M_STATION = True
elif _st in ("n", "no", "non"):
    WITHIN_500M_STATION = False
else:
    WITHIN_500M_STATION = None       # unknown: the comparison will later say "Données insuffisantes", it will not guess

# ---- 4. Average floor area per dwelling (only asked if the project includes housing) ----
AVG_DWELLING_SDP = None
if any(t in HOUSING_TYPES for t in types):
    print("\nAverage floor area (SDP, surface de plancher) per dwelling, in m2")
    while True:
        _a = input("  e.g. 58 or 72,5 (Enter = I don't know yet): ").strip().replace(",", ".")
        if _a == "":
            break
        try:
            _v = float(_a)
            if _v <= 0:
                raise ValueError
            AVG_DWELLING_SDP = _v
            break
        except ValueError:
            print("  Please type a positive number, for example 65")

PROJECT = {
    "sector": SECTOR,
    "building_types": types,
    "building_labels": [BUILDING_TYPES[k][1] for k in chosen],
    "within_500m_station": WITHIN_500M_STATION,
    "avg_dwelling_sdp_m2": AVG_DWELLING_SDP,
}
print("\n==== PROJECT PROFILE ====")
print("Sector:", PROJECT["sector"])
print("Building type(s):", "; ".join(PROJECT["building_labels"]))
print("Within 500 m of a station:", {True: "yes", False: "no", None: "not answered"}[PROJECT["within_500m_station"]])
if any(t in HOUSING_TYPES for t in types):
    print("Average SDP per dwelling:", f"{PROJECT['avg_dwelling_sdp_m2']} m2" if PROJECT["avg_dwelling_sdp_m2"] else "not answered")
print("(The program will find by itself which rules depend on the building type.)")