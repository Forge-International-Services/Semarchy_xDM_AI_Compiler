"""Sprint 04 acceptance: IR schema and semantic validation.

Every rule gets a positive and a negative case. The positive case for all of them
is the hand-authored example, which must validate silently.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.ir.schema import IR, Attribute, Enricher, MatchRule, ModelIR  # noqa: E402
from agent.ir.validate import errors, validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "agent" / "ir" / "examples"


@pytest.fixture
def ir():
    return IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")


def rules(issues):
    return {i.rule for i in issues}


# ------------------------------------------------------------------- positive
def test_hand_authored_example_validates_silently(ir):
    assert validate(ir) == []


def test_example_is_readable(ir):
    """D3's claim is a ~200-line spec instead of a 1.4 MB export."""
    total = sum(len((EX / f).read_text().splitlines())
                for f in ("customer_model.yaml", "customer_certify.yaml"))
    assert total < 200


def test_scenarios_1_and_2_are_expressible():
    """Basic reference data, and ID-matched with a shared key."""
    basic = ModelIR(model={"name": "RefData"},
                    entities=[{"name": "Country", "type": "basic",
                               "attributes": [{"name": "Code", "type": "String", "pk": True}]}])
    assert validate(IR(model_ir=basic)) == []
    idm = ModelIR(model={"name": "Hub"},
                  publishers=[{"name": "Crm", "code": "CRM"}],
                  entities=[{"name": "Party", "type": "id_matched",
                             "attributes": [{"name": "PartyId", "type": "Integer", "pk": True}]}])
    assert validate(IR(model_ir=idm)) == []


# ------------------------------------------------------------------- negative
def test_ir001_fuzzy_entity_without_a_matcher(ir):
    ir.certify.matchers = []
    assert "IR-001" in rules(errors(validate(ir)))


def test_ir002_basic_entity_with_survivorship(ir):
    ir.model_ir.entities[0].type = "basic"
    assert "IR-002" in rules(errors(validate(ir)))


def test_ir003_id_matched_entity_with_a_composite_key(ir):
    e = ir.model_ir.entities[0]
    e.type = "id_matched"
    e.attributes.append(Attribute(name="SubId", type="Integer", pk=True))
    ir.certify.matchers = []
    assert "IR-003" in rules(errors(validate(ir)))


def test_ir004_two_matchers_on_one_entity(ir):
    ir.certify.matchers.append(copy.deepcopy(ir.certify.matchers[0]))
    assert "IR-004" in rules(errors(validate(ir)))


def test_ir005_record1_and_record2_on_the_same_side(ir):
    ir.certify.matchers[0].rules[0].condition = "Record1.Email = Record1.Email"
    assert "IR-005" in rules(errors(validate(ir)))


def test_ir006_lowercase_publisher_code(ir):
    ir.model_ir.publishers[0].code = "crm"
    assert "IR-006" in rules(errors(validate(ir)))


def test_ir007_undeclared_complex_type(ir):
    ir.model_ir.complex_types = []
    assert "IR-007" in rules(errors(validate(ir)))


def test_ir013_undeclared_lov_used_as_an_attribute_type(ir):
    """An LOV-typed attribute names the LOV as its type — there is no separate
    `lov` field, because xDM has only one way to express this."""
    ir.model_ir.lov_types = []
    assert "IR-013" in rules(errors(validate(ir)))


def test_ir008_reference_to_an_unknown_entity(ir):
    ir.certify.enrichers[0].entity = "NoSuchEntity"
    assert "IR-008" in rules(errors(validate(ir)))


def test_ir009_post_conso_enricher_feeding_a_match_rule(ir):
    """The rule that earns its keep: invisible at import, bad matches months later."""
    ir.certify.enrichers[0].scope = "POST_CONSO"
    issues = errors(validate(ir))
    assert "IR-009" in rules(issues)
    why = next(i for i in issues if i.rule == "IR-009").why
    assert "master records" in why


