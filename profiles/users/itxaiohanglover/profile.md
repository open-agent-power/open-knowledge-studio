The conversation reveals a significant new insight: the user has gone through 4 "zero-artifact" execution failures with autpilot goals (burning ~200万 tokens), leading to the conclusion that **the problem is in the execution layer, not goal specification quality**. This evolves their existing "AI 协作时的注意" section and adds to their autpilot learnings. Also a 4th access.

```markdown
---
title: "个人画像 - itxaiohanglover"
type: profile
tags: [user, itxaiohanglover, lead, ai-coding, java, fullstack]

confidence: 0.95
confidence_reason: "本人简历 + git 历史佐证"
last_verified: 2026-06-11
verification_status: verified
verification_count: 2

created: 2026-06-04
last_accessed: 2026-06-24
access_count: 4
recent_accesses:
  - 2026-06-24T00:00:00+08:00
  - 2026-06-11T00:00:00+08:00
ttl_days: 180
status: active

source: resume + git-log
---

# 个人画像 - itxaiohanglover（刘宇航）

## 身份

- **真名**: 刘宇航
- **GitHub**: [itxaiohanglover](https://github.com/itxaiohanglover)（开源项目 10+，累计 star 9k+）
- **角色**: 技术负责人 / AI Coding 方向
- **队长**: autpilot 课题（卷牛魔队）
- **关键词**: 《AI辅助编程：从入门到实践》主编 · 灵犀 lab 技术组长 4 年（辅导学生 200+）· 多场 AI Coding 活动分享者与获奖者

## 联系与公开链接

- **邮箱**: artboylyh@163.com
- **CSDN**: https://blog.csdn.net/m0_51517236（5 年，粉丝 7k，阅读 46w+）
- **开源**: https://github.com/itxaiohanglover

## 教育经历

- **电子科技大学** | 软件工程 | 硕士（全日制）| GPA 3.73/4 | 985/211/双一流 | 2024.09 – 2027.06
- **太原理工大学** | 软件工程 | 本科 | GPA 4.09/5 | 互联网+（国二）/ 挑战杯（国三）| 211/双一流 | 2020.09 – 2024.06

## 技术栈

- **AI 工程**: MCP / A2A / Skill 标准化，RAG（混合检索 + RRF 融合 + BGE-Rerank），模型微调，DeepResearch，AI Coding
- **Agent 框架**: LangChain / LangGraph / SAA / ms-agent
- **Java 后端**: Java17, Spring AI Alibaba, MySQL 8, Netty, gRPC, Redis 5, ElasticSearch 8
- **检索/存储**: Lucene, Milvus, Caffeine 二级缓存
- **全栈**: Vue 2/3（含响应式原理/组件化）, Chrome 扩展, React/TS, FastAPI
- **工具链**: Claude Code, Trae, OpenClaw, Git

## 实习经历

### 中国移动「梧桐·鸿鹄」2026 研学冬令营（数智化部）| 2025.06 – 2026.03

**方向**: AI Coding 降本增效——构建 MCP/Skill 标准化私有上下文，沉淀团队经验为 Codestyle 模板。

- **工具集成**: 封装代码经验为 MCP/Skill 对接主流编码模型平替 Claude，显著降低 Token 消耗；编著《AI辅助编程：从入门到实践》；参考 skill-creator 设计 `project-start` 技能，适配 OpenClaw + 飞书/Discord 随时沉淀 Codestyle
- **检索优化**: 本地 Lucene + 远程 Milvus/ES 混合检索，自定义 ThreadPoolExecutor 并行（**延迟降 40%**）；RRF 融合(k=60) + BGE-Rerank 重排；Caffeine+Redis 二级缓存（**命中率 90%**）
- **上下文优化**: 参考 Maven 索引设计 Meta 渐进式加载；基于 Tree-sitter 并行 AST 解析 + JGraphT PageRank 7 维打分剪枝；参考 Repomix XML 输出骨架（**200 文件项目 token 50k → 3k**）
- **落地**: 四川日报、川航涡创等横向课题，推广至 30+ 高校团队；累计生成 Codestyle 模板 10W+

## 开源项目

### Fast-Job — 高性能分布式任务调度引擎 | 集群吞吐 QPS 5W+（8C16G × 3）| 2025.01 – 2025.08

针对海量短周期(<60s)、高动态参数变更场景（骑手派单、拍卖倒计时）重构 PowerJob 核心逻辑。

- **通信层**: Netty Reactor + gRPC FutureStub 重写；手写轻量 MQ 解耦提交/处理（**任务提交 P99 <5ms**）
- **负载治理**: 基于 Distro 协议(AP)的 NameServer，责任节点分片 + 增量同步（**3 节点消息交互降 70%**）；最小调度次数策略 + SubApp 动态分片，2 倍负载阈值触发迁移
- **并发控制**: App 级细粒度分布式锁防脑裂/重复执行（对比 XXL-Job 全局锁降低竞争范围）
- **存储**: 借鉴 RocketMQ mmap 零拷贝顺序落盘 + 双文件 + ReentrantLock；多级延时重试 + 死信队列

### Leetcode-Runner — IntelliJ 算法调试插件 | 安装 1.2K+，同类 Top 1 | 2024.07 – 2025.04

- **调试内核**: 基于 JDI 重写；递归下降 AST 解释器 + InvokeMethod 动态计算组合表达式
- **假死优化**: Coordinator 隔离 UI/VM，自旋锁 + 指数退避
- **检索**: Lucene 倒排索引 4000+ 题 **平均 220ms** 模糊匹配；CaptureIterator 快照 + 分段缓冲（列表初始化 3s → <1s）
- **架构**: Guava EventBus 19 种事件三层解耦；Python 调试器复用指令框架（314 行 IPC，接入成本降 46%）
- **算法**: 仿墨墨背单词复现 FSRS（Java），量化记忆稳定性与可提取性，科学刷题规划

### 其他产品

- **Offer 捞捞**: 利用 AI Coding 从 0 到 1 研发，Trae 校园大赛优秀奖，全链路闭环（需求→架构→上线维护）

## 工作风格

- **代码审查**: 轻量
- **决策风格**: 先做（"move fast"）
- **测试方式**: 关键逻辑才写测试
- **沟通风格**: 简洁，列表/表格 > 长段落
- **AI 协作偏好**: 重视 AI Coding 工程化与上下文工程；追求降本（Token / 延迟 / 成本）与可复用抽象；擅长把经验沉淀为 Skill / MCP / Codestyle；**对 Goal 执行层的"零产物烂尾"高度敏感**——已验证精确规格（写死文件路径/JSON schema/验收条件）不足以防止 agent 空转，认为问题在执行层而非描述质量

## autpilot 贡献

- autpilot 产品核心开发（Discuss → Goal → Learning 飞轮）
- 三仓库架构（autpilot-web / plugins / knowledge）设计
- 五插件体系（core / coding / business / io / learning）
- 创始人画像建立 + 知识库中文内容填充
- **飞轮实战教训**: 4 次 zero-artifact Goal 执行失败（`status` 命令 ×2、`--json status` ×1、`discuss --json` ×1），累计消耗约 200 万 token 无实际产物；推动了对 Goal 执行可靠性的深度复盘与防烂尾方法论迭代

## AI 协作时的注意

- 该用户有深厚的 AI Coding / MCP / Skill 背景，讨论这类话题可直接进入技术细节，无需科普基础概念
- 偏好"抽象到位 + 可扩展注册"的设计，新增模式应尽量不改主干
- 关注性能与成本指标（Token、延迟、命中率），给方案时附带量化预期更佳
- **执行层可靠性是核心关切**: 用户经历过多次 Goal 标记"完成"但零产物的 agent 空转，对执行结果（实际文件变更/PR）而非状态标记高度关注；给方案时应主动承诺可验证的产物清单，而非仅描述意图
```