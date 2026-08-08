---
description: Agent-native ingest — Source → Provider → EvidenceFragment → Manifest → oks raw commit → Candidate
---

# /ingest — Agent-Native Evidence Ingestion

Agent is the orchestrator.  OKS provides capability; Agent decides what to do.

## Flow

```
oks ingest prepare <source>  →  SourceEnvelope + Manifest skeleton
→ Judge modality → Read Recipe → Select Providers → Execute
→ Fill evidence_records  →  oks raw commit
→ AgentObservation → CandidateDraft → drafts/{slug}.md → Report
```

## Step 0: Prepare (use the CLI — do NOT hand-craft protocol JSON)

Run `oks ingest prepare <source>` to create the workspace and generate
the protocol skeleton (source-envelope.json, evidence-manifest.json,
artifacts/).  This command fills all deterministic fields — source_id,
content_hash, schema_version, timestamps, artifact hashes — so the
Agent only needs to supply evidence content.  For text sources the
skeleton includes pre-filled evidence fragments.

DO NOT manually construct SourceEnvelope, EvidenceManifest, or
EvidenceFragment JSON.  Use `oks schema show <name>` to inspect
schema requirements when filling evidence records.

## Step 1: Check text_ready

`oks ingest prepare` outputs a `text_ready` field in its JSON response.

**IF `text_ready` is `true`:**
- The source is a local Markdown (`.md`) or plain text (`.txt`) file.
- SourceEnvelope, EvidenceManifest, EvidenceFragment, and artifact are all pre-filled.
- All evidence is mechanically complete — no Provider execution is needed.
- **Skip Steps 2-5.** Go directly to Step 6 (`oks raw-commit`).
- Then proceed to Step 7 (Candidate), Step 8 (result.json), and Step 9 (Report).
- In result.json, set `providers_used: ["text-read"]` and
  `provider_selection.chosen: "text-read"`.

**IF `text_ready` is `false`:**
- Continue to Step 2 (Judge Modality) for full Provider orchestration.

## Step 2: Judge Modality

Run `oks capability catalog --json` to see available capabilities.
- `.md/.txt` -> text, `.pdf` -> pdf, `.docx/.pptx/.xlsx` -> office
- `.png/.jpg` -> image, `.mp4/.mkv` -> video, `.mp3/.wav` -> audio
- URL -> web (or video if bilibili/youtube/douyin)

## Step 3: Select Providers

Run `oks capability catalog --json`.  For the detected modality, find
providers whose `provides:` includes the relevant capability.
Prefer lowest-cost, local, stable providers first.
Recipe (`recipes/{modality}.md` in installed package) says WHAT is needed;
the catalog says WHO provides each capability.

## Step 4: Execute Providers

For each chosen provider:
1. Call the tool (Bash / MCP / API / Agent vision)
2. Save raw output to `.oks/runs/{run_id}/work/{provider}/`
3. **For external providers: sanitize before saving.**  Run `oks security sanitize .oks/runs/{run_id}/work/{provider}/output.json` to strip API keys, bearer tokens, session cookies, and internal IPs from the raw output before it enters the Raw Bundle.
4. Construct EvidenceFragment.  Get the fragment schema:
   `oks schema show evidence-fragment`

Agent's own multimodal observation is also a fragment
(`producer: agent-runtime`, `agent_judgment: agent_observed`).

## Step 5: Merge into EvidenceManifest

Collect all fragments.  Create EvidenceManifest — get the manifest schema:
`oks schema show evidence-manifest`
Judge overall status:
- `complete` — all required evidence obtained
- `partial` — some missing, must declare `failure_disposition` and `warnings`
- If ALL fragments failed — do NOT submit; report failure to user

Record every step in `manifest.steps[]` including provider name,
capability, status, and reason for any fallback.

## Step 6: oks raw commit

Create the manifest directory:
```
.oks/runs/{run_id}/manifest/
  source-envelope.json
  evidence-manifest.json
  fragments/          (all EvidenceFragment snapshots)
  artifacts/          (all evidence files)
```

Run: `oks raw-commit .oks/runs/{run_id}/manifest/ --output raw/{date}/{source}/{slug}/`