def test_ir010_unbinned_probabilistic_rule_warns(ir):
    ir.certify.matchers[0].rules[1].binning = []
    issues = validate(ir)
    assert "IR-010" in rules(issues) and not errors(issues)


def test_ir010_is_silenced_by_an_acknowledged_justification(ir):
    r = ir.certify.matchers[0].rules[1]
    r.binning, r.justification, r.acknowledged = [], "conflict rule, must be global", True
    assert "IR-010" not in rules(validate(ir))


def test_ir011_preferred_publisher_without_rankings(ir):
    ir.certify.survivorship[0].publisher_rankings = []
    assert "IR-011" in rules(errors(validate(ir)))


def test_ir012_rule_disabled_via_1_equals_0_is_flagged(ir):
    ir.certify.matchers[0].rules[0].condition = "1 = 0"
    assert "IR-012" in rules(validate(ir))


def test_ir013_unknown_datatype(ir):
    ir.model_ir.entities[0].attributes[1].type = "Varchar2"
    assert "IR-013" in rules(errors(validate(ir)))


def test_ir013_reserved_word_as_attribute_name(ir):
    ir.model_ir.entities[0].attributes.append(Attribute(name="Between", type="String"))
    assert "IR-013" in rules(errors(validate(ir)))


def test_ir014_undeclared_external_udf(ir):
    ir.certify.enrichers[0].expressions[0].expression = \
        "HUB_SCHEMA_DEV.SHARED.UDF_DOUBLE_METAPHONE(FullName)"
    assert "IR-014" in rules(validate(ir))


def test_ir014_is_silenced_by_declaring_the_dependency(ir):
    ir.certify.enrichers[0].expressions[0].expression = \
        "HUB_SCHEMA_DEV.SHARED.UDF_DOUBLE_METAPHONE(FullName)"
    ir.model_ir.external_dependencies = ["HUB_SCHEMA_DEV.SHARED.UDF_DOUBLE_METAPHONE"]
    assert "IR-014" not in rules(validate(ir))


def test_ir015_form_step_enricher_must_not_set_scope(ir):
    ir.certify.enrichers.append(Enricher(entity="Customer", name="F", kind="form_step",
                                         scope="PRE_CONSO"))
    assert "IR-015" in rules(errors(validate(ir)))


# ----------------------------------------------------------------- structural
def test_typo_in_a_field_name_is_rejected_not_dropped():
    with pytest.raises(ValidationError):
        Attribute(name="X", type="String", lenght=10)     # noqa: typo intended


def test_match_score_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        MatchRule(name="R", score=140, condition="a = b")


def test_issue_render_carries_rule_reason_and_source(ir):
    ir.certify.enrichers[0].scope = "POST_CONSO"
    text = next(i for i in validate(ir) if i.rule == "IR-009").render()
    assert "IR-009" in text and "see:" in text and "master records" in text


# ------------------------------------------- IR-017: SemQL parses offline (sprint 08b)
def test_semql_is_sql_and_the_whole_delta_is_one_construct():
    """docs/SemQL/semql-syntax.md: "the equivalent of SQL expressions, conditions or
    ORDER BY clauses". Measured, not assumed: every SemQL phrase in all three samples
    parses once the ANY|ALL <role> HAVE quantifier is rewritten."""
    from xml.etree import ElementTree as ET
    from agent.tools.semql import check
    TAGS = {"expression": "expression", "condition": "condition",
            "semQLCondition": "condition", "filter": "condition",
            "primaryTextExpression": "expression", "sortExpression": "order_by",
            "visibleInFormTabCondition": "condition"}
    bad = []
    for path in (ROOT / "samples").glob("*.xml"):
        for el in ET.parse(path).getroot().iter():
            if el.tag in TAGS and el.text and el.text.strip():
                bad += check(el.text, TAGS[el.tag], f"{path.name}:{el.tag}")
    assert bad == [], [b.render() for b in bad[:3]]


