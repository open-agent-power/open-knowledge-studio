---
title: "个人画像 - mrjlv1"
type: profile
tags: [user, mrjlv1, architect, distill]

confidence: 0.9
confidence_reason: "本人确认 + git 历史佐证"
last_verified: 2026-06-05
verification_status: verified
verification_count: 1

created: 2026-05-31
last_accessed: 2026-06-05
access_count: 3
recent_accesses:
  - 2026-06-05T13:00:00+08:00
ttl_days: 180
status: active

source: setup + git-log
---

# 个人画像 - mrjlv1

## 身份

- **GitHub**: mrjlv1
- **角色**: 知识库架构师
- **经验**: 全栈开发（Python + React/TS）

## 技术栈

- **语言**: Python, TypeScript, React
- **框架**: FastAPI, React + Vite
- **工具**: Git, Claude Code, pytest, vitest

## 工作风格

- **代码审查**: 详细 review
- **决策风格**: 严谨型，先设计再实现
- **测试方式**: TDD，完善测试覆盖
- **沟通风格**: 问清楚再动手，重视设计文档

## 项目职责

- 知识库 4 层架构设计（profiles / domain / sessions / extensions）
- 蒸馏机制设计（auto-distill / summary / dream 三模式）
- distill skill 编写（SKILL.md + auto-distill.md + summary.md + dream.md）
- 6 个蒸馏脚本开发（apply-decay / record-access / read-discussion / lift-session / archive-* 等）
- 衰减公式设计 + decay-config.yaml 参数化
- v0.7-v0.8 全套迭代（bug 修复 + 功能增强 + 结构重整）

## 贡献

- commit `b88c03c`: 建立知识库 4 层子系统（domain / extensions / profiles / sessions）
- v0.7: 修复 age=0 bug + 接通蒸馏 4 缺口 + AccessLog 闭环
- v0.8: sessions 改为 topic 目录 + goal 文件结构 + schema 抽取 + 归档机制

## AI 协作偏好

- 要求 AI 老实交代实际状态，不接受"应该 OK"
- 要求严谨一致（发现 dream Step 编号重复 / Phase 引用错误等）
- 要求精简（schema 文档从 359 → 158 行）
- 反对越权改别人代码
