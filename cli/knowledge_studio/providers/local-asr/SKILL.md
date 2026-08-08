# Local ASR Provider

本地语音识别（faster-whisper）。12 秒短音频已验证。

## 调用

通过 watch capability 调用：
```bash
# Historical: raw_bundle_adapter.py was removed in v0.4.0.
# Use /ingest skill in Agent Host (Claude Code / Codex) or:
# oks raw-commit .oks/runs/{run_id}/manifest/
```

## 限制

首次使用需下载模型文件。长音频未在当前环境验证。
