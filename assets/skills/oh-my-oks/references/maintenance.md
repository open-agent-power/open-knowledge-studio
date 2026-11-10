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

## 个人与团队

个人库和团队库共享raw/、drafts/、wiki/、skills/、profiles/、records/、settings/，各自保存文件与Git历史。通过个人库的settings/sources.yaml逻辑关联；不复制或混写内容。

`oks sources list`核对关联版本和状态。`oks fs ls oks://team/`浏览团队已提交内容，`oks fs read oks://team/<source-id>/<path>`读取并保留返回的revision和SHA。图谱可看候选，自动知识召回不采用未审核内容；Skill可见不等于获准执行。

修改内容时明确目标库；私人讨论和反馈留个人库，团队修订在团队仓库准备并按授权走Git PR。HEAD只跟随本地提交，不表示远端已同步；不自动fetch、push或批准。
