# 关联知识库与可观测调用

个人库保持一个 OKS 根目录；团队库保持独立 Git 仓库。OKS 关联读取两者，不将团队内容复制到个人 Wiki，不在团队库初始化 OKS。

## 关联团队库

```bash
oks sources link /path/to/team-knowledge --name team --repository owner/repo
oks sources list
oks sources unlink team
```

关联配置保存在个人库 `settings/sources.yaml`。个人与团队采用相同核心桶，支持普通OKS实例；仍兼容 `catalog/knowledge.yaml`、`knowledge/`、`sources/index.json` 旧格式。迁移目录和审核索引可保留于records/catalog/，来源位于raw/。读取本地 HEAD 的已提交 Git blob；可加 `--revision <40位SHA>` 固定版本。默认 HEAD 随本地提交更新，OKS 不执行 fetch、checkout 或上游脚本。

图谱显示来源仓库、完整提交、内容 SHA、原始证据链接与审核状态。标准Wiki依照审核元数据、Catalog条目依照绑定完整正文SHA的批准记录进入独立的 `team_knowledge` 召回通道；candidate 可浏览，但不会被自动批准。两个通道的词法分数不混合排序。当前离线 Wiki 评测仍只评个人 Wiki，不据此宣称已经验证团队联合召回质量。

团队更新由 Agent 在团队仓库分支修改、验证、发 PR；PR 合并不自动等于知识审核通过。

## 从使用记录形成数据集

```bash
oks eval capture --enabled --hash-query
oks recall "任务问题" --format json
oks use <slug> --observation <observation_id>
oks eval candidates
oks eval review <id> --query "任务问题" --accept good-slug --reject bad-slug --reason "不适用原因" --confirm
oks eval export --name personal-recall --kind recall
oks eval export --name personal-preferences --kind preference
```

- 基础调用观测始终保留查询哈希和命中来源，可作为未确认候选；扩展查询采集默认关闭，开启后默认仍只保存查询哈希，保留明文需显式 `--retain-query`。
- `oks use` / `oks wiki use` 记录显式使用。没有 observation 时记录独立使用事件，不猜测属于最近哪次查询。
- 采纳信号不直接变成人工 Gold。缺少反馈为未确认；拒绝必须明确提交并注明原因。
- `--clear slug` 撤回标签。补充或改写原问题需 `--derived-query`，不得冒充原始真实查询。
- 只有人工确认、来源版本未变化的标签才能导出。偏好对在同一查询内组合 accepted/rejected，保留来源 SHA 和审核事件。
- preference 导出是知识选择偏好对，不能直接声称为完整对话 DPO 训练集。
- 记录在 `records/evaluation/{observations,use-events,feedback,feedback-events,exports}`。原注入和 retrieval-debug 记录作为候选来源保留，旧的组级 used 不归因给所有命中。

## 虚拟文件与调用链

学习 → 文件展示现有 `oks://` 文件映射。`oks://skills/` 指向统一后的知识库 `skills/`；宿主安装入口只保留 `oks://host-skills/` 的显式兼容读取，不列入知识库浏览。旧 `oks://skill/`、`oks://goal/`、`oks://discuss/` 保留兼容解析，不在根目录重复展示。

```bash
oks fs ls oks:// --format json
oks fs read oks://wiki/example.md --format json
oks fs inspect oks://wiki/example.md --operation compare --limit 20000
```

普通 fs 命令保持原输出协议，额外保存观测；inspect 返回结果与 trace。界面/CLI 共用 VFS 的路径与 symlink 边界。记录真实解析、读取、裁剪、序列化 span 和父子关系；失败也保留。历史最多 200 条，写在 `records/observability/vfs.json`，不保存文件正文。

同文件对比固定同一文件、offset 和字符 limit，检查输出一致性。顺序固定 VFS 后直接读取，操作系统缓存未控制；单次结果不构成普遍加速结论。耗时不含观测落盘、HTTP、宿主和模型执行，字节数不伪装成模型 Token。

图谱 Query 详情复用同一调用时间线组件，显示任务配置、个人召回、团队来源等真实阶段；交互召回的阶段观测写到 `records/observability/recall.json`，只含查询哈希和命中来源元数据。它不代表宿主执行或模型生成的完整链路。
