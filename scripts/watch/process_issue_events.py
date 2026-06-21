#!/usr/bin/env python3
"""
Issue 监控 — 新增镜像请求自动触发器

轮询 watchlist 中的仓库 issues，检测标题中包含 trigger_title_keyword（默认「new-image」）
的 open issues，跳过已有 creating_label 或 done_label 的 issue（避免重复处理），
解析 issue 正文提取 package_name / source_repo / domain，
向 GitHub Actions 发送 repository_dispatch 触发 create-image-trigger workflow。
"""

import os
import sys
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PROJECT_ROOT)

from scripts.lib.gitcode_issues_api import (
    fetch_all_open_issues, filter_issues_by_title,
    get_issue_labels, add_issue_label,
    add_issue_comment, parse_issue_body,
)

WATCHLIST_FILE = os.path.join(PROJECT_ROOT, 'config', 'watchlist.json')


def log(msg: str):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def dispatch_create_image(payload: Dict, dispatch_token: str, target_repo: str) -> bool:
    url = f"https://api.github.com/repos/{target_repo}/dispatches"
    headers = {
        'Authorization': f'token {dispatch_token}',
        'Accept': 'application/vnd.github.v3+json',
    }
    body = {'event_type': 'create-image', 'client_payload': payload}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 204:
            log(f"  ✅ Dispatched create-image: {payload['package_name']}")
            return True
        log(f"  ❌ Dispatch failed HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        log(f"  ❌ Dispatch error: {e}")
        return False


def process_all():
    with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
        watchlist = json.load(f)

    settings = watchlist.get('settings', {})
    max_events = settings.get('max_events_per_run', 5)

    gitcode_token = os.getenv('GITCODE_TOKEN', '')
    dispatch_token = os.getenv('DISPATCH_TOKEN', '')
    target_repo = os.getenv('GITHUB_REPOSITORY', 'sunshuang1866/create-docker-images-workflow')

    if not gitcode_token:
        log("❌ GITCODE_TOKEN not set")
        sys.exit(1)
    if not dispatch_token:
        log("❌ DISPATCH_TOKEN not set")
        sys.exit(1)

    log("🔍 Starting issue monitoring cycle")
    log(f"   target_repo: {target_repo}  max_events: {max_events}")

    total_dispatched = 0

    for repo_config in watchlist.get('watched_repos', []):
        if not repo_config.get('enabled', True):
            continue

        repo = repo_config['repo']
        fork_repo = repo_config.get('fork_repo', '')
        base_branch = repo_config.get('base_branch', 'master')
        trigger_keyword = repo_config.get('trigger_title_keyword', '【new-image】')
        creating_label = repo_config.get('creating_label', 'image-creating')
        done_label = repo_config.get('done_label', 'image-created')

        log(f"\n{'='*60}")
        log(f"📦 {repo}  trigger_keyword={trigger_keyword}")

        try:
            all_issues = fetch_all_open_issues(repo, gitcode_token)
            issues = filter_issues_by_title(all_issues, trigger_keyword)
        except Exception as e:
            log(f"  ❌ Failed to fetch issues: {e}")
            continue

        log(f"  Found {len(issues)} issue(s) with '{trigger_keyword}' in title")

        for issue in issues:
            if total_dispatched >= max_events:
                log(f"\n  ⚠️ max_events_per_run ({max_events}) reached, stopping")
                break

            number = issue['number']
            title = issue.get('title', '')
            body = issue.get('body', '') or ''
            labels = get_issue_labels(issue)

            log(f"\n  🔎 Issue #{number}: {title[:60]}")

            # 跳过已经在处理或已完成的 issue
            if creating_label in labels:
                log(f"    → Skipping: already has '{creating_label}' label")
                continue
            if done_label in labels:
                log(f"    → Skipping: already has '{done_label}' label")
                continue

            # 解析 issue 正文
            parsed = parse_issue_body(title, body)
            if not parsed:
                log(f"    → Skipping: cannot parse package_name or source_repo from issue body")
                continue

            log(f"    → Parsed: package={parsed['package_name']} "
                f"repo={parsed['source_repo_url']} "
                f"domain={parsed['domain']} category={parsed['category']}")

            # 打标记，防止重复触发
            try:
                add_issue_label(repo, number, creating_label, gitcode_token)
                log(f"    → Added label '{creating_label}'")
            except Exception as e:
                log(f"    ⚠️  Add label failed: {e}")

            # dispatch
            payload = {
                'repo': repo,
                'fork_repo': fork_repo,
                'base_branch': base_branch,
                'issue_number': number,
                'issue_title': title,
                **parsed,
                'creating_label': creating_label,
                'done_label': done_label,
            }
            if dispatch_create_image(payload, dispatch_token, target_repo):
                total_dispatched += 1
            else:
                # dispatch 失败，移除 creating_label，下次重试
                try:
                    from scripts.lib.gitcode_issues_api import remove_issue_label
                    remove_issue_label(repo, number, creating_label, gitcode_token)
                except Exception:
                    pass

    log(f"\n✅ Issue monitoring cycle complete. dispatched={total_dispatched}")


if __name__ == '__main__':
    process_all()
