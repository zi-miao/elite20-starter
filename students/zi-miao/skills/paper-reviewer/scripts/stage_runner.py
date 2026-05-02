#!/usr/bin/env python3
"""
Per-stage context and prompt preparation.

The canonical pattern (monadic accumulation) from Appendix A:

    prompt_at_stage_n = base_instruction
                      + stage_n_instruction
                      + ALL prior stage outputs (context.history)

Each stage reads its stage-specific instruction from `references/stage_prompts.md`.
This script is the bookkeeper — it does NOT generate text itself. The LLM
step is handled by `llm_client.call_llm` (which in `claude-self` mode just
stages prompts on disk for Claude to process).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Local imports  (run as module or script)
try:
    from .llm_client import LLMRequest, call_llm, load_stage_output
except ImportError:
    from llm_client import LLMRequest, call_llm, load_stage_output  # type: ignore


STAGES: list[str] = [
    "story",
    "presentation",
    "evaluations",
    "correctness",
    "significance",
]

TOOLS_BY_STAGE: dict[str, list[str]] = {
    "story": [],
    "presentation": [],
    "evaluations": ["python_code_interpreter"],
    "correctness": ["python_code_interpreter"],
    "significance": ["web_search"],
}


# --------------------------------------------------------------------------- #
# Context object (the monad)
# --------------------------------------------------------------------------- #
@dataclass
class ReviewContext:
    pdf_path: Path
    markdown_path: Path
    work_dir: Path
    history: list[dict[str, Any]] = field(default_factory=list)

    def append(self, stage: str, output: str) -> None:
        self.history.append({"stage": stage, "output": output})

    def persist(self) -> None:
        dump = {
            "pdf_path": str(self.pdf_path),
            "markdown_path": str(self.markdown_path),
            "work_dir": str(self.work_dir),
            "history": self.history,
        }
        (self.work_dir / "context.json").write_text(
            json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# --------------------------------------------------------------------------- #
# Prompt assembly
# --------------------------------------------------------------------------- #
def _read_reference(skill_root: Path, filename: str) -> str:
    path = skill_root / "references" / filename
    if not path.exists():
        raise FileNotFoundError(f"Reference file missing: {path}")
    return path.read_text(encoding="utf-8")


def _extract_stage_instruction(stage_prompts_md: str, stage: str) -> str:
    """
    Parse references/stage_prompts.md and extract the section for `stage`.

    Sections are delimited by `## stage: <name>` headers.
    """
    marker = f"## stage: {stage}"
    low = stage_prompts_md.lower()
    start = low.find(marker)
    if start < 0:
        raise ValueError(f"Stage '{stage}' section not found in stage_prompts.md")
    # find next section header
    nxt = low.find("\n## stage:", start + 1)
    section = stage_prompts_md[start:nxt] if nxt > 0 else stage_prompts_md[start:]
    # drop the header line itself
    lines = section.splitlines()
    return "\n".join(lines[1:]).strip()


def build_stage_prompt(
    stage: str,
    ctx: ReviewContext,
    skill_root: Path,
) -> str:
    stage_prompts = _read_reference(skill_root, "stage_prompts.md")
    base = _extract_stage_instruction(stage_prompts, "__base__")
    stage_specific = _extract_stage_instruction(stage_prompts, stage)

    parts: list[str] = [base, "", stage_specific, ""]

    if ctx.history:
        parts.append("## Prior stage outputs (accumulated context)")
        for entry in ctx.history:
            parts.append(f"\n### {entry['stage']}\n{entry['output']}")
        parts.append("")

    parts.append(
        "## Your task now\n"
        f"Execute stage `{stage}` as specified above, using the prior outputs "
        "as context. Be concrete, cite specific page numbers / equation "
        "numbers / table references from the paper."
    )
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Stage execution (analytical stages 1–5)
# --------------------------------------------------------------------------- #
def run_analytical_stage(
    stage: str,
    ctx: ReviewContext,
    skill_root: Path,
    mode: str = "claude-self",
) -> str:
    prompt = build_stage_prompt(stage, ctx, skill_root)
    req = LLMRequest(
        prompt=prompt,
        pdf_path=ctx.pdf_path,
        markdown_path=ctx.markdown_path,
        tools=TOOLS_BY_STAGE[stage],
        stage_name=stage,
        reasoning="high",
    )
    call_llm(req, mode=mode, work_dir=ctx.work_dir)

    # In claude-self mode, Claude writes the output to trace/<stage>.output.md
    # and the orchestrator calls ctx.append after verifying it exists.
    # The call above only prepares the prompt.
    return str(ctx.work_dir / "trace" / f"{stage}.output.md")


# --------------------------------------------------------------------------- #
# Synthesis stages (6: synthesize, 7: critique, 8: revise)
# --------------------------------------------------------------------------- #
def run_synthesis_stage(
    stage_label: str,
    reference_file: str,
    ctx: ReviewContext,
    skill_root: Path,
    extra: dict[str, str] | None = None,
    mode: str = "claude-self",
) -> str:
    base_prompt = _read_reference(skill_root, reference_file)
    parts = [base_prompt, ""]

    # Include the full accumulated history
    if ctx.history:
        parts.append("## Accumulated stage outputs")
        for entry in ctx.history:
            parts.append(f"\n### {entry['stage']}\n{entry['output']}")

    # Stage-specific extra content (e.g., initial_review for the critique stage)
    if extra:
        for label, text in extra.items():
            parts.append(f"\n## {label}\n{text}")

    prompt = "\n".join(parts)
    req = LLMRequest(
        prompt=prompt,
        pdf_path=ctx.pdf_path,
        markdown_path=ctx.markdown_path,
        stage_name=stage_label,
        reasoning="high",
    )
    call_llm(req, mode=mode, work_dir=ctx.work_dir)
    return str(ctx.work_dir / "trace" / f"{stage_label}.output.md")


# --------------------------------------------------------------------------- #
# Convenience for Claude-in-the-loop: mark a stage complete after the agent
# has written the output file.
# --------------------------------------------------------------------------- #
def commit_stage(ctx: ReviewContext, stage: str) -> str:
    output = load_stage_output(ctx.work_dir, stage)
    ctx.append(stage, output)
    ctx.persist()
    return output
