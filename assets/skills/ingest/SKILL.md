---
description: Agent-native ingest — Source → Recipe → Capability Status → Provider Cluster → EvidenceFragment → Manifest → oks raw commit → Candidate
---

# /ingest — Agent-Native Evidence Ingestion

Agent is the orchestrator.  OKS provides capability; Agent decides what to do.

## Flow

```
oks ingest prepare <source>  →  SourceEnvelope + Manifest skeleton
→ Judge modality → Read Recipe → Query capability status → Select minimum sufficient provider set
→ Execute provider cluster (one execution → multiple evidence fragments)
→ Fill evidence_records  →  oks raw commit
→ AgentObservation → CandidateDraft → drafts/{slug}.md → Report
```

## Pre-flight: Search before adding

Before running `oks ingest prepare`, recall the topic to avoid a parallel
page on something already known:

```bash
oks recall "<the topic of this source>"
```

Decide from the results:

| Recall result | Action | Candidate frontmatter |
|---------------|--------|------------------------|
| No related wiki page | New page | (leave `relates_to` unset) |
| Existing page, new content extends it | Extend | `relates_to: <slug>, relationship: enriches` |
| Existing page, new content supersedes it | Replace | `relates_to: <slug>, relationship: supersedes` |
| Existing page, new content agrees | Reinforce | `relates_to: <slug>, relationship: confirms` |
| Existing page, new content contradicts | Flag conflict | `relates_to: <slug>, relationship: challenges` |

A4 relationships are a human-review concern, but the Agent is the one who
saw both the new source and the existing page — record the relationship in
the Candidate so `/promote` can apply it. Never write a parallel page on
the same topic: parallel pages dilute recall.

## Step 0: Prepare (use the CLI — do NOT hand-craft protocol JSON)

Run `oks ingest prepare <source>` to create the workspace and generate
the protocol skeleton (source-envelope.json, evidence-manifest.json,
artifacts/).  This command fills all deterministic fields — source_id,
content_hash, schema_version, timestamps, artifact hashes — so the
Agent only needs to supply evidence content.

**For text sources** (text_ready=true): SourceEnvelope, EvidenceManifest,
EvidenceFragment, and artifact are all pre-filled — skip to Step 6.

**For non-text sources** (text_ready=false): The skeleton includes pre-filled
evidence record slots for every required capability from the Recipe.
Each slot has `evidence_id`, `artifact_id`, `kind`, `method`, and `locator`
already filled — the Agent only fills `text`, `confidence`, and
`agent_judgment` after executing providers.  Steps are also pre-filled with
expected capabilities (provider and status left for Agent to fill).

The output also includes `candidate_providers` — a shortlist of 2–4
providers that cover the required capabilities.  The Agent selects from
this shortlist rather than scanning all 17 providers.  Use
`oks capability status --json` only when you need full provider details.

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

Determine the source's modality from its file extension or URL pattern:

- `.md/.txt` → text, `.pdf` → pdf, `.docx/.pptx/.xlsx` → office
- `.png/.jpg` → image, `.mp4/.mkv` → video, `.mp3/.wav` → audio
- URL → web (or video if bilibili/youtube/douyin)

## Step 3: Assess Evidence Demand vs Current Capability

### 3a. Read the Recipe

The Recipe for this modality is in the `recipe` field of the `oks ingest prepare`
output (Step 0).  Read it to understand what evidence is needed.

Do NOT read `recipes/{modality}.md` from disk — the user's knowledge base
does not contain a recipes/ directory.  The Recipe is served through the CLI.

- **required_capabilities**: the primary Evidence acquisition path for this Recipe.
  They are NOT an absolute "this specific provider capability ID must succeed" condition.
  Final completeness is determined by whether the `complete_when` conditions are satisfied
  (see Step 5 for the full coverage check).  A required capability that fails can still
  produce a complete result if a declared fallback capability yields equivalent Evidence.
- **optional_capabilities**: nice-to-have — missing optional capabilities don't block Candidate generation
- **degradation**: priority-ordered fallback chain — when a required capability at a given
  priority level fails, the next priority is attempted.  Fallback capabilities (including
  optional ones at lower priority) can satisfy the same `complete_when` condition.

### 3b. Query Current Capability

Run **one** command to get the complete environmental facts:

```bash
oks capability status --json
```

