# Critic Check

You are auditing the **final** review for release-blocking issues. This is
the last gate before the review leaves the pipeline. You are not rewriting —
you are producing a pass/fail report.

The final review is provided below. Apply the checks below in order. If any
check returns a flag of severity `blocker`, the review cannot be released
without human review.

## Checks

### 1. Bias and offensive content — **blocker**
- Any language targeting the authors' identity (nationality, gender,
  institution, race, etc.)?
- Any language that is dismissive rather than critical?
- Any culturally or linguistically biased judgments (e.g., penalizing
  non-native-English phrasing as a content flaw)?

Flag any match. A single match is a blocker.

### 2. Identity leakage — **blocker**
- Does the review name the authors (it shouldn't, review is blind)?
- Does the review speculate about author identity or affiliation?
- Does the review name the reviewer (it shouldn't)?
- Does the review reference "I" or "my" in a way that identifies the
  reviewer beyond normal reviewer voice?

### 3. Hallucinated citations — **blocker**
For each citation in the review's References section:
- Does a Google Scholar / arXiv / DBLP lookup confirm it exists?
- If you cannot verify, flag as `suspect-citation` with severity `major`.

For each inline citation:
- Does it appear in the References list?
- Does the cited work actually support the claim attached?

### 4. Structural completeness — **major**
- Title, Summary, Overall Assessment, Strengths, Weaknesses, Detailed
  Comments, References all present?
- Overall Assessment contains a calibrated verdict?
- Revision Notes section present and ready to be stripped (if this is the
  revised review)?

### 5. Tone — **minor**
- Any sarcasm, rhetorical questions implying the authors are stupid,
  unnecessarily strong language ("obviously wrong", "fundamentally
  misguided")?
- Any claims about author intent ("the authors clearly didn't read X")?

### 6. Coverage sanity — **major**
- Does the review mention all five analytical dimensions (story,
  presentation, evaluations, correctness, significance)?
- If any dimension is absent from the review, is there a defensible reason?

### 7. Length sanity — **minor**
- Reviews under 300 words are usually insufficient for a full-length paper.
- Reviews over 3000 words may be verbose — flag for trimming.

## Output format

```json
{
  "status": "pass" | "needs_human_review" | "block",
  "flags": [
    {
      "check": "<which check>",
      "severity": "blocker" | "major" | "minor",
      "location": "<which part of the review>",
      "detail": "<concise description>"
    }
  ],
  "recommendation": "release" | "escalate" | "revise",
  "notes": "<free-form notes for the human reviewer>"
}
```

## Decision rule

- Any `blocker` → `status: "block"`, `recommendation: "escalate"`.
- Two or more `major` → `status: "needs_human_review"`,
  `recommendation: "escalate"`.
- One `major` or only `minor` → `status: "pass"`,
  `recommendation: "release"` (unless notes say otherwise).
- Zero flags → `status: "pass"`, `recommendation: "release"`.

Produce the JSON now.
