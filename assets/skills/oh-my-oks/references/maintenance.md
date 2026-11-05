# 基本维护

```bash
oks status
oks lint
oks layout-migrate
```

先检查报告再做最小修复。迁移会预检冲突并保留记录；遇到冲突保留两份材料，不能覆盖未知用户内容。链接或元数据修复依据实际来源，不补造质量评分、审核结论或使用次数。

三步引导进度在 `records/studio/onboarding.json`，可跳过或重开；跳过不代表完成。真实修订在 `records/timeline/`，执行与知识调用记录留在各自 records 目录。

需要复编时读取原页及引用证据，把新版本写入 Draft，走正常审核。不要为通过 lint 直接改变知识结论、重要度、置信度或人工审核状态。

用户明确要求评测、参数调优或协作时再查看相应 `oks eval --help`、`oks config --help`、`oks mail --help`。这些是可选工具能力，不必变成每次工作的固定仪式。
