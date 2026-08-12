# LawVM — dependency evaluation for the Illinois statute VCS project

**Evaluated:** 2026-08-11. **Evaluator:** research pass for the Phase 0 task in
`margo/state/illinois-law-vcs-spec.md` §3.7 / §11 ("Whether LawVM's core is genuinely
jurisdiction-agnostic — could remove a third of the build — one hour with the repo").

**Method:** primary sources only. `lawvm.org` fetched 2026-08-11; GitHub REST API queried
2026-08-11; `github.com/eliask/lawvm` shallow-cloned at `e5f5f69` (2026-07-12) and read directly.
Every number below is measured from the tree or the API, not inferred.

---

## Verdict, up front

**Take the ideas and build fresh** — but treat LawVM's doctrine documents as a *normative input to
the Illinois design*, not a bibliography entry. Copy the model; do not copy the code.

Secondary, and worth doing before a line is written: **email the maintainer.** There is one concrete
asymmetry (below, §6) that makes an Illinois contributor genuinely useful to him rather than
generically welcome, and it could change this verdict.

The spec's hoped-for outcome — "write an Illinois frontend for it and contribute upstream, removing
a third of the engineering" — **is not available**, for a structural reason rather than a quality
one: *LawVM has no outside-the-tree extension point.* A jurisdiction is a first-party package inside
`src/lawvm/`, wired into a hardcoded CLI list. There is nothing to depend *on*; there is only a tree
to be inside of. Everything else follows from that.

Three findings invert assumptions in the spec, and two of them are good news:

1. **The Illinois amendment convention is LawVM's *best* case, not its awkward one.** The spec worried
   that European/UK jurisdictions would make whole-section restatement a fight. The opposite is true:
   Finland — the deepest, most-proven frontend — is a restatement jurisdiction, and the UK is the one
   LawVM itself calls the hard case. (§4)
2. **The oracle is not foreign to LawVM's design; it *is* LawVM's design.** `lawvm oracle-check` is a
   first-class command and the published headline metric is a percentage against the official
   compilation. LawVM's version of the oracle is more sophisticated than the spec's in at least one
   important way. (§5)
3. **LawVM *does* have a US frontend.** The spec says it doesn't. There is an exploratory
   `us_federal` lane with a committed bench corpus — and its measured coverage is the single most
   useful data point in this whole evaluation, because it is empirical evidence of what "point LawVM
   at a US corpus" actually costs. (§3, §7)

---

## 1. What it actually is, technically

**Language and runtime.** Python, `requires-python = ">=3.14"`, `uv`-managed
(`pyproject.toml`, read 2026-08-11). Not published to PyPI — `https://pypi.org/pypi/lawvm/json`
returns HTTP 404 (checked 2026-08-11). Installation is from git.

**Scale.** Measured on the cloned tree at `e5f5f69`:

| Package | Lines | Files |
|---|---:|---:|
| `src/lawvm/finland/` | 250,018 | 451 |
| `src/lawvm/tools/` (CLI) | 217,201 | 310 |
| `src/lawvm/uk_legislation/` | 107,722 | 158 |
| **`src/lawvm/core/`** (the portable kernel) | **79,519** | **201** |
| `src/lawvm/estonia/` | 41,288 | 28 |
| `src/lawvm/new_zealand/` | 29,564 | 30 |
| `src/lawvm/us_federal/` | 24,170 | 28 |
| others (eu, norway, sweden, ingest, substrate, semantic, open_law) | ~68,000 | ~120 |
| **`src/` total** | **820,126** | **1,326** |
| `tests/` | — | 1,144 test files |

That is not a library. It is a monolithic research system in which the reusable part — the kernel —
is under 10% of the tree.

**Architecture.** A documented three-zone split (`notes/CROSS_JURISDICTION_ARCHITECTURE.md`, status
"Current, Normative", dated 2026-06-22):

- **Portable kernel** — legal-address and tree model, canonical op vocabulary, replay execution
  semantics, timeline/version semantics, materialization, structural invariants, evidence bundle shape.
- **Shared-but-parameterized** — provision-family registry, sibling ordering, collision policy,
  address-normalization hooks, evidence aggregation. Driven by per-jurisdiction declaration.
- **Jurisdiction plugin** (local) — source acquisition, ingestion quirks, surface syntax frontend,
  payload extraction, typed elaboration, source-pathology production, lowering to canonical ops.

The governing design rule is stated explicitly and is a good one: *"Finland is the stress test for the
frontend boundary, not the template for the global kernel. If a Finland fix requires teaching the
portable kernel about Finnish clause words […] the boundary is wrong."*

**Data model.** Three primitives, and they match the spec's proposed model closely:

- `IRNode` — law stored as a hierarchical tree.
- `LegalAddress` — stable path-based fine-grained addressing.
- `LegalOperation` — typed operations, not prose edits.

The canonical action vocabulary is `StructuralAction` in `src/lawvm/core/semantic_types.py:51` —
eight members: `REPLACE`, `REPEAL`, `INSERT`, `RENUMBER`, `MOVE`, `HEADING_REPLACE`, `META`,
`TEXT_PATCH`. (`TEXT_PATCH` is a recent collapse of the former `text_replace`/`text_repeal` pair,
discriminated by `TextPatchSpec.kind` ∈ REPLACE/DELETE/APPEND.) The spec's "roughly seven operation
types" is accurate.

Above that sits an object grammar every frontend must flow through
(`notes/LAWVM_PROOF_SURFACES.md` §2, quoted in `jurisdiction_starter/README.md`):

```
SourceWitness → Claim/Assertion → ExecutionAuthorization → Proof
              → Materialization → Agreement → Residual/FrontierWorkItem
```

**Storage.** Archive-first, and this is a hard architectural commitment rather than a convention:
*"Live network reads belong to acquisition, not replay."* The substrate is `.farchive` files —
**the maintainer's own archive format** (`github.com/eliask/farchive`, MIT), a SQLite-backed
content-exact store of bytes observed at named locators. It is pinned in `pyproject.toml` to a
specific git commit, not a version range. Scale: the Finland import is *"roughly under 5 GB after
ingesting about 13 GB of ZIP input."*

**Runtime dependencies** (base, not optional): `PyYAML`, `lxml`, `aiohttp`, `python-Levenshtein`,
`rapidfuzz`, `zstandard`, `icontract`, **`ortools`** (Google OR-Tools — a constraint solver, ~100 MB),
`pyarrow`, and the git-pinned `farchive`. Optional extras pull `pdfplumber`/`pypdfium2`/`pillow` and,
for one lane, `docling` (torch + transformers).

### Is there an adapter/plugin seam, or is each jurisdiction bespoke?

**Neither, exactly — and the precise answer is what kills the "dependency" option.**

There *is* a real, documented, thoughtfully-maintained onboarding path:

- `jurisdiction_starter/` — a contract-first kit: 12 governing markdown documents
  (`JURISDICTION_PROFILE`, `SOURCE_STRATEGY`, `PHASE_PLAN`, `ADJUDICATION_PLAN`, `EVAL_PLAN`,
  `FILE_MAP`, `AI_AGENT_PROTOCOL`, `REVIEW_CHECKLIST`, …) plus seven example evidence artifacts and
  one runtime module. It has completion gates, four named frontend archetypes, and a doctrine that is
  frankly excellent: *"A new jurisdiction should begin with the smallest honest executable claim. […]
  'Probably works for most statutes' is not."*
- `lawvm scaffold <jur>` — a generator. It emits, deliberately, a **non-executing** shell that
  *"does not parse clauses, lower payloads, apply operations, or claim replay support."*
- Genuine shared-core reuse. NZ imports `source_witness.py`, `mutation_boundary_proof.py`,
  `agreement_residual.py`, `proof_surfaces.py`, `frontier_work_item.py` directly. This is not
  aspirational; a 2026-06-14 self-assessment (`jurisdiction_starter/STARTER_ASSESSMENT.md`) audited
  the starter against the just-finished NZ build and patched exactly the places that would have led a
  new author to re-derive core objects.

But there is **no plugin registry, no entry-point mechanism, no external adapter interface**. The CLI
dispatches on a hardcoded literal: `choices=["fi", "ee", "uk", "no", "nz", "us"]`
(`src/lawvm/tools/cli.py:236`). `FrontendCapability` (`core/frontend_contract.py`) is explicitly
*"report/control-plane metadata"* — a declaration of which phases you support, not a registration
hook. A new jurisdiction is a new first-party package inside `src/lawvm/`, plus an edit to that list.

So: **the seam is doctrinal and contractual, not technical.** An Illinois frontend cannot exist as a
package that depends on LawVM. It can only exist *inside a copy of LawVM.*

---

## 2. Licence

**MIT.** Exact, verified two ways:

- `LICENSE` in the tree: `MIT License / Copyright (c) 2026 Elias Kunnas`, standard unmodified text.
- `pyproject.toml`: `license = "MIT"`, `license-files = ["LICENSE"]`.
- GitHub API `repos/eliask/lawvm` → `"license": {"spdx_id": "MIT"}` (2026-08-11).

No separate licence on `docs/` or `notes/` — the MIT grant covers the whole repository, including the
doctrine documents. **That matters:** the doctrine is the most valuable thing here and it is freely
copyable with attribution.

`farchive` (the storage dependency) is also MIT. `ortools` is Apache-2.0.

**Compatibility with an Apache-2.0 project: yes, one-directionally, with two caveats.**

- MIT is permissive and compatible-in-one-direction with Apache-2.0. You may incorporate MIT-licensed
  code into a work distributed under Apache-2.0. You must retain the MIT copyright notice and
  permission text for the MIT-derived files. You **cannot** relicense LawVM's code *as* Apache-2.0 —
  the notice travels with it. A `NOTICE`/`THIRD_PARTY` file naming Elias Kunnas is the mechanical
  obligation, and it is trivial.
- **MIT has no express patent grant.** The spec chose Apache-2.0 for the core partly *because* of its
  patent grant (§9). Any LawVM-derived portion of the stack would carry no such grant. The practical
  risk is close to zero here, but it is a real asymmetry and should be stated rather than glossed.

Licence is **not** a blocker for any of the four options. It is the one dimension on which this
evaluation is unambiguously clean.

---

## 3. Is it alive?

**Alive, yes. Dependable, no. And the public repository is not where the work happens.**

Hard numbers, GitHub API, 2026-08-11:

| Signal | Value |
|---|---|
| Created | 2026-04-25 |
| Last code push (`eliask/lawvm`) | **2026-07-12** — 30 days before this evaluation |
| Total commits | **6,502** |
| Contributors | **1** (`eliask`, 6,502 of 6,502) |
| Releases | **0** |
| Tags | **0** |
| Issues, ever (open *or* closed) | **0** |
| Pull requests, ever | **0** |
| Forks / stars / watchers | 3 / 9 / 0 |
| Branches | 1 (`master`) |

Commit cadence in the shallow window: 2 / 45 / 92 / 53 / 8 over 2026-07-08 → 07-12. 6,502 commits in
78 days is ~83/day. `AGENTS.md` is titled *"an operating contract for agents working in the
repository"*; `STARTER_ASSESSMENT.md` describes itself as an *"automated assessment"*. **This is an
AI-agent-driven single-author codebase**, and that explains both the velocity and the unusual
discipline of the doctrine (the rules exist to keep the agents honest).

**The 30-day silence is not death — but the reason matters more than the silence.** The maintainer
pushed to `eliask/lawvm.org` (the website repo) **three times on 2026-08-11**, the day of this
evaluation. The site's jurisdictions page is stamped *"Reviewed: 11 August 2026"* and lists **four
staging jurisdictions — Japan, South Korea, Poland, Switzerland — that do not exist anywhere in the
public repository.**

The README says why, in as many words:

> *"The public v0.1 tree intentionally keeps only the current release-facing docs and current
> architecture notes. Historical investigation packets and noisy pre-release work queues are not part
> of the public source tree."*

**So the thing on GitHub is a curated export, published at the maintainer's discretion, currently
running at least 30 days and four jurisdictions behind the private working tree.** For a dependency
this is disqualifying on its own: there is no release, no tag, no semver, no changelog cadence you
can pin to, and no way to know whether the next export will preserve your assumptions. The README
states plainly: *"the public Python API, CLI output schemas, and frontend internals are not stable."*

**Open-issue behaviour: unmeasurable.** There has never been an issue, open or closed. That is *zero
signal*, not good signal — you cannot conclude "responsive maintainer" from an empty issue tracker
any more than "unresponsive". The same is true of PRs. There is no CONTRIBUTING.md, no
GOVERNANCE.md, no CODE_OF_CONDUCT.md, no issue templates, and Discussions is not enabled.

The spec's own framing applies here: a beautiful dead project is a liability. LawVM is not dead. It
is something slightly different and, for dependency purposes, similar in effect — **a live private
project with a public mirror.**

---

## 4. Does the model fit the Illinois shape? (whole-section restatement)

**Yes. Emphatically, and better than the spec feared.** This question inverts.

The Illinois shape, per the spec §2.5: an amendatory bill states *"The `<Act>` is amended by changing
Section `<N>` as follows:"* and then **reprints the entire section**, additions underscored and
deletions struck through. Repeals name sections without reprinting.

What LawVM's existing jurisdictions actually use:

| Jurisdiction | Convention | Maps to |
|---|---|---|
| **Finland** (the reference frontend, 250k lines) | **Whole-section restatement.** The *johtolause* — the instruction header at the head of the amending act — declares *what* changes (`muutetaan 12 §` = "section 12 is amended"); the body then reprints the new section text. LawVM catalogues 66 distinct johtolause constructions with stable rule ids. | `REPLACE` |
| **Estonia** | Authoritative-consolidation restatement; frontend is a consistency checker over Riigi Teataja. | `REPLACE` |
| **New Zealand** | Mixed. The dry-run surface has proven five operation forms: repeal, single text substitution, **whole-provision structural replacement (`replaced`/`substituted`)**, whole-provision insertion, nested insertion. | `REPLACE` + `TEXT_PATCH` |
| **United Kingdom** | **Word-level.** Effects-feed and version-graph oriented; *"In Section 12(2), the words 'Secretary of State' are replaced…"* | `TEXT_PATCH` |

The UK is the outlier, and LawVM says so itself: *"Commencement, extent, and prospective effects make
naive text replay insufficient"* (`docs/jurisdictions.md`). Illinois is not the awkward case here —
**the UK is.**

And the tree already contains the Illinois pattern written down explicitly, in the US federal
profile's amendment-style table (`us/spec/JURISDICTION_PROFILE.md` §4):

> *"whole-section replacement ('is amended to read as follows:') — `REPLACE` — **directly recoverable
> from act text**."*

with `INSERT`/anchor, `REPEAL`, `TEXT_PATCH` (strike-and-insert), and `RENUMBER` (redesignation)
covering the rest — and `RENUMBER` flagged as the genuinely hard one (*"recoverable only with hard
parsing: range arithmetic, ordering"*), which matches the spec's own §5 assessment that *"for
Illinois the apply step is mostly whole-section replacement, so the difficulty is target resolution,
not text surgery."*

**Two Illinois-specific things LawVM has no analogue for**, and they are real work regardless of which
option is chosen:

- **Underscore/strikethrough typography.** Illinois amendatory bills mark additions and deletions
  presentationally. That is an IL ingestion problem with no counterpart in Finlex XML or USLM. LawVM's
  `ingest/` layer (15k lines, including PDF/vision lanes for corrupt Finnish fonts) shows the shape of
  the solution but contains nothing reusable for it directly.
- **`(Text of Section before/after amendment by P.A. …)` dual-text conflict markers.** The spec calls
  this *"Illinois already publishes its merge conflicts"* and treats it as a major asset (§2.6).
  Nothing in LawVM models a jurisdiction that publishes competing simultaneous texts. There is a
  `core/cross_act_same_moment.py`, which is adjacent, but the IL marker is a distinct and *better*
  situation than anything LawVM handles. This is a place where the Illinois project would have
  something to teach upstream, not learn from it.

---

## 5. Could it host the oracle idea?

**It already is the oracle idea.** This is the closest convergence in the entire evaluation, and it
runs deeper than the spec realised.

Direct evidence:

- **`lawvm oracle-check <statute>` is a first-class CLI command**, alongside `replay`, `explain`,
  `diff`, and `bench`.
- **The published headline metric is exactly the spec's deliverable.** From
  `docs/benchmark-methodology.md`: Finland's v0.1 snapshot (measured 2026-04-16) is
  *"`0.65%` mean normalized text edit distance against the archived Finlex comparison surface"*, with
  structural tree distance *"below 5%"* reported separately as a secondary metric.
- **The declared, versioned normalisation function exists** — `core/comparison_normalization.py`,
  shared across frontends. This is precisely the artifact the spec's §4.4 demands
  (*"Byte-matching raw HTML-extracted text will report ~0% and teach you nothing"*).
- **The divergence taxonomy matches the spec's almost item for item.** LawVM classifies every
  mismatch before interpreting it: LawVM replay/parsing defect · missing-or-stale source · published
  corrigendum not represented · witness/editorial consolidation difference · noncommensurable
  comparison surface · bounded unresolved uncertainty. In the typed residual partitions this becomes
  `lawvm_wrong` / `oracle_suspect` / `missing_source` / `sunset_reversion`.
- **The confirmation posture is the spec's posture.** *"v0.1 public language should use 'divergence',
  'candidate finding', or 'reported candidate finding' unless an authority has confirmed the issue."*
  Compare the spec §4.5: *"a false accusation against the state's compilation costs more credibility
  than ten true ones earn."*
- **The section-granularity percentage the spec actually wants already exists — in the US lane.** The
  US federal bench reports `cov = agree / oracleΔ`, where the denominator is the oracle's
  changed-section count and *"'covered' means a section materialized in agreement with the oracle
  after-text."* That is the spec's Oracle-0 metric, implemented.
- **Full benchmark infrastructure:** saved runs, `--compare`, run history, and a regression guard that
  *rejects* comparisons between incomparable score lanes rather than silently averaging them.

**LawVM's oracle design is better than the spec's in one specific, important way.** The spec's metric
has a latent denominator bug it does not address: if you count "sections we reconstructed correctly"
over "sections we attempted", the number improves whenever extraction gets *narrower*. LawVM pins the
denominator to **a fact of the source** — the count of ground-truth operation witnesses from the
official history notes or classification tables — making coverage monotone and comparable across
cycles (`new_zealand/dry_run_north_star.py`, `tools/spec_ledger.py`). **The Illinois spec should adopt
this regardless of which option is chosen.** The natural Illinois denominator is the Public Act
numbers in each section's Source line — which the spec already parses for other purposes.

**One genuine doctrinal disagreement, and LawVM is right.** `AGENTS.md` §0:

> *"**Success = source-faithful text-state, not oracle overlap.** The terminal product is a
> correct-by-construction consolidation […] The official consolidation is a *fallible* comparison
> surface, not the objective — a replay-vs-oracle similarity score is a regression guard, and
> maximizing it rewards deleting oracle-present state to match a possibly-wrong oracle.
> **Over-retention (failing to delete) is the safe wrong; over-repeal (destroying state) is the
> forbidden one.**"*

The spec makes the percentage *"the product's first deliverable and its permanent regression metric"*
(§1). LawVM would say: a guard, never a goal — because a team that optimises the number will
eventually reach for the one move that always raises it, which is deleting text the oracle doesn't
have. That is not an incompatibility, it is a correction, and it is worth writing into the Illinois
spec's §4 as a stated hazard. The spec's §7 ruling (no hand-editing of reconstructed text, corrections
must go upstream into the pipeline) is the same instinct, applied one layer down.

**Also worth stealing verbatim:** *"Generators propose; typed validators authorize; replay consumes
only authorized operations."* That is the spec's §5 Tier-3 LLM rule
(*"an LLM may propose an operation; it may never produce statutory text"*) generalised correctly —
LawVM applies it to *every* heuristic, not just the LLM ones. *"A heuristic is allowed. An
**invisible** heuristic is forbidden."*

---

## 6. Community — would upstreaming be welcome?

**Single-maintainer project. A fork would be the realistic path — if the path were forking. It isn't
quite, and the reason is worth understanding.**

The measurable facts (§3) are stark: one contributor, 6,502/6,502 commits, zero PRs ever, zero issues
ever, three forks, nine stars, zero watchers, no CONTRIBUTING/GOVERNANCE files, Discussions disabled,
and a public tree that is a curated export of a private one.

The engagement model on `lawvm.org` (fetched 2026-08-11) confirms the read. The site's navigation is
Assurance / Solutions / Pilots / Assessment / Consolidation Assurance / Source Readiness / Drafting
CI. The call to action is *"Discuss a pilot"*, and a pilot is described as running *"read-only beside
the existing workflow"*, returning *"a source inventory, reproducible artifacts, classified residuals,
and a human-review queue for institutional disposition."* Contact is email only, with a caution about
*"processing boundaries"* for confidential source files.

That is a maintainer courting **ministries, legal publishers, and national gazettes** for
institutional adoption. It is not a project courting contributors. And `AGENTS.md` — the file that
would be CONTRIBUTING.md in another repo — is explicitly an operating contract for *AI agents working
in the repository*, i.e. the contribution surface is engineered for the maintainer's own agent fleet.

An upstreamed Illinois frontend would therefore require the maintainer to accept a first-party in-tree
package (no plugin seam exists), from an external contributor, into a repository that has never merged
a pull request, in a tree that is a curated export of a private one, with a publication cadence
entirely at his discretion. **The probability of a clean, low-latency upstream path is low.** Not
because anyone is unwelcoming — there is simply no evidence either way, and the structure argues
against it.

### The one genuine opening, and it is better than it sounds

Buried in `us/spec/SOURCE_STRATEGY.md` and `us/spec/JURISDICTION_PROFILE.md` is a repeated, specific
blocker:

> *"From outside the U.S., **OLRC `uscode.house.gov` is geo-blocked**."*
>
> *"OLRC classification tables (PL § → USC §) are geo-blocked and unreachable."*
>
> *"**NOT acquired.** OLRC `uscode.house.gov` is geo-blocked; the govinfo USCODE alternative needs a
> free `api.data.gov` key (not configured)."*

The maintainer is in Finland. **The single official source that would serve as both the US oracle and
the coverage denominator is unreachable from his machine, and he has written that down nine times
across two documents.** A US-based collaborator is not geo-blocked and can get an `api.data.gov` key
in ninety seconds.

This is the rare case where a prospective contributor has something the maintainer demonstrably cannot
get for himself, documented in his own words. If there is any reason for this project to want an
American collaborator, that is it — and it costs one email to find out. **Send it before committing to
a stack.** Even a "no" is worth the ten minutes; a "yes" changes the verdict.

---

## 7. The number that should decide this

The US federal lane has been built far enough to measure, and `us/spec/US_EVAL_STATE.md` reports the
result with the same honesty as the rest of the project:

> *"On a full-corpus scan (2026-06-22, 248 windows), the aggregate coverage is
> **2,395/45,735 = 0.0524**."*

**5.24% witness-anchored dry-run coverage.** Best individual window: 40% (title 11, 2018→2020, after
targeted work). Most windows are 0–14%. The typed residuals show where it goes: `missing_source`
dominates almost every row, `lawvm_wrong` is second.

Put that next to what the US lane had going for it. The source is **USLM XML** — structured,
official, machine-readable, keyless-downloadable from govinfo. Public Laws are drafted as explicit
operations. The oracle is the USC release points. It is, source-quality-wise, a far better starting
position than Illinois HTML-and-PDF prose. And it is running on a mature kernel by the author of that
kernel.

It still came out at 5.24%, and its own document says the bottleneck is source acquisition and
extraction precision — *"the coverage gap is extraction/emission precision and unsupported families
(the frontier), not kernel correctness."*

**This is the empirical answer to the spec's Phase 0 question.** The spec asked whether adopting
LawVM *"could remove a third of the engineering."* The measured evidence says: it removes a third of
the **design** risk — the model is right, the taxonomy is right, the discipline is right, and you can
have all of it for free under MIT — and close to **none** of the **implementation** cost, because the
implementation cost lives in exactly the five things the spec already identified as
jurisdiction-specific: source acquisition, amendment parsing, target resolution, temporal policy, and
evidence classification.

The spec's §3.7 instinct was correct. This evaluation just puts a number on it.

---

## 8. The four options, costed

### A. Adopt as a dependency — **not available**

Not "expensive" or "unwise": *not possible as specified.* There is no dependency to adopt.

- Not on PyPI (HTTP 404, 2026-08-11). No releases, no tags, no semver.
- README: *"the public Python API, CLI output schemas, and frontend internals are not stable."*
- **Jurisdictions live in-tree.** An Illinois frontend cannot be written outside the LawVM tree,
  because the extension mechanism is "add a package to `src/lawvm/` and edit a hardcoded list."
- Pulls Python ≥3.14, `ortools`, and a git-commit-pinned bespoke archive format as hard requirements.

**Cost: N/A.** Rule it out and stop reasoning about it.

### B. Fork it — **the honest form of "adopt", and still wrong here**

MIT permits this cleanly. It is the only way to genuinely reuse the kernel.

**What you get:** a 79.5k-line proven kernel, the evidence/proof-surface object grammar, the
comparison-normalisation layer, the bench harness, the CLI scaffolding, and a working `oracle-check`.

**What you pay:**

- **You own 820,126 lines you did not write and cannot meaningfully review**, of which ~740,000 are
  Finland, UK, EU, Nordic, and tooling you will never run. Deleting them is not free either: the
  kernel is exercised *through* the frontends, and the 1,144-file test suite is the thing keeping it
  honest. Cut the frontends and you cut your own regression net.
- **Python ≥3.14 + `ortools` + git-pinned `farchive`** become permanent constraints on a project whose
  spec (§6) assumes a conventional Python-plus-Postgres stack. `farchive` in particular is a
  single-author storage format on which all replay depends.
- **No merge path back.** Upstream moves in private and ships curated exports at unpredictable
  intervals. Your fork diverges on day one and there is no mechanism — no PRs, no releases — to
  reconcile. You are maintaining a permanent hard fork of another person's research system.
- **A hard fork of a live single-maintainer project is a reputational awkwardness**, in a domain
  (civic legal data) where the small number of participants all know each other.

**Cost: roughly 2–4 weeks to stand up and understand, then an open-ended maintenance tax on 820k lines
of someone else's code, in exchange for saving perhaps 4–8 weeks of kernel implementation.** The trade
is bad, and it gets worse every month.

### C. Take the ideas and build fresh — **recommended**

The doctrine is MIT-licensed. You can copy it, quote it, and cite it. It is the genuinely scarce
asset here, and it transfers at zero cost.

**Adopt into the Illinois spec, by name:**

1. **The three-zone split** — portable kernel / shared-parameterized / jurisdiction plugin — and the
   rule that enforces it: *if fixing Illinois requires teaching the kernel about Illinois, the
   boundary is wrong.* The spec's §8 already draws a jurisdiction-neutral/specific line; this
   sharpens it into three zones with a falsifiable test.
2. **The object grammar** — `SourceWitness → Claim → ExecutionAuthorization → Proof → Materialization
   → Agreement → Residual`. This is the spec's §6 schema with the epistemics made explicit, and it is
   strictly better than `origin ∈ {observed, replayed}` alone.
3. **The dry-run-before-replay gate.** Earn each operation family one at a time: apply the candidate
   to an immutable *before* tree, materialize a candidate *after*, compare against the archived
   oracle with a mutation-boundary proof and typed refusals. Actual replay stays **blocked** until
   dry-run agrees. LawVM's own assessment calls skipping this one of the two "wrong turns" the NZ
   build proved. The spec's Phase 1/2 plan currently has no such gate.
4. **The witness-anchored monotone denominator** (§5). For Illinois: the Public Act numbers in each
   section's Source line. Non-negotiable — without it the headline percentage is gameable by narrowing.
5. **The typed residual taxonomy** — `lawvm_wrong` / `oracle_suspect` / `missing_source` — and never
   folding a residual into the coverage numerator. The spec's §4 taxonomy is close; make it exactly
   this and the two projects' numbers become comparable, which is worth something on its own.
6. **"Success = source-faithful text-state, not oracle overlap"** as a stated hazard in §4.
7. **"Generators propose; typed validators authorize."** Generalise the spec's LLM rule to every
   heuristic. *"An invisible heuristic is forbidden."*
8. **The `jurisdiction_starter/` completion gates as a literal Phase 0 checklist.** Twelve questions
   that must be answerable before code starts. Copy them; they are good, they are free, and answering
   them for Illinois is a week that saves a month.
9. **Archive-first replay.** *"Live network reads belong to acquisition, not replay."* This is a
   reproducibility invariant the spec does not currently state, and retrofitting it is painful.

**What you build yourself:** the tree/address/operation model (~1–2 weeks; the vocabulary is eight
actions and you now know all eight), the replay engine, the bitemporal graph, and the oracle harness
— all of which the spec already scopes, in a stack the project actually controls.

**Cost: +1 week of Phase 0 design absorption. Saves an estimated 4–8 weeks of design error** — the
kind you only discover in month four, when the metric turns out to have been meaningless since month
two. Every implementation week the spec budgeted stays budgeted.

### D. Not viable — **rejected, but for a narrower reason than it might seem**

"Not viable" would be right if LawVM already covered Illinois, or if a US-state frontend were a
weekend's work against a stable plugin API. Neither is true. The spec's §3.8 search found no Illinois
statute-history tool, and this evaluation found nothing in LawVM that changes that: no US state
anywhere in the tree, the word "Illinois" appears zero times, and the *federal* lane sits at 5.24%.

**Should the Illinois project exist separately? Yes — but not as "LawVM for Illinois."**

They are different products for different users. LawVM is an **assurance instrument** sold to
institutions that already publish a compilation: pilots, source-readiness assessments, drafting CI,
a human-review queue for "is your consolidation correct?" The Illinois project is a **public artifact**
— a queryable history of Illinois law that does not currently exist, for lawyers, journalists,
researchers, and the public, with a published error rate as a credibility device rather than a
deliverable.

The spec already gets this right and should keep saying it: *"a project whose value proposition is
'we will find bugs in ILGA's compilation' will disappoint; a project whose value proposition is 'you
can finally see what changed, and by the way here is our correctness score' will not."* That framing
survives contact with LawVM entirely intact. If anything, LawVM occupying the assurance niche
*clarifies* the Illinois project's positioning rather than threatening it.

---

## 9. Corrections owed to the spec

To fix in `illinois-law-vcs-spec.md` §3.7:

- **"LawVM has no US frontend" — false.** There is an exploratory `us_federal` frontend: 24,170 lines,
  28 modules, a committed bench corpus (`us/bench/us_bench_corpus.csv`), eleven specification
  documents under `us/spec/`, Public Law USLM acquisition working, and a measured 5.24% dry-run
  coverage. It has no US *state* frontend — that part stands, and it is the part that matters.
- **"Jurisdictions: Finland, Estonia, New Zealand, UK" — undercounts.** Eight in-tree
  (fi, ee, uk, nz, no, se, eu, us-federal) and four more staged on the site as of 2026-08-11
  (Japan, South Korea, Poland, Switzerland).
- **The "European and NZ/UK jurisdictions may make Illinois a fight" worry — inverted.** Finland, the
  reference frontend, is a whole-section-restatement jurisdiction. Illinois is the natural fit; the UK
  is LawVM's hard case.
- **"An independent team" — it is one person.** `eliask` (Elias Kunnas), 6,502 of 6,502 commits,
  agent-assisted. This does not diminish the work, which is remarkable, but it changes every
  collaboration assumption downstream of the phrase.
- **"[UNVERIFIED — needs an hour with the repo]" in §10 and the §11 open-questions table** can now be
  closed: **build fresh, adopt the doctrine, and send the geo-block email.**

---

## Sources

All fetched or queried **2026-08-11**.

- LawVM homepage — <https://lawvm.org/>
- LawVM jurisdictions (stamped "Reviewed: 11 August 2026") — <https://lawvm.org/jurisdictions/>
- "Why Law Is Law-Shaped" — <https://lawvm.org/why-law-is-law-shaped/>
- Source repository — <https://github.com/eliask/lawvm> (cloned at `e5f5f69`, committed 2026-07-12)
- GitHub REST API: `repos/eliask/lawvm`, `/commits`, `/contributors`, `/releases`, `/tags`,
  `/issues?state=all`, `/pulls?state=all`, `/events`; `users/eliask/events/public`,
  `users/eliask/repos`
- PyPI: `https://pypi.org/pypi/lawvm/json` → HTTP 404; `farchive` → HTTP 200
- In-tree, read directly: `LICENSE`, `README.md`, `AGENTS.md`, `pyproject.toml`,
  `docs/jurisdictions.md`, `docs/benchmark-methodology.md`,
  `notes/CROSS_JURISDICTION_ARCHITECTURE.md`, `notes/FI_AMENDMENT_DRAFTING_GRAMMAR.md`,
  `jurisdiction_starter/README.md`, `jurisdiction_starter/STARTER_ASSESSMENT.md`,
  `us/README.md`, `us/spec/JURISDICTION_PROFILE.md`, `us/spec/SOURCE_STRATEGY.md`,
  `us/spec/US_EVAL_STATE.md`, `src/lawvm/core/semantic_types.py`,
  `src/lawvm/core/frontend_contract.py`, `src/lawvm/tools/cli.py`, `src/lawvm/tools/scaffold.py`
- Project spec under evaluation: `margo/state/illinois-law-vcs-spec.md` §§1, 2.5, 2.6, 3.7, 3.8, 4–11