This returns:
- Every action with its Chinese label and description
- Which providers supply each action
- Each provider's current availability (`ready`, `not_configured`, `unavailable`, `runtime_only`)
- Each provider's execution type, known limits, and platform metadata

You now have everything needed to select providers.  Do NOT also run
`oks capability list` — it only describes install boundaries; `status` is
the single source of truth for what is actually available.

### 3c. Select Minimum Sufficient Provider Set

For each required capability, find available providers from the status output.
Follow the formal **L0→L4 Degradation Ladder** (§Graceful Degradation below):

| Level | Trigger | Action |
|-------|---------|--------|
| **L0 Preferred** | Best capability available | Use it directly |
| **L1 Automatic Fallback** | Best unavailable, alternative exists | Auto-switch, user unaware |
| **L2 Honest Partial** | Only partial evidence obtainable | Continue with what we have, record gaps honestly |
| **L3 Guided Assistance** | Critical evidence missing | Aggregate gaps → one user message → recommend |
| **L4 Cannot Extract** | No reliable path exists | Stop, do not fabricate |

**The goal is the MINIMUM set of providers that covers all required
capabilities — not one provider per capability.**

**Stop escalating after required Evidence is reliably satisfied.**
Do not pursue optional capabilities at higher degradation levels —
optional means optional.

**When multiple providers satisfy the same capability**, `oks ingest prepare`
returns a `candidate_providers` shortlist of 2–4 relevant providers covering
the required capabilities.  The Agent selects from this shortlist based on
availability, maturity, and the provider's declared limits — not a static
weight/cost score.  For environments where privacy matters (sensitive
internal documents), prefer providers that run locally.

A single provider often satisfies multiple demands at once.  For example:
- **Firecrawl** one execution → `web.fetch` + `web.extract` + `metadata.fetch` (3 capabilities, 1 call)
- **Agent Runtime** one observation → `image.observe` + `layout.understand` + `chart.interpret` (3 capabilities, 1 observation)
- **pdf-lite** one execution → `document.text.extract` + `document.structure.extract` + `metadata.fetch` (3 capabilities, 1 call)

## Step 4: Execute Provider Cluster

A **Provider Cluster** is one provider execution that produces multiple
EvidenceFragments — do NOT iterate per capability.

### For each chosen provider:

0. Enforce the SourceEnvelope policy before touching source content:
   - `remote_processing: deny` forbids sending source bytes, rendered pages,
     screenshots, transcripts, or derived content to any third-party endpoint.
   - Do not read API credentials, write ad-hoc HTTP clients, or use an
     unregistered remote Runtime Tool to bypass this policy.
   - If no permitted local or current-runtime path can produce the required
     evidence, stop at L3/L4 and ask for an explicit processing decision.
   - `ask` is not consent. Resolve it with the user before the first remote call.

1. Call the tool (Bash / MCP / API / Agent vision) **once**.
2. **IMMEDIATELY persist the Provider's raw output** to
   `.oks/runs/{run_id}/work/{provider}/output.<ext>`.
   This MUST happen BEFORE any Agent semantic processing — at this point
   the saved output is the Provider's original response, unmodified
   except for security sanitization (step 3).  The persisted raw output
   is immutable evidence of what the Provider actually produced.
   **After writing, verify the file exists and has content (>0 bytes).**
   If the write fails or the file is empty, the Agent MUST NOT proceed
   with this provider's evidence — the raw output is the only proof
   that the Provider actually produced something.  Self-reported "saved"
   is not sufficient.
3. **For external providers: sanitize before saving.**  Run
   `oks security sanitize .oks/runs/{run_id}/work/{provider}/output.json`
   to strip API keys, bearer tokens, session cookies, and internal IPs
   from the raw output before it enters the Run Workspace.
4. Only after the raw output is safely persisted: read it, understand it,
   and construct **one EvidenceFragment per satisfied capability**.
   The text content in each evidence record MUST come from the persisted
   raw output, not from Agent memory or reformulated/reorganized content.
   Get the fragment schema: `oks schema show evidence-fragment`

### Provider-specific evidence construction:

**Firecrawl (one /scrape call → multiple fragments):**
- Fragment 1: `web.fetch` → `kind: "source_capture"`, `method: "http_fetch"`, text is raw response metadata
- Fragment 2: `web.extract` → `kind: "text"`, `method: "html_extract"`, text is extracted markdown
- Fragment 3: `metadata.fetch` → `kind: "metadata"`, `method: "html_metadata"`, text is title/author/date
- `producer.provider: "firecrawl"`, `agent_judgment: "mechanical"`

