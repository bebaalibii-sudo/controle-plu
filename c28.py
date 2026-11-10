#CELL 28 PROJECT FORM | Milestone 6 | All the project questions at once, in the order of the PLU articles (Enter keeps the previous answer)
def _ask(fact, label, kind):
    old = PROJECT.get(fact)
    if kind == "yn":
        a = input(f"{label} [y / n | Enter = {'keep ' + ('yes' if old else 'no') if old is not None else 'unknown'}]: ").strip().lower()
        if a in ("y", "yes", "o", "oui"): PROJECT[fact] = True
        elif a in ("n", "no", "non"): PROJECT[fact] = False
        elif a: print("  (answer y or n: ignored)")
    else:
        unit = {"m": "metres", "m2": "m2", "n": "whole number"}[kind]
        a = input(f"{label} [{unit} | Enter = {'keep ' + format(old, 'g') if old is not None else 'unknown'}]: ").strip().replace(",", ".")
        try: PROJECT[fact] = float(a) if a else old
        except ValueError: print("  (not a number: ignored)")
    return PROJECT.get(fact)

Y = lambda f: (lambda g: g(f) is True)
FORM = [
 ("GENERAL", "new_construction", "yn", "Is the work a NEW construction (not a modification of an existing building, thermal improvement, rebuilding after a disaster, technical works, public-service building)?", None),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "dist_road_m", "m", "Distance from the building to the road alignment (or private road limit)", None),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "borders_halage", "yn", "Does the plot border the chemin de Halage?", None),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "dist_halage_m", "m", "  Distance from the building to the alignment of the chemin de Halage", Y("borders_halage")),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "borders_ru", "yn", "Does the plot border the stream (ru)?", None),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "dist_ru_m", "m", "  Distance from the building to the banks of the stream", Y("borders_ru")),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "near_railway", "yn", "Is the plot near a railway?", None),
 ("UB.6  IMPLANTATION RELATIVE TO ROADS", "dist_rail_m", "m", "  Distance from the building to the nearest rail", Y("near_railway")),
]
for name in ("lateral boundary 1", "lateral boundary 2", "rear boundary"):
    t, S = name.replace(" ", "_"), "UB.7  NEIGHBOURING BOUNDARIES"
    FORM += [(S, f"{t}_exists", "yn", f"{name.upper()}: is there a neighbouring boundary to check here?", None),
             (S, f"{t}_on", "yn", "  Is the building ON this boundary (touching it)?", Y(f"{t}_exists")),
             (S, f"{t}_openings", "yn", "  Does the facade facing this boundary have openings (baies)?", Y(f"{t}_exists")),
             (S, f"{t}_L", "m", "  Distance from the building to this boundary (L)", lambda g, t=t: g(f"{t}_exists") is True and g(f"{t}_on") is False),
             (S, f"{t}_HT", "m", "  Height of the construction at this boundary, from the natural ground (HT)", lambda g, t=t: g(f"{t}_exists") is True and g(f"{t}_on") is False)]
FORM += [
 ("UB.9  FOOTPRINT AND OPEN GROUND", "plot_area_m2", "m2", "Total area of the plot (parcelle)", None),
 ("UB.9  FOOTPRINT AND OPEN GROUND", "building_footprint_m2", "m2", "Ground footprint of the buildings (emprise au sol)", None),
 ("UB.9  FOOTPRINT AND OPEN GROUND", "pleine_terre_m2", "m2", "Area kept as open ground (pleine terre)", None),
 ("UB.10 HEIGHT AND LEVELS", "slope_facing_oise", "yn", "Is the plot on sloping land facing the Oise?", None),
 ("UB.10 HEIGHT AND LEVELS", "roof_pitched", "yn", "Does the building have a PITCHED ROOF?", None),
 ("UB.10 HEIGHT AND LEVELS", "height_ridge_m", "m", "  Height at the ridge (faîtage)", Y("roof_pitched")),
 ("UB.10 HEIGHT AND LEVELS", "floors_above_ground_roof_pitched", "n", "  Besides the ground floor (R), how many other full levels (the n in R+n)? Do not count the top level in the roof", Y("roof_pitched")),
 ("UB.10 HEIGHT AND LEVELS", "attic_roof_pitched", "yn", "  Is the LAST (top) level a combles or an attique?", Y("roof_pitched")),
 ("UB.10 HEIGHT AND LEVELS", "roof_flat", "yn", "Does the building have a FLAT ROOF?", None),
 ("UB.10 HEIGHT AND LEVELS", "height_acroterion_m", "m", "  Height at the acrotère (flat roof)", Y("roof_flat")),
 ("UB.10 HEIGHT AND LEVELS", "floors_above_ground_roof_flat", "n", "  Besides the ground floor (R), how many other full levels (the n in R+n)?", Y("roof_flat")),
 ("UB.12 PARKING", "avg_dwelling_sdp_m2", "m2", "Average SDP (surface de plancher) PER LOGEMENT, in m2 (average of one logement)", None),
 ("UB.12 PARKING", "within_500m_station", "yn", "Is the parcel within 500 m of a gare (railway station)?", None),
 ("UB.12 PARKING", "n_dwellings", "n", "Number of logements in the project", None),
 ("UB.12 PARKING", "is_group_or_lotissement", "yn", "Is the project a group of constructions (groupe de constructions) or a lotissement?", None),
 ("UB.12 PARKING", "total_sdp_m2", "m2", "TOTAL SDP of the whole operation, in m2 (all logements together)", None),
 ("UB.12 PARKING", "n_f1_f2_dwellings", "n", "How many of the logements are of type T1 or T2?", None),
 ("UB.12 PARKING", "n_larger_dwellings", "n", "How many of the logements are larger than T2 (T3 or more)?", None),
 ("UB.12 PARKING", "multiple_uses", "yn", "Does the construction have several uses (housing plus shops, offices or activities)?", None),
 ("UB.12 PARKING", "places_provided", "n", "Number of parking places provided by the project", None),
 ("UB.13 OPEN SPACES AND PLANTING", "in_ecological_corridor", "yn", "Is the plot inside the ecological corridor perimeter of the Boulevard du Général de Gaulle?", None),
 ("UB.13 OPEN SPACES AND PLANTING", "corridor_strip_kept", "yn", "  Is a 5 m strip from the parcel boundary kept as open ground and planted with local species?", Y("in_ecological_corridor")),
]
print("Answer each question. Press Enter to keep the previous answer (unknown if none).")
last = None
for section, fact, kind, label, cond in FORM:
    if cond is not None and not cond(PROJECT.get):
        continue
    if section != last:
        print(f"\n===== {section} ====="); last = section
    _ask(fact, label, kind)
print("\nForm complete. Next: run the cell 'Fact-Test Evaluator & Human-in-the-Loop Architect Verification', then the Compliance Report.")
