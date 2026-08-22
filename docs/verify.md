---
title: 确认 OKS 正在工作
nav_order: 3
parent: 从这里开始
---

# 确认 OKS 正在工作

> 某一步失败了？逐步排查

---

## 快速诊断

对 Agent 说：

```
"诊断 OKS 状态，检查所有组件"
```

Agent 会自动检查：
- ✓ OKS 是否安装
- ✓ 知识库是否初始化
- ✓ Skill 是否可用
- ✓ 权限是否正常

---

## 手动检查清单

### ✅ 检查 1: OKS 已安装

```bash
oks --version
```

**期望**：返回版本号（如 `0.6.x`）

**失败**：看 [安装指南](installation.md)

---

### ✅ 检查 2: 在知识库目录

```bash
pwd
ls -la | grep ".oks"
```

**期望**：当前目录包含 `.oks/`

**失败**：
```bash
cd ./my-knowledge  # 进入知识库
```

---

### ✅ 检查 3: 状态正常

```bash
oks status
```

**期望**：显示状态面板（Wiki / Drafts 数量）

---

### ✅ 检查 4: Skill 可用

```bash
ls .claude/skills/
```

**期望**：包含 Skill 文件

---

## 按失败环节排查

### 收录失败

**现象**：Agent 说"找不到 Skill"或"命令失败"

**检查**：
1. 在正确目录？`pwd`
2. Skill 存在？`ls .claude/skills/`
3. 权限正常？`oks status`

**解决**：
```bash
cd /path/to/my-knowledge
```

---

### Candidate 不生成

**现象**：下载成功但没有生成 Candidate

**原因**：

| 问题 | 检查 | 解决 |
|------|------|------|
| AI API 不可用 | Agent 能正常回复吗 | 检查 Agent 配置 |
| 写入权限不足 | `touch drafts/test.md` | 修复权限 |

---

### 晋升失败

**现象**：Agent 说"文件不存在"或"权限错误"

**检查**：
```bash
# Candidate 存在？
ls drafts/

# Wiki 目录可写？
touch wiki/test.md && rm wiki/test.md
```

---

### 召回不准

**现象**：找不到相关知识，或找到的不相关

**检查**：
```bash
# Wiki 存在？
oks wiki list

# 手动测试
oks recall "关键词"
```

**常见原因**：

| 问题 | 原因 | 解决 |
|------|------|------|
| 找不到 | 未晋升 | `oks wiki list` 确认 |
| 不相关 | 用词不匹配 | 换个措辞 |
| 评分低 | 类型权重低 | 改 frontmatter `type` |

**调优**：
```bash
oks recall "关键词" --explain
```

> [召回调优指南](best-practices.md#阶段-3召回-recall---用自然语言提问)

---

## 状态解读

### oks status 输出

```
┌────────────────────────────────────────┐
│ Open Knowledge Studio — Status         │
│ Root: /path/to/knowledge               │
│                                        │
│ Wiki pages: 7  Domains: 2  Drafts: 4   │
│ Raw files: 167  Profiles: 0            │
└────────────────────────────────────────┘
```

| 字段 | 含义 | 正常范围 |
|------|------|---------|
| **Wiki pages** | Wiki 数量 | 0+ |
| **Drafts** | 待审核 | < 20 |
| **Raw files** | 原始资料 | 任意 |

### 异常信号

| 现象 | 问题 |
|------|------|
| Drafts > 50 | 堆积太多 |
| Wiki = 0 | 从没晋升过 |

---

## 还是不行？

### 寻求帮助

- **GitHub Issues**: https://github.com/open-agent-power/open-knowledge-studio/issues
- **Discussions**: https://github.com/open-agent-power/open-knowledge-studio/discussions

**提供信息**：
- `oks status` 输出
- 失败的具体步骤
- 错误信息

---

## 下一步

✅ **排查完成**：回到 [第一个知识闭环](first-knowledge-loop.md)

📚 **学习更多**：[最佳实践](best-practices.md)
