# Raw Evidence Sidecar — schema & recall contract

> Schema layer (`_meta/`), per CONSTITUTION P1 (schema versioned here, applied
> on read) and A1 (`_meta/` = schema, not memory). This is the **decoupling
> artifact** that keeps the OKS core generic while multimodal L1 tools produce
> richer `raw/`.

## Why this exists

Multimodal L1 tools (the independent `oks-connector`
package) emit a **Raw Bundle**: a directory holding a primary Markdown file
plus a provenance sidecar. See `docs/raw-multimodal-standard.md` for the full
`raw-multimodal/v0.1` output contract.

The core CLI (`oks`) must **not** hardcode that layout. Per P4/P5 the core does
only filesystem operations and recall scoring; recall over `raw/` is generic
(keyword + freshness, `rglob` any structure). This schema declares the *generic*
shape so recall stays format-agnostic and future bundle changes never ripple
into `cli/`.

## Contract

A `raw/` entry may be a **Bundle directory** under the usual
`raw/{YYYY}/{MM}/{DD}/{source}/` tree:

```
raw/2026/07/17/videos/{slug}/
├── content.md          # primary extracted text (any *.md name)
├── evidence.jsonl      # provenance sidecar (any *.jsonl name)
└── assets/             # optional extracted media (frames, images)
```

- **Primary text** — any `*.md` file. Faithful extraction only (P3): the tool
  converts format, never summarizes/grades/promotes.
- **Evidence sidecar** — any `*.jsonl` file. One JSON object per line. Each line
  SHOULD carry a human-readable `text` field; other keys (`type`, `page_idx`,
  `start`, `bbox`, `confidence`, …) are provenance and are free-form.

## How core recall consumes it (generic, no bundle-awareness)

`recall_episodic()` already indexes both parts through format-agnostic rules —
**no `content.md` / `ocr` special-casing lives in `cli/`**:

| Bundle part | Matched by | Recall type | Relevance |
|-------------|-----------|-------------|-----------|
| primary `*.md` | `rglob("*.md")` | `raw` | freshness |
| `*.jsonl` line | `rglob("*.jsonl")`, per-line JSON match | `trace` | freshness + 0.5 |

Consequently OCR/ASR evidence text is recallable via the generic `trace` path
(verified: an `evidence.jsonl` OCR line surfaces at relevance = freshness + 0.5,
higher than a bespoke gap-filler would rank it). No coupling is required or
desired.

## Rules

- **Do not** add bundle-format branches (`content.md`, `ocr_evidence`, bundle-root
  detection) to `cli/`. If richer evidence recall is ever needed, extend *this*
  schema and key core logic off the declared generic shape (`*.md` primary,
  `*.jsonl` sidecar with `text`), never off a specific filename.
- **Do not** let the core import the L1 adapter. Tools are spawned by the Agent
  via Bash per `settings/handlers.json`; the core only reads the files they wrote.