**Agent Runtime (one multimodal observation → multiple fragments):**
- Fragment 1: `image.observe` → `kind: "observation"`, `method: "agent_multimodal_observation"`
- Fragment 2: `layout.understand` → `kind: "observation"`, `method: "agent_layout_analysis"`
- Fragment 3: `chart.interpret` → `kind: "observation"`, `method: "agent_chart_reading"`
- `producer.provider: "agent-runtime"`, `agent_judgment: "agent_observed"`
- **IMPORTANT:** Agent observation is valid evidence but MUST be labeled as such.  Never present agent-observed content as raw source text.

**pdf-lite (one pymupdf4llm call → multiple fragments):**
- Run `oks capability guide pdf-lite` for the canonical execution guide (3-step workflow).
  Do NOT read `providers/pdf-lite/SKILL.md` from disk — the user's knowledge base
  does not contain a providers/ directory.  Provider guides are served through the CLI.
- Fragment per page OR one fragment covering all pages with `locator: {kind: "page", page: N}`
- `producer.provider: "pdf-lite"`, `agent_judgment: "mechanical"`

### Provenance Integrity: mechanical vs agent_observed

Every evidence record carries two provenance signals at different levels:

- **Fragment-level `producer`**: who produced the CONTENT in this fragment
- **Record-level `agent_judgment`**: whether the text is a deterministic
  transform of Provider output (`mechanical`) or Agent interpretation
  (`agent_observed`)

**`mechanical`** is ONLY for deterministic, non-semantic transforms of
Provider output:

| Allowed — keeps `mechanical` | Prohibited — forces `agent_observed` |
|---|---|
| Security sanitization (API key redaction) | Summarization |
| Encoding normalization (latin1 → utf-8) | Reorganization / reordering |
| Format extraction (JSON field → text) | Deletion of semantic content |
| Newline normalization | Translation |
| | Adding explanation, annotation, commentary |
| | Adding headers, questions, "Key Insights" |
| | Cross-paragraph merging or splitting |
| | Any operation that changes meaning or structure |

**When you perform ANY prohibited operation** on Provider output:

1. Create a **separate** evidence fragment with:
   - `producer.provider: "agent-runtime"`
   - `agent_judgment: "agent_observed"`
   - `method` describing the operation (e.g. `agent_reorganization`,
     `agent_summary`, `agent_annotated_extraction`)
   - `artifact_id` referencing the SAME Provider raw output artifact
     that was persisted in step 2
2. Keep the original Provider fragment **intact** — do not replace or
   delete it.  The original fragment retains its original
   `producer.provider` and `agent_judgment: "mechanical"`.
3. The derivation chain is traceable through `artifact_id`:
   - Provider raw output → `work/<provider>/output.<ext>` (artifact)
   - Provider mechanical fragment → references same `artifact_id`
   - Agent rewrite fragment → references same `artifact_id`, different
     `method` and `agent_judgment`

This preserves the audit trail: anyone can compare Agent-processed
content against the persisted Provider raw output in `work/<provider>/`.

## Step 5: Coverage Check & Merge into EvidenceManifest

After executing all providers, compare obtained evidence against the Recipe's demands:

### Required capabilities check:

For each required capability, determine its outcome against the Recipe's degradation chain:

1. **Original capability succeeds** → satisfied. Record the capability and provider.
2. **Original capability fails, but a declared fallback (from the degradation list)
   produces equivalent Evidence and satisfies the relevant `complete_when` condition**
   → satisfied by fallback.  Record both the attempted capability (status: `failed`)
   and the fallback that succeeded (status: `success`).  Do NOT mark as missing.
3. **Neither the original capability nor any degradation fallback produces
   valid Evidence for the related `complete_when`** → missing required evidence.

Final completeness is determined by `complete_when` satisfaction, not by counting
how many required capability IDs succeeded.  A recipe with one failed required
capability that was fully compensated by fallback is still `complete`.

Example: Video Recipe requires `subtitle.fetch`.  If subtitle extraction fails but
`speech.transcribe` (degradation priority 4, optional) produces a valid transcript,
`complete_when: subtitles_or_transcript_available` is satisfied — the ingest is
`complete`, not `partial`.

### Optional capabilities check:
- Satisfied → bonus, record in manifest
- Missing → note in warnings, do NOT block — optional means optional

### complete_when coverage check:

The `complete_when` conditions are the authoritative completeness standard —
they override any mechanical capability-ID success/failure tally.

A `complete_when` condition can be satisfied by evidence from **any**
capability — required OR optional, primary path OR degradation fallback.

- If `subtitle.fetch` (required) fails but `speech.transcribe` (optional, ASR)
  produces a valid transcript → `subtitles_or_transcript_available` is SATISFIED.
  Do NOT mark the ingest as partial for missing subtitles.

- If one capability satisfies multiple `complete_when` conditions → each
  condition is independently satisfied.

- A `complete_when` condition is only unmet when NO capability (required or
  optional) produced evidence that fulfills it.

**Never mark an ingest as partial solely because a required capability failed,**
if a different capability (including optional fallback) satisfied the same
`complete_when` condition.

Collect all fragments and create the EvidenceManifest (`oks schema show evidence-manifest`).
Record every step in `manifest.steps[]` including provider name, capabilities satisfied,
status, and reason for any fallback.

**If ALL fragments failed — do NOT submit; report failure to user with actionable guidance.**

### Provenance completeness prerequisites

Before declaring `status: "complete"` in the EvidenceManifest, ALL of
the following MUST be true:

1. **Required Evidence satisfied** — all `complete_when` conditions met
   (see complete_when coverage check below).
2. **Raw Provider output persisted** — every Provider execution that
   contributed evidence has its sanitized raw output saved in
   `.oks/runs/{run_id}/work/{provider}/`.
3. **Provenance legal** — every evidence record's `agent_judgment`
   matches the actual origin of its text content:
   - `mechanical` → text IS a deterministic transform of Provider output
     (sanitization, encoding, format extraction, newline normalization)
   - `agent_observed` → text contains Agent interpretation, and the
     fragment's `producer` is `"agent-runtime"` (NOT the original
     Provider)
   - NO record marked `mechanical` contains Agent-written, reorganized,
     summarized, annotated, or translated content
   - NO record whose fragment `producer` is a Provider other than
     `"agent-runtime"` contains content the Agent rewrote
4. **Raw output verified** — every `work/<provider>/output.<ext>` file
   claimed in the provenance chain actually exists on disk and has
   content (>0 bytes).  Agent MUST check file existence and size before
   declaring complete — self-reported "I saved it" is NOT proof.  If
   the file is missing or empty, provenance is illegal and `status`
   MUST be `"partial"` regardless of `complete_when` satisfaction.

Provenance legality (prerequisites 3 and 4) is a HARD prerequisite — if
provenance is illegal or unverifiable, the ingest is incomplete regardless
of `complete_when` satisfaction.  Fail-closed: when in doubt, `status: "partial"`.

### Missing capability → Guided UX (NOT silent partial)

When a required capability cannot be satisfied:

1. Complete ALL automatic fallbacks first — exhaust L1 before reaching L3
2. Query `oks capability status --json` to see if any unconfigured provider could help
3. If an auto-fallback is possible → execute it directly, don't ask
4. **Aggregate ALL remaining gaps** into a single user-facing message — never report gaps one at a time
5. If the only path forward needs user action → explain in user language with a recommendation

**Gap aggregation format:**
- 已获得什么
- 仍缺什么
- 影响什么
- 当前是否仍值得继续
- 推荐用户做什么

Example of aggregated gap report:

```
这份 PDF 的正文已完整提取（12 页，15,000 字），但其中 3 页是扫描图片，
目前缺少文字内容。

我可以：
1. 安装本地 OCR 后重新提取这 3 页 — 首次安装需要下载约 200MB
2. 使用远程 OCR 处理 — 需要配置 Firecrawl
3. 先生成待审核知识，标记"3 页图片内容缺失"

推荐选项 3：正文已经足够覆盖核心内容，图片缺失不影响主要知识的完整性。
```

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

## Step 7: Grade → AgentObservation → Candidate

1. Read the Raw Bundle's `evidence.jsonl`
2. Create AgentObservation — each claim references `artifact_id + locator`
   from evidence.  `supported` claims have direct evidence; `uncertain` are
   Agent inference needing human verification.