def test_the_quantifier_is_the_one_thing_plain_sql_cannot_parse():
    import sqlglot
    from agent.tools.semql import check, normalize
    q = "ANY Items HAVE ( UPC IS NOT NULL )"
    with pytest.raises(Exception):
        sqlglot.parse_one(q, read="snowflake")     # plain SQL cannot
    assert check(q, "condition") == []             # SemQL-aware can
    assert "SEM_QUANT_ANY_Items" in normalize(q)


def test_an_error_inside_a_quantifier_is_still_caught():
    """The rewrite must preserve the inner condition, or it becomes a blind spot that
    silently accepts anything between the brackets."""
    from agent.tools.semql import check
    assert check("ANY Items HAVE ( UPC IS NOT )", "condition")
    assert check("ANY Items HAVE ( UPC IS NOT NULL", "condition")


def test_order_by_is_not_parsed_as_an_expression():
    """A ranking expression takes commas, ASC/DESC and NULLS LAST — all illegal in a
    plain expression. Parsing it as one reports a spurious error at the first comma."""
    from agent.tools.semql import check
    assert check("Country DESC NULLS LAST", "order_by") == []
    assert check("Name, lpad(Size, 2, '0')", "order_by") == []
    assert check("Name, lpad(Size, 2, '0')", "expression")      # not an expression


def test_broken_semql_blocks_compilation():
    from agent.ir.validate import validate
    ir = IR.load(ROOT / "out/s3-three-sources/ir/model.yaml",
                 ROOT / "out/s3-three-sources/ir/certify.yaml")
    assert [i for i in validate(ir) if i.rule == "IR-017"] == []
    ir.certify.enrichers[0].expressions[0].expression = "UPPER(TRIM(FullName)"
    hit = [i for i in validate(ir) if i.rule == "IR-017"]
    assert hit and hit[0].severity == "error"
    assert "NormalizeName" in hit[0].where


def test_the_semql_check_is_syntax_only_and_says_so():
    """A typo'd attribute name parses fine. Claiming otherwise would be the worst kind
    of false confidence — the check must not be mistaken for xDM's validation."""
    from agent.tools.semql import check
    assert check("UPPER(TRIM(Custmer))", "expression") == []


def test_an_aggregate_in_an_enricher_is_caught_before_it_suspends_the_queue():
    """OBSERVED LIVE 2026-08-03. An enricher expression of JSONB_OBJECT_AGG('a', 1)
    generated a per-row SELECT with no GROUP BY, the database rejected it, and the
    whole integration queue SUSPENDED — which then blocked redeployment until the batch
    was cancelled.

    It is syntactically valid SQL, so the parser accepts it. xDM does not catch it
    either: its SemQL editor warns on unknown FUNCTION NAMES but passes them through,
    and JSONB_OBJECT_AGG raised no warning at all because the name is known."""
    from agent.tools.semql import check
    hit = check("JSONB_OBJECT_AGG('a', 1)", "expression")
    assert hit and "aggregate function JSONB_OBJECT_AGG" in hit[0].message
    assert "JSONB_BUILD_OBJECT" in hit[0].message      # names the row-level fix
    assert check("JSONB_BUILD_OBJECT('a', 1)", "expression") == []


def test_ordinary_scalar_functions_are_not_mistaken_for_aggregates():
    from agent.tools.semql import check
    for expr in ("SEM_NORMALIZE(Name)", "UPPER(TRIM(Name))", "METAPHONE(Name, 32)",
                 "COALESCE(A, B)", "SUBSTR(Zip, 1, 5)"):
        assert check(expr, "expression") == [], expr


def test_an_aggregate_is_legal_in_a_ranking_expression():
    """A survivorship ranking IS an ORDER BY, where aggregates are not the same
    mistake. Only row-level expressions are rejected."""
    from agent.tools.semql import check
    assert check("MAX(UpdateDate) DESC", "order_by") == []
    assert check("MAX(UpdateDate)", "expression")


def test_every_sample_expression_still_passes_the_aggregate_check():
    """The guard against a false positive: no real expression in any sample uses an
    aggregate, so adding this check must not reject anything that already worked."""
    from xml.etree import ElementTree as ET
    from agent.tools.semql import aggregates_in
    for path in (ROOT / "samples").glob("*.xml"):
        for el in ET.parse(path).getroot().iter():
            if el.tag in ("expression", "condition") and el.text:
                assert aggregates_in(el.text) == [], f"{path.name}: {el.text[:60]}"


