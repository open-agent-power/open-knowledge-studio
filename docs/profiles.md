---
title: Profiles 画像
nav_order: 17
parent: 内部机制
---

# Profiles 画像

`profiles/` 是五个记忆桶中**唯一稳定、直接读取、不衰减**的认知桶。它承载
"我是谁、我在做什么、我要去哪里"——这些事实变化缓慢，因此每轮对话开头都被
原样注入上下文，而不经过召回打分。

## 定位

| 属性 | 值 |
|------|-----|
| 召回方式 | 直接读取（不打分、不排序） |
| 衰减 | 无 |
| 注入时机 | 对话开头，稳定层（KV Cache 友好） |
| 写入者 | 人 / Agent（经确认） |

对比 `wiki/`（语义记忆，6 因子召回 + 衰减）与 `raw/`（情节记忆，关键词 +
新鲜度）：Profiles 不参与相关性竞争，它是"底座"而非"检索目标"。

## 目录结构

```
profiles/
├── team/                 # 团队画像、North Star（如存在）
├── users/{id}/profile.md # 用户画像：偏好、风格、约束
├── projects/{slug}.md    # 项目画像：技术栈、架构、当前目标
├── goals/                # 长期目标（如 OSS 贡献）
└── recipes/              # 可复用操作配方
```

- **User Memory** — 作者是谁、编码偏好、沟通风格、硬性约束。
- **Project Memory** — 某个项目的技术栈、架构决策、当前焦点。
- **Goals** — 跨会话追踪的长期目标（North Star 之下的具体目标）。
- **Recipes** — 沉淀下来的标准操作流程，供 Agent 复用。

## 注入顺序中的位置

Profiles 分布在注入序列的**稳定段与可变段**两处（见[记忆模型](memory-model.html)）：

1. System Prompt
2. **Team Profile + North Star**（profiles/，稳定）
3. **Project Memory**（profiles/，稳定）
4. Tool Schema + Skills
   ─── KV Cache 断点 ───
5. Recalled Semantic Memory（wiki/）
6. Recalled Episodic Memory（raw/）
7. **User Preferences**（profiles/，可变，放在末尾避免破坏前缀缓存）

稳定的团队/项目事实放前面以命中前缀缓存；易变的用户偏好放最后。

## 与 AI Profiles 理念的关系

业界的 "AI Profile" 通常指把用户偏好显式沉淀为可移植档案。OKS 的 `profiles/`
是它的一个**文件化、版本化、可 diff**的实现：画像即普通 Markdown，改动走 git，
既能被 Agent 读取，也能被人直接编辑审阅——不依赖任何厂商的私有存储。
