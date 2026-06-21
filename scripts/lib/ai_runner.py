#!/usr/bin/env python3
"""
AI Agent 调用统一入口

根据 AI_RUNNER 环境变量选择后端：
  opencode             → opencode_run.run_opencode（默认）
  claude-code          → claude_code_run.run_claude_code（Anthropic API Key）
  claude-code-account  → claude_code_run.run_claude_code（Claude.ai 账号 OAuth）
"""

import os
from typing import Dict, Any, Optional


def run_agent(
    prompt_file: str,
    context: Dict[str, Any],
    instruction: str,
    work_dir: str,
    output_file: str,
    log_dir: Optional[str] = None,
    timeout_ms: Optional[int] = None,
    label: str = 'agent',
    conventions_file: Optional[str] = None,
) -> Dict[str, str]:
    """统一 AI Agent 调用入口，透明切换 OpenCode / Claude Code。"""
    runner = os.getenv('AI_RUNNER', 'opencode')

    kwargs: Dict[str, Any] = dict(
        prompt_file=prompt_file,
        context=context,
        instruction=instruction,
        work_dir=work_dir,
        output_file=output_file,
        log_dir=log_dir,
        label=label,
        conventions_file=conventions_file,
    )
    if timeout_ms is not None:
        kwargs['timeout_ms'] = timeout_ms

    if runner in ('claude-code', 'claude-code-account'):
        from scripts.lib.claude_code_run import run_claude_code
        return run_claude_code(**kwargs)
    else:
        from scripts.lib.opencode_run import run_opencode
        return run_opencode(**kwargs)