On success: bundle_id returned.  On rejection: read error_code, do NOT retry blindly.

## Step 7: AgentObservation -> Candidate

1. Read the Raw Bundle's `evidence.jsonl`
2. Create AgentObservation — each claim references `artifact_id + locator`
   from evidence.  `supported` claims have direct evidence; `uncertain` are
   Agent inference needing human verification.
3. Write Candidate to `drafts/{slug}.md` with valid YAML frontmatter:
   ```yaml
   title: "Human-readable title"
   type: concept
   area: computing
   importance: 0.7
   confidence: 0.5
   created: "YYYY-MM-DD"
   tags: "comma, separated"
   status: provisional
   source_type: agent-ingest
   ```

## Step 8: Write result.json

MUST write `.oks/runs/{run_id}/result.json` before reporting to user.

```json
{
  "status": "complete|partial",
  "source": "<source uri>",
  "providers_used": ["pdf-lite", "rapidocr"],
  "capabilities_used": ["document.text.extract", "image.ocr"],
  "evidence_summary": {
    "page_count": 3,
    "text_chars": 696,
    "bbox_regions": 43
  },
  "missing": [],
  "reasons": [],
  "impact": [],
  "remote_processing": false,
  "cost": 0,
  "latency_ms": 6200,
  "bundle_id": "bundle:2789f4ff",
  "candidate_path": "drafts/controlled-chinese-scan.md",
  "review_status": "pending",
  "provider_selection": {
    "chosen": "pdf-lite",
    "candidates_considered": ["pdf-lite", "rapidocr", "agent-runtime"],
    "rationale": "pdf-lite selected as primary text extraction; rapidocr for OCR supplement; agent-runtime as fallback",
    "fallback_activated": false,
    "degradation_path": []
  }
}
```

### provider_selection fields

- **chosen** (required): the provider ultimately used
- **candidates_considered** (required): all providers evaluated, in preference order
- **rationale** (required): WHY the chosen provider was selected over alternatives
- **fallback_activated** (required): true if the first-choice provider failed
- **degradation_path** (required when fallback activated): ordered list of `{provider, status, reason}` for every attempt

### Degradation path status values

- `success` — provider succeeded
- `failed` — provider returned no useful output
- `blocked` — anti-bot, paywall, or access restriction
- `unavailable` — provider not configured or not installed
- `skipped` — provider was considered but not attempted (cost, maturity, etc.)

## Step 9: Report to User

MUST output the unified result card as the final user-facing message.

```
摄入完成：{complete|partial|failed}

来源：{source_uri}
使用路径：{provider_chain}

已获得：
- {item}
- {item}

缺失：
- {item} — {原因}

Raw Bundle：{bundle_id}
Candidate：{candidate_path}

下一步：
使用 /promote 审核、编辑或拒绝该 Candidate。
```

### Card field descriptions

- **摄入完成**: `complete` (all evidence obtained), `partial` (some evidence missing, usable), `failed` (no usable evidence)
- **使用路径**: `provider1 → provider2` for degradation; single provider name for direct path
- **已获得**: bullet list of acquired evidence items in plain language
- **缺失**: bullet list of missing items with reasons — MUST be honest, never claim completeness when partial
- **下一步**: always points to `/promote` for human review

### Provider chain format

```
firecrawl                          (single provider, no fallback)
firecrawl → trafilatura            (first failed, second succeeded)
firecrawl → trafilatura → 人工     (all automated failed, human supply)
```

## Constraints

- NEVER write to wiki/ directly — only drafts/
- NEVER upgrade partial to complete
- NEVER present agent inference as source text
- NEVER expose API keys, cookies, or tokens
- ALWAYS record failure reasons honestly
- ALWAYS preserve original tool output unmodified
- MUST write result.json to `.oks/runs/{run_id}/result.json` before reporting to user
- MUST include `provider_selection` in result.json with chosen, candidates_considered, and rationale
- MUST include `degradation_path` in provider_selection when fallback was activated
- MUST output the unified result card as the final user-facing message (Step 9 format)
- MUST record every attempted provider in degradation_path even if it failed
