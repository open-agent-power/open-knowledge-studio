---
description: Multi-modal intake — 3-level routing → raw/, then A/B/C triage → drafts/
---

# /ingest — Multi-Modal Intake

## Purpose

Accept any modality (URL, PDF, video, audio, image, repo), route to the
right tool, extract content with maximum fidelity, write to `raw/`.
Then triage: A-grade → drafts/, B-grade → skip, C-grade → skip.

## Phase 1: Intake — 3-Level Routing Table

Agent reads `settings/handlers.json` as a routing reference and routes
by modality detection.

### Modality Detection

| Input pattern | Modality | Route to |
|---------------|----------|----------|
| `http://` or `https://` (general) | url | curl (L0) or agent-reach (L2) |
| `youtube.com` or `youtu.be` | url:youtube | agent-reach (L2) or yt-dlp (L2) |
| `bilibili.com` | url:bilibili | agent-reach (L2) or yt-dlp (L2) |
| `*.pdf` | pdf | pdftotext (L0) |
| `*.mp4 *.mov *.avi *.mkv *.webm` | video | oks-video (L1) |
| `*.mp3 *.wav *.m4a *.flac *.aac *.ogg` | audio | oks-audio (L1) |
| `*.png *.jpg *.jpeg *.webp *.bmp` | image | oks-image (L1) |
| Directory path | repo | agent scans directly (L0) |

### Tool Availability Check

Before routing, agent checks if the selected tool is available by
running its `check_cmd` from `settings/handlers.json` via Bash:

```bash
# Example: check if curl is available
which curl
```

If the tool is missing, inform the user with the `install_hint` from
handlers.json and suggest an alternative tool if one exists.

### Level 0 — System Tools (agent runs directly)

Agent uses Bash to run system commands directly:
- `curl -sL <url>` → HTML → agent extracts text
- `pdftotext <file> -` → text
- Directory scan: `find`, `cat`, `ls` → agent reads structure

Output: raw stdout, agent writes to `raw/{YYYY}/{MM}/{DD}/{source}/{slug}.md`

### Level 1 — OKS Protocol CLIs (`oks-connector`)

L1 extractors come from the independently-installed `oks-connector` package
(console entry `oks-connector`). They emit a **Raw Bundle** — a directory
holding `content.md` (faithful primary text, the recall entry) plus sidecars
`raw.md`, `metadata.json` (source + hash), `evidence.jsonl` (atomic provenance),
`quality-report.json`, and `assets/` — conforming to the `raw-multimodal/v0.1`
contract. The tool writes the bundle directly via `--output`; the agent does
not reshape it.

```bash
oks-connector watch <file> --output raw/{YYYY}/{MM}/{DD}/videos/{slug}/   # video → transcript + frames + OCR
oks-connector watch <file> --output raw/{YYYY}/{MM}/{DD}/audio/{slug}/ --transcript-only   # audio → ASR
oks-connector image <file> --output raw/{YYYY}/{MM}/{DD}/misc/{slug}/     # image → OCR + bbox evidence
oks-connector validate <bundle_dir>                                       # check against v0.1 before it counts
```

The bundle **is** the raw record — recall reads `content.md` (type `raw`) and
`evidence.jsonl` lines (type `trace`) generically; no per-format handling in core.

### Level 2 — Independent Tools

Agent calls external tools directly, parses their output:
- `agent-reach <url>` → markdown/JSON
- `yt-dlp <url>` → downloaded file → further processing

Agent adapts to each tool's output format.

### Intake Workflow

1. **Detect** — agent determines modality from input pattern
2. **Check** — run `check_cmd` via Bash to verify tool is available
3. **Route** — select tool by level (prefer L0, then L1, then L2)
4. **Execute** — agent runs tool directly via Bash
5. **Write** — agent writes extracted content to `raw/{YYYY}/{MM}/{DD}/{source}/{slug}.md`
   - Source categories: `articles`, `papers`, `videos`, `audio`, `repos`, `misc`
   - Auto-create today's directory: `mkdir -p raw/{YYYY}/{MM}/{DD}/{source}/`
   - Use atomic write pattern (mkstemp + fsync + os.replace)
6. **Record** — log source URL/path, modality, tool used in frontmatter
   - Optional **human metadata** (P3-safe: annotation, not body content):
     - `note` — the human's verbatim intake comment, e.g.
       `note: "这个内容很不错，对于记忆管理"`. The LLM must not paraphrase or
       invent it; only record what the human actually said.
     - `flagged: true` — set when the human explicitly marks the item as
       worth promoting. Absent/false means normal triage.
   - These fields annotate the raw record; the raw **body** stays mechanical
     (P3). Recording a human's own words is metadata, not LLM authorship.

### Maximum Fidelity Principle (P3: raw is mechanical)

- Extraction is **mechanical** — curl/pdftotext (L0), or `oks-connector`
  ASR/OCR/frame sampling (L1). The tool produces the bytes.
- The **LLM never writes `raw/`** and never injects summaries, corrections, or
  descriptions. Faithful capture only; provenance goes in `evidence.jsonl`.
- Semantic understanding (captioning a frame, interpreting a diagram) happens at
  **conversation time or in Dreaming → drafts**, never at ingest into `raw/`.

## Phase 2: Triage — A/B/C Grading

After intake, scan `raw/` for unprocessed files:

1. **For each new file, AI-assess:**
   - **Relevance** — relates to active domains?
   - **Quality** — substantial content (≥50 chars)?
   - **Novelty** — run `oks search <keywords>` to check wiki duplicates, and
     `oks recall <keywords>` to catch near-dupes already in `raw/` (same
     source ingested recently). Skip if it is a clear re-ingest.
   - **Human signal** — a raw `flagged: true` (or a positive `note`) is a
     strong push toward A-grade; respect the human's explicit intent.
   - **Grade**: A (→ drafts/), B (→ skip), C (→ skip)

2. **For A-grade items** — Extract concepts, determine type + area,
   write to `drafts/{slug}.md` with source reference.
   - If the raw file carries a human `note`, copy it **verbatim** into the
     draft's `source_note` field. On promote it flows to the wiki page's
     `human_note` (handled automatically by `promote_draft`).

3. **Report** — Summary: X scanned, Y drafted, Z skipped.

## Rules

- Never write directly to `wiki/` — always through `drafts/`.
- Include source reference in every draft.
- Agent is the orchestrator — OKS does NOT wrap tool calls.
- Agent checks tool availability via Bash (`which curl`, etc.),
  NOT via a CLI doctor command.