# ------------------------------- IR-023: match rules below the review band (2026-08-04)
def test_a_match_rule_below_the_review_band_warns():
    """The operator's rule: "if the score doesn't land in the suspect band it is not a
    match, why pull the avg down?"

    Verified mechanism (docs/ + vendor training): a PAIR takes the HIGHEST score of the
    rules that matched it, so a weak rule is harmless there. But the GROUP CONFIDENCE is
    the AVERAGE of pair scores, and transitive pairs are multiplied down (0.9 x 0.9 =
    81). So a weak rule manufactures pairs that enter that average and drags extra
    records into the group.

    (100 + 100 + 10) / 3 = 70 — a group holding two CERTAIN duplicates falls out of the
    review band entirely. The rule does not add noise; it hides real duplicates.
    """
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    ir.certify.matchers[0].rules[0].score = 10
    issues = [i for i in validate(ir) if i.rule == "IR-023"]
    assert issues and issues[0].severity == "warning"
    assert "AVERAGE" in issues[0].why


def test_acknowledging_it_silences_it():
    """A deliberately low rule used only for grouping is conceivable; saying so out loud
    is the price."""
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    ir.certify.matchers[0].rules[0].score = 10
    ir.certify.matchers[0].rules[0].acknowledged = True
    assert not [i for i in validate(ir) if i.rule == "IR-023"]


def test_the_floor_follows_the_matcher_not_the_house_default():
    """An engagement that sets its own review band moves the floor with it."""
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    m = ir.certify.matchers[0]
    if m.policy is None:
        pytest.skip("example matcher states raw thresholds")
    m.policy.review_from = 60
    m.rules[0].score = 70
    assert not [i for i in validate(ir) if i.rule == "IR-023"], \
        "70 is above a 60 band; the floor must track the matcher's own policy"


# --------------------------------------------- IR-026: the generator and the key type
#
# The rule is MEASURED. `test_the_corpus_actually_says_so` is the one that matters: if a
# future export pairs a UUID key with SEQUENCE, the rule is wrong and this test says so
# before the scenarios do.
def test_a_uuid_key_with_a_sequence_generator_is_refused():
    """s3's ninth defect, and s4 carried it latent until the rule existed.

    SEQUENCE emits nextval() into a uuid column. Nothing rejects that at import or at
    deploy — the failure is the INTEGRATE_DATA job, which then suspends the queue and
    makes the NEXT redeploy refuse too.
    """
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    e = ir.model_ir.entities[0]
    pk = next(a for a in e.attributes if a.pk)
    pk.type = "UUID"
    e.golden_id_generation = "SEQUENCE"
    issues = [i for i in validate(ir) if i.rule == "IR-026"]
    assert issues and issues[0].severity == "error"
    assert "nextval" in issues[0].why
    assert issues in ([],) or issues[0] in errors(validate(ir)), "IR-026 must block"


def test_the_converse_is_refused_too():
    """A UUID generator on a String key is equally unattested, and the corpus is the
    only reason to believe either direction."""
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    e = ir.model_ir.entities[0]
    pk = next(a for a in e.attributes if a.pk)
    pk.type, e.golden_id_generation = "String", "UUID"
    assert [i for i in validate(ir) if i.rule == "IR-026"]


def test_a_string_key_with_a_sequence_generator_is_fine():
    """The rule must NOT over-fire. 20 of the 26 measured PKs are exactly this pair, so
    refusing it would refuse most of the corpus — and scenario 4's Opportunity."""
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    e = ir.model_ir.entities[0]
    next(a for a in e.attributes if a.pk).type = "String"
    e.golden_id_generation = "SEQUENCE"
    assert not [i for i in validate(ir) if i.rule == "IR-026"]


