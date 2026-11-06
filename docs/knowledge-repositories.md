# 个人库、团队库与 OKS 代码

OKS 是工具；个人库和团队库是独立的数据仓库。统一使用入口，不复制成一个混合知识目录。

## 两个知识文件夹

```text
personal-knowledge/                 # 私有 Git 仓库，个人正本
├── profiles/
│   ├── users/                      # 个人背景
│   ├── projects/                   # 项目画像，区别于项目源码
│   ├── agents/                     # Agent 背景与角色
│   ├── recipes/                    # 场景组合与约定，不代表自动执行
│   ├── discuss/YYYY/MM/DD/          # 讨论判断与开放问题
│   └── goals/YYYY/MM/DD/            # 每日目标与 Markdown 子目标
├── raw/YYYY/MM/DD/                  # 原始证据与转换产物
├── drafts/                         # 待审知识变更
├── wiki/                           # 已整理知识，审核状态须查证据
├── skills/                         # 可复用方法包
├── mail/                           # 交接事实
├── records/                        # 调用、时间轴、评测、迁移等记录
└── settings/sources.yaml            # 关联团队库，不复制其正文

team-knowledge/                     # 独立团队 Git 仓库
├── knowledge/                      # 团队内容
├── catalog/knowledge.yaml          # 稳定 ID、路径、状态与引用
├── sources/                        # 来源与人工审核凭据
└── governance/                     # 团队贡献与审核规则
```

文件夹不必处于同一父目录。个人库中配置团队库的实际路径即可；符号链接只是入口，不是第二份正本。团队库不必初始化成另一个 OKS 实例，也不存个人聊天、私有画像或个人运行日志。

## 查阅与贡献

```bash
OKS_ROOT=/path/to/personal-knowledge oks sources link /path/to/team-knowledge --name team --repository owner/team-knowledge
OKS_ROOT=/path/to/personal-knowledge oks sources list
```

关联读取团队仓库已提交的 Git 快照。`HEAD` 随本地提交更新；固定完整 commit SHA 用于可复现引用。工作区未提交修改不会自动成为共享知识，链接也不会代替拉取远端。

图谱可以展示团队候选及来源；检索供执行使用时只纳入审核证据有效的团队知识。个人与团队结果保留来源，不把不同评分直接混成一个可信度。冲突展示适用范围和版本，由人判断；不默认用个人偏好覆盖团队约束。

个人经验共享：挑选需要分享的内容与必要证据、去除私密信息 → 团队候选 → Git PR → 人工审核决定。PR 合并只表示代码或内容变更合入，不能替代知识审核。团队内容更新不覆盖个人 Wiki；个人补充留在个人库并引用团队稳定 ID 与 commit。

## 单一工具仓库

```text
open-knowledge-studio/
└── cli/
    ├── knowledge_studio/            # 知识管理、检索、界面与治理
    └── oks_connector/               # 采集、转换、Raw Bundle、可选搜索后端
```

安装 `open-knowledge-studio` 同时提供 `oks` 和兼容的 `oks-connector` 命令，不再依赖单独发布的 `oks-connector` 包。内部保留模块命名空间，减少已有调用的迁移成本。该部分沿用 Apache-2.0，原始 commit 和许可证在包内保留。

媒体、OCR、PDF 和 Embedding 的重依赖仍按需安装；合并仓库不意味着默认安装模型或启用语义检索。Connector 只做机械获取和转换，不生成知识结论、不自动审核或晋升 Wiki。第三方搜索后端仍可通过 entry point 扩展，不要求合并所有外部插件。

从旧版升级时应在独立环境验证新版，再切换运行环境，避免两个发行包同时占有 `oks_connector` 路径。旧 Connector 仓库可保留 Git 历史作为迁移来源；确认发布切换后再另行决定远端归档。

## Studio 中配置位置

点击右上角的知识库名称，可以查看当前个人库和团队关联目录，不新增主导航。

- 个人库：填写已有 OKS 实例目录并切换。页面重新连接，服务重新绑定观察器；同时保存 CLI 默认知识库位置。不会创建、搬迁或合并知识文件。显式 `--path` 和 `OKS_ROOT` 仍按原有优先级覆盖默认值。
- 团队库：只编辑路径，名称直接显示文件夹名，保存整组关联；已有内部引用标识保持稳定。仓库标识从已提交的 Catalog 读取；先校验所有条目，再原子替换 `settings/sources.yaml`。已有固定版本保持不变，换目录或新增时使用 `HEAD`。
- 解除关联只移除个人配置，不删除团队仓库。无效目录、过期编辑或校验失败不会覆盖原配置。只读服务可查看，修改需要 `--local-edit`。

文章创作等工作区可以独立保存稿件和产物，沿用个人知识库作为知识正本。先讨论读者、选题与判断，再形成目标，写作反馈经过确认后才形成长期知识候选；工作区不必复制个人库或团队库。
