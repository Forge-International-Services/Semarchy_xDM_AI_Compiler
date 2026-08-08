"""Dependency and execution order — step 1 of the block design.

Blocks decide whether the SHAPE is right. Decisions decide whether the VALUES are
justified. Neither can see the third way a model goes wrong: the pieces are all
correct and they run in the wrong order, or a piece that another piece needs is
missing.

Both failures are silent, and both cost a live run to find:

    ORDER   `PhoneticName` reads `NormalizedName` and both sat at the default
            position. The batch job runs enrichers in POSITION order, so the phonetic
            enricher hashed a NULL, every master record got an empty token, and BOTH
            phonetic match rules were dead. Nothing failed. Matching quietly fell back
            to email alone. (LESSONS §20)

    MISSING A `DupsManager` needs a Collection AND a Form tab; the product's own
            dialog refuses to close without them. A generated one that omits them
            imports and then renders an empty screen.

The single-record REST certify endpoint does NOT reproduce the ordering failure — it
resolved the dependency and returned a populated token, which is exactly the kind of
near-miss that makes a per-record probe look like proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\b")

#: What each application-layer construct cannot exist without. Observed by building
#: each one in the designer and watching which dialogs refused to close.
REQUIRES: dict[str, tuple[str, ...]] = {
    "dups_manager": ("collection", "form_tab"),
    "bo_view_node": ("collection", "form"),
    "stewardship_action": ("dups_manager",),
}


@dataclass(frozen=True)
class Dep:
    """`consumer` needs `producer` to have run first."""
    entity: str
    consumer: str
    producer: str
    attribute: str
    #: The producer NORMALISES this attribute IN PLACE (its expression reads the
    #: attribute it writes) rather than deriving it from nothing.
    #:
    #: That is a different failure, and a weaker one. A derived attribute is NULL until
    #: its producer runs, so a consumer that runs first hashes a null — silent, total,
    #: and the defect this whole module was written for (LESSONS §20). An in-place
    #: normaliser's attribute is publisher-supplied and already populated; a consumer
    #: running first sees the RAW value, not nothing.
    #:
    #: Sometimes that is precisely the point. `ENR_CAPTURE_INITIAL_ADDRESS` exists to
    #: copy the inbound address BEFORE anything rewrites it — ordering it after the
    #: normaliser would destroy the evidence it was added to preserve. So this case is
    #: reported and not refused, because refusing it would refuse a correct design.
    in_place: bool = False

    def __str__(self) -> str:
        return (f"{self.entity}/{self.consumer} reads {self.attribute!r}, "
                f"written by {self.producer}"
                + (" (in place)" if self.in_place else ""))


def enricher_dependencies(ir) -> list[Dep]:
    """Every read-after-write between enrichers on the same entity and scope."""
    out: list[Dep] = []
    for en in ir.certify.enrichers:
        # attribute -> is it normalised IN PLACE? An expression that reads the very
        # attribute it writes is carrying a publisher's value forward, not creating one.
        writes = {x.attribute: x.attribute in _IDENT.findall(x.expression or "")
                  for x in en.expressions}
        for other in ir.certify.enrichers:
            if other is en or other.entity != en.entity or other.scope != en.scope:
                continue
            for expr in other.expressions:
                for ident in _IDENT.findall(expr.expression or ""):
                    # A complex member reads as Address.Zip5; the producer writes the
                    # same dotted name, so compare on the full identifier first.
                    for cand in (ident, ident.split(".")[-1]):
                        if cand in writes and cand != expr.attribute:
                            out.append(Dep(en.entity, other.name, en.name, cand,
                                           in_place=writes[cand]))
                            break
    # dedupe, preserving order
    seen, uniq = set(), []
    for d in out:
        k = (d.entity, d.consumer, d.producer, d.attribute)
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def order_violations(ir) -> list[tuple[Dep, int, int]]:
    """Dependencies whose positions do not put the producer first.

    EQUAL positions count as violations. xDM does not promise an order within a
    position, so "they happen to work today" is not a property to rely on — and in the
    batch job they did not work.
    """
    pos = {(en.entity, en.name): en.position for en in ir.certify.enrichers}
    bad = []
    for d in enricher_dependencies(ir):
        p, c = pos[(d.entity, d.producer)], pos[(d.entity, d.consumer)]
        if c <= p:
            bad.append((d, p, c))
    return bad


def execution_order(ir) -> dict[tuple[str, str], int]:
    """The positions the enrichers SHOULD have: a topological layering.

    Returns (entity, name) -> position, 1-based, where every producer sits strictly
    before every consumer and independent enrichers share a layer. Flagging a wrong
    order is useful; handing back the right one is what makes it fixable.

    IN-PLACE dependencies are excluded. They are not "must run after" constraints —
    the attribute already holds the publisher's value — and honouring them here would
    make the suggested order recommend running a capture-the-raw-value enricher AFTER
    the normaliser that overwrites what it was there to capture.
    """
    deps = [d for d in enricher_dependencies(ir) if not d.in_place]
    out: dict[tuple[str, str], int] = {}
    for entity in {en.entity for en in ir.certify.enrichers}:
        names = [en.name for en in ir.certify.enrichers if en.entity == entity]
        needs = {n: {d.producer for d in deps
                     if d.entity == entity and d.consumer == n} for n in names}
        layer, placed = 1, {}
        remaining = set(names)
        while remaining:
            ready = {n for n in remaining if not (needs[n] & remaining)}
            if not ready:                      # a cycle: everything left is mutual
                for n in sorted(remaining):
                    placed[n] = layer
                break
            for n in ready:
                placed[n] = layer
            remaining -= ready
            layer += 1
        out.update({(entity, n): p for n, p in placed.items()})
    return out


def cycles(ir) -> list[list[str]]:
    """Enricher cycles — A reads what B writes and vice versa. Unschedulable.

    In-place dependencies cannot make a cycle unschedulable: both attributes are
    populated before either enricher runs, so some order always works.
    """
    deps = [d for d in enricher_dependencies(ir) if not d.in_place]
    out = []
    for d in deps:
        for e in deps:
            if (d.entity == e.entity and d.consumer == e.producer
                    and d.producer == e.consumer and d.producer < d.consumer):
                out.append([d.entity, d.producer, d.consumer])
    return out


def blocking_violations(ir) -> list[tuple[Dep, int, int]]:
    """Order violations that make a consumer read a NULL. The in-place ones are
    reported everywhere but refused nowhere — see `Dep.in_place`."""
    return [(d, p, c) for d, p, c in order_violations(ir) if not d.in_place]


def render(ir) -> str:
    deps = enricher_dependencies(ir)
    bad = order_violations(ir)
    want = execution_order(ir)
    blocking = sum(1 for d, _, _ in bad if not d.in_place)
    lines = [f"enricher dependencies: {len(deps)}, order violations: {len(bad)} "
             f"({blocking} blocking, {len(bad) - blocking} in-place)"]
    for d, p, c in bad:
        if d.in_place:
            lines.append(f"  IN-PLACE   {d}")
            lines.append(f"             producer at position {p}, consumer at {c}. The "
                         f"producer rewrites {d.attribute!r} in place, so the consumer "
                         f"reads the RAW value rather than a null — deliberate for a "
                         f"capture-the-inbound-value enricher, a bug otherwise.")
            continue
        lines.append(f"  VIOLATION  {d}")
        lines.append(f"             producer at position {p}, consumer at {c} — "
                     f"the consumer runs first or in an unspecified order")
        lines.append(f"             suggested: {d.producer}={want[(d.entity, d.producer)]}, "
                     f"{d.consumer}={want[(d.entity, d.consumer)]}")
    return "\n".join(lines)


# ------------------------------------------------------- structural prerequisites
@dataclass(frozen=True)
class Missing:
    where: str
    needs: str
    detail: str

    def __str__(self) -> str:
        return f"{self.where} needs {self.needs}: {self.detail}"


def missing_prerequisites(ir) -> list[Missing]:
    """Constructs whose prerequisites the designer enforces and the compiler did not.

    Every one of these was learned by building the thing in the UI and watching a
    dialog refuse to close. The compiler is more permissive than the product, which is
    the wrong direction: it produces a model that imports and then does nothing.
    """
    app = ir.app
    out: list[Missing] = []
    tabs = {(f.entity, f.name): {c.name for c in f.containers if c.kind == "tab"}
            for f in app.forms}
    colls = {(c.entity, c.name) for c in app.collections}

    for d in app.dups_managers:
        if not d.collection:
            out.append(Missing(f"dups manager {d.entity}/{d.name}", "a collection",
                               "the queue has no list to show the steward"))
        elif (d.entity, d.collection) not in colls:
            out.append(Missing(f"dups manager {d.entity}/{d.name}",
                               f"collection {d.collection!r}", "not declared"))
        if not (d.form and d.form_tab):
            out.append(Missing(f"dups manager {d.entity}/{d.name}", "a form tab",
                               "the designer refuses to create one without it; a "
                               "generated one imports and renders an empty screen"))
        elif d.form_tab not in tabs.get((d.entity, d.form), set()):
            out.append(Missing(f"dups manager {d.entity}/{d.name}",
                               f"tab {d.form_tab!r} of form {d.form!r}", "not declared"))

    dups = {(d.entity, d.name) for d in app.dups_managers}
    STEWARDSHIP = {"MergeOrSplit", "ReviewAndConfirm", "ReviewSuggestions"}
    for a in app.action_sets:
        for act in a.actions:
            if act.kind in STEWARDSHIP and not act.dups_manager:
                out.append(Missing(f"action {a.entity}/{a.name}.{act.name}",
                                   "a duplicate manager",
                                   f"{act.kind} operates ON a queue; without one "
                                   f"there is nothing for the steward to review"))
    for v in app.business_views:
        for n in v.nodes:
            if not n.collection:
                out.append(Missing(f"business view {v.name}/{n.name}", "a collection",
                                   "the node has no list, so the view opens empty"))
    return out


def build_order(ir) -> list[str]:
    """The order the application layer must be CONSTRUCTED in, from REQUIRES.

    Not cosmetic: the designer enforces it, so a generator that emits a DupsManager
    before the Form it points at is describing something the product cannot build.
    """
    return ["display_card", "form", "collection", "action_set",
            "dups_manager", "business_view", "application"]
