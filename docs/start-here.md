---
title: 从这里开始
nav_order: 2
has_children: true
---

# 从这里开始

> OKS 是 Agent 原生的。你通过**对话**使用它，不是命令行。

---

## 🎯 你需要什么

- **一个 Agent**：Claude Code / Codex / Cursor（任选其一）
- **2 分钟**：装好 OKS
- **5 分钟**：跑通第一次

**不需要**：
- ❌ 学命令行
- ❌ 记语法
- ❌ 配置文件

---

## 第一步：装好 OKS

```bash
pipx install open-knowledge-studio
oks init ./my-knowledge
cd ./my-knowledge
```

✅ **完成信号**：看到 `Initialized OKS repository`

> **装不上？** 看 [安装故障排查](reference/troubleshooting.md)

---

## 第二步：跟 Agent 说话

打开你的 Agent（Claude Code / Codex / Cursor），开始对话。

### 场景 1: 收录一篇文章

```
你: "把这篇技术文章收录进我的 OKS：
     https://example.com/deep-learning-guide"

Agent: 
  ✓ 读取文章内容
  ✓ 提取关键信息
  ✓ 生成 Candidate
  
  → Candidate 已保存到 drafts/20260820-deep-learning.md
  → 请审核后决定是否晋升到 Wiki
```

**Agent 做了什么**：
1. 读取 `/ingest` Skill
2. 下载文章内容
3. 提取核心信息
4. 生成结构化 Candidate

**你不需要**：
- ❌ 运行 `oks ingest`
- ❌ 管理文件路径
- ❌ 手动创建 Candidate

---

### 场景 2: 审核 Candidate

```
你: "看看有哪些 Candidate 需要审核"

Agent:
  → 找到 3 个 Candidates:
     1. deep-learning.md (今天)
     2. react-hooks.md (昨天)
     3. sql-optimization.md (2天前)

你: "第一个看起来不错，晋升到 Wiki"

Agent:
  ✓ 已晋升
  
  → wiki/computing/concepts/20260820-deep-learning.md
  → 现在可以被召回了
```

**完全对话式**：不需要记命令。

---

### 场景 3: 召回知识

几天后，你要写方案：

```
你: "帮我设计一个深度学习训练平台，需要考虑 GPU 调度"

Agent:
  🔍 自动召回相关知识...
  
  → 找到 2 个相关 Wiki:
     - deep-learning.md (相关性 0.85)
     - gpu-scheduling.md (相关性 0.72)
  
  基于你的知识库，我建议：
  
  1. 训练平台架构...
  2. GPU 调度策略...
  [基于你收录的知识给出方案]
```

**关键**：Agent 自动召回，你不需要记得"我收录过什么"。

---

## 三个核心理念

### 1. Agent 是界面，不是工具

❌ **错误理解**：  
"我要学 `oks` 命令"

✅ **正确理解**：  
"我跟 Agent 说话，Agent 帮我用 OKS"

---

### 2. 对话驱动，不是命令驱动

你说的是：
- "收录这篇文章"
- "看看有哪些 Candidate"
- "晋升这个到 Wiki"

不是：
- `oks ingest run ...`
- `oks drafts list`
- `oks drafts promote ...`

---

### 3. 知识工作台，不是笔记软件

**OKS 做什么**：
- ✅ 保留原始来源（Raw + 证据）
- ✅ 提出知识候选（Agent 生成）
- ✅ 等你审核（Candidate → Wiki）
- ✅ 自动召回（注入对话）

**OKS 不做什么**：
- ❌ 让你在里面写作
- ❌ 整理页面层级
- ❌ 管理标签和文件夹

---

## 常见疑问

### Q: 我必须学命令行吗？

**A**: 不需要。日常使用 100% 对话。

CLI 命令（`oks status`, `oks recall`）是：
- 调试时用
- 脚本集成时用
- 不是日常交互方式

---

### Q: Agent 怎么知道调用 OKS？

**A**: Agent 读取 `/ingest` Skill，里面告诉它：
- 什么时候用 OKS（你说"收录"、"召回"时）
- 怎么用（调用 CLI + 管理文件）
- 返回什么（Candidate 位置、召回结果）

你只需要说话，Skill 负责衔接。

---

### Q: 我已经有很多笔记，能导入吗？

**A**: 可以，但**不要一次性全导入**。

推荐：
- ✅ 从今天开始，新内容用 OKS
- ✅ 旧笔记按需迁移（用到时再收录）
- ❌ 不要批量导入几百条

原因：批量导入会产生大量 Candidate，审核负担重。

---

## 下一步

现在你理解了 Agent 原生的理念，开始实战：

1. **[跑通第一个知识闭环](first-knowledge-loop.md)**  
   用自己的真实资料，完整走一遍

2. **[看真实案例](examples.md)**  
   B 站视频 → Wiki → 技术方案（7 分钟）

3. **[学习最佳实践](best-practices.md)**  
   三个阶段，三个核心原则

---

**记住**：跟 Agent 说话，像跟人说话一样。