3. **Grade the material A / B / C.** This is your judgment, not the CLI's —
   `oks` never judges content quality (P4):

   | Grade | Meaning | Action |
   |-------|---------|--------|
   | **A** | Carries a reusable judgment or conclusion, and the evidence supports it | Write a Candidate |
   | **B** | Has value but is incomplete — thin evidence, or too situation-specific to reuse | No Candidate. Record why in `result.json`; the Raw Bundle stays for later |
   | **C** | Noise, a duplicate of existing knowledge, or a bare list of facts carrying no judgment | No Candidate. Record the reason |

   Grading decides **whether something is worth drafting** — nothing more. It
   never promotes: every Candidate still passes human review via `/promote`
   (A3). Never delete a Raw Bundle because you graded it C — the grade is your
   opinion, the evidence is the record.

4. For grade A, write the Candidate to `drafts/{slug}.md` with valid YAML
   frontmatter:
   ```yaml
   title: "Human-readable title"
   draft_type: concept       # concept | strategy | anti-pattern
   draft_area: computing     # target knowledge domain
   importance: 0.7
   confidence: 0.5
   created: "YYYY-MM-DD"
   tags: "comma, separated"
   status: pending
   source_type: agent-ingest
   intake_grade: A
   relates_to: ""            # slug of existing wiki page this relates to (Pre-flight)
   relationship: ""         # enriches | supersedes | confirms | challenges (A4); empty for new
   ```

   **The field names must be `draft_type` and `draft_area`.** `oks drafts
   promote` reads only those; writing `type:` / `area:` falls back to
   `concept` / `computing`, so a strategy about science lands silently in
   `wiki/computing/concepts/` with no error.

   **Important:** Candidate is a draft Markdown document written to `drafts/{slug}.md`.
   Candidate is NOT an OKS protocol schema object.
   Do NOT call `oks schema show candidate` — it does not exist as a schema.
   Use `oks drafts list` to see existing candidates.

## Step 8: Write result.json

MUST write `.oks/runs/{run_id}/result.json` before reporting to user.

```json
{
  "status": "complete|partial",
  "source": "<source uri>",
  "providers_used": ["pdf-lite", "agent-runtime"],
  "capabilities_used": ["document.text.extract", "image.observe"],
  "evidence_summary": {
    "page_count": 3,
    "text_chars": 696,
    "bbox_regions": 43
  },
  "missing": [],
  "reasons": [],
  "impact": [],
  "remote_processing_used": false,
  "cost": 0,
  "latency_ms": 6200,
  "bundle_id": "bundle:2789f4ff",
  "intake_grade": "A",
  "intake_grade_reason": "有可复用的结论，且每条断言都能追到证据",
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

### intake_grade fields

- **intake_grade** (required): `A` | `B` | `C` — your Step 7 judgment
- **intake_grade_reason** (required): one sentence on why. For `B` / `C` this is
  the only record of the decision; without it the next run re-derives it blind
- **candidate_path**: the draft path for `A`, and **`null` for `B` / `C`** —
  naming a file that was never written makes the report untrue

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

## Step 9: Report to User (Guided UX)

MUST output the unified result card as the final user-facing message.

**All user-facing text MUST be in Chinese natural language.**
**NEVER expose provider IDs, capability IDs, or schema names to the user.**
Translate everything into plain-language descriptions.

### Complete result:

```
✅ 摄入完成

来源：{source_uri}

已获得：
- 正文内容（12 页，约 15,000 字）
- 文档结构（标题层级和段落划分）
- 页面元数据（标题、作者）

缺失：无

待审核知识：{candidate_path}

下一步：
使用 /promote 审核、编辑或拒绝该 Candidate。
```

### Partial result (with guided recommendation):

```
⚠️ 部分完成

来源：{source_uri}

已获得：
- 正文内容（12 页，约 15,000 字）— PDF 文本层提取
- 文档结构 — 标题和段落划分

缺失：
- 3 页扫描图片中的文字内容 — 这些页面没有文本层

影响：这 3 页是附录中的扫描表格，不影响文档主体论证的完整性。

推荐：先生成待审核知识并标注"3 页图片缺失"。正文证据已足够覆盖核心内容。
如果后续需要完整的表格数据，可以再安装 OCR 补充处理。

待审核知识：{candidate_path}

下一步：
使用 /promote 审核 Candidate。你可以接受、修改或要求补充缺失的图片内容。
```

### Failed result (all providers exhausted):

```
❌ 无法完成

来源：{source_uri}

尝试了以下方式：
- 直接获取网页 — 失败（反爬保护）
- 远程抓取 — 失败（需要配置访问密钥）

