#!/usr/bin/env python3
"""
paper-reviewer: top-level orchestrator.

Pipeline (Appendix A of source paper):
    0. PDF → Markdown
    1. story         → narrative validity
    2. presentation  → clarity & structure
    3. evaluations   → datasets, baselines, metrics      (+python)
    4. correctness   → equations, proofs                 (+python)
    5. significance  → novelty, prior-work comparison    (+web)
    6. synthesize    → initial review
    7. self-critique → detect unsupported claims
    8. revise        → final review
    9. critic check  → bias, leakage, hallucinated refs

In `claude-self` mode (the default inside Claude sessions), stages 1–9 are
executed by Claude itself: this script prepares prompts on disk, and Claude
reads them, reasons, and writes outputs. In `anthropic` / `openai` modes the
script calls the API directly.

Usage (inside Claude / claude.ai):
    python scripts/run_review.py --pdf paper.pdf --out /mnt/user-data/outputs
    # then follow the prompts in work_dir/prompts/ in order

Usage (with API backend):
    python scripts/run_review.py --pdf paper.pdf --out ./out --mode anthropic
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as script
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pdf_to_markdown import convert as stage0_convert  # noqa: E402
from stage_runner import (  # noqa: E402
    ReviewContext, STAGES, run_analytical_stage,
    run_synthesis_stage, commit_stage,
)


SKILL_ROOT = _HERE.parent  # parent of scripts/


def _print_next_action(stage: str, work_dir: Path) -> None:
    """Human-readable hint for Claude (in claude-self mode)."""
    prompt_path = work_dir / "prompts" / f"{stage}.prompt.txt"
    output_path = work_dir / "trace" / f"{stage}.output.md"
    print(f"""
[next-action] stage={stage}
  1. Read the prompt at:    {prompt_path}
  2. Reason through it (with tool use if tools are declared in the manifest).
  3. Write your output to:  {output_path}
  4. Then run:              python run_review.py --resume --out {work_dir}
""")


def run_pipeline(
    pdf: Path,
    out_dir: Path,
    converter: str | None,
    stages_to_run: list[str] | None,
    mode: str,
    model: str | None,
    resume: bool,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / (pdf.stem + "_review_work")
    work_dir.mkdir(exist_ok=True)

    # --- Stage 0: PDF → Markdown --------------------------------------------
    ctx_path = work_dir / "context.json"
    if resume and ctx_path.exists():
        state = json.loads(ctx_path.read_text(encoding="utf-8"))
        ctx = ReviewContext(
            pdf_path=Path(state["pdf_path"]),
            markdown_path=Path(state["markdown_path"]),
            work_dir=work_dir,
            history=state["history"],
        )
        print(f"[resume] loaded {len(ctx.history)} prior stage(s)")
    else:
        md_path, pdf_resampled = stage0_convert(pdf, work_dir, force=converter)
        ctx = ReviewContext(
            pdf_path=pdf_resampled,
            markdown_path=md_path,
            work_dir=work_dir,
        )
        ctx.persist()
        print(f"[stage0] markdown ready at {md_path}")

    # --- Determine remaining stages ----------------------------------------
    stages = stages_to_run or STAGES
    done = {h["stage"] for h in ctx.history}
    pending = [s for s in stages if s not in done]

    # --- Analytical stages 1–5 ----------------------------------------------
    for stage in pending:
        if stage not in STAGES:
            continue
        print(f"\n[stage:{stage}] preparing prompt...")
        run_analytical_stage(stage, ctx, SKILL_ROOT, mode=mode)

        if mode == "claude-self":
            # In this mode the orchestrator yields control back to Claude.
            _print_next_action(stage, work_dir)
            return

        # In API mode we would wait for the response and commit here.
        # (Left as an exercise — current default is claude-self.)
        commit_stage(ctx, stage)

    # --- Stage 6: synthesize -------------------------------------------------
    if "synthesize" not in done:
        print("\n[stage:synthesize] preparing prompt...")
        run_synthesis_stage(
            "synthesize", "synthesis_prompt.md", ctx, SKILL_ROOT, mode=mode,
        )
        if mode == "claude-self":
            _print_next_action("synthesize", work_dir)
            return
        commit_stage(ctx, "synthesize")

    initial_review = next(
        (h["output"] for h in ctx.history if h["stage"] == "synthesize"), None
    )

    # --- Stage 7: self-critique ---------------------------------------------
    if "critique" not in done and initial_review:
        print("\n[stage:critique] preparing prompt...")
        run_synthesis_stage(
            "critique", "critique_prompt.md", ctx, SKILL_ROOT,
            extra={"Initial review to critique": initial_review},
            mode=mode,
        )
        if mode == "claude-self":
            _print_next_action("critique", work_dir)
            return
        commit_stage(ctx, "critique")

    critique = next(
        (h["output"] for h in ctx.history if h["stage"] == "critique"), None
    )

    # --- Stage 8: revise -----------------------------------------------------
    if "revise" not in done and initial_review and critique:
        print("\n[stage:revise] preparing prompt...")
        run_synthesis_stage(
            "revise", "revision_prompt.md", ctx, SKILL_ROOT,
            extra={
                "Initial review": initial_review,
                "Critique to address": critique,
            },
            mode=mode,
        )
        if mode == "claude-self":
            _print_next_action("revise", work_dir)
            return
        commit_stage(ctx, "revise")

    final_review = next(
        (h["output"] for h in ctx.history if h["stage"] == "revise"), None
    )

    # --- Stage 9: critic check ----------------------------------------------
    if "critic_check" not in done and final_review:
        print("\n[stage:critic_check] preparing prompt...")
        run_synthesis_stage(
            "critic_check", "critic_check_prompt.md", ctx, SKILL_ROOT,
            extra={"Final review to audit": final_review},
            mode=mode,
        )
        if mode == "claude-self":
            _print_next_action("critic_check", work_dir)
            return
        commit_stage(ctx, "critic_check")

    # --- Write final artifact ------------------------------------------------
    if final_review:
        final_path = out_dir / (pdf.stem + ".review.md")
        final_path.write_text(final_review, encoding="utf-8")
        print(f"\n[done] final review: {final_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="paper-reviewer orchestrator")
    ap.add_argument("--pdf", type=Path, help="Input paper PDF (omit with --resume)")
    ap.add_argument("--out", type=Path, required=True, help="Output directory")
    ap.add_argument("--converter", default=None,
                    help="Stage 0 converter: markitdown|pandoc|source-text-to-markdown|olmocr")
    ap.add_argument("--stages", default=None,
                    help="Comma-separated subset of analytical stages to run")
    ap.add_argument("--mode", default="claude-self",
                    choices=["claude-self", "anthropic", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--resume", action="store_true",
                    help="Continue from an existing context.json")
    args = ap.parse_args()

    if not args.resume and args.pdf is None:
        ap.error("--pdf is required unless --resume is given")
    if args.resume and args.pdf is None:
        # find the single working dir under --out
        candidates = [p for p in args.out.iterdir() if p.is_dir() and p.name.endswith("_review_work")]
        if len(candidates) != 1:
            ap.error("Cannot auto-resume: multiple or zero work dirs under --out")
        # derive original pdf stem from dir name
        args.pdf = Path(candidates[0].name.replace("_review_work", ".pdf"))

    stages_to_run = args.stages.split(",") if args.stages else None
    run_pipeline(
        pdf=args.pdf,
        out_dir=args.out,
        converter=args.converter,
        stages_to_run=stages_to_run,
        mode=args.mode,
        model=args.model,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
