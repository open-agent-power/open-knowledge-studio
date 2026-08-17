---
title: Profiles 画像
nav_order: 5
parent: 使用 OKS
---

# Profiles 画像

`profiles/` 是认知桶中**稳定、不衰减**的一层。它承载“我是谁、我在做什么、我要去
哪里”。Agent 或 Skill 可以直接读取这些文件；当前默认 hook 只读取 active goals 与
Registry 绑定，不会在每轮对话中自动注入所有 Profile 正文。

`profiles/agents/registry.jsonl` 保存终端身份与作用域绑定：`agent_id + cwd` 指向
profile 和 goals；`oks recall` 不检索该文件。可以使用
`oks registry bind/list/remove` 显式管理；`/assess` 完成 profile 与 goal 建档后也会
执行 bind，闭合首次引导流程。

## 定位

| 属性 | 值 |
|------|-----|
| 读取方式 | Agent / Skill 显式读取；当前 hook 自动读取 Goal 与 Registry 元数据 |
| 衰减 | 无 |
| 注入时机 | 由 Agent host 或 Skill 决定；不是所有 Profile 每轮自动注入 |
| 写入者 | 人 / Agent（经确认） |

对比 `wiki/`（语义记忆，6+1 因子召回 + 衰减）与 `raw/`（情节记忆，关键词 +
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

宪法中的目标注入顺序把 Profiles 分布在**稳定段与可变段**两处（见
[记忆模型](../concepts/memory-model.md)）。这是上下文组织原则，不表示当前 hook 已自动
装载以下所有文件：

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
