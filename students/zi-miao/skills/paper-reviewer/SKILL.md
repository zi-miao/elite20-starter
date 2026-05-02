---
name: paper-reviewer
version: "0.1.0"
description: >
  Generate publication-grade peer reviews of academic papers (PDF) via a
  multi-stage neuro-symbolic pipeline: PDF→Markdown ingestion, five orthogonal
  analyses (story, presentation, evaluations, correctness, significance) with
  accumulated context, synthesis, self-critique, revision, and final quality
  check. Each analytical stage runs with dual grounding (original PDF for
  visual context + Markdown for symbolic structure) and stage-appropriate tool
  augmentation (code interpreter for evaluations/correctness, web search for
  significance). Preserves the closed-loop pattern
  `decompose → analyze → synthesize → self-verify → revise` that distinguishes
  self-improving inference from one-shot generation.

  Use this skill whenever the user asks to: review a paper, write a peer review,
  critique a manuscript, generate an AI review, evaluate a submission for a
  conference/journal, check a paper's correctness or significance, assess a
  thesis or preprint, or any variant of "review this PDF" where the input is an
  academic paper. Triggers on: "review this paper", "peer review", "critique
  this manuscript", "evaluate this submission", "AI review", "check this paper",
  "assess this preprint", "review my thesis", "这篇论文评审", "帮我审稿",
  "写个同行评审", or upload of a paper PDF with review intent — even if the user
  does not explicitly say "review". Also use for iterative revision of an
  existing draft review, or for auditing a review for unsupported claims.
---

# paper-reviewer

Multi-stage academic paper reviewer implementing a closed-loop
decomposition-and-error-correction pipeline. Designed as a neuro-symbolic
agent workflow with dual-representation input (PDF + Markdown), stage-wise
tool augmentation, and monadic context accumulation across stages.

## When to use

Trigger on any request where the input is an academic paper PDF and the
deliverable is a substantive review — regardless of venue (conference,
journal, thesis committee, arXiv preprint). Also use for:

- Auditing an existing draft review for unsupported claims or citation errors
- Revising a draft review based on a critique
- Running just a subset of stages (e.g., only correctness check)

## Pipeline

```
┌────────────────────────────────────────────────────────────────┐
│                        PAPER PDF (input)                       │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stage 0: PDF → Markdown                                        │
│   markitdown | pandoc | source-text-to-markdown | olmOCR       │
│   Produces: normalized .md + resampled .pdf (250dpi)           │
└───────────────────┬────────────────────────────────────────────┘
                    │   context = {pdf, markdown, history:[]}
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stages 1–5 (sequential, context accumulates)                   │
│                                                                │
│  1. story         — problem formulation & narrative validity    │
│  2. presentation  — clarity, structure, readability            │
│  3. evaluations   — datasets, baselines, metrics, stats        │
│       + tool: python code interpreter                          │
│  4. correctness   — equations, proofs, algorithms, tables      │
│       + tool: python code interpreter                          │
│  5. significance  — novelty, prior-work comparison             │
│       + tool: web search                                       │
│                                                                │
│  Prompt at each stage = base + stage + ALL prior outputs       │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stage 6: Synthesize initial review                             │
│   → Title, Summary, Overall, Strengths, Weaknesses, Refs (APA) │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stage 7: Self-critique                                         │
│   Detect: unsupported claims, missing evidence,                │
│   inconsistencies, hallucinated/incorrect citations            │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stage 8: Revise → final review                                 │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────────────────┐
│ Stage 9: Critic quality check                                  │
│   Bias, identity leakage, structure, hallucinated citations    │
│   → optional human inspection gate                             │
└───────────────────┬────────────────────────────────────────────┘
                    │
                    ▼
              Final Review (.md + .docx)
```

## How to run

### Quick path (one command)

```bash
python scripts/run_review.py \
  --pdf path/to/paper.pdf \
  --out /mnt/user-data/outputs/ \
  --converter markitdown   # or: pandoc | source-text-to-markdown | olmocr
```

This orchestrates all stages and saves:
- `review_final.md` — the polished review
- `review_final.docx` — Word version (via docx skill if requested)
- `trace/` — per-stage outputs for audit
- `context.json` — accumulated history

### Stage-by-stage (when Claude runs the LLM stages directly)

The LLM-reasoning stages (1–8) are executed by **Claude itself**, not by a
subprocess. The orchestrator script prepares inputs, loads the right prompt
from `references/`, and writes the output back. A typical run looks like:

1. **Stage 0** — run `scripts/pdf_to_markdown.py` (deterministic, runs via
   `bash_tool`).
