---
title: 演化与 Skills
nav_order: 19
parent: 内部机制
---

# 演化与 Skills

业界常见一种设想：让 Agent 把成功经验**自动结晶成新技能（skill）**，技能库
自我进化。OKS **不这样做**——这里如实说明 OKS 的演化究竟发生在哪里，以及
Skills 在本系统中的真实定位。

## Skills 是什么：稳定的程序性记忆

在[记忆模型](memory-model.html)里，`.claude/skills/` 是 **Procedural Memory**：

| 属性 | 值 |
|------|-----|
| 召回方式 | 关键词触发 |
| 衰减 | 无 |
| 写入者 | 人 / Agent（显式编辑） |
| 自动结晶 | **无** |

Skills 是"怎么做某类任务"的稳定操作说明（如 `ingest`、`dreaming`）。它们由
人或 Agent **显式编写和修改**，不会因为某次任务成功就被系统自动生成或改写。

## 演化真正发生在 wiki

OKS 的"自我进化"不在技能层，而在**语义记忆层**——`wiki/` 通过 Dreaming
循环持续演化（见 [Dreaming 循环](dreaming-cycle.html) 与 [Wiki 知识](wiki.html)）：

1. **Collect** — 扫描 raw 情节记忆
2. **AI Dream** — 提炼候选知识
3. **Write Drafts** — 落到 `drafts/`
4. **Human Review** — 人工审查（A3 不变量）
5. **Promote** — 提升为 wiki 页面
6. **Apply Decay** — 应用类型 λ 衰减
7. **Evolve** — 建立 4 种知识关系
8. **Git Commit**

第 7 步的 4 种关系——`supersedes` / `enriches` / `confirms` / `challenges`——
就是知识演化的载体：旧知识被替代、补充、确认或挑战，而不是无脑堆积。

## 为什么不做技能自动结晶

- **可信度** — 自动生成的技能绕过了 A3 人工审查这道闸门；OKS 坚持
  "raw 忠实 + 人工把关"，不让模型自证自己该拥有什么新能力。
- **职责分离** — 演化应发生在**知识**（可衰减、可召回、可挑战）而非
  **能力**（稳定、需人为负责）层面。把二者混同会让系统难以审计。
- **可解释** — wiki 的每次演化都有 draft、source_pages、关系字段留痕，可
  git diff；自动结晶的技能往往是黑盒。

## 一句话

> OKS 让**知识**演化，而不是让**技能**自动结晶。
> 技能是你（或 Agent 经确认）写下的稳定操作；演化的智能沉淀在 wiki 里。