当前无法自动获取此来源。建议：
1. 手动复制网页正文，粘贴到 Markdown 文件后重新摄入
2. 配置 Firecrawl API 密钥以启用远程抓取能力

如果你能提供页面正文，我可以立即继续处理。
```

### Card principles:

- **摄入完成**: `complete` (all required evidence obtained), `partial` (some evidence missing, usable), `failed` (no usable evidence)
- **已获得**: bullet list in plain Chinese — describe WHAT was obtained, not HOW (say "正文内容" not "web.extract via Firecrawl")
- **缺失**: bullet list with impact explanation — always state what's affected
- **推荐**: always provide a recommended next step, don't just list options
- **下一步**: always points to `/promote` for human review
- **Provider chain**: only shown internally (result.json), not in user-facing card

## Guided UX Principles

These principles MUST be followed in every ingest session:

### 1. Ask users for judgment, not implementation

| Wrong | Right |
|-------|-------|
| "AgentKey 未配置。是否切换 MediaCrawler Provider？" | "这个页面需要登录态才能完整读取。我可以：1. 使用浏览器登录状态继续 2. 只收录公开内容。推荐 1。" |
| "RapidOCR capability unavailable." | "这张图片是文字截图。我可以直接使用当前视觉能力识别，也可以安装本地 OCR 后再处理。这次只有一张图片，推荐直接识别。" |
| "请运行 oks capability status。" | "让我确认一下当前可以使用的处理能力……" (Agent runs it internally) |

### 2. Proactive gap discovery

When capability is missing:
1. Query `oks capability status --json` to check for remediable capabilities
2. If auto-fallback possible → do it immediately, don't ask
3. If user action needed → explain impact → give actionable options → recommend one

Never: `capability missing → status: partial → done`

### 3. Plain Chinese, no internal IDs

User-facing text requirements:
- ✓ "正文内容" — ✗ "web.extract 能力"
- ✓ "远程网页抓取" — ✗ "Firecrawl Provider"
- ✓ "可以处理" — ✗ "status: ready"

Internal IDs (provider names, capability IDs, schema names) exist ONLY in:
- `result.json` (Step 8)
- `manifest.steps[]` (Step 5)
- Agent's internal reasoning (never shown to user)

### 4. Recommendation over menu

When presenting options, always recommend one. Don't dump a list of choices.

### 5. Three levels of detail

- **Level 0 (default)**: Task → Progress → Result → Missing → Choices → Review
- **Level 1 (user asks "why this way?")**: "因为页面是动态渲染的，直接获取拿不到正文，所以使用了远程抓取。"
- **Level 2 (user runs `oks capability status --json`)**: Full technical matrix — provider IDs, availability, checks

## Graceful Degradation

Capability Registry and external Providers are **enhancements**, never
single-point-of-failure dependencies on OKS core availability.

### Degradation Ladder (L0→L4)

| Level | Name | Trigger | Agent Action | User Perception |
|-------|------|---------|-------------|-----------------|
| **L0** | Preferred | Best capability available | Use it directly, complete processing | None (transparent) |
| **L1** | Automatic Fallback | Best unavailable, alternative exists | Auto-switch to alternative, continue silently | None (transparent) — required Evidence is satisfied |
| **L2** | Honest Partial | Only partial reliable Evidence obtainable | Process what we have, record gaps + impact honestly. Continue to Candidate with partial marker. | Sees partial result with honest gap description |
| **L3** | Guided Assistance | Critical Evidence cannot be obtained automatically | Aggregate ALL gaps → single user message → explain impact → give actionable options → recommend one | Sees aggregated gap report with concrete choices and a recommendation |
| **L4** | Cannot Reliably Extract | No reliable path exists for this Evidence | Stop generating this Evidence. Do not speculate, guess, or fabricate. Record `failed` in manifest. | Sees failure + alternative suggestions (e.g., paste content manually) |

### Core Rules

1. **Missing best capability → first seek alternative paths from what IS available.**
   Never skip straight to L3 because the preferred provider is absent.

2. **Alternative path satisfies required Evidence → auto-continue (L1), don't ask user.**
   User doesn't need to know we used trafilatura instead of Firecrawl if both produce valid text.

3. **Alternative path satisfies only partial Evidence → keep what's reliable, enter L2.**
   Preserve all obtained Evidence with honest provenance. Record what's missing and why.

4. **Only interrupt user when missing content genuinely affects their goal (L3).**
   Don't ask about missing optional image_context on a text-centric page.

5. **Missing optional capability → NEVER block the task.**
   Optional means optional. Record the gap, continue.

6. **Provider unavailable → NEVER fabricate Evidence.**
   `producer: agent-runtime, method: agent_observed` is valid (L2).
   Making up source text is never valid (L4 violation).

7. **All degraded results → preserve provenance, state actual Evidence source.**
   Every fragment records exactly which provider, method, and degradation level produced it.

8. **Multiple capability gaps → aggregate → ONE user message.**
   Complete all auto-fallbacks first. Then batch every remaining gap into a single L3 report.
   Never: "Missing A. (user replies) Also missing B. (user replies) Also missing C."

9. **Agent MUST recommend — never delegate implementation choices to user.**
   "推荐选项 3：正文已经足够" — not "请选择一个选项。"

10. **Required Evidence reliably satisfied → STOP escalating.**
    Do not pursue optional capabilities at higher degradation levels.
    Do not suggest capability upgrades when the core job is done.

### Text-Only Orchestrator

The Orchestrator (Agent model) may be a text-only model without native
multimodal perception (image, audio, video understanding).

When the current model lacks a modality:

1. **Use registered Providers** for that modality — pdf-lite, rapidocr,
   Firecrawl, ffmpeg, yt-dlp, local-asr, etc. This is the normal path.
2. **If a Provider exists** for the needed modality → execute it (L0/L1).
3. **If no Provider exists** for the needed modality:
   - required Evidence: enter L3 (Guided Assistance) or L4 (Cannot Extract)
   - optional Evidence: enter L2 (Honest Partial), note the gap
4. **NEVER hallucinate multimodal content.** Do not describe an image you
   cannot see. Do not transcribe audio you cannot hear. Do not invent
   source text you cannot read.

## Strategy-Aware Ingestion (Guided Decision UX v0.1)

When a Provider is needed but not available, the Agent MUST follow the
strategy configured by the user.  Read the current strategy:

```bash
oks config show   # check strategy field
```

### Strategy values

| Strategy | Behavior |
|----------|----------|
| `lightweight` (default when unset) | Prefer existing capabilities. Don't install large components. Ask only when genuinely blocked. |
| `quality` | Prefer best available extraction quality. Auto-use configured remote providers. Ask on install/fee/privacy impact. |
| `privacy` | Prefer local processing. Avoid uploading content. Can accept larger local deps but explain before installing. |
| `ask_each_time` | No fixed preference. Compare options with full impact and let user decide each time. |

### When strategy is unset

On first encounter of a capability gap that requires user decision:
1. Explain briefly what's needed and why
2. Present the four strategies in plain language:
   - ① 轻量优先（推荐）：尽量用已有能力，不主动安装大型组件
   - ② 效果优先：优先保证提取完整度
   - ③ 本地隐私优先：优先本地处理，尽量避免上传
   - ④ 每次由我决定：没有固定倾向，每次比较方案
3. Ask user to pick one
4. Save: `oks config set strategy <value>`
5. Apply the chosen strategy to the current decision and all future ones

### User-impact data

When a Provider has `user_impact` in its definition, use it to inform
the user.  `oks capability status --json` exposes this data.  Key fields:

- `install` — what needs to be installed/configured
- `disk` — estimated disk usage
- `runtime` — runtime requirements (CPU/GPU, speed)
- `execution` — `local` or `remote`
- `privacy` — whether content is uploaded
- `cost` — monetary cost
- `skip_effect` — what happens if not enabled

**Never invent numbers.** If `user_impact` says "未知" or a descriptive range,
report it honestly. Don't guess a specific size.

### Aggregated decision

When the same task needs multiple missing capabilities:
1. Judge which are truly necessary for this task
2. Skip optional ones that aren't needed
3. Present remaining needs as ONE aggregated message:
   - What's needed and why
   - Total resource impact
   - Recommendation
   - One decision point, not N sequential questions

### Provider selection transparency

- Agent selects Providers — user does NOT choose between RapidOCR/MinerU/Firecrawl
- Agent explains its recommendation in plain language
- User only decides: enable recommended capability / accept partial / use alternative

## Runtime Tool vs Registered Provider

Two categories of evidence sources exist.  The distinction matters for
honest provenance — evidence MUST record which category produced it.

### Registered Provider

Declared in a `provider.yaml` file inside the OKS package.  Listed in
`oks capability status`.  Has declared capabilities, known limits, costs,
and maturity levels.  Examples: firecrawl, pdf-lite, rapidocr, agentkey.

When using a Registered Provider:
- `producer.provider`: the provider ID from `provider.yaml`
- `producer.tool`: same as provider ID
- Evidence inherits the provider's declared `agent_judgment` default

### Runtime Tool

Ad-hoc tool available in the current Agent runtime.  NOT declared in any
`provider.yaml`.  No capability mapping, no known limits, no cost
declaration.  Examples:
- `curl` / `wget` — bash HTTP fetch
- Playwright MCP (`browser_snapshot`, `browser_take_screenshot`)
- Claude Code built-in browser / file reader
- Any Bash command that produces evidence content

When using a Runtime Tool:
- `producer.provider`: `"runtime-tool"` (NOT a registered provider ID)
- `producer.tool`: the actual tool name, e.g. `"curl"`, `"playwright"`, `"claude_browser"`
- `method`: descriptive, e.g. `"curl_fetch"`, `"playwright_snapshot"`
- `agent_judgment`: `"mechanical"` if output is used verbatim; `"agent_observed"` if Agent transforms it

### Impersonation rules

- `curl` fetching a URL is a Runtime Tool — it MUST NOT claim `producer.provider: "http-fetch"` or `"firecrawl"`
- Playwright MCP is a Runtime Tool — it MUST NOT claim `producer.provider: "browser"`
- Claude's native file reading is a Runtime Tool — it MUST NOT claim `producer.provider: "agent.vision"`
- Runtime Tools CAN be used for evidence acquisition — just label them honestly

## Constraints

- NEVER write to wiki/ directly — only drafts/
- NEVER upgrade partial to complete
- NEVER present agent inference as source text
- NEVER expose API keys, cookies, or tokens
- NEVER bypass `remote_processing` with ad-hoc scripts, direct HTTP calls, or credentials from the environment
- NEVER expose provider IDs, capability IDs, or schema names in user-facing messages
- ALWAYS record failure reasons honestly
- ALWAYS preserve original tool output unmodified
- ALWAYS explain missing evidence in terms of user impact, not technical failure
- ALWAYS recommend a default action when presenting choices to the user
- MUST write result.json to `.oks/runs/{run_id}/result.json` before reporting to user
- MUST include `provider_selection` in result.json with chosen, candidates_considered, and rationale
- MUST include `degradation_path` in provider_selection when fallback was activated
- MUST output the unified result card as the final user-facing message (Step 9 format)
- MUST record every attempted provider in degradation_path even if it failed
- MUST use Chinese natural language for all user-facing text
- MUST run `oks capability status --json` (not catalog + doctor separately) for capability decisions
- MUST treat one provider execution as a cluster that can satisfy multiple demands simultaneously
- MUST follow L0→L1→L2→L3→L4 degradation order — never skip levels silently
- MUST attempt auto-fallback (L1) before asking user (L3)
- MUST NOT block on missing optional capability — optional means optional
- MUST NOT fabricate evidence when no Provider is available (L4)
- MUST aggregate all gaps into a single user-facing message (L3)
- MUST preserve provenance for all degraded evidence — every fragment records true source
- MUST stop capability escalation after required Evidence is reliably satisfied
- MUST provide a recommendation, not delegate implementation choices to user
- MUST explain each gap in terms of user impact, not technical failure
- MUST label all Agent-observed evidence as agent_observed, never as source text
- MUST persist sanitized Provider raw output to work/<provider>/ BEFORE any Agent semantic processing — raw output is immutable evidence
- MUST construct primary evidence text from persisted Provider raw output, not from Agent memory or reformulated content
- MUST NOT label Agent-rewritten, reorganized, summarized, or annotated content as mechanical or with the original Provider as producer
- MUST create a separate agent-runtime fragment for any evidence record derived from Agent transformation of Provider output
- MUST verify provenance legality before declaring ingest status complete — illegal provenance blocks complete regardless of complete_when satisfaction
- MUST verify raw output file existence and size before declaring complete — self-reported save is not proof.  Fail-closed: missing or empty work/<provider>/output.<ext> → status MUST be "partial".
- MUST distinguish Runtime Tool from Registered Provider in evidence provenance
- MUST NOT label curl/bash/playwright/claude-native output with a Registered Provider's producer ID
- MUST use producer.provider: "runtime-tool" with descriptive tool name for ad-hoc tool output
