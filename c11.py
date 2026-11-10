# CELL 11 | Milestone 5 | Schema v1.2: a rule with a status, scope, sources and machine-readable applicability tests
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator

# ---------- Vocabularies (self-contained: this cell replaces Cell 1 from now on) ----------
class Parameter(str, Enum):
    IMPLANTATION_VOIES = "implantation_voies"
    EMPRISE_SOL = "emprise_au_sol"
    HAUTEUR_MAX = "hauteur_maximale"
    NB_NIVEAUX = "nombre_de_niveaux"
    LIMITES_SEPARATIVES = "limites_separatives"
    STATIONNEMENT = "stationnement"
    ESPACES_VERTS = "espaces_verts_pleine_terre"

class RuleKind(str, Enum):
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    EXACT = "exact"
    RANGE = "range"
    FORMULA = "formula"      # e.g. L >= H/2
    PER_UNIT = "per_unit"    # e.g. parking per dwelling
    TEXTUAL = "textual"      # no usable number

class Unit(str, Enum):
    METRE = "m"
    M2 = "m2"
    PERCENT = "%"
    LEVELS = "niveaux"
    SPACES = "places"
    SPACES_PER_DWELLING = "places_par_logement"
    SPACES_PER_100M2 = "places_par_100m2_surface_plancher"
    NONE = "aucune"

class ReviewStatus(str, Enum):
    PENDING = "a_verifier"
    VALIDATED = "valide_par_architecte"
    CORRECTED = "corrige_par_architecte"
    REJECTED = "rejete_par_architecte"

class RegulationStatus(str, Enum):
    REGULATED = "reglemente"                         # the PLU gives a rule
    EXPLICITLY_NOT_REGULATED = "non_reglemente"      # the PLU says "Non réglementé" (different from not found!)
    NOT_FOUND = "non_retrouve"                       # nothing relevant was retrieved

# ---------- Building blocks ----------
class SourceRef(BaseModel):
    """Where a statement comes from. Article and pages are filled by the CODE from the chunk, never by the language model."""
    chunk_id: str
    document: Optional[str] = None
    article: Optional[str] = None
    sub_item: Optional[str] = None
    pdf_pages: List[int] = []
    printed_pages: List[int] = []
    extract: str = Field(..., min_length=1, description="Verbatim text copied from the chunk")
    verified: Optional[bool] = None                  # set by the guardrails (Cell 17)

class Condition(BaseModel):
    description: str
    applies_to: Optional[str] = None
    source: Optional[SourceRef] = None

class FactTest(BaseModel):
    """A condition on ONE project fact, e.g. average dwelling area <= 60. Evaluated by CODE against the project profile, never by the language model."""
    fact: str                                  # a name from the FACTS list (Cell 18)
    op: str                                    # one of: == != < <= > >= is_true is_false
    value: Optional[float] = None
    text: Optional[str] = None                 # the condition in words

class Rule(BaseModel):
    parameter: Parameter
    regulation_status: RegulationStatus

    kind: Optional[RuleKind] = None
    value: Optional[float] = None
    value_max: Optional[float] = None
    unit: Optional[Unit] = None
    formula_text: Optional[str] = None
    summary: Optional[str] = None

    # Who the rule applies to ([] = nothing stated = general)
    applies_to_sectors: List[str] = []               # e.g. ["UBc3"]
    applies_to_building_types: List[str] = []        # e.g. ["logement"]

    conditions: List[Condition] = []
    exceptions: List[Condition] = []
    cross_references: List[str] = []
    unresolved_cross_references: List[str] = []
    ambiguity_flags: List[str] = []
    missing_context: List[str] = []

    # Applicability to the project: tests written from the PLU text, evaluated by code (Cell 21), confirmed by the architect
    applicability_tests: List[FactTest] = []
    applicability_logic: str = "all"            # "all" = every test must hold, "any" = alternatives joined by 'ou'
    needs_other_facts: List[str] = []           # conditions that need a project fact the form does not collect (yet)
    applicable_to_project: Optional[str] = None            # "applies" | "to_confirm" | "not_for_project" (set by Cell 21)
    applicability_confirmed: Optional[bool] = None         # the architect's decision (Cell 21)

    sources: List[SourceRef] = []
    guardrail_issues: List[str] = []                 # filled by Cell 17
    review_status: ReviewStatus = ReviewStatus.PENDING
    architect_note: Optional[str] = None

    @model_validator(mode="after")
    def check_consistency(self):
        s = self.regulation_status
        if s == RegulationStatus.NOT_FOUND:
            if self.value is not None or self.sources:
                raise ValueError("'not found' must not carry a value or sources.")
            return self
        if not self.sources:
            raise ValueError("A rule that is regulated or explicitly 'non réglementé' needs a source with a verbatim extract.")
        if s == RegulationStatus.EXPLICITLY_NOT_REGULATED:
            if self.value is not None:
                raise ValueError("'non réglementé' must not carry a value.")
            return self
        if self.kind is None:
            raise ValueError("A regulated rule needs a 'kind'.")
        if self.kind in (RuleKind.MINIMUM, RuleKind.MAXIMUM, RuleKind.EXACT, RuleKind.PER_UNIT):
            if self.value is None or self.unit is None:
                raise ValueError(f"Kind '{self.kind.value}' requires a value and a unit.")
        if self.kind == RuleKind.RANGE and (self.value is None or self.value_max is None):
            raise ValueError("Kind 'range' requires value and value_max.")
        if self.kind == RuleKind.FORMULA and not self.formula_text:
            raise ValueError("Kind 'formula' requires formula_text.")
        return self

    def auto_comparable(self) -> bool:
        """Conservative: a clear numeric rule, every source verified, nothing open."""
        return (
            self.regulation_status == RegulationStatus.REGULATED
            and self.kind in (RuleKind.MINIMUM, RuleKind.MAXIMUM, RuleKind.EXACT, RuleKind.PER_UNIT)
            and self.value is not None
            and bool(self.sources) and all(src.verified is True for src in self.sources)
            and not self.guardrail_issues
            and not self.conditions and not self.exceptions
            and not self.unresolved_cross_references
            and not self.ambiguity_flags and not self.missing_context
        )

