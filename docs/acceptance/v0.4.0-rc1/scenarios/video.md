# Scenario E — Video + Subtitles + Keyframes

**Status**: FULL PASS (partial by design)
**Date**: 2026-08-05 (original), 2026-08-06 (E2E re-verified)

## Command

```powershell
ols raw-commit tmp/cli-scenario-e/manifest --output tmp/cli-scenario-e --overwrite
# E2E:
# /ingest skill: "收录这个视频"
oks raw-commit .oks/runs/run-e2e-video-{id}/manifest --overwrite
```

## Input

- **URL**: `https://www.bilibili.com/video/BV1p4MD6KEaM`
- **Title**: varies (emoji-encoded)
- **Duration**: ~107s
- **Access**: public_url

## Providers

1. `yt-dlp` (2026.07.04) — metadata.fetch + subtitle.fetch
   - Video metadata (title, duration, format info)
   - Danmaku XML: 51,676 characters (600+ entries, no login needed)
2. `ffmpeg` (8.1.2) — video.keyframes
   - 7 I-frames from 30s segment (~28% of video duration)

## Bundle

- **E2E ID**: `bundle:9ae09df43b9d0d9c`

## Evidence

- **Count**: 2 records (metadata + danmaku sample)
- **Locator**: `kind: custom`
- **Artifacts**: metadata.json (full yt-dlp dump)

## Completeness

- **Status**: partial
- **Missing**: Regular subtitles (require Bilibili cookie auth)
- **Impact**: Topic search via danmaku works; full speech coverage unavailable
- **Known Limits**: Danmaku are user comments, not speech transcription; keyframes from first 30s only

## Commit

`8b28b4c` fix(release): close 6 RC readiness gaps
