"""House policy — the design answers the operator has actually given.

Principle 2.1: a decision that matters exists on disk, not in a chat log. Every value
here was DECIDED by the operator on 2026-08-03 in answer to a specific advisory
gap, and each records which gap it closes.

These are DEFAULTS THE AGENT PROPOSES, never constraints it enforces. Engagement A's
publisher ranking is not engagement B's — the operator was explicit that "the level of
trust per publisher will vary on each company". So the agent applies these when the
design is silent, and always shows what it applied.
"""
from __future__ import annotations

from agent.ir.schema import ThresholdPolicy

# ------------------------------------------------------------- physical naming
# A REPOSITORY limit, not a house preference — it is the product that refuses. It
# applies to the GENERATED column name, which for a complex-type member is the complex
# attribute's 3-character prefix, an underscore, and the member's own physical name.
# Lives here rather than in validate.py so there is one copy of the number.
MAX_PHYSICAL_NAME = 25


# --------------------------------------------------------------------- matching
# Closes CA-008. Stated as three bands, not nine numbers:
#
#   95–100  trusted entirely      -> auto-promote (auto-merge, no human)
#   80–94   suspected             -> a human confirms before the merge stands
#   < 80    not a match           -> never merged, never queued
#
# The operator's phrasing: "what I can entirely trust is close to 95-100 and I could
# auto-promote, I can suspect about something matching but I need to confirm 80-94,
# everything else should not be considered as a match".
HOUSE_THRESHOLDS = ThresholdPolicy(auto_merge_at=95, review_from=80)

# ---------------------------------------------------------- match rule scoring
# HOW xDM ACTUALLY SCORES, verified against docs/ and the vendor training material,
# because the design rule below only makes sense once this is understood:
#
#   pair score        the HIGHEST score among all rules that matched that pair.
#                     Rules of 100, 95 and 90 all firing gives the pair 100.
#   transitive pairs  A-B and B-C matched, A-C did not. The score is treated as a
#                     PROBABILITY and multiplied: 0.9 x 0.9 = 0.81 -> 81.
#   group confidence  the AVERAGE of every pair score in the group.
#                     (90 + 90 + 81) / 3 = 87.
#   thresholds        apply to the GROUP CONFIDENCE, not to the pair score.
#
# The operator's rule, and it is right:
#
#   "match rules should qualify the matching... I don't see a need for different name
#    different address score 1 or 10. If the score doesn't land in the suspect band it
#    is not a match, why pull the avg down?"
#
# At the PAIR level a weak rule is harmless, because max wins. At the GROUP level it is
# actively destructive, in two compounding ways:
#
#   1. It MANUFACTURES PAIRS that would not otherwise exist, and every manufactured
#      pair enters the average. One 10-scoring pair beside two genuine 100s gives
#      (100 + 100 + 10) / 3 = 70 — which is below the review band, so a group holding
#      two certain duplicates stops being reviewable AT ALL.
#   2. Transitivity drags a third record into the group on the strength of that weak
#      link, and its transitive pairs — themselves multiplied down — are averaged in too.
#
# So a below-band rule does not add noise. It HIDES REAL DUPLICATES by demoting the
# groups that contain them. Every rule must be able, on its own, to put a pair into the
# reviewable band; a rule that cannot is contributing only downward pressure.
MATCH_RULE_SCORE_FLOOR = HOUSE_THRESHOLDS.review_from


# A singleton is a golden record with exactly one master — nothing matched it, so
# there is no merge decision to make.
#
# DEFAULT TRUE, corrected 2026-08-03. The first version of this file defaulted to
# False on the grounds that it "costs steward time rather than silence". The operator
# rejected that reasoning:
#
#   "If we have the right validations in place and the data is robust enough, why have
#    people just clicking on confirm after reading? We should promote robust
#    certification process to encourage auto-confirmed/enabled-singletons."
#
# That is right, and the conservative default was worse than it looked. A steward
# confronted with every unmatched record cannot meaningfully assess any of them; they
# click confirm. That is not review — it manufactures an audit trail that says a human
# checked, and it spends the attention that belongs on the 80-94 band, which is the
# only place a human adds information a rule could not.
#
# The trust has to be EARNED, and that is checkable rather than assumed: CA-014 fires
# when singletons are auto-confirmed into a certification process with nothing in it
# to catch a bad record. The question moves from "do you trust this record?" to "have
# you built the thing that earns the trust?".
AUTO_CONFIRM_SINGLETONS = True

# What "robust enough" means, stated so the advisor can check it rather than assert it.
# Each is something the IR can actually see.
ROBUSTNESS_REQUIREMENTS = (
    "at least one PRE_CONSO validation, so a malformed record is rejected at the "
    "source rather than confirmed as golden",
    "mandatory attributes enforced at a scope, not merely flagged",
    "match inputs and binning keys normalized (CA-004, CA-013)",
)


