# create-docker-images-workflow

自动监测 [openeuler-docker-images](https://gitcode.com/openeuler/openeuler-docker-images) 仓库的 Issues，将新增上游软件包请求转化为 PR 的全自动 workflow。

## 工作流程

```
GitCode Issue (标题含【new-image】)
        │
        ▼ 每小时轮询
watch-issues.yml (cron: 0 * * * *)
        │  解析 issue → dispatch
        ▼
create-image-trigger.yml
        │
        ├─ Clone openeuler-docker-images fork
        ├─ 运行 Claude Code (image-creator agent)
        │   ├─ gh API 获取最新版本、Go 版本、License
        │   ├─ 创建 Dockerfile / meta.yml / README.md
        │   ├─ 创建 doc/image-info.yml + logo
        │   └─ 更新 image-list.yml
        ├─ git commit & push → add-{package} 分支
        ├─ GitCode API 创建 PR
        └─ GitCode API 回复 issue
```

## Issue 格式

在 https://gitcode.com/openeuler/openeuler-docker-images/issues 提交 issue，**标题中包含 `【new-image】`** 即可触发，正文格式（支持自由文本或结构化）：

**结构化格式（推荐）：**
```
**软件包名称（Package Name）：** fluid
**源码仓库（Source Repository）：** https://github.com/fluid-cloudnative/fluid
**所属领域（Domain）：** 虚拟化
```

**自由文本格式：**
```
新增openeuler上游软件包fluid，源码仓库链接是https://github.com/fluid-cloudnative/fluid，场景属于虚拟化
```

### 领域 → 目录 映射

| 领域关键词 | 目标目录 |
|-----------|---------|
| 虚拟化、云原生、云计算、网络 | `Cloud/` |
| AI、人工智能、机器学习 | `AI/` |
| 大数据 | `Bigdata/` |
| 数据库 | `Database/` |
| 高性能计算、HPC | `HPC/` |
| 安全 | `Security/` |
| 存储 | `Storage/` |
| 其他 | `Cloud/`（默认） |

## 配置 GitHub Secrets

| Secret | 说明 |
|--------|------|
| `GITCODE_TOKEN` | GitCode Personal Access Token（读写 issues、PR） |
| `DISPATCH_TOKEN` | GitHub PAT（用于 repository_dispatch） |
| `AI_API_KEY` | AI API Key。默认用 DeepSeek，填 DeepSeek API Key；切换 Claude 时填 Anthropic Key |
| `CLAUDE_CREDENTIALS_JSON` | 仅当 `AI_RUNNER=claude-code-account` 时需要（Claude.ai 账号 OAuth 凭据） |

## GitHub Variables（可选）

| Variable | 默认值 | 说明 |
|----------|--------|------|
| `AI_RUNNER` | `opencode` | AI 后端：`opencode`（DeepSeek）/ `claude-code` / `claude-code-account` |
| `AI_MODEL` | `deepseek/deepseek-v4-pro` | 模型名称，opencode 格式如 `deepseek/deepseek-v4-pro` |
| `AI_TIMEOUT_MS` | `1800000` | AI 执行超时（毫秒） |
| `OPENAI_BASE_URL` | _(空，使用默认)_ | 自定义 API 代理地址（可选） |
| `OS_VERSION` | `24.03-lts-sp3` | openEuler 版本 |
| `OS_TAG` | `oe2403sp3` | 镜像 Tag 后缀 |
| `GIT_COMMIT_NAME` | `github-actions[bot]` | Git 提交用户名 |
| `GIT_COMMIT_EMAIL` | `github-actions[bot]@...` | Git 提交邮箱 |

## 项目结构

```
create-docker-images-workflow/
├── .github/
│   ├── agents/
│   │   └── image-creator.md          # Claude Code Agent 提示词
│   └── workflows/
│       ├── watch-issues.yml           # 每小时 cron：轮询 GitCode issues
│       └── create-image-trigger.yml   # 触发：执行镜像文件创建 + PR
├── config/
│   └── watchlist.json                 # 监控仓库列表与设置
├── scripts/
│   ├── lib/
│   │   ├── gitcode_issues_api.py      # GitCode Issues API 客户端
│   │   └── claude_code_run.py         # Claude Code CLI 封装
│   ├── watch/
│   │   └── process_issue_events.py    # Issue 轮询 + dispatch
│   └── stages/
│       └── create-image.py            # 调用 Claude Code 创建文件
└── requirements.txt
```