def test_the_corpus_actually_says_so():
    """The evidence, re-measured. IR-026 is a claim about what the PRODUCT writes, so
    it is checked against the product's own exports rather than against this compiler
    (house rule: verify against what the product writes).

    If this fails, IR-026 is the thing to change — not the corpus.
    """
    from xml.etree import ElementTree as ET

    from agent.compile.registry import PLATFORM_TYPES

    def tx(el, tag):
        c = el.find(tag)
        if c is None or c.get("null") == "true":
            return None
        return c.get("val") if c.get("val") is not None else (c.text or None)

    exports = [f for d in ("samples", "live", "harvest")
               for f in sorted((ROOT / d).glob("*.xml"))]
    if not exports:
        # The public export ships no product-authored model export. An empty scan here
        # would fail on "check the instrument", which would be a true statement about
        # the tree and a misleading one about IR-026.
        pytest.skip("samples/, live/ and harvest/ product exports not present")

    pairs = []
    for f in exports:
        root = ET.parse(f).getroot()
        for pk in root.iter("PKAttribute"):
            ref = pk.find("abstractAtomicType")
            dt = PLATFORM_TYPES.get(ref.get("ref")) if ref is not None else None
            gen = tx(pk, "fuzzyMatchedEntityGoldenIdGenerationType")
            if dt and gen:
                pairs.append((dt, gen))

    assert len(pairs) >= 20, f"only {len(pairs)} PKs measured — check the instrument"
    for dt, gen in pairs:
        assert (dt == "UUID") == (gen == "UUID"), \
            f"corpus pairs a {dt} key with {gen}: IR-026's biconditional is wrong"


# ------------------------------------------------------ CA-017: the model grants nothing
def test_a_model_that_grants_nothing_is_asked_about():
    """The hole was exactly at zero: CA-011 only speaks once a grant exists, so the one
    model where every read is refused produced no gap at all."""
    from agent.ir.advise import advise
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    ir.model_ir.roles = []
    gaps = [g for g in advise(ir) if g.rule == "CA-017"]
    assert gaps, "a model with no privilege grant must raise CA-017"
    assert "200" in gaps[0].consequence, \
        "the consequence must name the silent register — HTTP 200, empty enrichedRecord"


def test_a_model_that_grants_something_is_not():
    from agent.ir.advise import advise
    from agent.ir.schema import Role
    ir = IR.load(EX / "customer_model.yaml", EX / "customer_certify.yaml")
    ir.model_ir.roles = [Role(name="admin", role_name="semarchyAdmin", data_admin=True)]
    assert not [g for g in advise(ir) if g.rule == "CA-017"]


def test_an_lov_only_model_is_not_asked():
    """Scenario 1 has no entities, so there is nothing to grant a privilege ON. A gap
    rule that fires on a model with no data is noise."""
    from agent.ir.advise import advise
    ir = IR.load(ROOT / "out/s1-country-reference/ir/model.yaml")
    assert not ir.model_ir.entities
    assert not [g for g in advise(ir) if g.rule == "CA-017"]


# ------------------------------------------- IR-030: the job is the executable half
#
# The rule exists because scenario 4 reached DL_READY, staged twelve records into a
# load, and was refused at SUBMIT with "Job [INTEGRATE_DATA] does not exist. Known
# jobs are []" (LESSONS §54). Three offline layers had passed it: `blocks` sees no
# malformed element because there is no element, `decisions` attributes no value
# because there is no field, and `depends` orders enrichers within an entity.
def _no_jobs(ir):
    ir.certify.jobs = []
    return ir


def test_a_certification_design_with_no_job_is_refused(ir):
    """The positive case for the whole rule, and s4's actual defect."""
    issues = [i for i in validate(_no_jobs(ir)) if i.rule == "IR-030"]
    assert issues and issues[0].severity == "error"
    assert "Known jobs are []" in issues[0].why
    assert issues[0] in errors(validate(ir)), "IR-030 must block, not advise"


def test_a_model_only_ir_is_not_asked_for_a_job():
    """`extract` on a vendor export produces exactly this, and it is a legitimate
    artefact. A rule that refused it would refuse the thing the extractor is for."""
    model_only = IR(model_ir=IR.load(EX / "customer_model.yaml").model_ir)
    assert not [i for i in validate(model_only) if i.rule == "IR-030"]


