# 查阅、采纳与知识更新

## 查阅

```bash
oks recall "<任务意图>" --limit 3 --explain
oks fs read "<返回的 oks:// URI>" --format json
```

选择与当前任务相关的结果，检查来源和审核状态，再据此回答或执行。未审核内容、原始材料和已审核结论保持区别。引用页面或来源，不把检索命中当成使用或事实确认。

实际采用后用 `oks use <slug>` 记录。若本次返回 observation_id，可附 `--observation <id>` 精确关联。缺少采纳为未确认；拒绝必须是显式反馈，不能由未点击或未记录推导。

## 材料与候选

```bash
oks ingest prepare <source>
oks drafts list
oks drafts get <slug>
```

按 prepare 返回的源类型、可用能力和指令继续。原始或机械转换材料进入 Raw，AI 提炼进入 Draft；保留证据、适用范围及 partial / failed / skipped 状态。

更新已有知识前读取原页和证据，将修订写入候选，保留版本与关联关系。用户已有明确审核决定时按其范围执行 `oks drafts promote <slug>` 或 `oks drafts reject <slug>`；没有决定时报告候选，不自填人工审批人或审核时间。

可执行能力包放在 `skills/`。宿主 `.claude/skills`、`.agents/skills` 等是安装入口，不是另一套知识分类。`oh-my-*` 是命名习惯，能力范围、来源与版本比前缀更重要。
