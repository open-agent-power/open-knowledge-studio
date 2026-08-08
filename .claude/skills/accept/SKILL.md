---
name: accept
description: Run evidence-first, isolated acceptance of Open Knowledge Studio capabilities. Use for clean-install, document, PDF, formula, video watch, or Feishu end-to-end validation; preserve honest reports and remove only per-run environments.
---

# /accept — OKS Modular Acceptance

Validate feasibility and component boundaries before proposing product changes.
Never modify an existing knowledge base, its scheduler, or OpenClaw.

## Run a non-Feishu capability

Run the helper on Linux/macOS from a controlled acceptance root. Supply the exact
wheel or Git package reference being tested; do not silently test a different
installed version.

```bash
python .claude/skills/accept/scripts/accept.py document \
  --root /opt/oks-acceptance \
  --package-spec /path/to/open_knowledge_studio-*.whl
```

When a server cannot fetch the fixed public fixture, copy an approved local
sample into the isolated server area and provide it explicitly. This records a
`local_fixture` source kind and SHA-256; it does not turn a network failure
into a product pass.

```bash
python .claude/skills/accept/scripts/accept.py all ... \
  --fixture document=/opt/oks-acceptance/fixtures/sample.pptx \
  --fixture pdf=/opt/oks-acceptance/fixtures/digital.pdf \
  --fixture formula=/opt/oks-acceptance/fixtures/scanned-formula.pdf \
  --fixture watch=/opt/oks-acceptance/fixtures/short-video.mp4
```

Supported capabilities are `document`, `pdf`, `formula`, `watch`, `feishu`,
and `all`. `all` is strictly serial: document → pdf → formula → watch →
Feishu preflight. The final Feishu E2E remains `awaiting_human` until its
dedicated Base and reviewer approval are supplied.

The helper creates one isolated pipx environment and one empty KB per ingest
capability. Formula acceptance verifies capability installation and paddleocr
import only — it is a secondary PDF sub-capability with no standalone ingest
route. Feishu preflight creates no cloud data.
It verifies install, `oks`, capability installation, Raw Bundle
artifacts, Candidate promotion, search, recall, and lint. It writes
`report.json` and `report.md`, then removes only that run's pipx and KB unless
`--keep-environment` is supplied. `all` additionally writes `matrix.json` and
`matrix.md` with install isolation, execution, resource cost, cleanup, and
observed blockers for every component.

## Interpret results honestly

- `passed`: every asserted local contract completed.
- `product_failure`: a local command, artifact, or lifecycle assertion failed.
- `environment_limited`: DNS, download, rate-limit, platform anti-bot, timeout,
  or unavailable external model prevented completion.
- `awaiting_human`: a required review or credential-gated step remains.

The public fixture URLs live in the helper. Reports record final source URLs,
SHA-256 values, command exit codes, elapsed time, and cleanup outcome. They
must never include environment-variable values, tokens, passwords, or private
keys.

## Run Feishu E2E

Feishu E2E creates a **new dedicated Base** and writes real test records. Before
running it, obtain explicit authorization for that creation and export only
runtime credentials:

```bash
export OKS_FEISHU_BASE_TOKEN='...'
export OKS_FEISHU_TABLE_ID='...'
```

Use a new Base created by `oks feishu setup`, submit the public text fixture,
run one bounded worker pass, generate a Candidate from the Raw Bundle, and use
bounded `oks feishu listen` while the designated reviewer sends an approval.
Verify promotion and recall. Record only redacted identifiers. Do not delete the
new Base automatically: report its identifier and wait for human confirmation.

## After every run

Read the report before changing product code. Convert only observed
`product_failure` entries into a separate proposal containing the command,
artifact path, root cause, smallest fix, and regression test.
