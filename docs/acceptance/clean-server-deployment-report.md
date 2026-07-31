# 干净服务器部署报告

日期：2026-07-29

远程主机：`root@47.82.119.154`

测试根目录：`/opt/oks-word-landing-20260729b`

清理后证据存档：`/opt/oks-word-landing-evidence-20260729`

生产项目未触碰：`/home/artboy-knowledge-studio`

OpenClaw 进程未触碰：`/usr/bin/node /home/openclaw/dist/index.js gateway --port 18789`

## 源码状态

测试使用的源码来自本地仓库 `HEAD`，对应提交：

`1e7cfaf fix: write ingest raw bundles under active kb`

源码压缩包：

`/tmp/oks-head-1e7cfaf.tar`

压缩包 SHA-256：

`cebe900b532aa4b08f15f16148b5526eddff3c8be9c682c78aa5cdf226c22158`

## 环境

| 检查项 | 结果 |
|---|---|
| 主机名 | `iZj6cbtjyd0o9lwltqg7weZ` |
| Python | `Python 3.12.3` |
| Git | `git version 2.43.0` |
| pipx | `1.4.3` |
| 根文件系统 | `79G`，测试前可用 `60G` |

## 命令与结果

| 步骤 | 结果 |
|---|---|
| `pipx install /opt/oks-word-landing-20260729b/src/cli --force` | 通过 |
| `oks --version` | `oks 0.2.4` |
| `oks init /opt/oks-word-landing-20260729b/kb` | 通过 |
| `OKS_ROOT=/opt/oks-word-landing-20260729b/kb oks status` | 通过 |
| 未安装 document 能力时 `oks ingest <txt>` | 预期失败，缺失 `document` 能力，退出码 `2` |
| `oks capability install document --yes` | 通过 |
| `oks ingest <txt> --mode quick --progress` | 通过 |
| Raw 位置断言 | 通过；最新 bundle 位于隔离 KB 内 |
| Candidate 草稿创建 | 通过；Agent 编写的最小草稿存储在隔离的 `drafts/` 下 |
| `oks drafts promote babbage-clean-server-poc` | 通过 |
| `oks search "Babbage clean server mental labour"` | 通过 |
| `oks recall "Babbage clean server mental labour verification"` | 通过 |
| `oks lint` | 通过 |
| `oks status` 最终状态 | 通过；`1` 条 Wiki 页面，`0` 条草稿 |

## 资源消耗

| 操作 | 耗时 | 峰值 RSS |
|---|---:|---:|
| 核心 `pipx install` | `11.58s` | `276304 KB` |
| `document` 能力安装 | `10.92s` | `109508 KB` |
| 安装 document 后 TXT 摄入 | `0.87s` | `111432 KB` |

测试目录大小约 `8.7 MB`，不含共享的 pipx virtualenv/cache。

## 关键发现与修复

首次干净服务器尝试发现了一个真实的产品缺陷：

`oks ingest` 进行了能力检测，但将 Raw 写入 `/root/raw/...` 而非当前激活的隔离 KB。这违反了"Raw 不得落入宿主机目录"的验收规则。

修复提交：

`1e7cfaf fix: write ingest raw bundles under active kb`

回归验证：

- `scripts/tests/test_raw_bundle_adapter.py`：`42 passed`
- 完整测试套件：`150 passed`
- 远程复测：Raw bundle 路径 `/opt/oks-word-landing-20260729b/kb/raw/20260729-232027-687843-0be7cbe1-pg4238-af31a5cc`

## 遗留发现

- `oks status --root <path>` 不是合法命令。正确方式是 `OKS_ROOT=<path> oks status` 或通过 `oks init` 设置的活动配置。
- `oks-connector --version` 仍报告 `0.1.0`，而 `oks --version` 报告 `0.2.4`；应统一。
- 干净服务器 Candidate 内容是最小化的、Agent 编写的，来自已批准的 Babbage 内容。它证明了 CLI 生命周期，但不构成全新的人工语义审核。
- 对猜测的 Gutenberg TXT URL 的公网下载返回 `404`；复测使用的是本地保存的公共领域源文件，并记录了 SHA-256。

## 远程证据文件

所有留存的证据位于：

`/opt/oks-word-landing-evidence-20260729/`

重要文件：

- `source-archive.sha256`
- `pipx-install.log`
- `pipx-install.time`
- `oks-init.log`
- `preinstall-status.txt`
- `document-install.log`
- `document-install.time`
- `ingest.log`
- `ingest.time`
- `raw-location-check.json`
- `drafts-list-before-promote.log`
- `promote.log`
- `search.log`
- `recall.log`
- `lint.log`
- `status-final.log`
- `wiki-files.txt`

## 清理结果

归档报告文件和 SHA-256 清单后：

- 已删除 `/opt/oks-word-landing-20260729`；
- 已删除 `/opt/oks-word-landing-20260729b`；
- 已删除失败运行的 `/root/raw` 测试输出；
- 已删除 `/tmp/oks-head-87315a3.tar`；
- 已删除 `/tmp/oks-head-1e7cfaf.tar`；
- 已卸载 root 用户的 pipx `open-knowledge-studio` 测试安装。

保留：

- `/opt/oks-word-landing-evidence-20260729`；
- `/home/artboy-knowledge-studio`；
- `/home/openclaw`；
- `/root/Desktop/kimi-k3-deep-analysis.md`。
