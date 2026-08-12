# Technical + Product Spec: a version-control system for Illinois statutory law

> **Two rulings this document lists as open have since been made** (2026-08-11): the community
> layer (§7) and the second jurisdiction (§10). See **[decisions.md](decisions.md)**, which is the
> authority where the two disagree. The rest of the spec stands as written.

**Status:** draft for owner review · **Scope:** Illinois, v1 · **Date:** 2026-08-11
**Name:** none yet — a naming decision is out with the owner. This document says "the project" / "the system" throughout.

All web sources were fetched **2026-08-11** unless noted otherwise. Claims I could not verify are marked **[UNVERIFIED]** or **[ESTIMATE]**.

---

## 0. One-paragraph summary

Illinois publishes the current text of its statutes, and it publishes every Public Act that ever changed them, but it does not publish the relationship between the two in any form a machine — or a person — can follow. The amendment history at the foot of an ILCS section is a bare list of Public Act numbers: a `git log` with no `git show`. This project reconstructs the missing diffs by treating Public Acts as commits and replaying them against the compiled text. The reconstruction is **self-validating**: the correct answer is already published on ilga.gov, so every run produces a byte-match percentage and a list of divergences, with no human grader. The percentage is the product's first deliverable and its permanent regression metric.

---

## 1. The core framing, and where it breaks

### 1.1 The mapping

| Version control | Illinois legislation |
|---|---|
| commit | Public Act |
| commit message / author | bill title, sponsors, GA session |
| commit timestamp | **two** timestamps: date approved and effective date — they differ, often by months |
| working tree | the compiled ILCS section as published on ilga.gov |
| `git log` | the `(Source: P.A. …)` line at the foot of each section |
| `git show` | **does not exist** — this is the gap the project fills |
| rendered diff | the enrolled bill with strike-through and underscore |
| patch format | the amendatory instruction: "The Election Code is amended by changing Section 28-1 as follows:" |
| merge conflict | two Public Acts amending the same section with overlapping effective windows |
| `git blame` | nothing. Nobody can tell you which Public Act put a given clause there. |

This framing is sound and it is not novel — it has been arrived at independently at least twice (see §3.7, LawVM). That is a good sign, not a bad one: it means the abstraction survives contact with more than one legal system.

### 1.2 Where the framing breaks — say this out loud, repeatedly

Four places. Three are engineering problems. The fourth is not.

1. **A commit is content-addressed; an amendatory instruction is not.** Git patches carry line numbers and context hunks. Illinois amendatory instructions carry a *citation* and rely on a human to find the target. Target resolution is the real work. (§5.1)
2. **Commits have a total order; Public Acts do not.** Effective date ≠ passage date ≠ approval date, and two Acts can arrive out of order. (§5.2)
3. **Git history is append-only; statute history is not.** Retroactive amendments rewrite the past. This forces bitemporality on the data model, and it is not optional. (§5.3)
4. **The text is not the law.** A court can render a clause a dead letter without changing a byte. `git show` on the statute tells you *the words*; it does not tell you *the law*. No amount of engineering fixes this. It is a permanent, structural limit and it must be visible in the UI, not buried in a footer. (§5.5)

Point 4 is the one that will get the project criticised by lawyers if it is handled badly, and it is the one most likely to be quietly under-designed. Design for it first.

---

## 2. What Illinois actually publishes (research findings)

### 2.1 The compiled statutes (ILCS)

**Entry points**
- Chapter index: `https://www.ilga.gov/Legislation/ILCS/Chapters`
- Acts within a chapter: `/Legislation/ILCS/Acts?ChapterID=2&ChapterNumber=5&Chapter=GENERAL%20PROVISIONS&MajorTopic=GOVERNMENT`
- Articles/sections within an act: `/Legislation/ILCS/Articles?ActID=79&ChapterID=2`
- Single section, application route: `/Legislation/ILCS/fulltext?DocName=000500700K4` (verified working)
- Single section, **static document route**: `https://ilga.gov/documents/legislation/ilcs/documents/000500700K4.htm` (verified working)

The `DocName` key is the useful discovery. It decomposes as **4-digit chapter + 5-digit act + `K` + section number**:

```
000500700K4        →  5 ILCS 70/4
072000050K11-501   →  720 ILCS 5/11-501
002501350K5.04     →  25 ILCS 135/5.04
```

That is a *deterministic, enumerable primary key over the entire corpus*, derivable from the chapter/act index without crawling every page to discover links. It is also stable across the site's 2025-ish redesign — the legacy `.asp` routes are gone (`/legislation/ilcs/fulltext.asp?DocName=…` now 404s) but the `DocName` itself survived into both the new app route and the static `/documents/` route. Prefer the static route: it is cheaper to serve, less likely to be rate-limited, and less likely to change shape again.

**Section anatomy**, verified on `5 ILCS 70/4`:

```
5 ILCS 70/4
(from Ch. 1, par. 1103)
    Sec. 4. No new law shall be construed to repeal a former law, whether such
former law is expressly repealed or not, …
(Source: R.S. 1874, p. 1011.)
```

Three parts matter:
- **ILCS citation** — chapter / act / section.
- **`(from Ch. …, par. …)`** — a cross-reference to the *pre-1993 Illinois Revised Statutes* numbering. Free identifier-mapping data for anything that wants to resolve old citations.
- **`(Source: …)`** — the amendment history line. This is the `git log`.

**Source-line shapes observed**
- `(Source: P.A. 102-839, eff. 5-13-22.)` — the common case: last amending Act plus its effective date.
- `(Source: P.A. 103-274, eff. 1-1-24.)`
- `(Source: R.S. 1874, p. 1011.)` — pre-Public-Act provenance. **Any section whose source predates machine-readable Public Acts is unreconstructable and must be labelled as such, not silently shown as "no changes."**

Longer sections carry multi-Act source lines listing several P.A. numbers. That list is the log with no `show`, and it is the literal thing the owner noticed in college.

### 2.2 The compilation is *not* official, and it is not a snapshot

Two disclaimers from ilga.gov, both load-bearing for the whole design.

**(a) Not official.** From the ILCS index and the ILCS guide:

> "The provisions have NOT been edited for publication, and are NOT in any sense the 'official' text of the Illinois Compiled Statutes as enacted into law. The accuracy of any specific provision originating from this site cannot be assured… This site should not be cited as an official or authoritative source."
> — <https://www.ilga.gov/Legislation/ILCS/Chapters>

**(b) It is a *forward-leaning drafting working tree*, not a point-in-time snapshot.** Paraphrasing the ILGA's own statement (fetched via search snapshot of the ILCS pages, 2026-08-11): the database is maintained primarily for legislative *drafting* purposes; statutory changes are sometimes included **before they take effect**; and if the source note at the end of a Section includes a Public Act that has not yet taken effect, **the version currently in force may already have been removed from the database.**

This is the single most consequential finding in the research, and it inverts a naive design:

> **The ILCS text on ilga.gov is not "the law today." It is closer to `origin/develop` — including merged-but-undeployed changes — than to a tagged release.**

Anything that renders ilga.gov text under a caption like "current law" is wrong on the site's own terms. It also means the oracle must **not** be defined as "reconstruct today and compare to ilga.gov today." It must be keyed per-version to the terminal Public Act in the Source line (§4.2).

### 2.3 Multiple versions of a section are a first-class, published phenomenon