def test_an_entity_outside_every_job_is_refused(ir):
    """A job that covers one of two entities is the harder shape: there IS a job, so
    the existence check passes and the records still never get certified."""
    ir.certify.jobs[0].tasks = []
    issues = [i for i in validate(ir) if i.rule == "IR-030"]
    assert issues and "no INTEGRATION job task covers" in issues[0].message


def test_a_matcher_the_job_never_runs_is_refused(ir):
    """The silent half (§54.3). Nothing merges and every editor reads as correct."""
    ir.certify.jobs[0].tasks[0].match = False
    assert [i for i in validate(ir)
            if i.rule == "IR-030" and "match: false" in i.message]


def test_preconso_enrichers_with_source_enrichment_off_are_refused(ir):
    ir.certify.jobs[0].tasks[0].source_enrichment = False
    assert [i for i in validate(ir)
            if i.rule == "IR-030" and "source_enrichment" in i.message]


def test_the_example_job_is_silent(ir):
    """The rule must not over-fire on the shape every corpus export actually has."""
    assert not [i for i in validate(ir) if i.rule == "IR-030"]


def test_a_child_certified_before_its_parent_is_refused():
    """ORDER IS MEASURED, not reasoned: gs-productretail orders its seven tasks
    Family, SubFamily, Brand, Size, Product, Item, ItemImage — parents first, matching
    the reference graph exactly. A PRE_CONSO reference resolves against the parent's
    certified records, so a child certified first has nothing to point at."""
    from agent.ir.schema import IR as _IR
    d = ROOT / "out" / "s4-multi-source-ids" / "ir"
    s4 = _IR.load(d / "model.yaml", d / "certify.yaml")
    assert not [i for i in validate(s4) if i.rule == "IR-030"], "s4 must be clean"
    tasks = {t.entity: t for t in s4.certify.jobs[0].tasks}
    tasks["Customer"].position, tasks["Opportunity"].position = 2, 1
    assert [i for i in validate(s4)
            if i.rule == "IR-030" and "OpportunityCustomer" in i.where]


def test_a_self_reference_never_trips_the_order_rule():
    """CustomerParent is Customer -> Customer: one task, so there is no order to get
    wrong. Refusing it would refuse the only shape s4 has for a hierarchy."""
    from agent.ir.schema import IR as _IR
    d = ROOT / "out" / "s4-multi-source-ids" / "ir"
    s4 = _IR.load(d / "model.yaml", d / "certify.yaml")
    assert not [i for i in validate(s4)
                if i.rule == "IR-030" and "CustomerParent" in i.where]


# ------------- IR-031 / IR-032: the three defects the server log named on 2026-08-07
#
# Fourteen deploys could not separate these because each probe moved one variable off a
# baseline that still held another (LESSONS §55.5). Each rule below quotes the product's
# own sentence, because that sentence is the difference between a rule and a hunch.
def _s4():
    from agent.ir.schema import IR as _IR
    d = ROOT / "out" / "s4-multi-source-ids" / "ir"
    return _IR.load(d / "model.yaml", d / "certify.yaml")


def test_the_fixed_s4_is_clean():
    """The scenario that cost the three defects must pass all three rules."""
    assert not [i for i in validate(_s4()) if i.rule in ("IR-031", "IR-032")]


def test_a_bare_complex_attribute_in_a_default_branch_rule_is_refused():
    """`least()` gets an empty column list: a complex attribute has no column of its
    own, only its definition attributes do."""
    ir = _s4()
    r = next(s for s in ir.certify.survivorship if s.name == "AddressRule")
    r.attributes = ["Address"]
    issues = [i for i in validate(ir) if i.rule == "IR-031"]
    assert issues and "least()" in issues[0].why