# ---------------------------------------------------------------- survivorship
# Closes CA-002. The operator distinguished attributes by WHERE THE VALUE COMES FROM,
# not by datatype:
#
#   "Override applies only for text fields mainly for user edits, calculated columns
#    like enriched IDs (external), API results shouldn't be editable (do not override)"
#
# So the question "may a steward's edit override consolidation?" has two answers, and
# which one applies is a property of the attribute's provenance.
OVERRIDE_ALLOWED = "UNTIL_NEXT_USER_CHANGE"   # a steward edit sticks until they change it
OVERRIDE_FORBIDDEN = "NO_OVERRIDE"            # the pipeline owns this value
#: A steward edit survives until CONSOLIDATION itself moves the value — the
#: change-of-address case, where the edit should stand until the sources genuinely say
#: something new rather than until the steward touches it again.
OVERRIDE_UNTIL_CONSOLIDATED = "UNTIL_CONSOLIDATED_VAL_CHANGE"

# The observed vocabulary.
#
# The first two were PROBED against the live importer one constant at a time on
# 2026-08-04, because the corpus available then carried a null `overrideStrategy` in
# every instance — nothing was there to read, and `NEVER` was an invention that survived
# every offline check until the importer refused the whole payload (LESSONS §16).
#
# `UNTIL_CONSOLIDATED_VAL_CHANGE` was added on 2026-08-06 on DIFFERENT and stronger
# evidence: the corpus grew, and the value now appears in exports THE PRODUCT ITSELF
# WROTE. Measured across samples/, live/ and harvest/ —
#
#     samples/gs-customerb2c-2025.1.0.xml      6
#     harvest/CustomerB2CDemo.workflow.xml     6   (the same model, re-exported)
#     samples/corpus-a-org-mdm-0.1.xml         1
#
# 13 occurrences across three exports of two distinct models. That is the same class of
# evidence as a harvested block shape, and it is why the §16 claim that all 42 instances
# are null is now stale rather than wrong-at-the-time.
#
# NOTE the near-miss that makes the spelling matter: the 2026-08-04 probe REFUSED
# `UNTIL_CONSOLIDATED_VALUE`, which is a different and shorter string. The value below is
# the one the product writes, character for character, and it was not guessed from the
# UI label.
#
# CONFIRMED AGAINST THE LIVE IMPORTER, 2026-08-06: a model carrying it on two
# survivorship rules imported at 204 on the training instance and came back out of the
# export with both values intact. So this constant has BOTH kinds of evidence the other
# two have separately — the product writes it, and the importer accepts it.
#
# The fourth UI option — "Always Authored in the MDM" — still has no known constant. It
# is NOT guessed: this tuple holds only what has been probed or observed.
OVERRIDE_STRATEGIES = ("NO_OVERRIDE", "UNTIL_NEXT_USER_CHANGE",
                       "UNTIL_CONSOLIDATED_VAL_CHANGE")


def override_strategy(*, computed: bool) -> str:
    """`computed` means the value is produced by an enricher, an external API or an
    integration — not typed by a person. Those are not editable, so an override would
    be a value the next run silently discards."""
    return OVERRIDE_FORBIDDEN if computed else OVERRIDE_ALLOWED


# ---------------------------------------------------------------- retention
# The operator's ruling, 2026-08-08, retiring the FOREVER default that left every
# KILLED workflow instance in the history permanently (decisions watches
# RetentionPolicy.retention_type; FOREVER was the ungoverned answer). Retention is a
# function of THROUGHPUT, because the cost FOREVER ignores is storage and storage
# pressure IS volume:
#
#   "increasing volumes by thousands daily then retention 90 days, millions then 30"
#
#   >= 1,000,000 records/day   ->  30 DAYS   (millions: storage-bound, aggressive)
#   >=     1,000 records/day   ->  90 DAYS   (thousands: the base governed tier)
#
# Below the thousands tier the operator carved out no third rule, so the base 90-day
# tier applies rather than an invented longer window OR a return to FOREVER — the point
# of the ruling is that nothing is retained forever by default. Higher volume shortens
# retention, not lengthens it, which is the counter-intuitive-but-correct direction:
# the more you accumulate per day, the sooner old rows have to age out.
RETENTION_UNIT = "DAYS"
RETENTION_TIERS = ((1_000_000, 30), (1_000, 90))   # (daily volume floor, days), descending
RETENTION_BASE_DAYS = 90


def retention_days(daily_volume: int | None = None) -> int:
    """Days to retain, from expected daily throughput. `None` (volume not yet known)
    takes the base tier — a governed default, never FOREVER."""
    for floor, days in RETENTION_TIERS:
        if daily_volume is not None and daily_volume >= floor:
            return days
    return RETENTION_BASE_DAYS


# "Steward authored data should be more trustable." Consolidation therefore ranks
# publishers, with the steward/manual publisher first. The REST of the ranking is
# engagement-specific and must be asked for — this only fixes the top of the list.
STEWARD_RANKS_FIRST = True

# Publisher codes that mean "a person typed this". Matched case-insensitively against
# the publisher code; extend per engagement rather than guessing new ones.
STEWARD_PUBLISHER_CODES = ("STEWARD", "MANUAL", "UI", "XDM", "DATA_STEWARD")


