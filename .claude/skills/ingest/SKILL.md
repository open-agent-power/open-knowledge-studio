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
| `*.png *.jpg *.jpeg *.webp *.gif *.bmp` | image | vision API via agent (L0) |
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

### Level 1 — OKS Protocol CLIs

Agent calls CLI tools that output standard JSON:
```json
{"markdown": "...", "title": "...", "source": "...", "modality": "...", "metadata": {}}
```

- `oks-video <file>` → JSON with transcript + frame descriptions
- `oks-audio <file>` → JSON with transcript

Agent writes `markdown` field to `raw/{YYYY}/{MM}/{DD}/{source}/{slug}.md`

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

### Maximum Fidelity Principle

- Extract original content directly when possible (curl, pdftotext)
- AI only fills gaps (frame descriptions, audio transcripts)
- Output is layered: `[原始文本]` + `[AI描述]` + `[元数据]`

## Phase 2: Triage — A/B/C Grading

After intake, scan `raw/` for unprocessed files:

1. **For each new file, AI-assess:**
   - **Relevance** — relates to active domains?
   - **Quality** — substantial content (≥50 chars)?
   - **Novelty** — run `oks search <keywords>` to check duplicates
   - **Grade**: A (→ drafts/), B (→ skip), C (→ skip)

2. **For A-grade items** — Extract concepts, determine type + area,
   write to `drafts/{slug}.md` with source reference.

3. **Report** — Summary: X scanned, Y drafted, Z skipped.

## Rules

- Never write directly to `wiki/` — always through `drafts/`.
- Include source reference in every draft.
- Agent is the orchestrator — OKS does NOT wrap tool calls.
- Agent checks tool availability via Bash (`which curl`, etc.),
  NOT via a CLI doctor command.
