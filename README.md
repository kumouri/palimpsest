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

- **Oracle-0** — single hop: Act text vs. the compiled section it sourced. **Built. 88.3 %.**
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

**Oracle-0 is built and has produced its first number.**

> ### 88.3 %
> **83 of 94** ILCS sections match the Public Act their own `(Source: …)` line says last set them.
> 112 sections sampled across 6 chapters; 18 excluded because their source Act is not published
> online at all. Against the **fixed** 112-section denominator — the figure that cannot be improved
> by seeing less — it is **74.1 %**. Exact-byte match rate: **0 %**, because the two routes wrap text
> at different column widths, so nothing matches byte-for-byte and that is expected.
>
> **Full report, with every mismatch categorised: [`docs/oracle-0-baseline.md`](docs/oracle-0-baseline.md).**

Three things that report establishes, beyond the number:

- **The Phase 0 gating question is answered.** Public Act HTML carries the amendatory markup as real
  `<strike>` and `<u>` tags. **No PDF pipeline is needed** — that was the largest schedule risk in
  Phase 0 (spec §2.5, Appendix A) and it is retired.
- **The corpus floor is the 93rd General Assembly (2003), not the ~90th (1997)** the spec estimated.
  Measured, not assumed. **16 % of sampled sections are permanently unverifiable** because the Act
  that last set them is not online.
- **The spec's guessed 1–5 % human-review load measures at 3.2 %** — roughly right about the wrong
  thing. The dominant cost is corpus coverage and structural cases (repeals, renumbering), not
  interpretive review.

**The bulk mirror is built** (`src/palimpsest/crawl.py`), and building it moved two numbers in the
spec:

- **The corpus is 3,479 ILCS Acts, not ~30,000 fetches.** The spec costed the crawl at one request
  per section and got ~83 hours. But an Act's index page carries the full text of *every section in
  it* — the Election Code is **963 sections in one request** — so the compiled side is ~10–19 hours.
  `DocName` is the right primary key; it was never the right fetch plan. See
  [`docs/spec.md`](docs/spec.md) §2.8.
- **Oracle-0's seven sample Acts already hold 4,600 mirrored sections** — it scored 112 of them. What
  stands between the oracle and the rest is the Public Act each names as its source: **680 Acts,
  ~1.7 hours of crawling.** So those go first, ahead of any new statute fetching.
- **But only 2,540 of those 4,600 are checkable, and that is the uncomfortable finding.** 39.1 % name
  a source Act published before the corpus floor and can *never* be checked against it; another
  5.7 % name no Public Act at all. Oracle-0 put that exclusion at 16 % — but its sample was
  *stratified*, deliberately under-drawing the pre-corpus stratum. **A sample built for coverage of
  the strata does not estimate their sizes**, and reading it as though it did understated the
  corpus-coverage problem by a factor of two and a half. The realistic next-oracle ceiling is
  **2,540 sections, 27× the 94 attempted** — a big number honestly arrived at, rather than a bigger
  one.

Live counts, what remains per tier, and the exact resume command:
**[`docs/crawl-status.md`](docs/crawl-status.md)**.

Run it yourself:

```bash
PYTHONPATH=src python -m palimpsest.oracle0 --out out   # first run crawls, ~30 min at Crawl-delay: 10
PYTHONPATH=src python -m palimpsest.crawl --max-hours 4 # the bulk mirror; resumable, stops on throttling
PYTHONPATH=src python -m palimpsest.crawl --report-only # where the mirror is, fetches nothing
PYTHONPATH=src python -m unittest discover -s tests -t . # 144 tests, no network
```

Stdlib-only, no runtime dependencies. The crawl cache is a build artifact and is **not** committed —
this repository distributes code, not a mirror of the state's statutes.

**On being a good guest.** `robots.txt` is re-read before each change to the fetcher and enforced in
code, not in a comment: `/search` and `/api` are refused at URL construction, the `Crawl-delay: 10`
clock persists on disk so it holds *across* runs, there is exactly one request in flight and no
parallelism to remove, and any response resembling rate limiting **ends the crawl** rather than
triggering a retry. ilga.gov is the only publisher of this data; there is no second source and being
blocked is unrecoverable.

The full technical and product spec is at **[`docs/spec.md`](docs/spec.md)** — 15 sections,
research-backed, sources cited.

**Prior art, stated honestly:** [LawVM](https://lawvm.org/) is this idea, already built and open
source, running for Finland, Estonia, New Zealand and the UK — but **no US state**. The concept is
not novel; the Illinois work is unoccupied. Phase 0 evaluates LawVM as a possible dependency rather
than assuming a rewrite.

Decisions so far — see [`docs/decisions.md`](docs/decisions.md):

- ~~**Licence.**~~ **Settled: [Apache-2.0](LICENSE)** for the code. See *Licence* below for why the
  statutory text itself is not covered by it.
- ~~**Contribution model.**~~ **Ruled** — statutory text is machine-derived and **immutable**;
  corrections are filed as claims against the *pipeline*, never as edits to the artifact; all human
  contribution lives in a visibly separate annotation layer. See
  [`docs/decisions.md`](docs/decisions.md) D-0001. Re-opens after Phase 1, when the measured error
  rate is known.
- ~~**Second jurisdiction.**~~ **Ruled** — federal if feasible, for reach. A strike/insert-style
  state is required as jurisdiction *three* before claiming the architecture generalises. D-0002.

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
