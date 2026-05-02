# KSTAR Mapping

This document makes explicit how the paper-reviewer pipeline is a KSTAR
instance, and what each pipeline element corresponds to in the
Knowledge–Situation–Task–Action–Result morphism.

## Analogy: a PhD student writing a conference review

Before formalism, the analogy. Imagine giving a PDF to a disciplined PhD
student and asking for a review. A *bad* student writes the whole review in
one pass — skimming the paper, generating plausible-sounding feedback,
submitting. A *disciplined* student:

1. Reads the paper carefully (Stage 0: ingest into working memory).
2. Makes five passes through separate lenses — story, writing, experiments,
   math, novelty (Stages 1–5: orthogonal analyses).
3. Synthesizes notes into a draft review (Stage 6).
4. **Sleeps on it**, then reads the draft against the paper checking for
   errors, unsupported claims, hallucinated references (Stage 7: critique).
5. Revises (Stage 8).
6. Has an advisor skim for bias and blockers before submitting (Stage 9).

KSTAR formalizes this loop. The "sleeping on it" step — the critique — is
the ΔE (epistemic deviation) signal. It is what distinguishes
self-improving inference from one-shot generation.

## Morphism

```
  F : (K, S, T) → Â → R̂ → Δ → Update → R

  where:
      K  = stage instructions + accumulated prior stage outputs
      S  = paper (PDF + Markdown)  — the situation
      T  = "produce a peer review"  — the task
      Â  = five-stage decomposition (story, presentation, evaluations,
                                     correctness, significance)
      R̂  = initial synthesized review (expected result)
      Δ  = ΔR (outcome deviation) and ΔE (epistemic deviation),
           detected by the self-critique stage
      Update = revision applied using Δ
      R   = final reviewed, quality-gated output
```

## Per-stage KSTAR view

| Pipeline stage | K | S | T | Â | R̂ | R |
|---|---|---|---|---|---|---|
| 0 | — | PDF | ingest to MD | MD produced | MD text | MD committed |
| 1 story | base instruction | PDF+MD | analyze narrative | questions about claim structure | narrative audit | audit committed |
| 2 presentation | base + story | PDF+MD | analyze clarity | questions about writing | presentation audit | audit committed |
| 3 evaluations | base + 1,2 | PDF+MD + Python | verify experiments | numerical checks | experimental audit | audit committed |
| 4 correctness | base + 1,2,3 | PDF+MD + Python | verify math/algos | re-derivations | correctness audit | audit committed |
| 5 significance | base + 1..4 | PDF+MD + web | compare prior work | searches | significance audit | audit committed |
| 6 synthesize | base + 1..5 | — | compose review | template filling | initial review | draft review |
| 7 critique | base + 1..5 + R̂ | PDF+MD | audit R̂ | checklist walk | Δ (issue list) | critique committed |
| 8 revise | base + 1..5 + R̂ + Δ | PDF+MD | apply Δ | edits | final review | final review |
| 9 critic check | base + R | — | release gate | checklist | pass/block/escalate | decision |

## Why the accumulated context (monadic) matters

Without accumulation, each stage is a fresh draw from the LLM and the
five analyses drift apart — they may contradict each other, miss obvious
connections, or cover the same ground. Accumulation enforces *coherence*:
the correctness stage knows what the story stage found and can connect a
suspicious equation to a broader claim of contribution.

In functor-theoretic terms: the stage outputs are morphisms composed
left-to-right; the monad (accumulated history) is the comonadic environment
that makes each later morphism aware of earlier ones. This is why the
prompt pattern is:

    prompt_n = base ∘ stage_n ∘ (⨁_{i<n} stage_i.output)

and not simply

    prompt_n = base ∘ stage_n

## Why ΔE, not just ΔR

Ground-truth is not available at review time — we don't know whether the
review is *correct*. What we can compute is ΔE: the gap between the
review's internal consistency and the paper's actual content. The critique
stage computes exactly this. It is this epistemic-deviation-only learning
signal that lets the pipeline self-improve without an external oracle.

See also: `kstar-delta` skill (`/mnt/skills/user/kstar-delta`) for the
general theory; this pipeline is a concrete instance.

## Skill composition

This skill composes naturally with:

- **`source-text-to-markdown`** — Stage 0 implementation.
- **`kstar-episode-compiler`** — compile a completed review run into a
  reusable episode trace for memory.
- **`bibitem-retriever`** — verify citations in the critic check stage.
- **`paper-refinement`** — if the output is to be integrated back into an
  evolving review draft across multiple sessions.
- **`docx`** — produce a Word version of the final review.

## KSTAR DB insertion

After a successful run, the pipeline can emit a KSTAR record:

```json
{
  "K": {
    "skill_id": "paper-reviewer@0.1.0",
    "stage_instructions_ref": "references/stage_prompts.md@<hash>"
  },
  "S": {
    "paper_title": "<title>",
    "paper_hash": "<sha256 of PDF>",
    "venue_context": "<if known>"
  },
  "T": "produce peer review",
  "A_hat": ["story", "presentation", "evaluations", "correctness", "significance", "synthesize", "critique", "revise"],
  "R_hat": "<sha256 of initial review>",
  "delta": {
    "critique_flags": [...],
    "critic_check_flags": [...]
  },
  "R": "<sha256 of final review>",
  "R_observed": "<if post-submission acceptance data becomes available>"
}
```

The final field `R_observed` closes the outer learning loop: once the
actual venue decision is known, ΔR can be computed and fed back into K.
