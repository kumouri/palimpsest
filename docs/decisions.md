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