2. **Stages 1–5** — for each stage: read `references/stage_prompts.md` for
   that stage, read accumulated `context.history`, perform the reasoning,
   append the result to `context.history`. For stages with tool augmentation,
   actually invoke the tool:
   - `evaluations` / `correctness` → use `bash_tool` to run Python
     (verify reported numbers, re-derive equations, sanity-check tables).
   - `significance` → use `web_search` to check claimed novelty against
     prior work.
3. **Stage 6** — read `references/synthesis_prompt.md`, synthesize initial
   review using the full history.
4. **Stage 7** — read `references/critique_prompt.md`, self-critique the
   initial review against the paper.
5. **Stage 8** — read `references/revision_prompt.md`, produce the final
   review.
6. **Stage 9** — read `references/critic_check_prompt.md`, run quality
   check; if issues flagged, surface them to the user for human inspection.

Skipping stages is fine for partial reviews (e.g., `--stages correctness` for
a correctness-only audit). Always run Stage 9.

## Key design patterns (preserved from source paper)

- **Monadic context accumulation.** Every stage sees all prior stage outputs,
  so later reasoning is conditioned on earlier findings. Do not drop history
  between stages.
- **Dual representation.** PDF gives visual grounding (figures, layout,
  tables as rendered); Markdown gives symbolic structure (tokens, headings,
  equations as LaTeX). Both are passed at every stage.
- **Stage-wise tool augmentation.** Don't give all tools to all stages —
  that dilutes reasoning. Tools attach where they sharpen a specific check
  (numbers in `evaluations`, math in `correctness`, claims in `significance`).
- **Decompose-then-synthesize.** Never generate the review in one shot.
  Always run the five orthogonal analyses first, then synthesize.
- **Self-verify before finalizing.** The self-critique step is not optional —
  it is where most citation and support errors are caught.
- **Retry with exponential backoff.** All LLM/tool calls use the retry
  helper in `scripts/llm_client.py`.

## Stage 0 converter options

| Converter | When to use | Notes |
|---|---|---|
| `markitdown` | Fast, well-structured PDFs, no math | Microsoft's tool; `pip install markitdown` |
| `pandoc` | Generic fallback | Robust, widely available |
| `source-text-to-markdown` | Already in skill ecosystem | Wraps pandoc + metadata extraction + YAML front matter; preferred when available |
| `olmocr` | Scanned PDFs, heavy math, complex layout | Original paper's choice; slowest but highest fidelity |

Auto-selection: the runner picks `source-text-to-markdown` if installed,
falls back to `markitdown` if available, then `pandoc`, then errors out
with instructions.

## Output contract

Final review follows `templates/review_template.md`:

```
# <Paper Title>
## Summary
## Overall Assessment
## Strengths
## Weaknesses
## Detailed Comments
  ### Story / Framing
  ### Presentation
  ### Evaluations
  ### Correctness
  ### Significance
## References (APA)
## Metadata
  - model: <llm-name>
  - converter: <stage0-tool>
  - stages_run: [...]
  - critic_flags: [...]
```

## KSTAR mapping

This pipeline is a direct KSTAR instance. See `references/kstar_mapping.md`
for the full morphism; the short version:

| Pipeline element | KSTAR component |
|---|---|
| Paper PDF + Markdown | Situation `S` |
| "Write a review" | Task `T` |
| Stage instructions + prior reviews | Knowledge `K` |
| Stage outputs | Action-plan decomposition `Â` |
| Initial review | Expected result `R̂` |
| Self-critique | ΔR / ΔE detection |
| Revision | Learning/update loop |
| Final review | Actual result `R` |
| Critic check | Validation oracle |

The full morphism: `F(K, S, T) → Â → R̂ → Critique → ΔR → Update → R`.

## Reference files

- `references/stage_prompts.md` — stage-specific instructions (Table 3 from source paper)
- `references/synthesis_prompt.md` — how to compose the initial review
- `references/critique_prompt.md` — self-critique checklist
- `references/revision_prompt.md` — revision instructions
- `references/critic_check_prompt.md` — post-hoc quality gate
- `references/kstar_mapping.md` — full KSTAR/Functorism morphism
- `templates/review_template.md` — output format

## Scripts

- `scripts/run_review.py` — top-level orchestrator (CLI entry point)
- `scripts/pdf_to_markdown.py` — Stage 0 converter dispatcher
- `scripts/stage_runner.py` — per-stage context+prompt preparation
- `scripts/llm_client.py` — LLM wrapper with retry/backoff

## Notes

- The paper PDF should be resampled to ~250 DPI before stage 1 if using a
  vision-capable model; `pdf_to_markdown.py` does this automatically.
- For very long papers (>30 pages), `stage_runner.py` will chunk the
  Markdown into logical sections (by heading) and run a map-reduce pass per
  stage. The chunker preserves equation, table, and figure integrity.
- If the critic detects ≥2 flags in Stage 9, the runner surfaces the review
  for human inspection rather than auto-finalizing. This is the
  human-in-the-loop gate.
