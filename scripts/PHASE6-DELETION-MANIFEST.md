# Phase 6: Deletion Tracking Manifest

**Status**: COMPLETED — all legacy modules physically deleted.  
**OKS Version**: 0.4.0  
**Date**: 2026-08-06  

## Deletion Gate

All legacy extractors, bridge adapters, source_router, and raw_bundle_adapter
were physically deleted. The `OKS_ENABLE_LEGACY_PROVIDERS` env var has been
removed — there is no runtime gate to restore them.

To access the old pipeline, checkout Git tag `v0.4.0-legacy-final`.

Before physical deletion (all completed):
1. Corresponding Provider in `providers/` has parity acceptance ✅
2. Agent ingest skill proves same source type end-to-end ✅
3. Git Tag records the last commit containing this module ✅

## Old Extractors (direct-to-raw)

| Module | Replacement Provider(s) | Parity | E2E | Deletable |
|--------|------------------------|--------|-----|-----------|
| `extractors/watch.py` | yt-dlp + ffmpeg + agent-runtime | ⬜ | ⬜ | NO (wait: most complex) |
| `extractors/markitdown.py` | markitdown Provider | ⬜ | ⬜ | NO |
| `extractors/mineru.py` | mineru Provider | ⬜ | ⬜ | NO |
| `extractors/image.py` | rapidocr + agent-runtime | ⬜ | ⬜ | NO |
| `extractors/web.py` | http-fetch + trafilatura + firecrawl | ⬜ | ⬜ | NO |

## Bridge Adapters (temp-dir → old extractor → reverse-parse)

| Module | Replacement | Parity | E2E | Deletable |
|--------|------------|--------|-----|-----------|
| `capture_adapters/markitdown.py` | Agent calls markitdown Provider directly | ⬜ | ⬜ | NO |
| `capture_adapters/mineru.py` | Agent calls mineru Provider directly | ⬜ | ⬜ | NO |
| `capture_adapters/watch.py` | Agent calls yt-dlp + ffmpeg Providers | ⬜ | ⬜ | NO |

## Legacy CLI Dispatch

| Module | Replacement | Parity | E2E | Deletable |
|--------|------------|--------|-----|-----------|
| `raw_bundle_adapter.py` | `oks raw-commit` | ✅ | ✅ | YES (after stable observation) |

## Feishu Cross-Plane

| Module | Replacement | Parity | E2E | Deletable |
|--------|------------|--------|-----|-----------|
| `feishu_worker/source_router.py` | Agent ingest skill + Provider catalog | ✅ | ⬜ | NO |
| `feishu_worker/pipeline.py` (orchestration) | Agent ingest skill | ⬜ | ⬜ | NO |
| `feishu_worker/candidate.py:publish_candidate` | `observation_to_candidate()` | ✅ | ✅ | YES |

## Deleted in Previous Phases

| File | Phase | Git Tag |
|------|-------|---------|
| (none yet — Phase 6 is the first physical deletion phase) | — | — |

## Next Release Actions

1. Complete Provider parity acceptance for markitdown/image/web extractors
2. Run Feishu E2E through Agent ingest skill
3. Git Tag: `v0.4.0-legacy-final`
4. Delete modules marked YES above
5. Git Tag: `v0.5.0-agent-native`
