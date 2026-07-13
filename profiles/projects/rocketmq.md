---
name: project-rocketmq
description: 'Apache RocketMQ — Java message queue. Competition project. Already has PRs from previous sessions.'
title: Apache RocketMQ Project Profile
type: profile
status: active
tags: [project, competition, java, apache]
---

# Apache RocketMQ

## Repo Info

| Field | Value |
|-------|-------|
| GitHub | `apache/rocketmq` |
| Language | Java |
| Framework | Message queue / streaming |
| Prize | Part of competition |
| Competition Period | 2026-06-15 to 2026-09-20 |

## Technical Stack

- **Java version**: Check `pom.xml` for `maven.compiler.source`
- **Build**: `mvn compile`, `mvn test`
- **Test**: `mvn test -pl module-name`
- **Linting**: Check for checkstyle / spotbugs config

## CI Rules

- **Apache CLA REQUIRED**: Sign at https://cla.apache.org/ before pushing
- PR title format: `[ISSUE #NNN] Description` (Apache convention)
- CI may show `action_required` for first-time contributors — this is normal, wait for maintainer approval
- Read `.github/workflows/` and `pom.xml` for checkstyle rules
- Check for license header requirements (Apache License 2.0)

## Contribution Guidelines

- **Target branch**: `develop` (NOT `main` — RocketMQ uses `develop` as default)
- Fork → feature branch → PR
- PR title MUST include `[ISSUE #NNN]` prefix
- Apache CLA must be signed — email must match `git config user.email`
- License headers required on all new files

## Key Modules

| Module | Purpose |
|--------|---------|
| `broker/` | Broker core |
| `client/` | Client SDK |
| `namesrv/` | Name server |
| `remoting/` | Network layer |
| `store/` | Storage engine |

## Known Gotchas

- `byte[].equals()` uses identity comparison — use `ByteBuffer.wrap()` for cache keys
- Target branch is `develop` not `main` — always verify before creating PR
- First-time contributor CI shows `action_required` — this is normal, do NOT close and resubmit
- Apache PR title format: `[ISSUE #NNN] Description`
- Check for `@author` Javadoc tags — may need to add your name
- License headers required: `/* Licensed to the Apache Software Foundation (ASF) ... */`

## Previous PRs

| PR | Status | Description | Lesson |
|----|--------|-------------|--------|
| #10531 | Closed | gRPC queue permission (duplicate of #10530) | Gate 1 失败：没查 competing PR |
| #10532 | Closed | RocksDB `byte[].equals()` cache key fix | 提交后不监控：1 天后被 #10422 抢先 merge，17 天后才发现 |

## Lessons Learned

- **Gate 1 必须 `gh pr list --search "ISSUE_NUMBER" --state all`**，不能只查 issue assignment
- **提交后必须监控**：每 1-3 天查 PR mergeable 状态 + issue 是否 closed
- Apache review 周期长，但竞争 PR 随时可能 merge — 不能提交后就忘
