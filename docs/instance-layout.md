# 实例目录与每日思考记录

Studio 仍只有讨论、目标、学习三个主菜单。讨论与目标按日期切换；学习没有日期入口，面向全库。检索不等同于使用。

```
knowledge/
├── profiles/
│   ├── users/                 # 个人背景、偏好与边界
│   ├── projects/              # 项目背景与约束，项目源码另存
│   ├── agents/                # Agent 角色、能力与协作约定
│   ├── recipes/               # 触发条件、输入、步骤和验收配方
│   ├── goals/YYYY/MM/DD/       # 每日目标与 TODO，Markdown → 思维导图
│   └── discuss/YYYY/MM/DD/     # 问题、人的判断、AI 理解与待确认
├── skills/                    # 可共享的 SKILL.md、脚本与资源
├── wiki/                      # 经人工审核的长期知识
├── raw/                       # 原始证据
├── drafts/                    # 待审核知识
├── mail/                      # 协作交接
├── settings/                  # 当前运行参数
└── records/
    ├── registry/terminals.jsonl
    ├── studio/onboarding.json
    ├── timeline/YYYY/MM/DD/
    └── layout/migration.json
```

`.agents/skills`、`.claude/skills` 等是宿主加载入口；程序的 `assets/skills` 是工具内置技能的发行源。它们不表示个人知识库存在第二个技能资产目录。`oh-my-*` 只是命名习惯：query、ingest、promote 等负责操作 OKS，同样有用；不以名称前缀判断是否保留。

Recipe 是场景化任务契约，可以组合多个知识和技能；Skill 是可执行、可复用的能力包。Recipe 不会因为搬目录而自动获得运行权限或被晋升为已审核 Skill。

## 日期与修订

目标页按天合并多个目标文件：日期为根，文件与 Markdown 层级为分支。编辑、添加子目标、完成和删除分支都写回原 Markdown。原文编辑仍保留。

页面提交记录准确的提交时刻、修改前后内容、内容哈希和结构变化。事务记录先 prepared，正文成功写入后才 complete；失败状态不得当作已完成操作回放。

启用 `--local-edit` 的服务每两秒观察目标与讨论文件，捕捉其他 Agent 的直接编辑。这里记录的是 observed-at，无法宣称是修改精确发生时刻；首次扫描是 baseline，不补造旧历史。服务未运行期间可能合并了多次外部编辑，无法重建未观察到的中间步骤。

时间轴按实际时间排序，可点选只读快照与倍速回放。回放按阶段推进并压缩长空档；逐步展开当前图谱仍是结构浏览，和历史修订回放分开。

## 初始化与迁移

`oks init` 建立规范目录和 `records/studio/onboarding.json`。引导围绕讨论、目标、学习三步，状态为 not_started / in_progress / completed / skipped。跳过保留未完成步骤，不伪造完成；右上角问号可以重新打开。

```bash
oks layout-migrate
```

迁移预检重名冲突，按内容 SHA 校验，迁移结果记录到 `records/layout`。旧 goal/discuss/skill 路径可经 OKS 解析到规范位置；团队的独立知识仓库不会被这个实例迁移改写。

日常新建文件直接使用日期目录；旧版长期目标模板可通过上述命令归档。历史任务的签名快照保持原样，通过路径兼容读取，不重写其约定或审核结果。

## 基础 Skill 与场景配方

默认知识操作入口`oh-my-oks`由工具发行并安装到选定宿主的全局目录，兼容项目入口位于`.claude/skills`、`.agents/skills`等隐藏目录；不再自动放入个人`skills/`作为知识资产。团队可以在自己的`skills/`维护共享采用版本。文件视图的根、tree 和全库 find 不枚举宿主安装目录；旧 `host-skills` URI 只保留显式兼容读取。

`oh-my-oks` 只含讨论与目标维护、查阅与采纳、材料入库与知识候选审核、基本状态与健康检查。Office、媒体处理、通信、宿主适配、复杂评测不放入核心入口；需要时单独调用。

```bash
oks skills-install                 # 安装或补齐最小入口，保留用户的其他 Skill
oks skills-install --consolidate   # 将旧 OKS 绑定的 Skill 归档到 records/skill-migration
oks skills-install --all-bundled   # 明确需要旧入口与专用能力时按需安装
```

`--force` 只覆盖本次选中的发行文件，不删除整个宿主技能目录。第三方和用户自建 Skill 不随核心合并删除。配方依然是场景资料：按当前 Goal 引用，不作为默认动作或计时器运行。

目标图中，每个可编辑节点右侧的加号直接新建子分支，Enter 写回 Markdown，Esc 取消且不产生修订。日期根节点加号新建当日目标文件；历史快照不提供新增入口。


## 保持实例精简

`oks init`不复制`_meta/`、`templates/`、示例团队目标或示例配方。规范随程序维护，模板随Skill提供；已有自定义目录不自动删除。`--upgrade`刷新工具入口并补齐缺失默认配置，保留现有settings和profiles内容。团队初始化只补团队画像，不预设active目标；目标由实际讨论产生。

Raw先登记来源并按任务读取，不要求逐份材料生成Wiki。Wiki承载可复用判断，Skill承载执行方法；个人/团队是归属范围，文件独立，逻辑关联。源码和输出留外部工作区，知识与必要证据回库。

旧Raw情景召回仍扫描Markdown/JSONL正文；来源manifest尚不等于统一可搜索索引。低成本来源检索需独立验证覆盖、定位、时延与上下文成本，不能由目录调整宣称完成。

参数页沿用现有公式下的检索算法、召回数量与阈值、向量补召回和注入预算等开放项。格式规范、目录生成、是否逐份生成Wiki不是用户调参项，不额外增加开关。材料处理依据任务需求执行；将来只有在已有实现且取舍可观测时才考虑开放新的成本参数。保留默认值即可正常使用，不要求用户先调参。


## 跨工作区入口与对话引导

`oks skills-install --global --editor codex|claude|agents`只向选定宿主安装全局oh-my-oks，不要求当前目录是知识库，不修改其他Skill；存在入口时完整保留，显式`--force`先备份再更新发行文件。其他宿主核对自身支持，不将项目适配误称全局安装。

`oks onboarding status|complete|skip|reset`使用与Studio相同的三步引导记录；complete需指定discuss/goals/learning，代表教学步骤完成，不表示知识获批。个人库路径可用`--path`明确指定。


知识库根README说明用途和实际前置要求。`oks sources inspect <目录>`在关联前读取已提交README（兼容readme.md），返回来源版本与哈希，不自动注册、安装依赖或执行命令；工作区未提交要求不冒充共享版本。根README通过团队VFS可查阅，作为reference，不进入已审核知识召回。
