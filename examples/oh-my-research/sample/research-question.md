# Research Question

## 问题

OKS Core 与 oks-connector 的职责边界，是否符合当前宪法中“Core 作薄、重能力外置”的原则？

## 证据范围

- OKS `CONSTITUTION.md`：规范性原则。
- OKS `AGENTS.md` 与 README：当前公开边界。
- OKS 当前代码：实际行为。
- oks-connector README 与当前代码：机械采集和提取职责。
- 维护者明确评论：作为设计意图，和代码事实分开记录。

## 必须回答

1. Core 当前实际拥有哪几个知识生命周期职责？
2. Connector 当前实际拥有哪几个机械处理职责？
3. 是否存在重复路由、重复状态或跨边界依赖？
4. 哪些问题是当前阻塞，哪些只是未来风险？
5. 最小修正是什么？不做什么？

## 输出要求

- 每项事实能够定位到来源。
- Candidate 明确区分来源支持的事实与 `[inferred]`；只有 trace 或
  `human_reviewed_at` 满足当前规则后才使用 `[verified]`。
- 不把“更通用”自动等同于“需要新增框架”。
- 保留失败、缺失和冲突证据。