class ParameterResult(BaseModel):
    """Everything found for ONE parameter. A parameter can have several rules (one per sector or building type)."""
    parameter: Parameter
    sector: str
    building_types: List[str] = []
    status: RegulationStatus
    rules: List[Rule] = []
    notes: List[str] = []

    @model_validator(mode="after")
    def check_result(self):
        if self.status == RegulationStatus.NOT_FOUND and self.rules:
            raise ValueError("A result 'not found' cannot contain rules.")
        if self.status != RegulationStatus.NOT_FOUND and not self.rules:
            raise ValueError("A result that is not 'not found' needs at least one rule.")
        return self

# ---------- Quick tests (dummy data: invented, not a real PLU) ----------
src = SourceRef(chunk_id="DUMMY#1", extract="Texte factice servant uniquement au test.")
ok = Rule(parameter=Parameter.HAUTEUR_MAX, regulation_status=RegulationStatus.REGULATED,
          kind=RuleKind.MAXIMUM, value=9.0, unit=Unit.METRE, sources=[src])
print("A regulated rule accepted. auto_comparable BEFORE verification:", ok.auto_comparable(), "(expected False: not verified yet)")

nr = Rule(parameter=Parameter.NB_NIVEAUX, regulation_status=RegulationStatus.EXPLICITLY_NOT_REGULATED, sources=[src])
print("Explicit 'non réglementé' accepted:", nr.regulation_status.value)

for label, build in [
    ("regulated rule without source", lambda: Rule(parameter=Parameter.EMPRISE_SOL, regulation_status=RegulationStatus.REGULATED, kind=RuleKind.MAXIMUM, value=40, unit=Unit.PERCENT)),
    ("'non réglementé' carrying a value", lambda: Rule(parameter=Parameter.EMPRISE_SOL, regulation_status=RegulationStatus.EXPLICITLY_NOT_REGULATED, value=40, sources=[src])),
    ("'not found' carrying a source", lambda: Rule(parameter=Parameter.EMPRISE_SOL, regulation_status=RegulationStatus.NOT_FOUND, sources=[src])),
    ("result 'not found' with a rule", lambda: ParameterResult(parameter=Parameter.EMPRISE_SOL, sector="UB", status=RegulationStatus.NOT_FOUND, rules=[ok])),
]:
    try:
        build(); print("ERROR, should have been rejected:", label)
    except Exception:
        print("Correctly rejected:", label)

pr = ParameterResult(parameter=Parameter.HAUTEUR_MAX, sector="UB", status=RegulationStatus.REGULATED, rules=[ok])
ft = FactTest(fact="avg_dwelling_sdp_m2", op="<=", value=60, text="dwelling of 60 m2 or less")
rt = Rule(parameter=Parameter.STATIONNEMENT, regulation_status=RegulationStatus.REGULATED, kind=RuleKind.MINIMUM, value=1, unit=Unit.SPACES_PER_DWELLING,
          sources=[src], applicability_tests=[ft])
print("A rule with an applicability test accepted:", rt.applicability_tests[0].fact, rt.applicability_tests[0].op, rt.applicability_tests[0].value)
print("ParameterResult accepted with", len(pr.rules), "rule(s). Schema v1.2 ready.")