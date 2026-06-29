#!/usr/bin/env python3
"""
GitCode Issues API — issue 读写操作（Gitee v5 兼容）
"""

import re
import requests
from typing import Dict, List, Any, Optional

GITCODE_BASE = "https://gitcode.com"


def parse_repo(repo: str):
    """'https://gitcode.com/owner/name' 或 'owner/name' → (owner, name)"""
    repo = repo.rstrip('/')
    if repo.startswith(f'{GITCODE_BASE}/'):
        repo = repo[len(f'{GITCODE_BASE}/'):]
    parts = repo.split('/')
    return parts[0], parts[1]


# ── Issue 查询 ──

def fetch_all_open_issues(repo: str, token: str, max_issues: int = 100) -> List[Dict]:
    """获取仓库全部 open issues（不过滤标签），由调用方按标题关键词过滤。"""
    owner, name = parse_repo(repo)
    url = f"{GITCODE_BASE}/api/v5/repos/{owner}/{name}/issues"
    params = {
        'state': 'open',
        'per_page': min(max_issues, 100),
        'sort': 'created',
        'direction': 'desc',
        'access_token': token,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def filter_issues_by_title(issues: List[Dict], keyword: str) -> List[Dict]:
    """过滤标题中包含 keyword 的 issues（大小写不敏感）。"""
    kw = keyword.lower()
    return [i for i in issues if kw in (i.get('title') or '').lower()]


def get_issue_labels(issue: Dict) -> List[str]:
    return [l.get('name', '') for l in (issue.get('labels') or [])]


# ── Issue 写操作 ──

def add_issue_label(repo: str, issue_number: int, label: str, token: str):
    owner, name = parse_repo(repo)
    url = f"{GITCODE_BASE}/api/v5/repos/{owner}/{name}/issues/{issue_number}/labels"
    resp = requests.post(url, params={'access_token': token}, json=[label], timeout=30)
    resp.raise_for_status()


def remove_issue_label(repo: str, issue_number: int, label: str, token: str):
    owner, name = parse_repo(repo)
    url = f"{GITCODE_BASE}/api/v5/repos/{owner}/{name}/issues/{issue_number}/labels/{label}"
    resp = requests.delete(url, params={'access_token': token}, timeout=30)
    if resp.status_code not in (200, 204, 404):
        resp.raise_for_status()


def add_issue_comment(repo: str, issue_number: int, body: str, token: str):
    owner, name = parse_repo(repo)
    url = f"{GITCODE_BASE}/api/v5/repos/{owner}/{name}/issues/{issue_number}/comments"
    resp = requests.post(url, params={'access_token': token}, json={'body': body}, timeout=30)
    resp.raise_for_status()


def create_pull_request(repo: str, head: str, base: str, title: str, body: str, token: str) -> Dict:
    owner, name = parse_repo(repo)
    url = f"{GITCODE_BASE}/api/v5/repos/{owner}/{name}/pulls"
    payload = {'title': title, 'body': body, 'head': head, 'base': base}
    resp = requests.post(url, params={'access_token': token}, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── Issue 正文解析 ──

# 支持格式：
#   **软件包名称：** fluid
#   **源码仓库：** https://github.com/...
#   **所属领域：** 虚拟化
# 以及自由文本：
#   新增软件包 fluid，源码仓库链接是 https://github.com/...，场景属于虚拟化

_PACKAGE_PATTERNS = [
    re.compile(r'\*\*软件包名称[（(].*?[）)]?[：:]\*\*\s*(\S+)', re.IGNORECASE),
    re.compile(r'\*\*Package Name[：:]\*\*\s*(\S+)', re.IGNORECASE),
    re.compile(r'软件包名称[^：:\n]*[：:]\s*(\S+)', re.IGNORECASE),
    re.compile(r'软件包[名称]*[：:\s]+(\S+)', re.IGNORECASE),
    re.compile(r'新增\s*(?:上游\s*)?软件包\s*[：:]?\s*(\S+)', re.IGNORECASE),
    re.compile(r'package\s*[：:]\s*([a-zA-Z0-9_-]+)', re.IGNORECASE),
]

_REPO_PATTERN = re.compile(r'https?://github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)', re.IGNORECASE)

_DOMAIN_PATTERNS = [
    re.compile(r'\*\*所属领域[（(].*?[）)]?[：:]\*\*\s*(.+)', re.IGNORECASE),
    re.compile(r'\*\*Domain[：:]\*\*\s*(.+)', re.IGNORECASE),
    re.compile(r'所属领域[^：:\n]*[：:]\s*(.+)', re.IGNORECASE),
    re.compile(r'(?:场景|领域|分类)[^：:\n]*[：:]\s*(.+)', re.IGNORECASE),
    re.compile(r'(?:category|domain)[^：:\n]*[：:]\s*(.+)', re.IGNORECASE),
]

# 领域 → 目录 映射
DOMAIN_TO_CATEGORY = {
    '虚拟化': 'Cloud', 'virtualization': 'Cloud',
    '云原生': 'Cloud', '云计算': 'Cloud', 'cloud': 'Cloud', 'cloudnative': 'Cloud',
    '网络': 'Cloud', 'network': 'Cloud',
    '人工智能': 'AI', 'ai': 'AI', '机器学习': 'AI', 'ml': 'AI', 'deep learning': 'AI',
    '大数据': 'Bigdata', 'bigdata': 'Bigdata', 'big data': 'Bigdata',
    '数据库': 'Database', 'database': 'Database', 'db': 'Database',
    '高性能计算': 'HPC', 'hpc': 'HPC',
    '安全': 'Security', 'security': 'Security',
    '存储': 'Storage', 'storage': 'Storage',
}


def parse_issue_body(title: str, body: str) -> Optional[Dict[str, str]]:
    """从 issue 标题和正文中解析出 package_name / source_repo / domain / category。

    返回 None 表示解析失败（信息不足）。
    """
    text = f"{title}\n{body or ''}"

    # package_name
    package_name = None
    for pat in _PACKAGE_PATTERNS:
        m = pat.search(text)
        if m:
            package_name = m.group(1).strip().rstrip('，,。.')
            break

    # source_repo URL
    m = _REPO_PATTERN.search(text)
    source_repo_url = f"https://github.com/{m.group(1)}" if m else None

    # 从 URL 推断 package_name（fallback）
    if not package_name and source_repo_url:
        package_name = source_repo_url.rstrip('/').split('/')[-1]

    # domain
    domain_raw = None
    for pat in _DOMAIN_PATTERNS:
        m2 = pat.search(text)
        if m2:
            domain_raw = m2.group(1).strip().rstrip('，,。.').lower()
            break

    # category
    category = 'Cloud'  # 默认
    if domain_raw:
        for key, cat in DOMAIN_TO_CATEGORY.items():
            if key in domain_raw:
                category = cat
                break

    if not package_name or not source_repo_url:
        return None

    return {
        'package_name': package_name,
        'source_repo_url': source_repo_url,
        'domain': domain_raw or 'cloud',
        'category': category,
    }
