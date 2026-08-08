# MinerU Provider

重型 PDF 布局解析。~300MB 依赖，按需安装。

## 安装

```bash
oks capability install pdf --yes
```

## 调用

Agent 通过 Bash 调用：
```bash
# Historical: raw_bundle_adapter.py was removed in v0.4.0.
# Use /ingest skill in Agent Host (Claude Code / Codex) or:
# oks raw-commit .oks/runs/{run_id}/manifest/
```

## 限制

依赖体积大。W3C PDF（750KB）曾超时 ~244 秒。子进程清理不完整。仅在 pdf-lite 文本层为空且有 GPU 时推荐使用。
