---
title: OKF 兼容性
nav_order: 23
parent: 参考
---

# OKF 兼容性

[Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
是 Google 提出的一种把知识存为 **Markdown + YAML frontmatter 文件树**的开放格式
（当前为 v0.1 Draft）。OKS 的 `wiki/` 桶在理念上与它高度一致。本页**先核对
SPEC，再给出诚实的兼容性结论**——不做"已认证 OKF"这类夸大声明。

## OKF v0.1 的硬性规则（摘自 SPEC）

- **唯一必填键**：`type`（非空）。`title`/`description`/`resource`/`tags`/
  `timestamp` 均为**建议**；允许自定义扩展键。
- **保留文件**：`index.md`（目录清单）、`log.md`（变更历史）——有特殊结构含义。
- **concept-id**：即文件在集合内的路径去掉 `.md`。
- **关系/链接**：用标准 Markdown 链接（相对或以 `/` 开头的根相对）；关系的
  具体含义由上下文文字决定，链接本身无方向。解析方 **MUST 容忍死链**。
- **消费者宽容原则**：消费者 **MUST NOT** 因为缺少可选元数据、出现未知
  `type` 值、包含额外自定义键、缺少 index、或存在死链而拒绝一个 bundle。
- **生产者一致性**：集合中每个非保留 `.md` 都含合法 YAML 且 `type` 非空。

## OKS wiki 与 OKF 的对照

| 维度 | OKF v0.1 | OKS `wiki/` | 结论 |
|------|----------|-------------|------|
| 载体 | MD + YAML 文件树 | MD + YAML 文件树 | ✅ 一致 |
| 必填键 | 仅 `type` | `title` + `type` + `area` | ✅ 满足（多出的键属允许的扩展） |
| `type` 非空 | 必需 | concept/strategy/anti-pattern | ✅ 满足 |
| concept-id | 路径去 `.md` | slug + 路径 | ✅ 兼容 |
| 保留文件 | index.md / log.md | 未实现 | ⚠️ 缺口 |
| 关系表达 | 正文 Markdown 链接 | frontmatter 字段（`relates_to`/`relationship`） | ⚠️ 表达方式不同 |

## 诚实的结论

- **OKS wiki 满足 OKF 的生产者核心要求**：每个 wiki 页面都有合法 YAML 且
  `type` 非空。由于 OKF 消费者必须宽容，一个 OKF 阅读器可以直接消费 OKS
  的 wiki 页面而不报错。
- **但 OKS 不宣称是"认证 OKF 生产者"**，因为存在两处真实缺口：
  1. OKS 不产出 OKF 的保留文件 `index.md` / `log.md`；
  2. OKS 用 frontmatter 字段（`relates_to`、`relationship` 的 4 种关系）编码
     知识关系，而非 OKF 的正文 Markdown 链接。
- 准确表述是：**OKS wiki 与 OKF v0.1 在理念与 frontmatter 层兼容/对齐**，
  而非逐字符实现该 SPEC。

## 导出路径（尚未实现）

要产出"地道的 OKF bundle"，只需一层薄导出器：
1. 为每个目录生成 `index.md`，为集合生成 `log.md`；
2. 把 `relates_to` 关系改写为正文中的根相对 Markdown 链接；
3. 其余 frontmatter 原样保留（OKF 允许自定义键）。

这条路径是**可行且低成本**的，但当前版本尚未内置。

---

## 参考

- [How the Open Knowledge Format can improve data sharing](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)
- [OKF SPEC.md](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