def is_steward_publisher(code: str) -> bool:
    return code.strip().upper() in STEWARD_PUBLISHER_CODES


# "The users will like to choose which data to survive, so they should be able to
# select from matching records (optional)." That is not a survivorship strategy — it is
# a duplicate-manager setting, and xDM already has it. Observed in all four sample
# DupsManagers as enableMasterValuePicking=true.
MASTER_VALUE_PICKING = True


# --------------------------------------------------------------------- stewarding
# Closes CA-003. The operator scoped the MVP explicitly:
#
#   "MVP a screen (App business view) presenting the pending items for confirmation."
#
# So a business view over pending items SATISFIES the gap at MVP. The fuller shape
# discussed earlier — a duplicate manager, a workflow assigning tasks, and email
# reminders for unattended items — remains the target, but is not what MVP requires.
#
# CORPUS_A already contains the pattern: OrganizationStewardView, filtered on
# HasSuggestedMerge = '1'.
STEWARD_QUEUE_FILTERS = ("HasSuggestedMerge", "ConfirmationStatus", "MastersCount")


# ------------------------------------------------------------------ view types
# The seven data sets a business view can be opened against
# (docs/Design/applications/application-actions-and-folders.md § Browse Business View).
# `viewType` is a property of the MENU ACTION, not of the view, so the same business
# view opened twice can show two different data sets.
VIEW_TYPES = {
    "GD": "Golden Data — the data certified in the hub",
    "GDWE": "Golden Data With Errors — golden data flagged as erroneous",
    "MD": "Master Data — latest records from source systems",
    "SA": "Source Authoring — records directly authored by users",
    "SAWE": "Source Authoring With Errors",
    "SD": "Source Data — loaded from source systems or authored by users",
    "SDWE": "Source Data With Errors — rejected by the validations",
}

# Master records only exist for ID- and fuzzy-matched entities, so these two modes are
# meaningless on a Basic entity. Stated by the docs twice: "Master Data is the latest
# records from source systems (for ID- and fuzzy-matched entities)" and, for GDWE,
# "ID- and fuzzy-matched entities only".
VIEW_TYPES_NEEDING_MATCHING = ("MD", "GDWE")

# CORRECTED 2026-08-03, same day, after navigating properly.
#
# The first version of this note claimed "a curated collection does not govern what an
# error view shows", from a screen showing `Load ID, <PK>, Name, Address, Street1,
# Street2, County` against a collection defining ten different columns.
#
# THAT SCREEN WAS NOT A BUSINESS VIEW. It was the ENTITIES BROWSER — the surface
# BrowseEntitiesFolderAction opens, which lists the seven data sets as folders and
# renders a GENERIC per-entity column set. I read a title of "Fuzzy Prove" as the
# business view when the business view is titled "Business View1".
#
# Opened properly, the business view renders EXACTLY the collection's TableColumns:
# Name, Array Of Items, Normalized Name, Masters Count, Is Confirmed, Phonetic…
#
# So the actual rule, and it is the reassuring one:
#   business view  -> the collection's TableColumns govern
#   Entities browser -> a generic set the model does not control
COLLECTION_GOVERNS_BUSINESS_VIEWS = True

# What DOES change with viewType, observed on the same view opened as GDWE: the
# available ACTIONS. An errors view offers Export, Select all, Refresh, Select columns
# and Sort — no Create, no authoring. Authoring lives on Golden Data. So viewType
# decides whether a screen can be authored into, which is the real constraint behind
# CA-016.
AUTHORING_VIEW_TYPES = ("GD", "SA")


# ---------------------------------------------------------------- normalization
# Closes CA-004: "normalize first as much as possible. Including trimming."
#
# Every match input gets a PRE_CONSO normalizer. TRIM is the floor, not the ceiling —
# these are the transforms to propose per attribute class, in order.
NORMALIZE_ALWAYS = ("TRIM",)
NORMALIZE_BY_KIND = {
    "name":    ("TRIM", "UPPER", "collapse-internal-whitespace", "strip-punctuation"),
    "email":   ("TRIM", "LOWER"),
    "phone":   ("TRIM", "digits-only"),
    "address": ("TRIM", "UPPER", "collapse-internal-whitespace"),
    "id":      ("TRIM", "UPPER"),
    "text":    ("TRIM",),
}


def normalizers_for(attribute_name: str) -> tuple[str, ...]:
    """A proposal, from the attribute's name. The designer overrides it; the point is
    that the default is never 'compare the raw value'."""
    n = attribute_name.lower()
    for kind, steps in NORMALIZE_BY_KIND.items():
        if kind in n:
            return steps
    if any(k in n for k in ("mail",)):
        return NORMALIZE_BY_KIND["email"]
    if any(k in n for k in ("tel", "mobile", "fax")):
        return NORMALIZE_BY_KIND["phone"]
    if any(k in n for k in ("street", "city", "zip", "postal", "addr")):
        return NORMALIZE_BY_KIND["address"]
    return NORMALIZE_ALWAYS
