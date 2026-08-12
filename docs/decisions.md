# Decisions

Rulings that are settled, why, and what they cost. Newest last. A decision recorded here is the
authority; where the spec still describes one as open, this file wins.

---

## D-0001 — Community layer: immutable text, corrections as claims

**Date:** 2026-08-11 · **Status:** Accepted (working default) · **Ruled by:** Ceryce Armstrong
**Supersedes:** the open ruling in [`spec.md` §7](spec.md)

**Decision.** Adopt the spec's §7 recommendation. The reconstructed statutory text is
**machine-derived and immutable** — no human, including the maintainer, edits the artifact by hand.
A person who finds an error files a **correction claim against the pipeline**, not an edit to the
output. All human contribution (plain-language summaries, "what changed and why", links to
litigation and news) lives in a **visually separate annotation layer** that can never be mistaken
for the statute.

**Why.** The project's entire value is that its output is *derived*, reproducibly, from published
sources. A single hand-edit destroys that: from then on the text is "mostly machine-generated,
plus whatever someone fixed," which is unverifiable and therefore worthless as a source of truth.
Worse, it silently converts a pipeline bug into a patched symptom — the bug survives and reappears
in every other section it touches. Filing corrections against the pipeline means one report fixes
the whole class.

This is the same rule §5 already applies to LLM assistance: *a model may propose an operation, it
may never produce statutory text.* Same reason, same line.

**Cost.** Slower to fix any individual error, and a contributor who spots a typo cannot just fix
it — a real friction that will lose some contributors. Accepted deliberately.

**Revisit.** The spec (§14) argues this ruling is *better made after Phase 1*, when the measured
error rate is known, because the right answer genuinely depends on that number. Treat this as the
working default, and re-open it once Phase 1 reports — with the number in hand, not before.

---

## D-0002 — Second jurisdiction: federal, with a hard state required third

**Date:** 2026-08-11 · **Status:** Accepted (direction) · **Ruled by:** Ceryce Armstrong

**Decision.** After Illinois, go **federal** if it proves feasible. If it does not, the fallback
set is **Missouri, Indiana, Michigan, Colorado, South Dakota** — in no fixed order.

**Why.** Reach. Federal is also, counter-intuitively, the *easy* option rather than the hard one:
the GPO ships US Code as **USLM XML** ([`spec.md` §3.5](spec.md)), so the extraction adapter is
thin compared with scraping a state site under a 10-second crawl delay.

**The trap this ruling has to name.** The spec (§10) frames jurisdiction two as a choice between
two different goals: **reach** (federal — easy, large audience) and **proof** (a state using
genuine strike/insert amendatory instructions — hard, and the only thing that demonstrates the
architecture generalises past Illinois-style whole-section restatement). Choosing reach is
legitimate. **Drifting into it because it was easy is not**, and it would leave the seam untested
while feeling like progress.

**Therefore, the sequencing is part of the ruling:** federal is jurisdiction two for reach, and a
**strike/insert-style state is required as jurisdiction three** before this project claims in
public that its architecture generalises. Until that exists, the honest claim is "works for
whole-section-restatement jurisdictions."

**Open and unverified.** Which of Missouri, Indiana, Michigan, Colorado and South Dakota use
restatement versus strike/insert is **not known** — nobody has checked. That question decides
whether a fallback pick is cheap or is itself the hard proof case, so check before choosing.


---

## D-0003 — LawVM: take the ideas, build fresh

**Date:** 2026-08-11 · **Status:** **Accepted** · **Ruled by:** Ceryce Armstrong, 2026-08-11
**Evidence:** [lawvm-evaluation.md](lawvm-evaluation.md)

**Proposed decision.** Do not adopt or fork [LawVM](https://lawvm.org/). Build fresh, and steal its
ideas deliberately and with attribution.

**Why "adopt" is off the table** — it is *unavailable*, not merely unattractive. Not on PyPI. Zero
releases, zero tags, self-declared unstable API. Decisively: **no extension point outside the
tree.** A jurisdiction is a first-party package in `src/lawvm/` plus an edit to a hardcoded CLI
list. There is nothing to depend on, only a tree to be inside of. Licence is MIT, which is
one-directionally compatible with this project's Apache-2.0 (retain the notice; MIT carries no
patent grant, which is part of why Apache-2.0 was chosen here).

**The number that decides it.** LawVM's *own* US-federal lane — better sources than Illinois, a
mature kernel, written by its own author — sits at **2,395 / 45,735 = 5.24% coverage.** Adopting
removes perhaps a third of the *design* risk and almost none of the *implementation* cost.

**Steal these, explicitly:**
- **`oracle-check` as a first-class command.** Their published headline is 0.65% mean normalised
  text edit distance against an archived Finlex surface. The oracle is not foreign to their design,
  it *is* their design.
- **The witness-anchored monotone denominator.** This project's spec does not have it and needs it:
  it prevents coverage from improving when extraction *narrows*. Without it, the cheapest way to
  raise a match rate is to quietly measure less — the exact self-deception the normaliser was
  already flagged for.
- Their divergence taxonomy and normalisation layering.

**Also worth knowing:** it is a single maintainer, AI-agent-driven (~83 commits/day, 6,502 commits,
**1 contributor, 0 issues ever, 0 PRs ever**), courting ministries rather than contributors, and the
public repo is an admitted curated export of a larger private tree. Upstreaming a US-state adapter
is not a realistic path.

**One outbound action this unlocks, and it is Ceryce's to send:** LawVM's `us/spec/` states nine
times that `uscode.house.gov` and the OLRC classification tables are **geo-blocked** from the
maintainer's location. They are not blocked from Illinois. That is a concrete, specific thing this
project can offer him that he demonstrably cannot get for himself.

**Ruled 2026-08-11.** Build fresh, borrow deliberately and with attribution. Ceryce's framing:
*"sounds like this would be better as separate projects for now that borrow portions from each
other."* A friendly outreach email to the maintainer is drafted and held at her gate — praise, an
honest statement that we are not proposing to upstream, and a concrete offer of the US federal
sources that are geo-blocked from him.
