# Agent Runtime Provider

Agent 自身的多模态理解能力。扫描 PDF 和截图/OCR 离线验证通过。

## 适用场景

- 扫描 PDF：页面图像→理解正文/表格/布局
- 截图补充：判断页面上下文，区分内容与 UI
- 图表：理解数据可视化
- 交叉验证：对比多个机械提取结果的矛盾

## 输出约束

- 每条 evidence 标注 `agent_judgment: agent_observed`
- 每条 evidence 绑定 `artifact_id + locator`
- 不能替代 OCR 字符准确率验证
- 不确定项标注 `status: uncertain`
- 不把推断写成来源原文
