# Oracle-0 baseline: the first measured match rate

**Date:** 2026-08-12 · **Pipeline:** `oracle0/0.1.0` · **Normaliser:** `0.1.0`
**Status:** first run. This number is a baseline to be beaten, not a claim.

---

## The number

> ## 88.3 %
> **83 of 94** attempted ILCS sections match the text of the Public Act their own
> `(Source: …)` line says last set them.
>
> Against a **fixed** denominator of all 112 sections sampled — the figure that cannot be improved by
> seeing less — it is **74.1 %**. Both are reported throughout; see
> [the denominator note](#the-denominator-and-the-way-this-number-could-be-gamed).
>
> **Exact-byte match rate: 0.0 % (0 of 94).** Not a typo. See [§4](#4-the-two-numbers).

112 sections were drawn from 7 ILCS Acts across 6 chapters, and 86 distinct Public Acts were fetched
to check them. 18 sections are excluded from the denominator because their source Act is **not
published on ilga.gov at all** — we cannot see the answer, so we do not score it (spec §4.7).

This measures exactly the two things spec §4.2 says it measures: **extraction fidelity** (did we read
the strike-through and underscore correctly) and **editorial drift** (where does the compilation
legitimately differ from the enrolled Act). It is *not* a history reconstruction and does not
attempt one.

### Was the number earned, or copied?

A match rate over reprinted text is worthless if the reprints were clean copies. They were not:

| | n | matched |
|---|---:|---:|
| Sections whose reprint **actually carried strike/underscore markup** | 87 of 94 | **81 (93.1 %)** |
| Sections the source Act *added* (`… new`, so nothing to strike) | 15 | 13 |

93 % of the attempted sample required the amendatory markup to be resolved correctly for the match to
happen at all. Verified by extracting each Act twice — once applying the amendment, once reversing it
— and confirming the two readings differ.

---

## 1. Reproducing this exactly

Everything below is derived from a run of code in this repository. No figure was typed by hand.

```bash
git checkout feat/oracle-0
PYTHONPATH=src python -m palimpsest.oracle0 --out out        # first run crawls (~30 min)
PYTHONPATH=src python -m palimpsest.oracle0 --out out --offline   # re-runs cost zero fetches
PYTHONPATH=src python scripts/report_tables.py out/results.json   # every table below
```

**The sample is declared in code**, in `SAMPLE_ACTS` and `QUOTAS` in
[`src/palimpsest/oracle0.py`](../src/palimpsest/oracle0.py), so it is reproducible from the source
alone with no seed to record:

- **7 ILCS Acts across 6 chapters**, chosen for subject-matter spread and a mix of section lengths:
  5 ILCS 70 (Statute on Statutes — short, definitional), 5 ILCS 140 (FOIA), 10 ILCS 5 (Election
  Code — 1,009 sections, some of the longest in Illinois law), 35 ILCS 200 (Property Tax Code),
  625 ILCS 5 (Vehicle Code), 720 ILCS 5 (Criminal Code of 2012), 820 ILCS 305 (Workers'
  Compensation Act).
- **Per Act, three strata**, each sampled by `take_evenly` — evenly spaced across the whole Act
  rather than clustered at the front, where sections are short and definitional:
  - `recent` — last set by the **103rd GA or later** (2023+): quota 10
  - `modern` — last set by the **90th–102nd GA**: quota 10
  - `pre_corpus` — last set **before the 90th GA**: quota 2, drawn deliberately to *measure* the
    corpus floor rather than assume it
- Sections are selected **before** any Public Act is fetched, because an Act's Articles page carries
  every section's `(Source: …)` line, so stratifying by "when was this last amended" is free.

Some strata are smaller than their quota (5 ILCS 70 has no section last set by the 103rd GA), which
is why the sample is 112 rather than 154.

**Crawl cost:** 129 documents, ~119 MB, one fetch every 10 seconds. The cache is gitignored and is
not in this repository — see [§8](#8-what-is-deliberately-not-here).

---

## 2. Results

### Headline

| | |
|---|---|
| Sections sampled | 112 |
| Excluded: Source names no Public Act | 0 |
| Excluded: source Act not published online | 18 |
| **Attempted (the denominator)** | **94** |
| **Match rate, normalised** | **88.3 %** (83/94) |
| Match rate, exact bytes | 0.0 % (0/94) |

### The denominator, and the way this number could be gamed

[D-0003](decisions.md) adopts LawVM's **witness-anchored monotone denominator**, on the grounds that
a denominator which shrinks when extraction narrows is *"the cheapest way to lie to yourself about a
match rate."* The headline above is **not** monotone-anchored: it drops the 18 sections whose source
Act is unavailable, so anything that made *more* Acts unresolvable would push the percentage **up**.

So all three denominators, with the gameable one named as such:

| Denominator | Rate | Gameable by narrowing? |
|---|---:|---|
| Fixed — every section sampled (112) | **74.1 %** (83/112) | **No.** Cannot rise by seeing less. |
| Attempted — excludes unreachable Acts (94) | **88.3 %** (83/94) | **Yes.** The headline. |
| Reachable — also excludes repeals/renumbering (86) | 96.5 % (83/86) | Yes, more so. |

**74.1 % is the honest regression metric**, and it is the one to track over time. 88.3 % is quoted as
the headline because it answers the question Oracle-0 was built to ask — *when we can see both texts,
do they agree* — but it should never be reported without the 112-section figure beside it. Wiring the
monotone denominator into the harness properly is follow-up work, not something this report claims to
have done.

### Every sampled section, classified

| Class | n | % of attempted | Meaning |
|---|---:|---:|---|
| `MATCH` | 83 | 88.3 % | The compiled section and the Act's reprint agree. |
| `ACT_NOT_ONLINE` | 18 | *excluded* | The source Public Act is not published on ilga.gov. |
| `REPEALED_STUB` | 7 | 7.4 % | The compiled section is a repeal tombstone; a repealing Act reprints no text. |
| `NORMALIZE` | 2 | 2.1 % | Differs only in punctuation/whitespace. Counted as a **failure**, not an excuse. |
| `DIVERGENCE` | 1 | 1.1 % | Candidate finding: single Act, single version, and the words differ. |
| `RENUMBERED` | 1 | 1.1 % | The section was renumbered away; the Act prints it under a new citation. |

Note what is **absent**: zero `TARGET_RESOLUTION` failures, zero `MULTI_ACT`, zero `MULTI_VERSION`.
The first was 14 before a parser fix ([§6.1](#61-the-new-suffix-14-failures-that-were-mine)).

The other two absences need care, because "zero" here means *"never the cause of a mismatch"*, not
*"not present in the sample"*. Both were present and both matched — see
[§6.5](#65-the-two-categories-that-were-expected-to-fail-and-did-not).

### By ILCS Act

| ILCS Act | attempted | matched | rate | excluded |
|---|---:|---:|---:|---:|
| Statute on Statutes | 2 | 1 | 50.0 % | 2 |
| Freedom of Information Act | 2 | 2 | 100.0 % | 1 |
| Election Code | 20 | 18 | 90.0 % | 2 |
| Property Tax Code | 19 | 16 | 84.2 % | 3 |
| Illinois Vehicle Code | 18 | 16 | 88.9 % | 4 |
| Criminal Code of 2012 | 20 | 17 | 85.0 % | 2 |
| Workers' Compensation Act | 13 | 13 | 100.0 % | 4 |

The Statute on Statutes row is 1 of 2 — a 50 % that is one section, and it is the `DIVERGENCE` in
[§5](#5-a-case-where-the-enrolled-act-is-wrong-and-the-compilation-is-right). Two-section
denominators should not be read as rates.

### By stratum

| Stratum | attempted | matched | rate | excluded |
|---|---:|---:|---:|---:|
| `recent` (103rd GA+) | 45 | 40 | 88.9 % | 0 |
| `modern` (90th–102nd) | 49 | 43 | 87.8 % | 5 |
| `pre_corpus` (<90th) | 0 | 0 | n/a | 13 |

**Recently-amended sections do not fare worse.** That matters: it is the case where ilga.gov's
"forward-leaning working tree" behaviour (spec §2.2) would be most likely to bite, and it did not.

---

## 3. The corpus floor, measured

The spec (§2.9, Appendix A) records as **UNVERIFIED** that machine-readable text begins "around the
90th General Assembly (1997–98)", inferred from `legisnet90/` paths, and asks for it to be probed.

**Measured: for Public Act documents the floor is the 93rd General Assembly (2003–04).**

| GA | 76 | 77 | 78 | 79 | 82 | 83 | 85 | 86 | 88 | 90 | 91 | 92 | **93** | 94 | 95 | 96 | 97 | 98 | 99 | 100 | 101 | 102 | 103 | 104 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| online | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **2** | 2 | 5 | 8 | 11 | 4 | 2 | 3 | 5 | 7 | 29 | 16 |
| not online | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 3 | 2 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

The boundary is clean and was confirmed by direct probe outside the sample: `090-0001`, `091-0001`,
`091-0500`, `092-0001` are all unavailable; `093-0001` onward all return the Act.

**This is six years later than the spec's estimate, and it matters.** The `legisnet90/` paths the
spec found are *bill* documents, not Public Acts. Oracle-1 (chain replay) can only start where Act
text exists, so the reconstructable window is 2003→, not 1997→. **19 % of this sample (18 of 112) is
out of reach for that reason alone**, and those sections are not unusual — they are ordinary
provisions that simply have not been amended in twenty years.

> **Correction (2026-08-12): 19 % is a property of this sample, not of the corpus. The population
> figure is 39 %.**
>
> The bulk crawl enumerated every section in these same seven Acts — 4,600 of them, against the 112
> sampled here — and counted how many name a source Public Act at or above the floor. The answer:
> **2,540 checkable (55.2 %), 1,798 below the floor (39.1 %), 262 naming no Public Act (5.7 %)**.
>
> The gap is not an error in either number; it is what stratification does. `QUOTAS` draws ten
> `recent` and ten `modern` sections per Act but only two `pre_corpus`, precisely so that the strata
> are all *represented*. That makes the sample excellent for asking "does the pipeline work on each
> kind of section" and invalid for asking "how much of the corpus is each kind" — and the 19 % was
> quietly being read as the second. **A sample designed for coverage of the strata does not estimate
> their sizes.**
>
> Nothing above changes: the match rate, the taxonomy and the floor measurement are all unaffected,
> because they are all conditioned on the sample. What changes is the project's expectation of
> reach. Two out of five sections in these Acts can never be single-hop checked against their own
> source Act, and that is a corpus-coverage ceiling rather than something better engineering can
> lift. Oracle-1 (chain replay) inherits it.

### The trap in how that is discovered

An unavailable Act does **not** return HTTP 404. It returns **HTTP 200** with a 128-byte body:

```
Document: 96-0542 is not currently available.
```

A crawler that trusts the status code records a successful fetch of an Act containing zero sections,
and then reports "the Act does not contain this section" — filing a corpus-coverage limit as a
parser failure. The two are kept apart deliberately (`fetch.is_soft_404`).

### A second trap: the URL is not the citation

The Source line prints `P.A. 97-81`. The URL needs **`097-0081`** — *both* halves zero-padded, the GA
to three digits. `PrinterFriendly/97-0081` returns the "not currently available" placeholder;
`PrinterFriendly/097-0081` returns the Act. Getting this wrong makes **every Public Act before the
100th General Assembly look withdrawn from the site**. It cost 6 spurious exclusions before it was
caught, and it would have silently truncated the measured corpus floor to the 100th GA.

---

## 4. The two numbers

Spec §4.5 requires `exact_bytes` and `normalized` side by side, and warns that a wide gap means the
normaliser is doing too much work and hiding findings. The gap here is as wide as it can be — 0.0 %
against 88.3 % — so it needs answering rather than presenting.

**The entire gap is one transformation: treating a line break as a space.** The two sources are
fixed-width printer layouts that wrap at *different widths* — the compiled ILCS page at roughly 70
columns, the printer-friendly Act at roughly 60 — so the same sentence carries newlines in different
places in every single section. No section in Illinois law could match byte-for-byte between these
two routes, and a 0 % exact rate is the expected reading, not a signal.

The ablation below is the evidence, not the assertion.

### Normalisation ablation

Rules applied cumulatively. `marginal` is how many matches that one rule bought.

| Rules enabled | matched | rate | marginal |
|---|---:|---:|---:|
| none (raw extracted text) | 0/89 | 0.0 % | — |
| + `N1` Unicode NFC | 0/89 | 0.0 % | +0 |
| + `N2` straight quotes, drop soft hyphens/BOM | 0/89 | 0.0 % | +0 |
| + `N3` collapse all whitespace to single spaces | **83/89** | **93.3 %** | **+83** |
| + `N4` remove whitespace before closing punctuation | 83/89 | 93.3 % | +0 |
| + `N5` remove whitespace after opening bracket | 83/89 | 93.3 % | +0 |
| + `N6` single space after sentence punctuation | 83/89 | 93.3 % | +0 |

(89 is the number of cases that reached a text comparison; the other 5 never produced two texts to
compare. The denominator differs from the headline's 94 for that reason.)

**Every match in this report rests on exactly one rule, and it is the least contestable one.** N1,
N2 and N4–N6 contribute nothing. They are retained precisely because a documented `+0` is the proof;
if a later change makes any of them start earning matches, that is a signal to investigate rather
than a free improvement.

### How N4 stopped being worth +18

In the first version of this pipeline, **N4 alone bought 18 of 83 matches (+20 percentage points)** —
more than a fifth of the headline number resting on a blanket "strip whitespace before punctuation"
rule applied to both texts.

That is exactly the shape of the self-deception this project is built to avoid. An enrolled Act
brackets a deletion around a *phrase*, and the space joining that phrase to its neighbours goes with
it, so applying:

```
the effective date <u>of … 103rd</u> <strike>of … 102nd</strike>, the provisions
```

leaves `…103rd , the provisions` against the compilation's `…103rd, the provisions`. A global rule
fixes it — and would equally fix any two texts that merely happened to be punctuated differently.

So the repair was **moved out of the normaliser and into the extractor**, applied only at the site
where text was actually removed, on one side only (`extract._close_deletions`). **The match rate did
not change: 83/94 before, 83/94 after.** N4's marginal went from +18 to +0.

That is the useful result. It demonstrates the 18 matches were genuinely about deletions rather than
about loose punctuation matching — and the number now no longer depends on a rule that *could* have
been manufacturing agreement, whether or not it was.

### The rules, in full

Every rule the normaliser applies, with the risk each one carries. All six are listed; none is
omitted.

| Rule | What it does | Why it is a rendering difference, not a real one | Risk |
|---|---|---|---|
| `N1` | Unicode NFC | The two routes were generated by different toolchains and can encode the same accented character as a precomposed codepoint or as base + combining mark. NFC makes those one string. | None material. NFC is a canonical, information-preserving mapping; it cannot merge two characters that a reader would distinguish. |
| `N2` | Straight quotes, drop soft hyphens and BOM | Curly quotes are typesetting. The compiled page and the printer view of an Act do not agree about them, and no statutory meaning turns on the direction of an apostrophe. Soft hyphens are line-break hints. | Low, but not zero: this is the one rule that touches characters inside the operative text. It maps quote glyphs onto each other and deletes only characters that have no printed width. |
| `N3` | Collapse all whitespace to single spaces | The single most necessary rule. Both sources are fixed-width printer layouts that hard-wrap, at roughly 70 and roughly 60 columns, so the *same* sentence carries newlines in different places. Paragraph indents are four non-breaking spaces in one layout and literal tabs in the other. | **Real**: it erases paragraph structure, so a genuine difference consisting only of where a paragraph broke would be invisible. Accepted, because neither source's line breaks carry meaning — they are artifacts of column width, and the two column widths differ. |
| `N4` | Remove whitespace before closing punctuation | Was the artifact of applying a deletion; that repair now happens in the extractor at the deletion site instead. | Moderate — it is applied to both sides and so *could* manufacture agreement. Now measured at +0. |
| `N5` | Remove whitespace after opening bracket | The mirror of N4. | Same as N4, and measured at +0. |
| `N6` | Single space after sentence-ending punctuation | Redundant once N3 is on; kept so the ablation can show it. | None. Measured at +0. |

**What is deliberately never normalised**, each guarded by a test that fails if it breaks
(`tests/test_normalize.py::TestWhatTheNormaliserMustNotDo`): words (`shall` ≠ `must`), singular vs
plural, case (`Act` ≠ `act`), cross-references (`Section 5-1` ≠ `Section 5.1`), numbers and dates,
and meaningful punctuation.

---

## 5. A case where the enrolled Act is wrong, and the compilation is right

One `DIVERGENCE` survived. It is real, it is verified against the raw HTML, and it is small.

**5 ILCS 70/1.25** — Statute on Statutes, source `P.A. 97-81, eff. 7-5-11`:

```diff
--- 5 ILCS 70/1.25 (ILCS compilation)
+++ 5 ILCS 70/1.25 (as printed in its source Public Act)
@@ -1,2 +1,2 @@
-Sec. 1.25. Unless an Act otherwise specifically provides, any writing of any kind or description
+Sec. 1.25. Unless An Act otherwise specifically provides, any writing of any kind or description
 required or authorized to be filed with, and any payment of any kind or description required or
```

Confirmed in the raw markup of `PrinterFriendly/097-0081`:

```html
<code>Sec. 1.25. </code><code>Unless An Act otherwise specifically provides, </code>
```

**The enrolled Public Act contains a capitalisation error** — "Unless **An** Act" — almost certainly
an artifact of the drafting system, which capitalises `AN ACT` in the enacting title. The LRB
corrected it to "Unless an Act" in the compilation and left no trace of having done so.

**This is a finding about the compilation being *right*, not wrong**, and it is worth reporting for
three reasons. It is a real, silent, unannotated editorial intervention in text that is otherwise
presented as a faithful reproduction of the Act — precisely the class of change spec §4.6 calls
`EDITORIAL` and says should be encoded as a declared rule with a citation. It confirms the oracle
detects single-character differences across a 2,400-character section without drowning in noise. And
it is the honest shape of the yield: LawVM's one confirmed finding across four jurisdictions (spec
§3.7) sets the expectation, and a typo fix is what a 94-section sample buys.

**No case was found where the compilation looks wrong.** Not one. On a sample this size that is a
weak result rather than a reassuring one, and it should not be quoted as evidence that the ILCS is
error-free.

---

## 6. Every mismatch, categorised

The four categories the brief asks for, plus two structural ones the data forced.

| Category | n | Share of attempted |
|---|---:|---:|
| Normalisation artefact | 2 | 2.1 % |
| Target-resolution failure | **0** | 0.0 % |
| Section touched by multiple Acts | **0** | 0.0 % |
| Genuine divergence | 1 | 1.1 % |
| *Structural: repeal tombstone* | 7 | 7.4 % |
| *Structural: renumbering* | 1 | 1.1 % |

"Section touched by multiple Acts = 0" is a statement about *causes of mismatch*. 27 of the 94
attempted sections do have multi-Act source lines; none of them mismatched on their text
([§6.5](#65-the-two-categories-that-were-expected-to-fail-and-did-not)).

### 6.1 The ` new` suffix: 14 failures that were mine

The first complete run scored **74.5 %**, with 14 target-resolution failures. All 14 were one bug.

A Public Act that *adds* a section writes the header with a trailing marker:

```
(820 ILCS 305/1.1 new)
(35 ILCS 200/1-21 new)
```

The citation parser was taking `1.1 new` as the section number, so it never compared equal to the
compiled `820 ILCS 305/1.1`, and every section added by its own source Act looked like a
target-resolution failure while the Act plainly contained it. A census across the cached corpus found
**382 ` new` headers and 261 ` rep.` headers**. Handling both took the rate from **74.5 % → 87.2 %**
and target-resolution failures from 14 to 0.

The lesson is not the bug. It is that **a target-resolution failure is the most flattering possible
label for a parser bug** — it sounds like a hard research problem and reads as a limit of the domain.
It was 15 % of the sample, and it was a suffix.

### 6.2 The one `DIVERGENCE` that wasn't

Before a second fix, the run reported a `DIVERGENCE` on **35 ILCS 200/10-700**, with the Act
containing an extra `Section 99. Effective date. This Act takes effect upon becoming law.`

A section an Act *adds* has **no `(Source: …)` trailer** — there is no prior provenance to print — so
the block had no terminator and ran on into the Act's own closing division. The compilation was
correct and the parser was wrong.

Blocks are now bounded at the Act's next internal division. Illinois drafting makes this safe: an
Act's own divisions are `Section N.` while a codified section's catchline is `Sec. N.`

**This is the argument for the high bar on findings, made concretely.** The single candidate finding
in the first run was the pipeline's own bug, and it was *plausible* — an off-by-one at a section
boundary is exactly what a real divergence would look like. Publishing it would have been a false
accusation against the LRB.

### 6.3 Normalisation artefacts (2)

Both are a space before a closing double quote.

- **720 ILCS 5/11-14.4** — compilation `"person engaged in the sex trade"`, Act
  `"person engaged in the sex trade "`.
- **10 ILCS 5/16-6** — the ASCII ballot-form box: rules of 62 vs 61 hyphens, plus
  `"CONSTITUTION AMENDMENT"` vs `"CONSTITUTION AMENDMENT "`.

Both are counted as **failures**. Adding `"` to rule N4 would convert the first to a match — one line,
+1.1 points — and **it is deliberately not done**: N4 strips whitespace *before* a character, so
adding `"` would turn every opening quote `said "hello` into `said"hello` and corrupt the text
everywhere to buy one match here. This is the kind of change that makes a match rate go up while
making it mean less.

### 6.4 Structural limits of the single hop (8)

Not failures of the pipeline; cases the single-hop oracle cannot address by construction.

**Repeal tombstones (7)** split into two shapes:

- **Repealed by a later Act (4)** — e.g. `35 ILCS 200/9-60`, `(Source: P.A. 88-455. Repealed by P.A.
  95-925, eff. 1-1-09.)`. The Act names it as `(35 ILCS 200/9-60 rep.)` and reprints no text, exactly
  as spec §2.5 describes.
- **Self-repealing sections (3)** — `10 ILCS 5/1-25`, `35 ILCS 200/18-184.21`, `625 ILCS 5/3-685`.
  These are more interesting. The Act prints the section in full, and its final subsection says *"This
  Section is repealed on July 1, 2026."* The compilation already shows `Sec. 1-25. (Repealed).` —
  **for a repeal date that has not yet arrived.** This is spec §2.2's "forward-leaning drafting
  working tree" caught in the act, and it is a concrete argument for bitemporality (§5.3): the text in
  force today is not the text ilga.gov is showing.

**Renumbering (1)** — `720 ILCS 5/12-31`, `(Source: P.A. 88-392. Renumbered by P.A. 96-1551, eff.
7-1-11.)`. P.A. 96-1551 reorganised the Criminal Code wholesale; the text now lives at
`720 ILCS 5/12-34.5` under a `(was 720 ILCS 5/12-31)` marker. Illinois publishes the renumbering
mapping in the Act, so this is tractable in Oracle-1 — but not in a single hop keyed on citation.

Excluding all 8 as out of scope for a single-hop oracle gives **83/86 = 96.5 %**. The headline stays
**88.3 %**, the conservative figure, because "the oracle cannot address this" is not the same as
"the oracle succeeded".

### 6.5 The two categories that were expected to fail, and did not

Spec §2.5 names multi-version sections as *"the main source of genuine review load"*, and §5.2
predicts that two Acts amending the same section can silently revert one another. Both were present
in this sample. Neither produced a single textual mismatch.

**Sections whose Source line names more than one Public Act — 27 of 94:**

| | matched | rate |
|---|---:|---:|
| Multi-Act source line (27) | 22 | 81.5 % |
| Single-Act source line (67) | 61 | 91.0 % |

The 81.5 % looks like the predicted effect, and it is not. **All 5 multi-Act non-matches are
`REPEALED_STUB` or `RENUMBERED`** — structural cases, which are over-represented among multi-Act
sections for the obvious reason that a section repealed or renumbered after a long life has a long
Source line. Removing the structural cases from both groups:

| | matched | rate |
|---|---:|---:|
| Multi-Act, structural cases excluded (22) | 22 | **100 %** |
| Single-Act, structural cases excluded (64) | 61 | 95.3 % |

**Every multi-Act section in this sample matched its terminal Act's reprint exactly.** On n=22 that
is weak evidence, but it points the opposite way to the worry: for these sections the LRB's merge
and the terminal Act's reprint agreed completely.

**Sections carrying ILGA's own version markers — 3:**

| Section | Compiled version marker | Result |
|---|---|---|
| `625 ILCS 5/11-1414.1` | `(Text of Section from P.A. 104-367)` | MATCH |
| `820 ILCS 305/4` | `(Text of Section from P.A. 101-40, 102-37, and 103-590)` | MATCH |
| `820 ILCS 305/4` | `(Text of Section from P.A. 101-384, 102-37, and 103-590)` | MATCH |

`820 ILCS 305/4` is the interesting one: the compilation publishes **two** simultaneous versions of
the same section, and so does P.A. 103-0590. The two had to be paired correctly, and the markers do
**not** match textually — the compiled marker lists `103-590` (the Act now in the lineage) while the
Act's own marker does not yet. Pairing therefore fell back to closest normalised text, and picked
both correctly.

That is a real multi-version resolution, and it is also *three sections*. It demonstrates the
mechanism works; it does not measure how often it works.

---

## 7. What this sample did not exercise

Stated plainly, because the absent categories are the ones a reader would most want.

- **Only 3 multi-version sections.** All matched (§6.5), which is a real result — but 3 is far too
  few to measure the category spec §2.5 calls *"the main source of genuine review load"*. The
  mechanism is demonstrated; its error rate is not. **This is the single largest gap**, and it is
  cheap to close: select the next sample on sections that carry a version marker rather than on
  recency.
- **Multi-Act evidence points the other way, weakly.** 22 of 22 non-structural multi-Act sections
  matched. That is encouraging and it is n=22.
- **No pre-93rd-GA sections could be attempted at all** — 18 of 112, entirely excluded.
- **One jurisdiction's worth of one format.** Every result here depends on Illinois reprinting whole
  sections. Nothing generalises to a strike/insert state (decision D-0002).
- **94 sections is small.** 88.3 % on n=94 has a 95 % Wilson interval of **80.2 %–93.3 %**. Treat
  the point estimate accordingly.

Closing the multi-version gap is the highest-value next measurement.

---

## 8. What is deliberately not here

The 119 MB crawl cache is **gitignored and not committed**, and CI has a job that fails the build if
it ever is. This repository distributes code, not a mirror of the state's statutes. The terms-of-use
question in spec §2.8 is **open** — that email to the LRB is a Phase 0 task and it is the owner's to
send — and committing a mirror would answer it by accident.

Every fetch obeyed `Crawl-delay: 10`, sent an identifying User-Agent with a contact URL, and touched
only routes robots.txt permits. `/search` and `/api` are refused **in code**, at URL construction,
with tests. Enumeration goes through the chapter/act index instead, which is why
`sample.py` exists at all.

---

## 9. What this does to the spec's 1–5 % guess

Spec §2.5 estimates **1–5 % of instructions will need human review**, flags it `[ESTIMATE]` with low
confidence, and says: *"It is a guess about a measurable quantity, which is exactly the kind of guess
this project exists to destroy."*

**It does not survive contact, but it fails in an interesting direction: it is roughly right about
the wrong thing.**

### What the guess got right

The guess was about *residual hard cases* — irregular instructions needing a human to interpret them.
On that reading, this sample produces a number in the band:

| Needs a human to look at it | n | % of attempted |
|---|---:|---:|
| Genuine divergence requiring judgement | 1 | 1.1 % |
| Normalisation artefacts needing a decision | 2 | 2.1 % |
| **Total** | **3** | **3.2 %** |

**3.2 %, inside the 1–5 % band.** If the plan needs a review-load number for the text layer, that is
the honest one from this measurement — and it is genuinely *review* load, since each of the three is
a judgement call rather than a bug with an obvious fix.

### What the guess got wrong, and it is the load-bearing part

The guess located the difficulty in the wrong place. Ranked by how much human attention each category
actually consumed:

| Where the effort went | Sample impact | Fixed by |
|---|---|---|
| **Corpus coverage** — Acts not online at all | **16.1 %** (18/112) | Nothing. Permanent. |
| **Structural limits** — repeals, renumbering | **8.5 %** (8/94) | Oracle-1 and a repeal/renumber model, not review |
| **Parser bugs wearing a research-problem costume** | **14.9 %** at first (14/94) | A one-line suffix fix |
| **Genuine interpretive review** | **3.2 %** (3/94) | A human, once each |

The dominant cost is not review. It is **that 16 % of Illinois statutory sections cannot be checked at
all**, because the Public Act that last set them predates 2003. That number is not in the spec, is
not reducible by better engineering, and is four times larger than the review load the plan was
scoped around.

### The three corrections to make to the plan

1. **The corpus floor is the 93rd GA (2003), not the 90th (1997).** Six years of Acts the spec
   assumed were available are not. Oracle-1's anchor problem (§4.3) is correspondingly harder, and
   the Wayback/Justia anchor strategies become more important, not less.
2. **Budget for structural cases before review cases.** Repeals and renumbering were 8.5 % here
   against 3.2 % needing judgement. Both are mechanical, both need modelling in Phase 2, and neither
   is a human-review problem.
3. **Do not plan around 3.2 % either.** It rests on 94 sections containing just **3 multi-version
   sections** — and spec §2.5 names multi-version sections as *"the main source of genuine review
   load"*. All 3 matched, which is a point in the plan's favour, but 3 cases cannot establish the
   rate for the category the guess said would dominate. Until that measurement exists, the
   review-load figure has been *displaced*, not *established*.

**The measurement to run next is not a bigger sample. It is a sample selected on version markers.**

---

## 10. Bottom line

- **88.3 %** (83/94) single-hop match rate, first run, on a 112-section sample across 6 ILCS
  chapters — or **74.1 %** (83/112) against the fixed denominator that cannot be gamed by narrowing.
- **93.1 %** of matches required amendatory markup to be resolved correctly, not copied.
- Spec §2.5's Phase 0 gating question is **answered**: Public Act HTML carries `<strike>` and `<u>` as
  real tags. **No PDF pipeline is needed.** That was the largest schedule risk in Phase 0 and it is
  retired.
- The spec's corpus floor is **wrong by six years**; 16 % of sections are permanently unverifiable.
- The 1–5 % review guess measures at **3.2 %**, but the sample that produced it contained only 3 of
  the multi-version sections the spec expected to dominate that load.
- **1 confirmed divergence**, in which the compilation is correct and the enrolled Act has a typo.
- **0 cases where the compilation looks wrong.**

The number to beat is 88.3 %. The honest way to raise it is Oracle-1 and a version-marker sample —
not another normalisation rule.