def test_the_same_scope_is_fine_when_the_strategy_bypasses_least():
    """NO_OVERRIDE takes the switch's first branch and never reaches `least()`. A rule
    that fired there would refuse a shape that demonstrably deploys."""
    ir = _s4()
    r = next(s for s in ir.certify.survivorship if s.name == "AddressRule")
    r.attributes, r.override_strategy = ["Address"], "NO_OVERRIDE"
    assert not [i for i in validate(ir) if i.rule == "IR-031"]


def test_a_matched_entity_with_no_default_rule_is_refused():
    ir = _s4()
    next(s for s in ir.certify.survivorship if s.name == "DefaultRule").default_rule = False
    assert [i for i in validate(ir)
            if i.rule == "IR-031" and "no default survivorship rule" in i.message]


def test_two_default_rules_are_refused():
    ir = _s4()
    next(s for s in ir.certify.survivorship if s.name == "NameRule").default_rule = True
    assert [i for i in validate(ir)
            if i.rule == "IR-031" and "default survivorship rules" in i.message]


def test_an_entity_with_nothing_overridable_is_refused():
    """Defect C, and the only way to reach it is by switching strategies off to debug
    something else — which is exactly what a probe did on 2026-08-07."""
    ir = _s4()
    for s in ir.certify.survivorship:
        if s.kind != "id":
            s.override_strategy = "NO_OVERRIDE"
    assert [i for i in validate(ir)
            if i.rule == "IR-031" and "nothing is overridable" in i.message]


def test_a_bare_reference_role_used_as_a_scalar_is_refused():
    """`Parent IS NULL` sat in the IR for four days. It parses as SQL so IR-017 passes
    it; only the job's validation-SQL builder ever objected."""
    ir = _s4()
    v = next(x for x in ir.certify.validations if x.name == "NoSelfParent")
    v.condition = "Parent IS NULL OR Parent.CustomerGoldenId <> CustomerGoldenId"
    issues = [i for i in validate(ir) if i.rule == "IR-032"]
    assert issues and "TO_ONE_PATH" in issues[0].why
    assert "FID_Parent" in issues[0].why


def test_the_derived_scalar_forms_of_a_role_are_not_refused():
    """`FID_Parent`, `SourceID_Parent` and `Parent.<Attribute>` are the legal forms.
    A rule that flagged them would refuse the only correct spellings there are —
    and `\\b` must not match the role inside `FID_Parent`, where `_` is a word char."""
    ir = _s4()
    v = next(x for x in ir.certify.validations if x.name == "NoSelfParent")
    for ok in ("FID_Parent IS NULL OR FID_Parent <> CustomerGoldenId",
               "SourceID_Parent IS NULL OR PublisherID_Parent IS NOT NULL",
               "Parent.CustomerGoldenId IS NULL"):
        v.condition = ok
        assert not [i for i in validate(ir) if i.rule == "IR-032"], ok


def test_a_role_that_is_also_an_attribute_name_is_left_alone():
    """The role/attribute namespaces can collide, and an attribute IS a scalar. When
    the name is ambiguous the rule must say nothing rather than guess wrong."""
    ir = _s4()
    cust = next(e for e in ir.model_ir.entities if e.name == "Customer")
    cust.attributes.append(Attribute(name="Parent", type="String", length=10))
    v = next(x for x in ir.certify.validations if x.name == "NoSelfParent")
    v.condition = "Parent IS NULL"
    assert not [i for i in validate(ir) if i.rule == "IR-032"]


# ------------- IR-033 / IR-034: what the Application Builder's Validation view named
#
# A register no REST call reaches, run by the operator on 2026-08-07 against a model
# that imports, exports, deploys, runs a job and holds data. Ten errors. Each rule below
# quotes the sentence, for the same reason IR-031 and IR-032 do (LESSONS §56).
def test_every_authored_scenario_passes_the_two_new_rules():
    """These are rules about shapes we ALREADY SHIPPED, so the scenarios have to be
    clean before the rules mean anything — otherwise the first thing they do is refuse
    the corpus of our own work."""
    for d in sorted((ROOT / "out").glob("s*/ir*")):
        if not (d / "model.yaml").exists():
            continue
        from agent.ir.schema import IR as _IR
        cert, app = d / "certify.yaml", d / "app.yaml"
        ir = _IR.load(d / "model.yaml", cert if cert.exists() else None,
                      app if app.exists() else None)
        bad = [i for i in validate(ir) if i.rule in ("IR-033", "IR-034")]
        assert not bad, f"{d}: " + "\n".join(i.render() for i in bad)


