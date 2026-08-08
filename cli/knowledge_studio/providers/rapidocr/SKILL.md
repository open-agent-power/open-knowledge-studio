# RapidOCR Provider

轻量 OCR。46 blocks/5.5s 已验证。

## 最佳组合

RapidOCR (mechanical, bbox) + Agent Vision (agent_observed, 页面语义) = 混合最优。

## 调用

```bash
# Historical: raw_bundle_adapter.py was removed in v0.4.0.
# Use /ingest skill in Agent Host (Claude Code / Codex) or:
# oks raw-commit .oks/runs/{run_id}/manifest/
```