From "Using the Illinois Compiled Statutes and Public Acts" (<https://www.ilga.gov/Legislation/ILCS/Guide>): multiple versions of a Section appear when

- multiple Public Acts amend the same Section,
- multiple new Sections carry the same Section number,
- a Public Act has a delayed effective date, or
- a version of the Section has been **held unconstitutional**.

Each version is prefixed by a parenthetical showing its derivation, e.g. `(Text of Section before amendment by P.A. 103-274)`. The Guide points to **5 ILCS 70/6** (Statute on Statutes) and **Chapter 70 / §25-50 of the Illinois Bill Drafting Manual** for the construction rules.

This is enormously good news and it deserves emphasis: **Illinois already publishes its merge conflicts.** It does not silently pick a winner. The `(Text of Section before/after amendment by P.A. …)` marker *is* a conflict marker. The project should parse it as one and render it as one, rather than inventing a conflict detector from scratch and hoping it agrees. The detector in §5.2 then becomes a *cross-check on ILGA's own conflict marking* — which is itself a second oracle.

**[UNVERIFIED]** I was not able to retrieve the verbatim text of 5 ILCS 70/6 (direct fetch 404'd, and the search snapshot only paraphrased). Before implementation, pull `DocName=000500700K6` from the static document route and read it directly. It governs how simultaneous amendments are construed and it is a normative input to the conflict-surfacing design, not background reading.

### 2.4 Public Acts

- Index by GA: `https://www.ilga.gov/legislation/publicacts` — listed in blocks of 100 (e.g. 104-0001 … 104-0833 for the 104th GA).
- Per-Act HTML: `/Legislation/PublicActs/View/104-0001`
- Printer-friendly HTML: `/Legislation/PublicActs/PrinterFriendly/104-0001`
- PDF: `/Documents/Legislation/PublicActs/104/PDF/104-0001.pdf`
- Legacy bill text (older GAs), e.g. 92nd GA: `/Documents/legislation/legisnet92/sbgroups/sb/920SB1855LV.html`; 90th GA `legisnet90/…`

**Act anatomy**, verified on P.A. 103-0565 and 104-0001:

```
AN ACT concerning local government.
Be it enacted by the People of the State of Illinois, represented in the General Assembly:

    Section 5. The Election Code is amended by changing Section 28-1 as follows:

    (10 ILCS 5/28-1) (from Ch. 46, par. 28-1)
    (Text of Section before amendment by P.A. 103-274)
    Sec. 28-1. …
    (Source: P.A. 102-839, eff. 5-13-22.)

    …

    Section 999. Effective date. This Act takes effect upon becoming law.
```

Note the structure: **the Public Act embeds the codified section with its own header, version marker, and Source line.** The Act is not a bare patch — it carries its own copy of the target's identity and provenance. Target resolution therefore has strong redundant signal (ILCS citation *and* `from Ch.` cross-reference *and* the section catchline), which materially reduces the fuzzy-matching problem.

Effective-date clauses observed in the wild are richer than a single date. P.A. 104-0001:

> "This Act takes effect upon becoming law, except that the changes to Section 6.11 of the State Employees Group Insurance Act of 1971 take effect on July 1, 2027."

So **effective date is a property of the (Act, target-provision) pair, not of the Act.** Any schema that hangs one `effective_date` off the Act is wrong on real 2025 data. This is a concrete, cheap-to-get-wrong modelling decision; get it right in the first migration.

### 2.5 The amendatory format — a correction to the project's premise

The brief describes amendatory instructions as fuzzy patches: *"in Section 504(b-1), strike X and insert Y."* **For Illinois, this is largely not the case, and the difference is worth more than any other single finding in this document.**

Illinois practice, per the Illinois Bill Drafting Manual (<https://www.ilga.gov/commission/lrb/Manual.pdf>) and confirmed against actual Acts:

- An amendatory bill states `The <Act> is amended by changing Section <N> as follows:` and then **reprints the entire section**, with additions underscored and deletions struck through.
- Repeals do **not** reprint text — they name the act and list the repealed section numbers.
- Entirely new Acts are **not** marked up at all (nothing to strike).

**Consequence: for the dominant instruction type, "applying the patch" is not a fuzzy edit at all. It is `cp`.** The enrolled Act contains the complete post-amendment text of the section; the apply step is (a) resolve the target, (b) strip struck-through text, (c) accept underscored text, (d) replace the whole provision. There is no hunk matching, no line numbers needed, no "second occurrence of" ambiguity in the common path.

This moves the difficulty. It does **not** remove it. The residual hard cases:

| Case | Why it's hard | Rough share **[ESTIMATE]** |
|---|---|---|
| `by changing Section N` | trivial once target resolved | ~80–90% |
| `by adding Section N` | needs insertion position within the Act's ordering | ~5–10% |
| `by changing … and, in part, by resectioning Sections …` (observed verbatim in 92nd GA SB1855) | renumbering: identity of provisions changes, so version lineage forks/merges | low single digits |
| repeal of act/section | no text; must materialise a tombstone version | low single digits |
| target has multiple published versions | which version does this Act amend? Requires reading the `(Text of Section …)` marker and reconciling | **the main source of genuine review load** |
| `(Source: R.S. 1874 …)` and other non-P.A. provenance | pre-machine-readable; unreconstructable | small but permanent |

**My honest estimate of the fraction requiring human review: 1–5% of instructions, concentrated almost entirely in multi-version sections and resectioning.** I am flagging this as **[ESTIMATE]** with low confidence and a wide band. It is a guess about a measurable quantity, which is exactly the kind of guess this project exists to destroy — **Phase 1 replaces this number with a measurement within weeks.** Do not build a plan that depends on this estimate being right; build the plan that measures it.

The struck-through/underscored markup does need to survive extraction. In HTML views the strike/underscore is carried by markup; in the PDF it is carried by font styling. **[UNVERIFIED]** — I could not decompress the PDF streams or read the raw HTML through the fetch tool's markdown conversion, so the exact tags (`<strike>`/`<s>`/`<del>` vs CSS class) are unconfirmed. **This is the first thing to check in Phase 0**, because it determines whether the HTML route is usable at all or whether you must render PDFs. If the HTML flattens the markup and loses deletions, the HTML route is worthless for Acts and the PDF becomes the source of record. That single unknown is the largest schedule risk in Phase 0.

### 2.6 Effective dates: the statutory rules

- **Ill. Const. art. IV, §10** — the General Assembly provides a uniform effective date for laws passed before June 1; a bill passed after May 31 does not take effect before June 1 of the *next* calendar year unless three-fifths of each house provide an earlier date. (<https://www.ilga.gov/commission/lrb/con4.htm>)
- **Effective Date of Laws Act, 5 ILCS 75** (`ActID=80`) — implements the above; supplies the default when an Act is silent.
- **5 ILCS 70/4** (Statute on Statutes) — savings clause: a new law is not construed to repeal a former law as to offenses committed, acts done, penalties incurred, or rights accrued under the former law.

The practical rule the ingest must encode: **an Act with no effective-date section does not have "no effective date" — it has a statutory default**, and computing it requires the passage date and the vote margin. Sourcing the three-fifths vote flag means touching bill status pages, not just the Act text. Budget for that; it is a real dependency, not a footnote.

### 2.7 Judicial overlay — Illinois hands you a starting point

The Legislative Reference Bureau publishes an annual **Case Report**, a cumulative report of Illinois statutes held unconstitutional:

- <https://lrb.ilga.gov/Commission/lrb/2025_Case_Report.pdf> (latest found)
- back-years: `2019_Case_Report.pdf`, `2018_`, `2016_`, `2015_`, `2014_`, and `Case_Report_2004.pdf`

This is not a citator and must never be described as one. It *is* a published, authoritative, machine-ingestible list of "this text is on the books and is not the law." Ingesting it is cheap and buys the single most important honesty affordance in the product (§5.5). Do it in v1.

### 2.8 Access constraints: robots.txt, rate, terms

**robots.txt** (<https://www.ilga.gov/robots.txt>, fetched 2026-08-11):
- Several commercial crawlers banned outright (MJ12bot, AhrefsBot, SemrushBot, DotBot, Yandex, Baiduspider, Sogou, SiteExplorer).
- For all agents, disallowed paths: `/account`, `/admin`, `/search`, `/api`.
- `Crawl-delay: 10` for all bots.
- Sitemap: <https://ilga.gov/sitemap.xml>

Three conclusions:

1. **`/Legislation/ILCS/…`, `/documents/legislation/…` and `/Legislation/PublicActs/…` are not disallowed.** Crawling the corpus is permitted by robots.txt. `/search` and `/api` are disallowed, so **do not** drive ingest through the site's search or any API endpoint — enumerate via the chapter/act index and the derived `DocName` key instead.
2. **`Crawl-delay: 10` is the binding constraint on schedule.** At 10 s/request, 30,000 ILCS sections is ~83 hours of single-threaded crawling **[ESTIMATE]** — over three days. The Public Act corpus is comparable or larger. Design the crawler as a resumable, conditional-GET, content-addressed mirror that runs once and is then incrementally refreshed; treat the mirror as an artifact to be preserved, not re-fetched. Honour the 10 s delay literally. This project's entire premise is civic good faith; hammering the state's web server is both rude and the fastest way to get blocked.
3. **The sitemap is useless for ingest** — 32 landing-page entries, no enumeration of sections or Acts. Enumeration must be derived.

**Terms of use: UNRESOLVED, and this is an action item, not a footnote.** I could not locate an explicit terms-of-use or data-reuse policy page on ilga.gov. Separately, the Illinois compilation is widely described as an official state compilation in the public domain for federal copyright purposes **[UNVERIFIED — the claim traces to Wikipedia in my search results, not to a primary source]**; the *Georgia v. Public.Resource.Org* government-edicts doctrine points the same way for statutory text. **Recommendation: before publishing a bulk mirror, send one plain email to the Legislative Reference Bureau / Legislative Information System describing the project and asking whether bulk copies are acceptable and whether they would prefer a specific access pattern.** Cost: one email. Value: converts the project's largest non-technical risk into either a yes or a documented no, and a state legislative body that knows who you are is an asset rather than a threat. Do this in Phase 0.

### 2.9 Corpus coverage floor — the hard boundary on ambition

Machine-readable bill/Act text on ilga.gov appears to begin around the **90th General Assembly (1997–98)** based on the `legisnet90/` document paths observed. Everything earlier exists in the printed *Laws of Illinois* and would require OCR of scanned volumes.

**Therefore: v1 cannot answer "what did this section say in 1985."** It can answer "what did it say in 2003" for sections whose entire post-1997 history is reconstructable, and "here is every change since 1997" for the rest. **[UNVERIFIED — confirm the earliest GA with full text online; the 90th is the earliest I saw, but I did not test 89th and below.]**

State this limit in the product, prominently, the way legislation.gov.uk states its 1991 basedate (§3.1). A tool that is honest about its floor is trusted; a tool that silently renders a partial history as complete is worse than nothing, because a partial history *looks exactly like a complete one*.

---

## 3. Prior art, assessed honestly

### 3.1 legislation.gov.uk — the best in the world, and the most useful teacher

<https://www.legislation.gov.uk/> · limitations: <https://www.legislation.gov.uk/developer/limitations> · help: <https://www.legislation.gov.uk/help>

**What it does well — steal all of this:**

- **True point-in-time versions.** Any provision can be viewed as it stood on a given date, via a timeline of changes.
- **The "Changes to Legislation" box.** Applied vs unapplied effects are *distinguished and both shown*. Unapplied effects are listed at the top of the provision in a red box.
- **It ships its backlog as a feature.** The editorial team cannot keep up, and rather than hiding that, the site tells you on every page whether there are outstanding effects. From the help pages: on opening content with outstanding changes, the outstanding effects are listed at the top of the provision.
- **It publishes its own limitations page** and does not oversell: "The completeness and accuracy of the data cannot be guaranteed."
- **Structured data alongside every page** (`/data.xml`, `/data.htm`), so the human view and the machine view are the same object.

**Where it stops:**

- **Basedates.** Revised (consolidated) text starts at **1 February 1991** for most UK legislation and **1 January 2006** for Northern Ireland. "No version history is available prior to these basedates."
- **Secondary legislation is not revised at all** (amendments are not incorporated into the text), except NI Orders in Council.
- **The consolidation is human editorial work.** There is a team applying effects by hand. The backlog is structural, not a bug: "the legislation is somewhat out of date because the SLD itself is out of date."

**The lesson, and it is the central strategic lesson of this whole document:** the best legislative-text system on earth is a *human* consolidation with a permanent, publicly-declared backlog. This project's differentiator is not "point-in-time views" — the UK solved that. It is that **the consolidation is mechanical and re-runnable**, so the backlog is a compute cost rather than a staffing cost, and correctness is measurable rather than asserted. Design every UI affordance in imitation of legislation.gov.uk, and design the *pipeline* to be the thing they don't have.

### 3.2 Akoma Ntoso / OASIS LegalDocML

<https://www.oasis-open.org/standard/akn-v1-0/>

Mature, international, genuinely well-designed for parliamentary/legislative/judicial documents, and the parent of the US **USLM** schema (<https://github.com/usgpo/uslm>). AKN's FRBR-derived Work/Expression/Manifestation layering is exactly the right conceptual model for "the same provision at different points in time," and its naming convention is an OASIS standard.

**Where it stops:** adoption. "The rate of adoption has been strikingly low, perhaps owed to the two-fold complexity of migrating legislative documents from text to XML and the requirement of XML competency in the translation process" — *The Legislative Recipe: Syntax for Machine-Readable Legislation*, <https://arxiv.org/pdf/2108.08678>. Converting to AKN requires a legal expert to hand-sort text, structure, metadata, and ontology while fluent in the schema. **No Illinois source publishes AKN, and nothing will convert Illinois HTML to good AKN for free.**

Verdict in §6: borrow AKN's *identity model*, do not adopt its *document model* for v1.

### 3.3 Open States / Plural

<https://docs.openstates.org/> · bulk data: <https://open.pluralpolicy.com/data/>

Solved and battle-tested: 50-state **bill** metadata, sponsors, actions, votes, and links to bill text versions, with bulk downloads and an API. Scrapers are open source and have absorbed a decade of per-state weirdness.

**Where it stops:** Open States models the *legislative process*, not the *code*. It tracks bills; it does not maintain codified statutes and does not attempt point-in-time statutory reconstruction. Its "versions" are versions of a bill (introduced/engrossed/enrolled), not versions of a statute.

**Do not rebuild bill metadata.** If Open States has usable IL coverage for bill→Public Act linkage, sponsors, and vote margins (needed for the three-fifths effective-date rule, §2.6), consume it and keep custom scraping to the statutory side. **[UNVERIFIED — check IL coverage depth and whether P.A. numbers are carried.]**

### 3.4 Cornell LII

<https://www.law.cornell.edu/states/illinois>

Excellent free access to federal materials (US Code, CFR) and a long-trusted brand. For state law it is largely a curated **link directory** to official sources. No Illinois point-in-time, no reconstruction. Nothing to rebuild; a good citation-format and cross-reference reference.

### 3.5 The @unitedstates project / USGPO / govinfo

<https://github.com/usgpo/uslm> · <https://www.govinfo.gov/bulkdata/PLAW/resources/readme.html>

Federal only, and **federal is the easy case**: GPO publishes USLM XML for enrolled bills and public laws (113th Congress forward) and Statutes at Large (108th forward), plus Statute Compilations in USLM. When the upstream publisher ships structured XML, most of this project's hard problems evaporate.

**The lesson:** the federal ecosystem's tooling is not portable to Illinois, because the *input* is different in kind — Illinois ships HTML and PDF prose, not XML. Any plan that assumes "we'll adapt the federal tools" is wrong at the first step.

### 3.6 Free Law Project / CourtListener / eyecite

<https://free.law/> · <https://github.com/freelawproject/eyecite> · citator progress: <https://free.law/2025/05/01/citator/>

Case law, dockets, and citation extraction — including **statutory** citation recognition in eyecite, tested against 50M+ citations. FLP is actively building a citator using eyecite plus LLM analysis of citation context.

**Where it stops:** they do not maintain state codes, and the citator is in progress rather than shipped.

**Use eyecite; do not write a citation parser.** And watch the citator: if it lands, the judicial-overlay layer this project scopes out of v1 (§5.5) becomes an integration rather than a build. For ILCS-citation-shaped strings specifically, **datamade/ilcs-parser** (<https://github.com/datamade/ilcs-parser>) is a probabilistic parser for ILCS references — narrow, but exactly on point and already written.

### 3.7 LawVM — direct prior art. Read this before writing a line of code.

<https://lawvm.org/> · <https://lawvm.org/why-law-is-law-shaped/>

**This is the same idea, built, open source, and already producing findings.** It describes itself as a deterministic replay compiler that reconstructs point-in-time legal text from declared amendment sources, treating legislation as executable state transitions and preserving provenance, replay evidence, and divergence findings.

Convergent details worth noting because they validate the design proposed here:

- It models amendments as **typed operations** with a target address, an action, a payload, and a source; roughly seven operation types (replace, repeal, insert, renumber, text-replace, text-repeal…).
- It uses the **published consolidation as an oracle**: in Finland, where Finlex consolidated texts are informational rather than binding, it acts as "an independent replay witness"; in Estonia, where consolidated text has official weight, "an independent consistency check."
- It reports **confirmed divergences**: one confirmed Estonian correction (April 2026), plus three New Zealand and two UK candidate findings below the confirmation threshold.
- It scopes itself explicitly to the **text layer**, excluding interpretive overlays, deeming clauses, delegated-legislation authority chains, conditional applicability, and revivor rules.

**Jurisdictions: Finland (active frontend), Estonia, New Zealand, UK. No US states. No Illinois.**

**Does this kill the project? No — and here is the honest reasoning rather than a reassuring one.**

- The *idea* is not novel. Anyone pitching this as an original insight will be corrected, and should stop pitching it that way. Cite LawVM up front; it is a strength, not an embarrassment, that an independent team reached the same abstraction.
- The *work* is not done. LawVM has no US frontend and, on its own account, "a general replay workflow still has to connect source acquisition, amendment parsing, target resolution, temporal policy, and evidence classification across jurisdictions." Nearly all of the cost of an Illinois system is in those five things, and all five are jurisdiction-specific.
- The confirmed-findings count (one) tells you the honest yield rate: **this technique finds real errors, and it finds a small number of them.** Plan the product around the *artifact* (a queryable history of Illinois law that does not currently exist) and treat divergence findings as a bonus. A project whose value proposition is "we will find bugs in ILGA's compilation" will disappoint; a project whose value proposition is "you can finally see what changed, and by the way here is our correctness score" will not.
- **Before building: evaluate LawVM as a dependency rather than a competitor.** If its core is genuinely jurisdiction-agnostic, the right move may be to write an Illinois frontend for it and contribute upstream. That decision needs an hour with its GitHub repo and is a Phase 0 task. It could remove a third of the engineering.

### 3.8 Has anyone done this for Illinois specifically?

**Searched, and found no one.** Specifically checked for: an Illinois statute diff/version-history tool, an ILCS scraper or dataset, a civic-tech launch in 2024–2026, and Illinois coverage in the general-purpose legal-data projects above.

What exists for Illinois:
- **Justia** publishes **annual snapshots** of the ILCS (`law.justia.com/codes/illinois/2019/`, `/2024/`, and a current view). These are point-in-time at **one-year granularity** — coarse, no diffs, no Public Act attribution. **Strategically important anyway: they are an independent second oracle** (§4.4) and the only readily-available historical baseline other than the Internet Archive.
- **datamade/ilcs-parser** — parses ILCS *citations*. Not text, not history.
- **LegiScan** (<https://legiscan.com/IL/datasets>) — bill-level session archives in JSON/XML/CSV. Bills, not code.
- Commercial annotated compilations (West/Smith-Hurd, LexisNexis) — annotated, historical, paywalled, and not reusable.
- **mattstoller/bill-diff-tool** — federal bills vs US Code. Right idea, wrong jurisdiction.

**Finding: the Illinois-specific gap is real and unoccupied.** The generic gap is partially occupied by LawVM. That is the accurate framing and it should go in the README.

---

## 4. The oracle — the spine of the plan

Everything else in this document is negotiable. This is not.

### 4.1 Why it matters more than it sounds

Most legal-informatics projects cannot tell you whether they are correct. They ship, and correctness is a matter of reputation and spot-checking. This project can compute its own accuracy on every commit, over the whole corpus, with no human grader, because **the answer is already published.** That converts a research project into an engineering project with a regression suite, and it is the reason to build this rather than something else.

Two design commitments follow:

1. **The oracle runs in Phase 1, before the parser is good, before there is a UI.** Its first number will be bad. That is fine and expected; a bad number you can improve beats a good story you cannot check.
2. **The percentage is public.** On the site, in the README, per-chapter and per-Act. A system that publishes its own error rate is trusted in a way that one which doesn't cannot be. (legislation.gov.uk proves the point — its limitations page is a credibility asset.)

### 4.2 Oracle-0: the single-hop match (available on day one, no history required)

This is the highest-value, lowest-cost measurement available, and it falls out of §2.5.

Because an Illinois amendatory Act **reprints the entire amended section**, you do not need to chain anything to start measuring:

```
for each ILCS section version V:
    P := terminal Public Act in V's (Source: …) line
    T := the text of that section as printed in Public Act P, with
         struck-through text removed and underscored text retained
    compare normalize(T) with normalize(V.text)
```

**No base snapshot. No chain. No effective-date reasoning. Runs on day one of having the corpus.** It measures exactly two things, both of which you must fix before anything harder is meaningful:

- **extraction fidelity** — did you correctly read the strike/underscore markup and the section boundaries?
- **editorial drift** — where does the LRB's compiled text legitimately differ from the enrolled text?

Every ILCS section with a P.A. source line is a test case. That is tens of thousands of test cases on day one **[ESTIMATE]**.

### 4.3 Oracle-1: the chain

Once Oracle-0 is high, replay: pick a section, take an anchor version, apply every subsequent Public Act in effective-date order, and compare each intermediate result against the corresponding published version.

The anchor problem is real and must be stated plainly: **you cannot replay from origin.** Machine-readable Acts start ~1997 (§2.9) and many sections have pre-1997 provenance. Three anchor strategies, in order of preference:

1. **Internet Archive captures of ilga.gov** — gives dated baselines at whatever cadence the Wayback Machine crawled. Best available true point-in-time anchor. **[UNVERIFIED — check actual capture density for `/legislation/ilcs/` URLs.]**
2. **Justia annual snapshots** — coarse but well-structured and dated.
3. **Reverse replay** — start from today's text and *un-apply* Acts backwards. Elegant, and it doubles as a check: forward-from-anchor and backward-from-today must meet in the middle. Where they don't, something is wrong and you know roughly where.

Do all three. Their disagreements are findings.

### 4.4 Oracle-2: cross-publisher agreement

Compare reconstructed text at date *D* against Justia's snapshot for the year containing *D*, and against Wayback captures. Three independent publishers agreeing is strong evidence; two agreeing against one is a triage signal pointing at the odd one out.

### 4.5 Normalisation — where a naive implementation dies

Byte-matching raw HTML-extracted text will report ~0% and teach you nothing. You need a **declared, versioned normalisation function**, and its aggressiveness is a correctness/sensitivity tradeoff that must be an explicit, reviewable artifact:

| Normalise (safe) | Never normalise (would hide real findings) |
| --- | --- |
| Unicode NFC; smart→straight quotes; en/em dash spacing | any word, number, or punctuation *inside* the operative text |
| collapse runs of whitespace; strip leading indent | cross-references (`Section 5-1` vs `Section 5.1`) |
| HTML entity decode; `&nbsp;`→space | singular/plural, "shall"/"must" |
| line-wrapping differences | anything the diff would render to a user |

Report **two numbers, always, side by side**: `exact_bytes` and `normalized`. If they diverge widely, the normaliser is doing too much work and is hiding findings.

### 4.6 Divergence taxonomy — every mismatch gets a label

A mismatch is not automatically a finding. Classify (borrowing LawVM's "evidence classification" framing):

| Class | Meaning | Action |
|---|---|---|
| `EXTRACT` | our HTML/PDF parsing lost or mangled something | fix the extractor; regression fixture |
| `NORMALIZE` | cosmetic, below the normaliser's threshold | tune normaliser; document |
| `EDITORIAL` | legitimate LRB compilation work (renumbering, internal-reference updates, removing `Section 999`, combining versions) | encode as a **declared editorial rule** with a citation to the Drafting Manual |
| `TEMPORAL` | we applied the wrong Act, or in the wrong order | fix the temporal model — this is the interesting class |
| `CONFLICT` | two Acts genuinely collide; no single right answer | surface, never resolve (§5.2) |
| `DIVERGENCE` | our replay is defensible and the published text does not match | **candidate finding** — hold to a high bar |
| `UNRECONSTRUCTABLE` | pre-1997 provenance, or missing source | label in UI; exclude from the denominator, and say so |

**Only `DIVERGENCE` is ever published as a finding, and only after a human reviews it and a second reviewer agrees.** LawVM's language of "candidate findings below the confirmation threshold" is the right posture: a false accusation against the state's compilation costs more credibility than ten true ones earn.

### 4.7 The metric

```
match_rate = |versions where normalized(replay) == normalized(published)|
             ----------------------------------------------------------
             |versions attempted|          (excluding UNRECONSTRUCTABLE)
```

Published per chapter, per act, per GA, and over time. Regressions block merges. `EXTRACT` and `NORMALIZE` classes count as *failures*, not excuses — the temptation to reclassify your way to a high number is the single most likely way this project quietly stops being honest.

---

## 5. The hard problems

### 5.1 Amendatory instructions as a patch format

**Restating §2.5:** for Illinois the apply step is mostly whole-section replacement, so the difficulty is **target resolution**, not text surgery.

**Parsing strategy — three tiers, in this order:**

**Tier 1 — deterministic grammar (expect the large majority).** The instruction sentence is highly stereotyped:

```
Section <n>. The <Act name> is amended by <verb-phrase> Section(s) <list> as follows:
```

with `verb-phrase` ∈ {`changing`, `adding`, `changing and adding`, `changing … and, in part, by resectioning`, `repealing`, …}. Write a real grammar (PEG or an LR parser), not regexes — the constructs nest and coordinate, and regexes will rot. Emit **typed operations**:

```python
Op = Replace(target, new_text) | Add(target, new_text, anchor) | Repeal(target)
   | Renumber(from_target, to_target) | TextReplace(target, old, new)
```

Target resolution then uses **three redundant signals present in the Act itself**: the ILCS citation in the embedded header, the `(from Ch. …, par. …)` legacy cross-reference, and the section catchline. Require **at least two to agree**; disagreement is an automatic review flag. This redundancy is why Illinois is more tractable than the brief assumes, and it should be exploited deliberately rather than incidentally.

**Tier 2 — structural fallback.** When the grammar fails but the Act still embeds a recognisable section block with a header and a Source line, extract the block and treat it as a `Replace` on the cited target, flagged `LOW_CONFIDENCE`. This will catch a lot.

**Tier 3 — human review queue, with LLM assistance permitted but constrained.** For genuinely irregular instructions ("in Section 504(b-1), strike X and insert Y" — rarer in IL but not absent). **Hard rule: an LLM may propose an operation; it may never produce statutory text.** The operation is applied deterministically or not at all. The reason is the oracle: if a model writes text, the match rate becomes a measure of the model's ability to copy rather than of the pipeline's correctness, and the project loses the one thing that makes it different. This is the same line the community-layer ruling draws (§7), for the same reason.

**Every Tier 2/3 resolution becomes a permanent regression fixture.** Human effort spent once should never need spending twice — that is the entire economic argument for a mechanical consolidation over the UK's editorial one.

### 5.2 Effective dates are not merge dates

Two Public Acts amend the same section, pass months apart, and take effect in either order. Each restates the whole section as it existed *when its bill was drafted*, so the second one to take effect silently reverts the first's changes unless someone reconciles them. Today that reconciliation is done by hand at the LRB.

**Detection algorithm:**

```
group operations by target provision
for each pair (A, B) targeting the same provision:
    if A.effective_window and B.effective_window overlap
       or |A.effective - B.effective| is small
       and A.base_text_hash == B.base_text_hash        # both drafted from the same predecessor
       and A.result_text_hash != B.result_text_hash:
           emit CONTESTED_WINDOW(provision, A, B)
```

The `base_text_hash` comparison is the crux, and it is only possible **because Illinois Acts reprint the full section**: you can hash what each Act *believed* the prior text to be. Two Acts that disagree about the starting text are, definitionally, drafted in ignorance of each other. That is a clean, cheap, high-precision conflict detector, and it is a direct dividend of the format finding in §2.5.

**Surfacing, not resolving.** The system renders a **contested window**: both candidate texts, both Acts, both effective dates, a diff between them, a link to 5 ILCS 70/6, and a plain statement that the system does not choose. Where ILGA has published its own `(Text of Section before/after amendment by P.A. …)` versions, show those *as the compiler's answer* alongside the machine's — and where the detector fires but ILGA published no marker, or vice versa, that is a finding in its own right.

**Do not build an auto-resolver.** Not in v1, not in v3. Choosing between two colliding statutory texts is statutory construction, which is a legal act; a tool that does it silently is claiming an authority it does not have and cannot support. Surfacing is the product.

### 5.3 Retroactive amendments rewrite history

A Public Act can change what the law *was*, and Illinois courts run the *Landgraf* framework — legislature's express temporal reach controls, and absent that, an amendatory act is read against 5 ILCS 70/4, with procedural changes generally applying to pending cases and substantive changes generally prospective.

**This forces bitemporality.** Not "would be nice." Forces.

Every version carries two independent intervals:

- **valid time** — when this text is/was the law: `[effective_from, effective_to)`
- **transaction time** — when the system (and the world) knew it: `[known_from, known_to)`

A retroactive Act inserts a version whose *valid* start precedes its *transaction* start. Every point-in-time query therefore takes **two** dates:

> "What did § X say **as of 2019-03-01**, **as best known on 2019-03-01**?" (what a practitioner would have relied on then)
>
> versus
>
> "What did § X say **as of 2019-03-01**, **as known today**?" (what a court would now hold it said)

**These can differ, and the difference is often the whole point of the question.** A UI that offers only one date is quietly answering a question the user didn't ask. Offer both; default to as-known-today; make the toggle visible and explain it in one sentence.

Bitemporality is cheap in Postgres (two `daterange` columns, GiST indexes, exclusion constraints) and enormously expensive to retrofit. Put it in the first migration.

### 5.4 Session law vs compiled code — the Illinois rule

The rule, stated precisely and sourced:

1. **The Public Act is the enactment.** ILCS is "a cumulative organization of Public Acts into a coherent framework" (<https://www.ilga.gov/Legislation/ILCS/Guide>). Not every Public Act enters the ILCS — the Guide names land conveyances and appropriations as examples that may not.
2. **The ILCS text on ilga.gov is expressly not official**: "NOT in any sense the 'official' text… should not be cited as an official or authoritative source" (§2.2).
3. **There is no official ILCS at all.** Several unofficial annotated compilations exist (West's Smith-Hurd, LexisNexis) **[UNVERIFIED — sourced to Wikipedia in my research, not to a primary source; verify before publishing this claim]**.
4. **To determine current law you must check the Public Acts** — the Guide says so directly, because recent Acts may not yet be incorporated.

**Product consequences, all non-negotiable:**

- Every reconstructed provision cites the Public Act(s) it derives from, with links to the Act text. The Act is the primary citation; the compiled text is the convenience.
- The compilation is labelled as **an editorial product** everywhere it appears, including ILGA's own.
- The system's own reconstruction is labelled at least as loudly. It is a *third* editorial product — machine-made, reproducible, and unofficial. Never present it as more authoritative than ILGA's just because it has better provenance. Better provenance is not authority.

### 5.5 Judicial construction is an overlay, not an edit

**The hardest limit, and the one to state most loudly.**

A court can hold a statute unconstitutional, or read a clause so narrowly that it does nothing, without changing a single byte. The text on the page and the law in force then differ, permanently, with no textual signal. **Current text is not current law**, and no version-control system over text can fix that, because the change did not happen in the text.

A tool that presents perfectly reconstructed, beautifully diffed statutory text and implies that this is the answer is **more dangerous than no tool**, precisely because it looks complete. Its polish is the hazard.

**A citator is out of v1 scope** — building one is a multi-year project, and Free Law Project is already at it (§3.6). But "out of scope" cannot mean "not represented."

**Design requirements for v1:**

1. **Ingest the LRB Case Report** (§2.7). It is a published, cumulative list of Illinois statutes held unconstitutional, and it costs one PDF parser. Any section appearing in it gets a prominent, non-dismissible badge: *"A court has held some version of this section unconstitutional — see the LRB Case Report."*
2. **A persistent, always-visible affordance on every provision page.** Not a footer, not a modal, not a checkbox. Something like a permanent strip: *"This is the text. The law is the text plus how courts have read it. This system shows only the text."*
3. **Never use the word "current" unqualified.** Say "as compiled by ILGA on 2026-08-11" or "as reconstructed through P.A. 104-0833." Precision here is free and it is the difference between a research tool and a liability.
4. **Link out** to CourtListener/Google Scholar searches for the citation from every provision page. It costs a URL template and it tells the user, structurally, that there is more to know.
5. **Model the overlay in the schema now, even unpopulated.** An `overlay` table (`provision_version_id`, `source`, `kind` ∈ {held_unconstitutional, narrowed, preempted}, `citation`, `note`) costs nothing today and prevents a schema fight when the citator arrives.

---

## 6. Data model, storage, and point-in-time query

### 6.1 Akoma Ntoso vs a custom schema — decision

**Recommendation: a small custom relational schema, with AKN-compatible identifiers and an AKN export path deferred to v2+.**

The argument, since it should be argued rather than asserted:

**For AKN:** it is an OASIS standard; it already models exactly the Work/Expression/Manifestation distinction this project needs; its naming convention is standardised; adopting it would make the data interoperable with LegalDocML tooling and with USLM-adjacent federal work; and rolling your own schema for a solved modelling problem is the classic engineering mistake.

**Against AKN, and why it wins here:**

1. **No input is in AKN.** Illinois publishes HTML and PDF prose. Adopting AKN means writing a prose→AKN converter, which is a hard, expert-labour-intensive project in its own right (§3.2) — and it would sit *between* the crawler and the oracle, delaying the one thing that makes this project worth doing.
2. **No consumer is asking for AKN.** Zero Illinois consumers. Interop with nobody is not interop.
3. **AKN's granularity is wrong for the oracle.** The oracle compares *text*. Rich XML markup adds a large surface of things that can differ cosmetically — attribute order, whitespace, element choice — which inflates the divergence-triage burden without improving correctness. The natural comparison unit is normalised text plus a light structural skeleton.
4. **Cost asymmetry.** Custom schema: days. AKN pipeline: months, plus ongoing expert review. The oracle can be running in weeks with the custom schema.
5. **It is not a one-way door.** Keep the provision tree explicit (act → article → section → subsection → paragraph) and AKN export is a serialiser later, not a rewrite.

**Take from AKN regardless — this is not a rejection, it's a partial adoption:**

- **The FRBR layering**, as the conceptual spine: `Provision` (the Work — "5 ILCS 70/4, the thing that persists"), `ProvisionVersion` (the Expression — "as it read from X to Y"), `Rendition` (the Manifestation — HTML/text/PDF as published).
- **Stable, resolvable URIs** shaped compatibly with AKN's naming convention, e.g.
  `/us-il/act/5/70/4@2022-05-13` and `/us-il/publicact/102-839`.
  Getting URIs right on day one is the highest-leverage cheap decision in the whole schema; getting them wrong is a permanent migration.

**Flagging my own uncertainty:** this is the recommendation I hold least strongly. If a collaborator with real AKN fluency joins, or if a funder requires it, the calculus changes — the identity model above is deliberately chosen so that it can.

### 6.2 Schema sketch

```sql
-- WORK: the persistent identity of a provision
CREATE TABLE provision (
  id             bigserial PRIMARY KEY,
  jurisdiction   text NOT NULL DEFAULT 'us-il',
  chapter        text NOT NULL,          -- '5'
  act            text NOT NULL,          -- '70'
  section        text NOT NULL,          -- '4'
  doc_name       text,                   -- '000500700K4' (ILGA key)
  legacy_cite    text,                   -- 'Ch. 1, par. 1103'
  canonical_uri  text NOT NULL UNIQUE,   -- '/us-il/act/5/70/4'
  UNIQUE (jurisdiction, chapter, act, section)
);

-- COMMITS
CREATE TABLE enactment (
  id             bigserial PRIMARY KEY,
  jurisdiction   text NOT NULL DEFAULT 'us-il',
  pa_number      text NOT NULL,          -- '102-839'
  ga             int  NOT NULL,          -- 102
  bill_id        text,                   -- 'SB 0126'
  approved_on    date,
  title          text,
  raw_sha256     char(64) NOT NULL,      -- the captured Act document
  UNIQUE (jurisdiction, pa_number)
);

-- Effective date is per (Act, target), NOT per Act -- see 2.4
CREATE TABLE enactment_effect (
  id             bigserial PRIMARY KEY,
  enactment_id   bigint REFERENCES enactment(id),
  provision_id   bigint REFERENCES provision(id),
  op_kind        text NOT NULL,          -- replace|add|repeal|renumber|text_replace
  effective_on   date,
  effective_rule text,                   -- 'upon becoming law' | 'stated' | 'default 5 ILCS 75'
  payload_sha256 char(64),               -- content-addressed new text
  confidence     text NOT NULL,          -- grammar|structural|human
  review_state   text NOT NULL DEFAULT 'auto'
);

-- EXPRESSIONS: bitemporal, content-addressed
CREATE TABLE provision_version (
  id             bigserial PRIMARY KEY,
  provision_id   bigint REFERENCES provision(id),
  text_sha256    char(64) NOT NULL REFERENCES text_blob(sha256),
  valid_time     daterange NOT NULL,     -- when it IS/WAS the law
  known_time     daterange NOT NULL,     -- when we/the world knew it
  derived_from   bigint REFERENCES provision_version(id),
  enactment_id   bigint REFERENCES enactment(id),
  origin         text NOT NULL,          -- 'replayed' | 'observed_ilga' | 'observed_justia'
  version_marker text,                   -- '(Text of Section before amendment by P.A. 103-274)'
  EXCLUDE USING gist (
    provision_id WITH =, origin WITH =,
    valid_time WITH &&, known_time WITH &&
  )
);

CREATE TABLE text_blob (sha256 char(64) PRIMARY KEY, body text NOT NULL);

-- Oracle results: first-class data, queryable, charted
CREATE TABLE oracle_run (
  id bigserial PRIMARY KEY, started_at timestamptz, pipeline_version text,
  normalizer_version text, attempted int, matched int
);
CREATE TABLE oracle_result (
  run_id bigint, provision_version_id bigint,
  class text,                            -- EXTRACT|NORMALIZE|EDITORIAL|TEMPORAL|CONFLICT|DIVERGENCE|UNRECONSTRUCTABLE
  exact_match bool, normalized_match bool, diff jsonb
);

-- Judicial overlay: empty in v1 except the LRB Case Report, but present
CREATE TABLE overlay (
  provision_id bigint, kind text, source text, citation text, note text,
  effective_on date
);
```

**Design notes worth defending:**

- **`text_blob` is content-addressed.** Most Public Acts change a handful of sections; unchanged text dedupes automatically, and equality checks become hash comparisons. This is the git object store, and it is the right borrowing.
- **The GiST exclusion constraint enforces bitemporal non-overlap at the database level** — per `(provision, origin)`, so ILGA's observed versions and the system's replayed versions coexist without colliding. Diverging by construction is the point; overlapping *within* a lane is a bug and the database should refuse it.
- **`origin` separates observation from replay.** Observed ILGA text and replayed text are different epistemic objects and must never be silently merged. Merging them is precisely how the oracle would become meaningless without anyone noticing.
- **`enactment_effect.confidence` and `review_state`** make the human-review queue a query, not a side system.

### 6.3 Point-in-time query

```sql
SELECT b.body
FROM provision_version v JOIN text_blob b ON b.sha256 = v.text_sha256
WHERE v.provision_id = $1
  AND v.origin = 'replayed'
  AND v.valid_time @> $2::date     -- "as of"
  AND v.known_time @> $3::date;    -- "as known on"  (default: today)
```

With GiST indexes on both ranges this is a two-index lookup. **Materialise nothing in v1.** If it gets slow, cache rendered HTML by `(provision, as_of, known_on)` — but the naive query will comfortably serve a corpus this size, and premature materialisation would obscure the temporal logic while it is still being debugged.

### 6.4 Corpus size **[ESTIMATE]**

Rough sizing, all flagged as estimates and all pointing the same direction:

- ILCS: ~30,000 sections, avg ~4 KB → **~120 MB** of current text.
- Public Acts 1997–2026: ~25,000 Acts, avg ~40 KB → **~1 GB** raw.
- All historical provision versions with content-addressed dedupe: **~2–5 GB**.
- Raw crawl captures (HTML + PDF, preserved for reproducibility): **~10–30 GB**.

**Conclusion: this fits on one modest server with room to spare.** No distributed anything. Any architecture proposing sharding, a search cluster, or a queue farm for this corpus is solving a problem the data does not have.

---

## 7. The community / wiki layer — **a ruling the owner still has to make**

The owner has explicitly reserved this decision. What follows is analysis, a costed recommendation, and the strongest case against it. **It is not a decision.**

### 7.1 The four models

| Model | What users can do | Moderation cost | Vandalism blast radius | Contribution ceiling |
|---|---|---|---|---|
| **A. Read-only** | nothing | ~0 | none | zero — no community, ever |
| **B. Suggest-an-edit / PR-style** | propose changes to text; maintainer merges | **high** — every PR needs a legally-literate reviewer, and review does not parallelise | none until merge; **unbounded after** | moderate; bottlenecked on reviewer time |
| **C. Full wiki** | edit statutory text directly | **extreme** — 24/7, adversarial, needs subject-matter expertise | **unbounded and immediate** | high volume, unknown quality |
| **D. Annotation overlay** | add commentary *beside* immutable text | **moderate** — bounded by the fact that nothing they write can be mistaken for law | contained to the annotation layer | high — and it's the contribution people actually want to make |

### 7.2 The recommendation, argued

**Recommend: D, with a specific and important addition — model E below.**

**The affirmative case for machine-derived, immutable text:**

1. **It is the only thing that keeps the oracle meaningful.** The moment a human can hand-edit reconstructed text, the match rate stops measuring the pipeline and starts measuring "how much has been manually reconciled." The project's single distinguishing property — *we can prove how right we are* — evaporates, and it evaporates silently. Nobody notices the day it stops meaning anything.
2. **It preserves falsifiability.** Reproducibility (same corpus + same pipeline version → same output, bit for bit) is what lets someone else check the work. That is the difference between a research artifact and a website.
3. **It makes divergence findings credible.** "Our independent replay disagrees with the published compilation" carries weight only if no human touched the replay. If humans can edit, every finding invites "did someone just type that in?" — and the answer would be unfalsifiable.
4. **It contains liability.** Nobody can vandalise "the law" on this site, because the site does not let anyone write law. In a domain where a malicious edit to a criminal statute could plausibly cause real harm, this is not an abstract concern.
5. **It matches the domain's actual authority structure.** Statutory text is produced by a legislature. A crowd-editable statute is a category error dressed as openness.

**The strongest case against, stated fairly rather than strawmanned:**

> The pipeline will be wrong on some percentage of provisions. A knowledgeable reader can often see *exactly* what the right answer is in ten seconds. Refusing that correction on purity grounds means knowingly serving text you know is wrong, to protect a metric. Wikipedia works. Legal blogs correct courts. Refusing free labour to preserve an internal number is the tail wagging the dog.

**This objection is substantially right, and it should not be waved away.** The synthesis is:

### 7.3 Model E — "PR against the compiler, not against the artifact" (the actual recommendation)

Humans **may not** edit statutory text. Humans **may** file a **correction claim** against a reconstruction:

> *"§ 720 ILCS 5/11-501 as of 2019-06-01 is wrong. P.A. 100-987 was applied but its §15 changes to this subsection had a delayed effective date of 2020-01-01. Here is the Act, here is the clause."*

A correction claim is **data about the pipeline**, not an edit to the output. Accepting one means writing a rule, a fixture, or an editorial-normalisation entry — and then **re-running the pipeline**, so the text changes only as a *consequence* of a code change that is versioned, reviewed, and permanently regression-tested.

This gets everything: real human labour absorbed, the immutability line never crossed, the oracle still meaningful, and every accepted correction improves *every future run* rather than patching one page. It is exactly `git`'s own distinction between editing a build artifact and fixing the build.

Cost: a claim queue, a triage UI, and someone's attention. Roughly the same moderation load as model D plus a bug tracker — and **strictly less than model B**, because a claim is a bug report with a citation rather than a diff requiring legal review.

**The annotation layer (D) rides alongside, and it is where the community actually lives:** plain-language summaries, "what changed and why," links to news coverage and litigation, practice notes. Attributed, versioned, separately licensed (§10), and **visually unmistakable** — different background, persistent "Community annotation — not law" label, never inline with statutory text, never in the copy buffer when a user copies the statute.

### 7.4 The failure mode if the line blurs

Concretely, in order of how it actually plays out:

1. Someone hand-fixes a provision the pipeline got wrong. Reasonable, well-intentioned, correct on the merits.
2. The match rate rises. Nobody can now tell whether it rose because the patcher improved or because someone typed the answer in.
3. Divergence findings become unpublishable — "our replay disagrees with ILGA" no longer means anything, because the replay is partly hand-made.
4. Reproducibility dies. Same corpus + same pipeline no longer yields the same output, because the output depends on undocumented human interventions.
5. The project becomes a slower, less-funded Justia with a git metaphor in the marketing — and its one genuine advantage is gone.

**Step 1 is indistinguishable from good citizenship, and steps 2–5 follow without anyone deciding anything.** That is why this has to be an architectural constraint enforced by the schema (no write path to `text_blob` except the pipeline) rather than a policy in a CONTRIBUTING.md.

### 7.5 The ruling, costed

| Option | Build cost | Ongoing moderation | Risk |
|---|---|---|---|
| **A** read-only | +0 | ~0 | no community; all correction labour wasted |
| **B** PR-style on text | +3–4 wks | **high**, needs legal literacy, doesn't scale | oracle meaningless; liability |
| **C** full wiki | +4–6 wks | **extreme**, 24/7 | disqualifying |
| **D** annotation only | +2–3 wks | moderate, bounded | correction labour still wasted |
| **E** D + correction claims *(recommended)* | +4–5 wks | moderate + a bug queue | none structural; needs owner attention |

**Owner's ruling required on:**
1. Model A / B / C / D / E.
2. If D or E: are annotations open to anyone, or to approved contributors? (Recommend approved-contributor for the first year — reversible in the permissive direction, painful in the restrictive one.)
3. If E: who triages the claim queue, and what happens when nobody does for a month? (Recommend: claims stay visible and *publicly* unresolved. A visible backlog is honest — legislation.gov.uk proves it works.)

---

## 8. Tech stack

**Recommendation, with reasons rather than assertions:**

| Layer | Choice | Why |
|---|---|---|
| Ingest / patcher | **Python 3.12**, stdlib-first, `httpx` + `selectolax`/`lxml` | best HTML/PDF ecosystem; eyecite and ilcs-parser are Python; the owner's existing tooling culture is stdlib-first Python |
| Grammar | **PEG** (`parsimonious`) or hand-written recursive descent | amendatory instructions nest and coordinate; regexes will rot within a session |
| PDF | `pdfplumber` / `pypdfium2` — **only if HTML loses strike-through** (§2.5) | decide in Phase 0; HTML is far cheaper if it survives |
| Storage | **PostgreSQL 16** | `daterange` + GiST exclusion constraints are exactly the bitemporal primitive needed; nothing else gives that without hand-rolling |
| Object store | local disk or S3-compatible (R2/B2) | raw crawl captures, ~10–30 GB, write-once |
| API | **FastAPI** | typed, fast, OpenAPI for free |
| Web | **Server-rendered Jinja + htmx**, no SPA | pages are documents; a diff is a document; SSR is faster, more accessible, more citable, and permanently linkable. An SPA here buys nothing and costs SEO, accessibility, and the "view source" property that makes legal tools trustworthy. |
| Diff rendering | server-side word-level diff (`difflib`, custom tokenizer) | must handle legal text sensibly: whole-word, punctuation-aware, no character noise inside citations |
| Search | **Postgres FTS** first | the corpus is ~120 MB of text. Reaching for Elastic/Meili at this size is solving an imaginary problem. Revisit if and only if FTS measurably fails. |
| Deploy | one VM + Docker Compose, or Fly.io | see §9 |
| CI | GitHub Actions running **the oracle** on every PR | the match rate is a test; regressions block merges |

**Deliberate non-choices:** no Kubernetes, no message queue, no vector database, no microservices, no SPA framework, no ORM-heavy abstraction over the temporal queries (write the SQL — the temporal logic *is* the product, and hiding it behind an ORM is how it gets subtly wrong).

**One genuine open question:** whether to build on **LawVM's core** rather than a fresh Python pipeline (§3.7). Phase 0 task. If its operation model and replay engine are jurisdiction-agnostic and its Illinois-shaped gaps are only in the frontend, adopting it removes a large slice of §5.1 and §6 and buys a collaborator. **[UNVERIFIED — needs an hour with the repo before committing to the stack above.]**

---

## 9. Phased build plan

Every phase ends in a number or a URL. No phase ends in "the architecture is ready."

### Phase 0 — Feasibility and corpus (2–3 weeks)
- Resolve the **strike-through markup question** (§2.5). *This gates everything.*
- Evaluate **LawVM** as a dependency (§3.7).
- Email the **LRB/LIS** re: bulk access and terms (§2.8).
- Build the resumable, `Crawl-delay: 10`-respecting, content-addressed mirror; enumerate `DocName` keys from the chapter/act index.
- Crawl one chapter end-to-end plus its Public Acts.
- Confirm the earliest GA with full text (§2.9).

**Ends with:** a reproducible local mirror of one chapter + a manifest + a written go/no-go on the markup question.

### Phase 1 — **Oracle-0** (3–4 weeks) · *the most important phase in the plan*
- Extract ILCS sections + Source lines.
- Extract embedded sections from Public Acts, resolving strike/underscore.
- Normaliser v1 with the two-number report (§4.5).
- Single-hop compare across the whole crawled corpus; divergence classifier (§4.6).

**Ends with:** *a percentage.* Published, per-chapter, with the divergence taxonomy breakdown. This is the first demo and it is the moment the project becomes real — before there is a UI, before there is a parser worth the name.

### Phase 2 — Amendatory grammar and typed operations (4–6 weeks)
- PEG grammar over instruction sentences; typed ops; three-signal target resolution.
- Human-review queue for Tier 2/3; every resolution becomes a fixture.
- **Oracle-1**: chain replay from anchors (Wayback / Justia / reverse).

**Ends with:** the match rate for *multi-hop* reconstruction, and — replacing the guess in §2.5 — **the measured fraction of instructions needing human review.**

### Phase 3 — Version graph, point-in-time API, diff UI (4–6 weeks)
- Bitemporal schema loaded; `/us-il/act/5/70/4@2022-05-13` resolves.
- Diff view: any two versions of any provision, word-level, with the Public Act cited.
- The timeline view: the `(Source: …)` line rendered as an actual, clickable history.

**Ends with:** **the thing the owner wanted in college** — a URL where the amendment-history line is clickable and each Public Act shows its diff.

### Phase 4 — Conflicts, retroactivity, "not yet applied" (3–4 weeks)
- Contested-window detector (§5.2); cross-check against ILGA's own `(Text of Section …)` markers.
- Bitemporal query UI: the two-date control, defaulted and explained.
- **The legislation.gov.uk banner**, adapted: "N Public Acts affecting this section are not yet reflected."

**Ends with:** a public conflicts dashboard — every contested window in Illinois law, which as far as I can tell has never been published anywhere.

### Phase 5 — Annotations + judicial overlay (3–4 weeks, gated on §7 ruling)
- LRB Case Report ingest → badges.
- Annotation layer per the owner's ruling.
- The persistent "text ≠ law" affordance, designed properly rather than bolted on.

**Ends with:** a provision page that is honest about what it does not know.

### Phase 6 — Prove the seam (open-ended)
- Second jurisdiction. Recommend a *structurally different* one over an easy one — a state that uses genuine strike/insert instructions rather than whole-section restatement — because the seam is only proven by the case it wasn't designed for. Picking an easy second state proves nothing and feels like progress.

**Ends with:** two jurisdictions, one core, and a match rate for each.

---

## 10. Growing beyond Illinois

The seam, from day one, is a **jurisdiction adapter** — LawVM's "frontend" (§3.7), and the convergence on that shape is evidence it's right.

**Jurisdiction-specific (the adapter):** source discovery/URL shapes; document extraction; the amendatory instruction grammar; the citation format; effective-date defaults; the compilation's editorial conventions.

**Jurisdiction-neutral (the core):** the typed operation vocabulary; the bitemporal version graph; content-addressed text; the replay engine; the oracle harness and divergence taxonomy; diff rendering; the API and URI scheme; the whole web layer.

**Rules that keep the seam honest:**
1. **No `if jurisdiction == 'us-il'` in the core.** Ever. It's a one-line review rule and it holds the line better than any doc.
2. **The operation vocabulary is closed and jurisdiction-neutral.** If Illinois needs a new op, it is because the vocabulary was incomplete, not because Illinois is special.
3. **`jurisdiction` is a column on every table from the first migration.** Retrofitting it later is a full-corpus rewrite.
4. **The oracle is core.** Any jurisdiction that publishes a compilation gets a match rate on arrival, for free. That property is what makes a second jurisdiction weeks rather than months.
5. **Federal is easier, not harder** — GPO ships USLM XML (§3.5), so the extraction adapter is thin. Consider federal as jurisdiction two *if* the goal is reach; consider a strike/insert state *if* the goal is proving the seam. **These are different goals and the owner should pick one deliberately rather than drift.**

---

## 11. Hosting and cost

Corpus fits on one node (§6.4). **[All figures ESTIMATE, 2026-08-11 pricing.]**

| Item | Spec | Monthly |
|---|---|---|
| App + Postgres VM | 4 vCPU / 16 GB / 160 GB NVMe (Hetzner CPX41-class) | **$30–40** |
| Object storage (raw captures, ~30 GB) | Cloudflare R2 / B2, zero egress fees | **$1–3** |
| Backups (nightly `pg_dump` → object store) | | **$1–2** |
| Domain | | **~$1** |
| CDN / TLS | Cloudflare free tier | **$0** |
| CI | GitHub Actions free tier (public repo) | **$0** |
| **Total, steady state** | | **≈ $35–50/mo** |

**Notes:**
- The crawl is the only heavy compute and it is **rate-limited by politeness, not by hardware** — `Crawl-delay: 10` means a slow, cheap, long-running job. Nothing to scale.
- A full replay of the corpus is minutes-to-hours of single-node CPU. Run it nightly and on every PR.
- If Phase 2 uses an LLM for Tier-3 instruction triage only (**never for text**, §5.1), budget **$20–100/mo [ESTIMATE]** and note that the cost is one-time per instruction, since every resolution becomes a permanent fixture. The cost curve bends down over time, which is the whole point.
- **Managed Postgres (RDS/Neon) would roughly triple the bill for no benefit at this size.** Revisit if it ever becomes someone's job to run.

---

## 12. Licensing

**Code and data are licensed separately, deliberately.**

**Code — recommend split:**
- **Core library** (replay engine, temporal model, operation vocabulary, oracle harness): **Apache-2.0**. Permissive maximises adoption by other jurisdictions and by existing legal-data organisations, includes an explicit patent grant, and is the licence most compatible with the ecosystem this project wants to join (Open States, FLP, GPO tooling).
- **Web application** (the site itself): **AGPL-3.0**. If someone runs a modified version as a public service, the modifications come back. This matters specifically because the modification most worth policing is *changing how the reconstruction works while still calling it a reconstruction* — the AGPL makes that visible.

Argued against the obvious alternatives: **all-MIT** maximises reuse but permits a closed commercial fork of the *reconstruction pipeline* — the one asset whose trustworthiness depends on inspectability. **All-AGPL** would deter exactly the institutional adopters (universities, other states, legal-aid orgs) the project needs, and would make the core unusable inside otherwise-permissive stacks. The split gets both.

**Data — three tiers, three licences:**

| Tier | Licence | Reasoning |
|---|---|---|
| Raw Illinois statutory text and Public Acts | **public domain / no additional rights asserted** | It is government edicts. Asserting rights over it would be both wrong and hypocritical. **[Verify the Illinois-specific public-domain claim against a primary source before publishing — §2.8.]** |
| Derived version graph, diffs, oracle results | **CC0** | This is the project's real contribution and its usefulness scales with frictionless reuse. Attribution requirements on a citation graph create licence-compatibility problems for exactly the downstream users most worth having. Give it away. |
| Community annotations | **CC-BY-SA 4.0** | Human-authored commentary; attribution is owed to the author, and share-alike keeps the commons intact. **Requires contributor agreement at submission time — build the checkbox in Phase 5, not after.** |

Publish a **`DISCLAIMER.md`** and a **`LIMITATIONS.md`** at the repo root. The latter, modelled directly on <https://www.legislation.gov.uk/developer/limitations>, is a credibility asset and not a liability shield.

---

## 13. "Not legal advice" — posture

The failure mode to avoid is the one every legal site falls into: a modal nobody reads, a wall of disclaimer that makes the tool feel unusable, and the resulting quiet assumption by users that the disclaimer is boilerplate and the text is authoritative.

**Do:**
- One sentence, persistently visible on every provision page, that is **specific and informative rather than defensive**:
  > *"This is reconstructed statutory text, not legal advice. Courts, not text, decide what the law means."*
- Make the **provenance the disclaimer.** Every provision shows: which Public Acts produced it, which oracle class it fell into, the reconstruction date, and whether it byte-matches the published compilation. A user who can see *"reconstructed through P.A. 103-274; matches ILGA's published text"* — or *"does not match; see divergence #418"* — needs less warning than one who can't, and trusts the tool more.
- Never say **"current law."** Say "as compiled on <date>" or "as reconstructed through P.A. <n>."
- Link out to the official ILGA page for every provision, every time.

**Don't:**
- Modal interstitials, click-through acceptance, or an "I am not a lawyer" gate. They train users to dismiss warnings and they signal that the operator is protecting themselves rather than informing the reader.
- Hedge the *product*. The text either reconstructs or it doesn't, and the oracle says which. Confidence about what the system *does* is compatible with — and reinforces — humility about what the system *means*.

**The honest one-line framing, which should be near the top of the front page:**

> *"Illinois publishes what the law says and it publishes every act that changed it. It does not publish the connection between them. This system reconstructs that connection mechanically, checks its own work against the official text, and tells you the score."*

---

## 14. Open questions for the owner

1. **The name.** Out with the owner; every URI shape in §6.1 is name-independent, so this does not block Phase 0–2.
2. **The community-layer ruling** (§7). Blocks Phase 5 only. Recommend deciding after Phase 1, when the real error rate is known — the correct answer genuinely depends on that number.
3. **Build on LawVM, or build fresh?** (§3.7) Blocks the Phase 2 stack decision. One hour of investigation.
4. **Second jurisdiction: reach (federal, easy) or proof (a strike/insert state, hard)?** (§10) Not urgent, but drifting into the easy one by default would waste the seam.
5. **Public divergence findings — publish, or report privately to the LRB first?** My recommendation: **report privately, publish after a response window.** It costs little, it is the norm in security disclosure for good reasons, and a state legislative body that experiences this project as a collaborator rather than a critic is worth more than any single finding.

---

## 15. Sources

All fetched **2026-08-11**.

**Illinois primary**
- ILCS chapter index + disclaimer — <https://www.ilga.gov/Legislation/ILCS/Chapters>
- "Using the Illinois Compiled Statutes and Public Acts" — <https://www.ilga.gov/Legislation/ILCS/Guide>
- ILCS full text (app route) — <https://www.ilga.gov/Legislation/ILCS/fulltext?DocName=000500700K4>
- ILCS section (static document route) — <https://ilga.gov/documents/legislation/ilcs/documents/000500700K4.htm>
- Public Acts index — <https://www.ilga.gov/legislation/publicacts>
- P.A. 104-0001 — <https://www.ilga.gov/Legislation/PublicActs/View/104-0001>
- P.A. 103-0565 — <https://www.ilga.gov/Legislation/publicacts/view/103-0565>
- P.A. PDF route — <https://www.ilga.gov/Documents/Legislation/PublicActs/104/PDF/104-0001.pdf>
- Legacy bill text (92nd GA) — <https://www.ilga.gov/Documents/legislation/legisnet92/sbgroups/sb/920SB1855LV.html>
- Illinois Bill Drafting Manual — <https://www.ilga.gov/commission/lrb/Manual.pdf>
- Illinois Constitution art. IV — <https://www.ilga.gov/commission/lrb/con4.htm>
- Effective Date of Laws Act (5 ILCS 75) — <https://www.ilga.gov/Legislation/ILCS/Articles?ActID=80&ChapterID=0>
- Statute on Statutes (5 ILCS 70) — <https://www.ilga.gov/Legislation/ILCS/Articles?ActID=79&ChapterID=2>
- 5 ILCS 70/4 — <https://ilga.gov/documents/legislation/ilcs/documents/000500700K4.htm>
- LRB Case Report 2025 (statutes held unconstitutional) — <https://lrb.ilga.gov/Commission/lrb/2025_Case_Report.pdf>
- Researching legislative history — <https://www.ilga.gov/commission/lrb/lrbres.htm>
- robots.txt — <https://www.ilga.gov/robots.txt>
- sitemap.xml — <https://ilga.gov/sitemap.xml>

**Prior art**
- legislation.gov.uk — <https://www.legislation.gov.uk/>
- legislation.gov.uk limitations — <https://www.legislation.gov.uk/developer/limitations>
- legislation.gov.uk help (applied vs unapplied changes) — <https://www.legislation.gov.uk/help>
- Changes To Legislation — <https://www.legislation.gov.uk/changes>
- LawVM — <https://lawvm.org/>
- LawVM, "Why Law Is Law-Shaped" — <https://lawvm.org/why-law-is-law-shaped/>
- Akoma Ntoso v1.0 (OASIS) — <https://www.oasis-open.org/standard/akn-v1-0/>
- USLM schema — <https://github.com/usgpo/uslm>
- govinfo bulk data / USLM readme — <https://www.govinfo.gov/bulkdata/PLAW/resources/readme.html>
- "The Legislative Recipe: Syntax for Machine-Readable Legislation" — <https://arxiv.org/pdf/2108.08678>
- Open States docs — <https://docs.openstates.org/>
- Open States / Plural bulk data — <https://open.pluralpolicy.com/data/>
- Cornell LII Illinois — <https://www.law.cornell.edu/states/illinois>
- Free Law Project — <https://free.law/>
- eyecite — <https://github.com/freelawproject/eyecite>
- FLP citator progress (2025-05-01) — <https://free.law/2025/05/01/citator/>
- datamade/ilcs-parser — <https://github.com/datamade/ilcs-parser>
- mattstoller/bill-diff-tool — <https://github.com/mattstoller/bill-diff-tool>
- LegiScan Illinois datasets — <https://legiscan.com/IL/datasets>
- Justia Illinois Compiled Statutes (annual snapshots) — <https://law.justia.com/codes/illinois/> · <https://law.justia.com/codes/illinois/2019/>
- "Some Pointers: Building Point-in-Time Versions of Statutes" (Great Library) — <https://greatlibrary.blog/2021/10/07/some-pointers-building-point-in-time-versions-of-statutes/>
- DocuToads (minimum-edit-distance amendment tracking) — <https://arxiv.org/pdf/1608.06459>

---

## Appendix A — Claims I could not verify

| Claim | Why it matters | How to resolve |
|---|---|---|
| Exact markup carrying strike-through/underscore in Public Act HTML | **Gates the entire extraction approach** — HTML vs PDF pipeline | fetch raw HTML of a PA and read the tags directly (Phase 0, first task) |
| Verbatim text of 5 ILCS 70/6 | normative input to the conflict design | fetch `DocName=000500700K6` from the static document route |
| Earliest GA with full machine-readable text | sets the hard floor on historical reach | probe `legisnet88/`, `89/`, `90/` paths |
| ILCS is public domain for federal copyright purposes | licensing tier 1 | primary source; *Georgia v. Public.Resource.Org*; ask the LRB |
| ilga.gov terms of use / bulk-copy policy | legal posture of the mirror | ask the LRB/LIS directly |
| Illinois section count (~30,000) and corpus sizes | hosting estimates | count during Phase 0 crawl |
| Fraction of instructions needing human review (1–5%) | Phase 2 scoping | **measured in Phase 2 — do not plan around the guess** |
| Wayback capture density for ilga.gov ILCS URLs | anchor strategy for Oracle-1 | CDX API query |
| Whether Open States carries IL Public Act numbers and vote margins | avoids rebuilding bill metadata | inspect the bulk data |
| Whether LawVM's core is genuinely jurisdiction-agnostic | could remove a third of the build | one hour with the repo |
