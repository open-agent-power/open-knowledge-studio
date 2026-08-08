# Feishu Worker — Architecture Boundary Document

**Status**: Contraction in progress (Phase 5).  
**Target**: Source Plane + Review Control Plane only.

## Current vs Target

```
CURRENT (violations)                    TARGET (Phase 6)
──────────────────────────────────────  ──────────────────────────
pipeline.py: process_record()
  ├─ claim record            ✅         feishu_worker/claim.py
  ├─ extract URL             ✅         feishu_worker/capture.py
  ├─ probe URL               ❌ → Agent  Agent via capability system
  ├─ select extractor         ❌ → Agent  Agent via Capability Catalog
  ├─ subprocess connector    ❌ → Agent  Agent via provider run.py
  ├─ assemble Raw Bundle     ❌ → Agent  Agent → oks raw-commit
  ├─ publish candidate       ❌ → Agent  Agent → observation_to_candidate()
  ├─ send notification       ✅         feishu_worker/notification.py
  └─ write status back       ✅         feishu_worker/base_client.py

source_router.py              ❌ DEL     Agent owns provider selection
candidate.py:publish_candidate ❌ SPLIT   draft→Agent, notification→keep
```

## Module Disposition

| Module | Phase 5 | Phase 6 |
|--------|---------|---------|
| `base_client.py` | Keep | Keep |
| `config.py` | Keep | Keep |
| `states.py` | Keep | Keep |
| `claim.py` | Keep | Keep |
| `capture.py` | Keep (envelope + hash) | Keep |
| `io_utils.py` | Keep | Keep |
| `notification.py` | Keep | Keep |
| `review_events.py` | Keep | Keep |
| `pipeline.py` | Marked @deprecated | Decompose: keep claim wrapper, delete orchestration |
| `source_router.py` | Marked @deprecated | Delete |
| `candidate.py` | Marked @deprecated on publish | Split: draft→Agent, notification→keep |
| `cli.py` | Keep | Keep |

## Migration Gate

Before deletion in Phase 6, each deprecated module must have:
1. A replacement Provider in `providers/` with equivalent capability
2. The replacement verified by an acceptance test
3. The Agent ingest skill proven to handle the same source types
4. At least one Feishu E2E cycle through the new path
