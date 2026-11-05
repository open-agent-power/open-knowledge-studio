# 讨论与每日目标

读取实例的现有约定，沿用用户所在日期和文件，避免同一任务重复建档。

- `profiles/users/`：人的背景、偏好及适用边界。
- `profiles/projects/`：项目背景和约束，项目源码在获准的项目仓库。
- `profiles/agents/`：角色与协作约定；运行绑定在 `records/registry/`。
- `profiles/recipes/`：场景化输入、步骤与验收约定。
- `profiles/discuss/YYYY/MM/DD/`：讨论记录。
- `profiles/goals/YYYY/MM/DD/`：当日目标与 TODO。

讨论可使用 `人的判断`、`AI 理解`、`待确认` 三个小节。引用相关 Goal、Wiki 或来源，保留判断适用条件；单次选择不直接升级成永久个人偏好。

目标的标题层级和嵌套任务对应思维导图节点。保留原文的备注、关联知识与来源。只在实际完成并检查后勾选对应节点，任务交付与人的最终验收保持可区分。

Studio 入口：`oks mail serve --path <知识库> --local-edit`。页面提交保留准确提交时刻与前后快照；运行中的观察器记录直接修改 Markdown 的 observed-at。服务未运行时，不补造未记录的中间过程或时间。

正式执行任务需要已选中的任务约定时，查看 `oks task --help`，使用现有 Goal 绑定与 checkpoint 能力；一次性问答不用自动创建执行任务。
