# Self-Critique

You have produced an initial review of the paper. Your task now is to
**critique your own review**, as a senior reviewer would before forwarding it
to the area chair. You are not rewriting — you are generating a checklist of
issues the reviewer (your earlier self) must fix.

The paper is still available to you in PDF + Markdown form. The initial
review is provided below.

## Checklist (apply rigorously)

Go through the review claim-by-claim and flag:

### 1. Unsupported claims
Every evaluative statement in the review should be traceable to specific
evidence in the paper. Flag any claim that:
- Asserts something about the paper without a citation.
- Cites a section/page but the cited location does not actually say what
  the review claims it says. (Check this literally — open the Markdown and
  the PDF at the cited location.)

### 2. Missing evidence
Are there claims in the paper that the review *should* have addressed but
missed? Specifically:
- Major claims in the abstract that are not evaluated in the review.
- Key equations, theorems, or headline results not mentioned.
- Experimental results that contradict the review's assessment.

### 3. Inconsistencies with the paper
Does the review ever contradict the paper? E.g.:
- Review says "no ablation study" but the paper has §4.3 "Ablation".
- Review says "only one dataset" but Table 2 lists three.
Flag every such case with a specific pointer.

### 4. Hallucinated or incorrect citations
For each reference in the review's References section and each inline
citation:
- Does the cited work exist? (Author, title, year, venue all consistent?)
- Is the citation used correctly? (Does it actually support the claim
  attached to it?)
- Are there citations in the review that do not appear in the paper's
  bibliography, and if so, are they actually relevant?

### 5. Internal inconsistencies within the review
- Does the Overall Assessment match the balance of Strengths vs Weaknesses?
  (A "strong accept" verdict with 8 weaknesses and 2 strengths is a red flag.)
- Do the Detailed Comments contradict the Summary?
- Are the Questions for the Authors actually answerable, and would the
  answers actually change the verdict?

### 6. Tone and professionalism
- Any language that could be read as dismissive, sarcastic, or personal?
- Any confident claims about the paper's intent rather than its content?
- Any suggestions that cross into authorial preference rather than
  technical critique?

### 7. Structural completeness
- Are all required sections present (per `synthesis_prompt.md`)?
- Are strengths and weaknesses each at least 3 items (unless genuinely
  unwarranted)?
- Is the recommendation verdict included and calibrated?

## Output format

Return a structured list. For each issue:

```
[SEVERITY] <blocker | major | minor>
[CATEGORY] <unsupported | missing | inconsistent | hallucinated | internal | tone | structural>
[LOCATION] <which part of the review>
[ISSUE] <concise description>
[FIX] <what the revision should do>
```

Do not rewrite the review yourself — that is Stage 8. Produce the critique
now.

If the review is actually solid, say so, but list at minimum three candidate
improvements (no review is perfect).
