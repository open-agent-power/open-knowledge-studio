---
title: 本地 Studio
parent: 日常使用
nav_order: 5
---

# 本地 Studio

让 Agent 启动当前知识库的 Studio，即可查看讨论、编辑目标、检查知识调用和运行评测。执行与任务编排仍由宿主 Agent 负责。

```bash
oks mail serve --path <知识库路径> --port 3184 --local-edit
```

不加 `--local-edit` 时为只读。所有数据来自指定实例，不保存在浏览器副本中。

## 讨论与目标

顶部按日期选择文件，新文档默认保存在：

```text
discuss/YYYY/MM/DD/讨论.md
goal/YYYY/MM/DD/目标.md
```

旧的 `profiles/goals/` 和无日期文档仍可读取，列为“历史未归档”。日期来自目录，不以修改时间推测；归档不代表完成目标。

讨论图谱根据文件中明确写下的引用连接 Goal、Wiki、Raw 和判断。例如：

```markdown
# 简化界面

## 人的判断
只保留三个顶层菜单。

## AI 理解
将评测收进学习。

## 关联目标
[[goal/2026/11/04/界面.md]]
```

目标页采用单列清单，只显示标题与勾选项；正文、备注和关联保留在原文中，可切换编辑。保存会校验文件版本，避免覆盖其他窗口的修改。外部文件变动会定期反映到页面。

讨论图谱的倍速展开是当前结构的渐进展示，不是历史事件回放，也不表示模型内部注意力。

## 学习图谱与参数

学习页包含**图谱、参数、评测**。

图谱统一呈现 Wiki、候选、Profile、Project、Goal、Discuss 与知识库 `skill/` 中的技能。点击分支可独立展开区域，点击条目在右侧查看内容、属性和关联。草稿使用灰色虚线，审核入口复用已有权限；已有 Wiki 缺少审核记录时仍显示“审核记录未知”。

输入可筛选图谱；点击 Query 或回车才执行 Wiki 召回。右侧显示实际后端、返回项、请求往返耗时和诊断，图上聚焦命中及祖先路径。命中节点短暂闪烁，并遵守减少动画设置。往返耗时不是纯检索耗时，也不是阶段火焰图。

颜色区分类别，深浅映射显式使用次数。读取或召回不等于采用，更不等于人工审核。图中引用来自文件，不凭相似词推断关系。

参数页按 Node-BM25、注入预算、Memory Curve 和运行配置分组，本地渲染公式。可保存参数显示改动增减；固定算法常量只读。预算和衰减曲线是预览，不代表效果提升，需通过固定评测集验证。

## 通用评测

上传 YAML/JSON 后，选择方法与可选 split，运行完整数据集。后台任务离开页面后继续，重新打开可查看进度、成功或失败记录。

当前适配器支持 `recall-case/v1` 与 `recall-case/v2`，方法为 fts5、native、fusion，复用 `oks eval recall`。v2 的范围、版本、时间及拒答审计也会展示。其他能力需新增受控适配器，上传内容不会作为脚本执行。

数据集不需要携带语料；省略时使用当前知识库。也可上传独立 benchmark bundle：

```yaml
dataset:
  schema_version: recall-case/v1
  dataset_id: my-recall-set
  version: '1.0'
  cases:
    - case_id: case-1
      query: 如何定位这个知识？
      relevant: [my-evidence]
corpus:
  my-evidence: |
    ---
    title: 我的证据
    type: concept
    area: computing
    status: active
    ---
    # 我的证据
    支撑问题的完整原文。
```

上传上限为 8 MiB。缺少 Gold 语料时提示覆盖缺口，不跳过题目后计算分数。

结果包含指标柱状图、延迟 ECDF、逐题 RR 配对图、失败题目筛选和逐题详情。运行保留数据、知识、代码及配置快照。选择基线后复用 `oks eval compare` 检查可比性；“配置实验”显式声明 settings / parameters 变化。不同语料快照不计算受控提升；题目一致时可描述性并排查看，并保留不兼容原因。历史记录缺少配置证据时标为有限对比，不虚构置信区间或显著性结论。

README 中的 50-case、LoCoMo 和历史 JSON 是可导入的实例材料，不是页面写死的默认数据。迁入数据时保留来源、许可与原始记录。LoCoMo 的召回命中率与 OpenViking 发布的 QA accuracy 口径不同，外部报告单独展示，不直接相减。

## 文件与状态边界

评测材料保存在实例的 `records/evaluation/`：`datasets/` 管数据集，`corpora/` 管可选语料，`jobs/` 管进度与失败，`runs/` 管逐题结果，`sources/` 保留原始材料。评测语料不会进入个人 Wiki。

编辑 Goal 不会启动 Agent、更新冻结的任务约定或宣告验收。查看、使用和评测不会自动批准候选。Raw、AI 提议、人工审核和执行证据保持各自的状态。
