---
description: Universal intake — multi-modal handler dispatch + A/B/C triage of raw/ into drafts/
---

# /ingest — Universal Intake & Triage

## Purpose

Two roles:
1. **Intake** — Accept any modality (URL, PDF, video, audio, image, repo), auto-detect and process through the handler pipeline into `raw/`.
2. **Triage** — Scan `raw/` for unprocessed materials, AI-assess quality, write A-grade items as draft proposals to `drafts/`.

## Phase 1: Universal Intake

When the user provides a URL, file path, or directory:

```bash
# Auto-detect modality and process
oks ingest <input>              # writes to raw/{articles,papers,repos,misc}/

# Preview without writing
oks ingest <input> --dry-run

# Force a specific handler
oks ingest <input> --handler video
```

### Handler Pipeline

```
Input (any modality)
  ↓ detect_modality() — URL? file ext? directory?
  ↓ HandlerRegistry.find_handler() — match to available handler
  ↓ handler.process() — modality-specific processing
  ↓ Maximum Fidelity Principle:
    - Original text extracted directly (no AI summary)
    - AI only fills gaps (frame descriptions, audio transcripts)
    - Layered output: [原始文本] + [AI描述] + [元数据]
  ↓ Write to raw/{subdir}/{slug}.md with frontmatter
```

### Available Handlers

| Handler | Modalities | Dependencies | Status |
|---------|-----------|--------------|--------|
| web | http/https URLs | None (stdlib) | Enabled |
| pdf | .pdf files | pypdf | Enabled |
| repo | Git directories | None (stdlib) | Enabled |
| video | mp4/mov/youtube/bilibili | ffmpeg + whisper + vision API | Disabled (opt-in) |
| audio | mp3/wav/m4a/flac | whisper | Disabled (opt-in) |
| image | png/jpg/webp | Vision API key | Disabled (opt-in) |

Enable handlers: `oks handlers enable video` → install deps → set API keys via `oks config set`.

## Phase 2: A/B/C Triage

After materials are in `raw/`, or when the user asks to "ingest" or "process raw":

1. **Scan raw/** — List files in raw/articles/, raw/papers/, raw/repos/, raw/misc/.
2. **For each file, AI-assess:**
   - **Relevance** — Does this relate to active domains?
   - **Quality** — Is the content substantial (≥50 chars)?
   - **Novelty** — Run `oks search <keywords>` to check duplicates.
   - **Grade**: A (→ drafts/), B (→ held), C (skip)
3. **Quality gates:**
   - Content < 50 chars → skip
   - Generic title ("Untitled", "Note") → skip
   - Importance < 0.3 → skip
   - Duplicate fingerprint → skip
4. **For A-grade items** — Extract concepts, determine type + area, write to `drafts/{slug}.md`.
5. **Report** — Summary: X scanned, Y drafted, Z held, W skipped.

## Rules

- Never write directly to `wiki/` — always through `drafts/` for human review (CONSTITUTION.md A3).
- Include source reference in the draft body.
- Handlers that need AI models (vision, STT) read API keys from `~/.oks/config.json`.
- If a handler is not available, report the dependency hint — don't silently fail.
