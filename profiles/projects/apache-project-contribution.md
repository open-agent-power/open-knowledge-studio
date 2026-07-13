---
title: Apache Project Contribution Conventions
type: convention
area: computing
confidence: 0.9
created: '2026-07-06'
last_verified: '2026-07-06'
status: active
source: session/rocketmq-prs
tags: [apache, java, contribution, oss]
---

# Apache Project Contribution Conventions

When contributing to Apache open source projects (RocketMQ, Dubbo, Flink, etc.).

## Target Branch

Apache projects often use `develop` as the primary integration branch, NOT `main` or `master`:

```bash
# Check .asf.yaml for branch protection
cat .asf.yaml 2>/dev/null

# Check actual default branch
git branch -r | grep -E "develop|main|master"
gh repo view OWNER/REPO --json defaultBranchRef
```

**Apache RocketMQ**: target `develop`
**Apache Dubbo**: target `master` (verify per-repo)
**Apache Flink**: target `master` (verify per-repo)

Always verify per-repo — do NOT assume.

## PR Title Format

```markdown
[ISSUE #NNN] Brief description of the change
```

The `[ISSUE #NNN]` prefix is required. Without it, CI checks may fail or the PR may be labeled `invalid`.

## License Headers

Every new file must have the ALv2 header:

```java
/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
```

CI checks: `apache-rat-plugin` at `validate` phase, or `license-checker`.

## CLA (ICLA)

- Sign Individual Contributor License Agreement at https://www.apache.org/licenses/#clas
- CLA email MUST match `git config user.email`
- If mismatch: add commit email to CLA profile, or `git commit --amend --reset-author --no-edit`

## First-Time Contributor CI

```bash
gh pr checks <PR_NUMBER>
# Output: action_required (not pending or failed)
```

Large Apache repos require maintainer approval before running CI for new contributors.
This is **normal** — do NOT close/recreate the PR or push more commits. Wait for approval.

## Checkstyle Rules

Apache projects typically enforce strict checkstyle:

| Rule | Enforcement |
|------|-------------|
| `System.out` / `System.err` | Banned — use logger |
| `TODO` / `FIXME` comments | Banned in some projects |
| `@author` Javadoc tags | Check per-project — some require, some ban |
| Chinese characters | Banned in source code and comments |
| `*`-imports (`import java.util.*`) | Banned — use specific imports |
| Line length | Usually 120 or 160 chars |

Run before committing:
```bash
mvn validate -pl <module>
```

## Review Cycle

- Apache review cycle: **1-4 weeks** for first response
- For competition PRs: submit as early as possible to account for review time
- Do not ping more than 3 times per PR
- After 3 pings with no response, move to other work

## Common Gotchas

### `byte[]` as Map key

```java
// WRONG — byte[].equals() uses identity comparison
Map<byte[], Value> cache = new HashMap<>();
cache.put(key.getBytes(), value);
cache.get(key.getBytes());  // Returns null — different byte[] instance

// CORRECT — use ByteBuffer.wrap()
Map<ByteBuffer, Value> cache = new HashMap<>();
cache.put(ByteBuffer.wrap(key.getBytes()), value);
cache.get(ByteBuffer.wrap(key.getBytes()));  // Returns value
```

See `plugins/autpilot-coding/skills/fixes/java-cache-keys.md` for full fix recipe.

## Source

- PR #10531, #10532 (Apache RocketMQ): gRPC queue permission, RocksDB cache key
