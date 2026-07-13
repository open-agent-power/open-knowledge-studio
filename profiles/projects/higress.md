---
name: project-higress
description: 'Higress — Go/Envoy AI gateway. Competition project (¥50000).'
title: Higress Project Profile
type: profile
status: active
tags: [project, competition, go, java]
---

# Higress

## Repo Info

| Field | Value |
|-------|-------|
| GitHub | `alibaba/higress` |
| Language | Go (gateway), Java (plugins), YAML (config) |
| Framework | Envoy-based AI gateway |
| Prize | ¥50000 |
| Competition Period | 2026-06-15 to 2026-09-20 |

## Technical Stack

- **Go version**: Check `go.mod` for minimum version
- **Java version**: Check `pom.xml` for Maven plugins
- **Build**: `go build`, `mvn compile`
- **Test**: `go test ./...`, `mvn test`

## CI Rules

- Read `.github/workflows/` before pushing
- MCP server YAML configs are part of the build — changes affect generated code
- Check for integration tests that depend on MCP tool names

## Contribution Guidelines

- **CLA REQUIRED**: Sign Alibaba CLA before pushing
- CLA email MUST match `git config user.email`
- Target branch: `main`
- Fork → feature branch → PR

## Key Files

| File | Purpose |
|------|---------|
| `plugins/wasm-go/mcp-servers/` | MCP server configs (YAML) |
| `plugins/wasm-go/` | Go plugins |
| `plugins/wasm-java/` | Java plugins |
| `.github/workflows/` | CI rules |

## Known Gotchas

- MCP tool names in YAML configs are PUBLIC API — renaming them is a breaking change
- Search for ALL references before renaming any MCP tool name: `grep -rn "tool-name" --include="*.yaml"`
- Internal fork references may use misspelled names — fixing the spelling breaks them
- CLA must be signed BEFORE pushing — if not signed, PR will be auto-closed
- Higress uses both Go and Java — identify which language the issue is in before coding

## Previous PRs

| PR | Status | Description | Detail |
|----|--------|-------------|--------|
| #4077 | Open | MCP docs typo fixes | CLA ✅ signed, CI ✅ all green, mergeStateStatus: **BEHIND** — needs rebase before merge |

## PR #4077 Status (2026-07-07)

- **CLA**: Signed (CLAassistant confirmed)
- **CI**: All checks passed (translate, DCO, etc.)
- **Mergeable**: MERGEABLE but **BEHIND** — base branch has new commits
- **Reviews**: 0 reviews, 0 comments
- **Next Action**: Rebase onto `main`, force-push, then wait for maintainer review
- **Repo Activity**: Last push 2026-07-07 (today) — very active repo ✅
