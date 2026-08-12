# palimpsest

[![license: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-00ff0f?style=flat-square)](LICENSE)

> *palimpsest* (n.) — a manuscript page that has been scraped and written over, where the earlier
> text is still faintly visible underneath.

**Version control for Illinois statutes.** What the law says right now, how it got that way, and
which Public Act made each change — with the diff.

---

## The observation this is built on

Legislation is **already a version control system**, run without any tooling.

| Git | Illinois law |
|---|---|
| commit | a **Public Act** |
| working tree | the compiled **ILCS** section as published |
| rendered diff | the **enrolled bill**, with strikethrough for deletions |
| `git log` | the legislative-history line at the foot of each ILCS section |
| `git show` | **does not exist** |

That last row is the whole problem. The history line names every commit and lets you read none of
them. Reconstructing what a statute said on a given date — or seeing what one Public Act actually
changed — is currently manual work.

It goes further than analogy — and Illinois is unusually kind here. An amendatory bill says:

> *"The Election Code is amended by changing Section 28-1 as follows:"*

…and then **reprints the entire section**, with deletions struck through and insertions
underscored, per the Legislative Reference Bureau's Bill Drafting Manual. The drafter has already
rendered the diff *and* the post-amendment text.

That matters more than it sounds. The apply step for the dominant case is **whole-section
replacement**, not fuzzy in-place editing — so the hard problem moves from *"can we execute this
instruction correctly"* to **target resolution and ordering**: which section, which version, in
what sequence, effective when. (An earlier framing of this project assumed a fuzzy,
line-number-free patch format in the style of federal drafting. For Illinois that is largely
wrong, and it is wrong in our favour.)

## The oracle

This project can grade its own homework, which is rare and is the reason it is tractable.

Because each Public Act carries the **full post-amendment text** of every section it touches, and
each compiled ILCS section ends with a `(Source: P.A. …)` line naming the Act that last set it,
the two can be compared directly — **tens of thousands of test cases available before a single
line of parser exists.**

- **Oracle-0** — single hop: Act text vs. the compiled section it sourced.
- **Oracle-1** — chain: reconstruct from history, compare to compiled.
- **Oracle-2** — cross-publisher: compare against an independent compilation.

No human evaluator is required. Every mismatch is a genuine finding: either the engine is wrong or
the official compilation is. Both are worth knowing, and progress is a percentage from day one.

**One honest caveat, and it is load-bearing:** ilga.gov's ILCS is a drafting **working tree, not a
snapshot**. The ILGA states that changes are sometimes shown *before* they take effect, and that
the version currently in force may already have been removed. Nothing this project publishes can
truthfully be captioned "current law."

## Scope

**v1 is Illinois only.** The architecture should generalise to other states and to federal law
without a rewrite, but nothing here is built for that yet, and breadth before the oracle passes
would be a mistake.

## Known-hard problems, stated up front

- **Effective dates are not merge dates.** Two Public Acts can amend the same section, pass months
  apart, and take effect in either order. That is a real merge conflict, resolved today by hand.
  The system should *surface* these, never silently resolve them.
- **Retroactive amendments** rewrite history.
- **Judicial construction is an overlay, not an edit.** A court can render a clause a dead letter
  without changing a single byte — so **current text is not the same thing as current law.** This
  tool shows text. It must never imply it shows more than that.
- **Session law versus compiled code.** The session law is authoritative; the compilation is an
  editorial product.

## Status

**Day one.** Nothing is built. The full technical and product spec is at
**[`docs/spec.md`](docs/spec.md)** — 15 sections, research-backed, sources cited.

**Prior art, stated honestly:** [LawVM](https://lawvm.org/) is this idea, already built and open
source, running for Finland, Estonia, New Zealand and the UK — but **no US state**. The concept is
not novel; the Illinois work is unoccupied. Phase 0 evaluates LawVM as a possible dependency rather
than assuming a rewrite.

Open decisions, deliberately not yet made:

- ~~**Licence.**~~ **Settled: [Apache-2.0](LICENSE)** for the code. See *Licence* below for why the
  statutory text itself is not covered by it.
- **Contribution model.** Working prior: the reconstructed statutory text stays machine-derived and
  **immutable**, with all human contribution (plain-language summaries, "what changed and why",
  links to litigation) in a visibly separate annotation layer. If a person can hand-edit the
  authoritative text, it stops being a source of truth.

## Licence

The **code** in this repository is [Apache-2.0](LICENSE) © 2026 Ceryce Armstrong.

The **statutory text** is not, because it cannot be. Under the *edicts of government* doctrine,
the official text of the law is uncopyrightable — reaffirmed by the Supreme Court in
*Georgia v. Public.Resource.Org, Inc.*, 590 U.S. 255 (2020), which held that even a state's own
annotations to its code were not protected. Nothing here licenses the ILCS to you, because nothing
needs to. Original work built *around* that text — the schema, the reconstruction engine, any
commentary — is Apache-2.0 like the rest.

## This is not legal advice

This is a tool for reading and diffing published statutory text. It is not a substitute for a
lawyer, it does not tell you whether a provision is still good law, and it has no citator.