def test_a_survivorship_scope_naming_nothing_is_refused():
    """`Attribute Name on SurvivorshipRuleAttribute`. A scope that resolves to nothing
    is not a narrow scope — it is NO scope, silently, and those attributes end up
    consolidated by whatever the default rule says."""
    ir = _s4()
    r = next(s for s in ir.certify.survivorship if s.name == "NameRule")
    r.attributes = ["Nmae"]
    issues = [i for i in validate(ir) if i.rule == "IR-033"]
    assert issues and "Nmae" in issues[0].message


def test_the_three_forms_that_do_resolve_are_left_alone():
    """Measured over the 37 SurvivorshipRuleAttribute instances in the product-authored
    corpus: an atomic attribute bare, a complex MEMBER dotted, and a reference ROLE
    bare (gs-customerb2c scopes CommChanPref's rules to `Person` and `Preference`)."""
    ir = _s4()
    r = next(s for s in ir.certify.survivorship if s.name == "NameRule")
    for ok in (["Name"], ["Address.Zip5"], ["Parent"]):
        r.attributes = ok
        assert not [i for i in validate(ir) if i.rule == "IR-033"], ok


def test_the_bare_complex_attribute_stays_ir031_and_is_not_double_reported():
    """IR-031(a) already owns it and says something SHARPER — zero columns, and the
    sentence from the job generator. Two rules firing on one shape would make the
    specific one look optional."""
    ir = _s4()
    r = next(s for s in ir.certify.survivorship if s.name == "AddressRule")
    r.attributes = ["Address"]
    rules = {i.rule for i in validate(ir) if i.where.endswith("AddressRule")}
    assert "IR-031" in rules and "IR-033" not in rules


def test_master_historization_on_a_basic_entity_is_refused():
    """`Could not have Historize Master Records on Entity Opportunity because it is a
    Basic entity`. It deployed, ran and loaded four goldens exactly like this."""
    ir = _s4()
    opp = next(e for e in ir.model_ir.entities if e.name == "Opportunity")
    assert opp.type == "basic" and opp.historize_master is False
    opp.historize_master = True
    issues = [i for i in validate(ir) if i.rule == "IR-034"]
    assert issues and "Basic entity" in issues[0].why


def test_ir035_the_node_sort_scope_has_no_matching_builtins():
    """`sort_expression: ConfidenceScore DESC` imports at 204, deploys and runs; the
    Application Builder's Validation view is the only register that refuses it
    (measured 2026-08-08 on scenario 4's CustomerNode, whose error enumerates the
    whole legal scope: model attributes, roles, FID_/FDN_ and the audit columns).
    Collection COLUMNS and the view FILTER resolve the matching built-ins fine —
    s3 renders a Score column at runtime — so the rule is scoped to node sorts only."""
    from agent.ir.validate import validate
    d = ROOT / "out/s4-multi-source-ids/ir"
    ir = IR.load(d / "model.yaml", d / "certify.yaml", d / "app.yaml")
    assert not [i for i in validate(ir) if i.rule == "IR-035"], \
        "the shipped scenario must be clean"
    node = ir.app.business_views[0].nodes[0]
    node.sort_expression = "ConfidenceScore DESC"
    hits = [i for i in validate(ir) if i.rule == "IR-035"]
    assert len(hits) == 1 and hits[0].severity == "error", hits
    assert "ConfidenceScore" in hits[0].message
    # A model attribute, a role, an audit column and a FID_ column all resolve.
    for legal in ("Name", "Parent.Name", "CreationDate DESC", "FID_Parent"):
        node.sort_expression = legal
        assert not [i for i in validate(ir) if i.rule == "IR-035"], legal
