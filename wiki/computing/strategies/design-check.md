---
title: Design Check — 改代码前先问的问题
tags:
- code-review
- design
- strategy
area: computing
source: learnings/2026/06/20/20260620-multi-repo-pr-retrospective
type: strategy
status: active
importance: 0.7
confidence: 0.8785
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---



# Design Check

## 招式

改代码前花 2 分钟回答这些问题，能避免 80% 的返工。

## 5 个必问

1. **作者已经解决了吗？** — 现有设计是否已覆盖这个问题？
   - 如果是 → 不要改代码，只加测试或文档

2. **问题在别的层吗？** — 是 Docker config？OS 设置？依赖版本？
   - 如果是 → 改代码没用，改配置

3. **有注释解释为什么这么写吗？** — 看起来"奇怪"的代码通常有原因
   - 如果有注释 → 不要删，理解后再决定

4. **if/return 管了多个行为吗？** — early return 是否阻止了不相关的递归/处理？
   - 如果是 → 拆条件，分别控制

5. **test 注释说了设计意图吗？** — test 名和注释往往记录了"为什么这样做"
   - 如果 test assert 当前行为 → 行为是 intentional，不能改

## 执行时机

```
读文件 → 读 sibling 文件 → Design Check → 才开始编辑
```

## 实战案例

| PR | 没问的问题 | 后果 |
|----|-----------|------|
| agentscope-java #1392 | 问题 4 | early return 阻止了子节点递归 |
| browser-use #5106 | 问题 5 | test 注释说了 `step_interval` 是"上一步时长"，PR 改成了"间隔" |
| agentscope-java #1387 | 问题 3 | 方案改了但标题没同步更新 |

## 关联

- Semantic Intent：`semantic-intent.md`
- Coding skill：`plugins/autpilot-coding/skills/coding/SKILL.md`
