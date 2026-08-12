# palimpsest

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

It goes further than analogy. Bills are written as **amendatory instructions**:

> *"in Section 504(b-1), strike 'X' and insert 'Y'"*

That is a patch. Illinois law is stored as a patch series against a base text. It is simply a
**fuzzy** patch format — no line numbers, no context hunks, and occasionally instructions like
*"strike the second occurrence of"* — which is why applying it has resisted automation.

## The oracle

This project can grade its own homework, which is rare and is the reason it is tractable.

Take the codified base text, apply every Public Act in effective-date order, and compare the
reconstruction against **the official current text published on ilga.gov**. No human evaluator is
required — the right answer is already published.

Every mismatch is a genuine finding: either the patch engine is wrong, or the official compilation
contains an error. Both are worth knowing. Progress is a percentage, measured per section, from
day one.

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

**Day one.** Nothing is built. A full technical and product spec is being written and will land
here as `docs/spec.md`.

Open decisions, deliberately not yet made:

- **Licence — code and data will be licensed separately.** Not yet chosen; until then the default
  applies and this is *not* an open-contribution repo.
- **Contribution model.** Working prior: the reconstructed statutory text stays machine-derived and
  **immutable**, with all human contribution (plain-language summaries, "what changed and why",
  links to litigation) in a visibly separate annotation layer. If a person can hand-edit the
  authoritative text, it stops being a source of truth.

## This is not legal advice

This is a tool for reading and diffing published statutory text. It is not a substitute for a
lawyer, it does not tell you whether a provision is still good law, and it has no citator.
