#!/usr/bin/env python3
"""
LLM client wrapper with exponential backoff retry.

This is the *transport* layer. The skill is backend-agnostic: you can plug in
Anthropic, OpenAI, a local model, or (most commonly when this skill is used
inside a Claude session) a no-op passthrough where Claude itself does the
reasoning and just reads the prepared prompt from disk.

Three modes are supported:

    mode="claude-self"   # Default. Writes the prompt to `prompt_path` and
                         # expects Claude (the agent running the skill) to
                         # read it, reason, and write the output to
                         # `output_path`. This is the canonical mode inside
                         # Claude Code / claude.ai sessions.

    mode="anthropic"     # Use the `anthropic` SDK. Requires ANTHROPIC_API_KEY.

    mode="openai"        # Use the `openai` SDK. Requires OPENAI_API_KEY.

The retry helper wraps any callable and applies exponential backoff on
failure (network, rate-limit, transient 5xx).
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


# --------------------------------------------------------------------------- #
# Retry primitive (from Appendix A.5 of source paper)
# --------------------------------------------------------------------------- #
def retry_with_backoff(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    **kwargs: Any,
) -> Any:
    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt == max_attempts - 1:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            if jitter:
                delay *= 0.5 + random.random()
            print(f"[llm] attempt {attempt + 1} failed: {e}; sleep {delay:.1f}s")
            time.sleep(delay)
    raise RuntimeError(f"LLM failed after {max_attempts} retries") from last_err


# --------------------------------------------------------------------------- #
# Request/response dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class LLMRequest:
    prompt: str
    system: str | None = None
    pdf_path: Path | None = None
    markdown_path: Path | None = None
    history: list[dict[str, Any]] | None = None
    tools: list[str] | None = None
    reasoning: str = "high"
    stage_name: str | None = None


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict[str, Any]] | None = None
    raw: Any = None


# --------------------------------------------------------------------------- #
# Mode: claude-self  (canonical for in-Claude skill execution)
# --------------------------------------------------------------------------- #
def call_claude_self(req: LLMRequest, work_dir: Path) -> LLMResponse:
    """
    Prepare the prompt package on disk so Claude (running this skill) can
    read it, reason, and write back the output.

    Writes:
        work_dir/prompts/<stage>.prompt.txt     (the full prompt)
        work_dir/prompts/<stage>.manifest.json  (paths, tools, metadata)

    Returns a placeholder response; the actual content is produced by Claude
    and later loaded by stage_runner via `load_stage_output`.
    """
    stage = req.stage_name or "unnamed"
    prompts_dir = work_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = prompts_dir / f"{stage}.prompt.txt"
    manifest_path = prompts_dir / f"{stage}.manifest.json"

    prompt_path.write_text(req.prompt, encoding="utf-8")
    manifest = {
        "stage": stage,
        "system": req.system,
        "pdf": str(req.pdf_path) if req.pdf_path else None,
        "markdown": str(req.markdown_path) if req.markdown_path else None,
        "tools": req.tools or [],
        "reasoning": req.reasoning,
        "history_len": len(req.history) if req.history else 0,
        "output_path": str(work_dir / "trace" / f"{stage}.output.md"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    (work_dir / "trace").mkdir(parents=True, exist_ok=True)
    return LLMResponse(
        text=f"<claude-self: prompt ready at {prompt_path}>",
        raw=manifest,
    )


def load_stage_output(work_dir: Path, stage: str) -> str:
    """Read back Claude's reasoning output for a given stage."""
    out = work_dir / "trace" / f"{stage}.output.md"
    if not out.exists():
        raise FileNotFoundError(
            f"Stage '{stage}' output not found at {out}. "
            "Did Claude complete the reasoning step?"
        )
    return out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Mode: anthropic  (uses the official SDK)
# --------------------------------------------------------------------------- #
def call_anthropic(req: LLMRequest, model: str = "claude-opus-4-7") -> LLMResponse:
    import anthropic  # type: ignore

    client = anthropic.Anthropic()
    content: list[dict[str, Any]] = []
    if req.pdf_path and req.pdf_path.exists():
        import base64
        data = base64.b64encode(req.pdf_path.read_bytes()).decode()
        content.append(
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        )
    content.append({"type": "text", "text": req.prompt})

    messages = (req.history or []) + [{"role": "user", "content": content}]
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": 8000,
        "messages": messages,
    }
    if req.system:
        kwargs["system"] = req.system
    resp = retry_with_backoff(client.messages.create, **kwargs)
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    return LLMResponse(text=text, raw=resp)


# --------------------------------------------------------------------------- #
# Mode: openai
# --------------------------------------------------------------------------- #
def call_openai(req: LLMRequest, model: str = "gpt-4o") -> LLMResponse:
    import openai  # type: ignore

    client = openai.OpenAI()
    messages: list[dict[str, Any]] = []
    if req.system:
        messages.append({"role": "system", "content": req.system})
    messages.extend(req.history or [])
    messages.append({"role": "user", "content": req.prompt})
    resp = retry_with_backoff(
        client.chat.completions.create,
        model=model, messages=messages, max_tokens=8000,
    )
    text = resp.choices[0].message.content or ""
    return LLMResponse(text=text, raw=resp)


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def call_llm(
    req: LLMRequest,
    mode: str = "claude-self",
    work_dir: Path | None = None,
    model: str | None = None,
) -> LLMResponse:
    if mode == "claude-self":
        if work_dir is None:
            raise ValueError("claude-self mode requires work_dir")
        return call_claude_self(req, work_dir)
    if mode == "anthropic":
        return call_anthropic(req, model=model or "claude-opus-4-7")
    if mode == "openai":
        return call_openai(req, model=model or "gpt-4o")
    raise ValueError(f"Unknown mode: {mode}")
