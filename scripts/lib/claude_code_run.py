#!/usr/bin/env python3
"""
Claude Code CLI 调用封装

关键工程要点:
  1. 无 TTY 环境下 claude --dangerously-skip-permissions < prompt_file
  2. stdbuf 行缓冲，workflow 日志实时可见
  3. 进程组 SIGKILL 确保子进程清理
  4. prompt 落盘支持 replay
"""

import os
import sys
import json
import time
import signal
import subprocess
from pathlib import Path
from datetime import datetime
from threading import Timer
from typing import Optional, Dict, Any

DEFAULT_MODEL = os.getenv('AI_MODEL', 'claude-sonnet-4-6')
DEFAULT_EXTRA_RAW = '--dangerously-skip-permissions'
DEFAULT_TIMEOUT = int(os.getenv('AI_TIMEOUT_MS', '1800000'))


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] claude-code {msg}", file=sys.stderr)


def run_claude_code(
    prompt_file: str,
    context: Dict[str, Any],
    instruction: str,
    work_dir: str,
    output_file: str,
    log_dir: Optional[str] = None,
    timeout_ms: int = DEFAULT_TIMEOUT,
    model: str = DEFAULT_MODEL,
    extra_args_raw: str = DEFAULT_EXTRA_RAW,
    label: str = 'claude-code',
    conventions_file: Optional[str] = None,
) -> Dict[str, str]:
    """
    跑一次 claude code

    接口与 run_opencode 兼容（无 agent 参数）。
    Agent 通过 Write tool 将结果写入 output_file。
    """
    if not prompt_file:
        raise ValueError('prompt_file required')
    if not work_dir:
        raise ValueError('work_dir required')
    if not output_file:
        raise ValueError('output_file required')

    Path(work_dir).mkdir(parents=True, exist_ok=True)
    artifact_dir = log_dir or work_dir
    if artifact_dir != work_dir:
        Path(artifact_dir).mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
    log_file = os.path.join(artifact_dir, f'claude-code-{label}-{ts}.log')

    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_body = f.read()

    context_json = json.dumps(context or {}, indent=2, ensure_ascii=False)

    conventions_text = ''
    if conventions_file and os.path.exists(conventions_file):
        with open(conventions_file, 'r', encoding='utf-8') as f:
            conventions_text = f.read()
        log(f'📋 Loaded conventions from {conventions_file} ({len(conventions_text)} chars)')

    prompt_parts = [
        prompt_body.strip(),
        '',
        '## 上下文 (Context)',
        '```json',
        context_json,
        '```',
    ]

    if conventions_text:
        prompt_parts.extend([
            '',
            '## 项目规范与约束 (Project Conventions)',
            '以下是当前项目的规范要求，请在分析和设计时严格遵守：',
            '',
            conventions_text,
        ])

    prompt_parts.extend([
        '',
        '## 任务指令',
        instruction or '',
        '',
        '## 输出要求',
        f'请把最终结果写入文件: `{output_file}`',
        '(写入完成后即可结束，无需在 stdout 重复输出全文)',
    ])

    full_prompt = '\n'.join(prompt_parts)

    if os.path.exists(output_file):
        os.remove(output_file)

    prompt_dump_file = os.path.join(artifact_dir, f'claude-code-prompt-{label}-{ts}.txt')
    with open(prompt_dump_file, 'w', encoding='utf-8') as f:
        f.write(full_prompt)

    claude_bin = os.getenv('CLAUDE_CODE_BIN', 'claude')
    extra_args = extra_args_raw.split() if extra_args_raw else []
    claude_args = ['--model', model] + extra_args

    bash_cmd = f'stdbuf -oL -eL {claude_bin} {" ".join(claude_args)} < "{prompt_dump_file}"'

    log(f'▶ [{label}] starting (timeout={timeout_ms // 1000}s)')
    log(f'    bin:     {claude_bin}')
    log(f'    args:    {json.dumps(claude_args)}')
    log(f'    cwd:     {work_dir}')
    log(f'    model:   {model}')
    log(f'    prompt:  {len(full_prompt)} chars → {prompt_dump_file}')
    log(f'    log:     {log_file}')
    log(f'    output:  {output_file}')
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    log(f'    api:     key={("***" + api_key[-4:]) if len(api_key) > 4 else "NOT SET"}')
    log(f'    replay:  cd {work_dir} && {claude_bin} {" ".join(claude_args)} < {prompt_dump_file}')

    t0 = time.time()

    try:
        header = (
            f'==== claude-code-run [{label}] @ {datetime.now().isoformat()} ====\n'
            f'bin={claude_bin}\nargs={json.dumps(claude_args)}\ncwd={work_dir}\n'
            f'prompt_file={prompt_dump_file} ({len(full_prompt)} chars)\n'
            f'output_file={output_file}\n'
            f'replay: cd {work_dir} && {claude_bin} {" ".join(claude_args)} < {prompt_dump_file}\n'
            f'---- stdout/stderr 见 workflow log ----\n'
        )
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(header)
    except Exception as e:
        log(f'    ⚠ log file header 写入失败(不阻断): {e}')

    try:
        process = subprocess.Popen(
            ['bash', '-c', bash_cmd],
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            start_new_session=True,
        )
    except Exception as e:
        raise RuntimeError(f'claude-code spawn failed: {e}')

    log(f'    pid:     {process.pid}')

    timed_out = False

    def timeout_handler():
        nonlocal timed_out
        timed_out = True
        duration = time.time() - t0
        log(f'  ⏱ [{label}] TIMEOUT {duration:.1f}s, SIGKILL pid=-{process.pid}')
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception as exc:
            log(f'     kill -PG 失败({exc}), fallback kill')
            try:
                process.kill()
            except Exception:
                pass

    timer = Timer(timeout_ms / 1000, timeout_handler)
    timer.daemon = True
    timer.start()

    try:
        stdout, stderr = process.communicate()
        timer.cancel()

        duration = time.time() - t0

        stderr_text = stderr.decode('utf-8', errors='replace').strip()
        stdout_text = stdout.decode('utf-8', errors='replace').strip()

        if stderr_text:
            for line in stderr_text.split('\n'):
                log(f'  [stderr] {line}')
        if stdout_text:
            stdout_lines = stdout_text.split('\n')
            if len(stdout_lines) > 20:
                log(f'  [stdout] ... ({len(stdout_lines)} lines total, showing last 20)')
                for line in stdout_lines[-20:]:
                    log(f'  [stdout] {line}')
            else:
                for line in stdout_lines:
                    log(f'  [stdout] {line}')

        if timed_out:
            raise TimeoutError(
                f'claude-code [{label}] TIMEOUT after {duration:.1f}s '
                f'(limit {timeout_ms / 1000:.0f}s). '
                f'replay: cd {work_dir} && {claude_bin} {" ".join(claude_args)} < {prompt_dump_file}'
            )

        if process.returncode != 0:
            if not os.path.exists(output_file):
                raise RuntimeError(
                    f'claude-code [{label}] exit {process.returncode} '
                    f'且未生成 outputFile {output_file}。\n'
                    f'stderr: {stderr_text[:2000]}\n'
                    f'replay: cd {work_dir} && {claude_bin} {" ".join(claude_args)} < {prompt_dump_file}'
                )
            log(f'  ⚠ [{label}] exit={process.returncode} in {duration:.1f}s (outputFile 存在)')
        else:
            log(f'  ✅ [{label}] exit=0 in {duration:.1f}s')

        if not os.path.exists(output_file):
            raise RuntimeError(
                f'claude-code [{label}] exit {process.returncode} in {duration:.1f}s, '
                f'但未找到 outputFile {output_file}。\n'
                f'replay: cd {work_dir} && {claude_bin} {" ".join(claude_args)} < {prompt_dump_file}'
            )

        return {
            'output_file': output_file,
            'log_file': log_file,
            'prompt_file': prompt_dump_file,
            'exit_code': process.returncode,
        }

    except KeyboardInterrupt:
        timer.cancel()
        log(f'  ⚠ [{label}] 被用户中断')
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            pass
        raise
    except Exception:
        timer.cancel()
        if not timed_out:
            raise
