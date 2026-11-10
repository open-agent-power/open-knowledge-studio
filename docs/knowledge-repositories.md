# 个人库、团队库与 OKS 代码

OKS 是工具；个人库和团队库是独立的数据仓库。统一使用入口，不复制成一个混合知识目录。

## 两个知识文件夹

```text
knowledge/
├── personal-knowledge/             # 独立个人 Git 仓库
└── team-knowledge/                 # 独立团队 Git 仓库

# 每个库使用相同核心桶
raw/YYYY/MM/DD/                    # 原始证据与转换产物
drafts/                           # 待审核候选
wiki/                             # 审核后可复用知识
skills/                           # 可执行能力包
profiles/                         # 背景、项目、讨论、目标
records/                          # 调用、评测、审核、迁移等记录
settings/                         # 库声明与配置
```

文件夹不必处于同一父目录。个人库中配置团队库的实际路径即可；符号链接只是入口，不是第二份正本。个人库和团队库共享目录协议，团队库可用 `oks team init` 创建。它不承接个人聊天、私有画像或个人运行日志。

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
- 团队库：只编辑路径，名称直接显示文件夹名，保存整组关联；已有内部引用标识保持稳定。仓库标识从已提交的 `settings/library.yaml`、兼容 Catalog 或 Git origin 读取；先校验所有条目，再原子替换 `settings/sources.yaml`。已有固定版本保持不变，换目录或新增时使用 `HEAD`。
- 解除关联只移除个人配置，不删除团队仓库。无效目录、过期编辑或校验失败不会覆盖原配置。只读服务可查看，修改需要 `--local-edit`。

文章创作等工作区可以独立保存稿件和产物，沿用个人知识库作为知识正本。先讨论读者、选题与判断，再形成目标，写作反馈经过确认后才形成长期知识候选；工作区不必复制个人库或团队库。

## 跨库读取与兼容

普通OKS实例直接按wiki/、drafts/、raw/、skills/、profiles/和records/中的Markdown建立只读视图；Wiki沿用个人库的human_reviewed_at标记，未审核、废弃和技能登记不进入知识召回。该标记是状态依据，不能独立证明审核人身份。

旧团队库的catalog/knowledge.yaml、knowledge/和sources/index.json保持兼容。迁移后的可选records/catalog/knowledge.yaml继续保存稳定ID、旧路径和精确正文审核哈希；settings/library.yaml可声明repository与source_index。候选迁入drafts/不改变审核状态。修改正文必须重新审核，不能更新旧批准哈希来伪装有效。

跨库结果保留命名空间、提交、路径、状态和哈希。团队文档可用 `oks fs ls oks://team/` 与 `oks fs read oks://team/<source-id>/<path>` 读取；该视图只暴露已索引的提交文档，不能写入或越过知识桶访问机器配置。读取结果中的revision用于重现该版本。图谱解析显式相对链接、稳定团队ID和oks://team/链接，不把同名标题推断成同一知识。

团队召回目前仍是独立词法通道，不混入个人BM25分数。类型筛选按知识类型执行；查询合并不表示联合排序质量已完成评测。关联本地HEAD不会自动拉取远端，也不读取未提交修订。技能在图谱中可见不表示已安装或会自动执行。
