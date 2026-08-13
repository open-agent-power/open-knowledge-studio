# 飞书集成参考实现

> 自 OKS v0.5 起，飞书集成从 `oks` CLI 核心迁出为**参考脚本**。这里不再是
> 可安装的命令组，而是一份可读、可改、可独立运行的实现样本。

## 这是什么

`feishu_base_worker.py` + `feishu_setup.py` + `_lark_cli.py` + `feishu_worker/` 包，
合计约 6165 行，演示完整的飞书采集→Raw→Candidate→IM 审核闭环。

它曾随 `oks feishu` 命令组分发，但飞书是 SaaS 控制面 + 外部 `lark-cli`，
不属于「装完即用」的 CLI 核心（见 CONSTITUTION P4）。迁出后 OKS 核心更薄，
飞书作为案例保留在这里，供需要的人照抄、改造、自部署。

## 运行

从 `examples/feishu-loop/` 目录运行（这样 `code/` 在相对路径上可达）：

```bash
# 前置：lark-cli 已安装并认证（OKS 不代管你的飞书凭据）
lark-cli auth

# 一次性配置：创建 Base + 采集表 + 表单
python code/feishu_setup.py --base-name "Open Knowledge Studio" --table-name "每日知识采集"

# 日常循环
python code/feishu_base_worker.py run-once          # 认领→采集→Raw→Candidate
python code/feishu_base_worker.py listen-reviews --max-events 1 --timeout 5m
python code/feishu_base_worker.py review-once       # 应用审核动作并晋升
```

子命令与原 `oks feishu` 命令一一对应：`enqueue` / `run-once` /
`publish-candidate` / `review-once` / `listen-reviews` / `pending` /
`reconcile-review`。完整清单见 `python code/feishu_base_worker.py --help`。

凭据从环境变量读：

```bash
export OKS_FEISHU_BASE_TOKEN="<setup 输出的 base token>"
export OKS_FEISHU_TABLE_ID="<setup 输出的 table id>"
export OKS_FEISHU_REVIEW_USER_ID="<你的飞书 user id>"
export LARK_CLI_EXE="/path/to/lark-cli"   # 找不到时指定绝对路径
```

## 测试

```bash
cd examples/feishu-loop/code
python -m pytest tests/
```

`feishu_setup.py` 创建并读回校验一个严格的六问题用户表单：内容、附件、思考、
重点问题（可选）、评级、知识域。Worker 控制字段只存在于底层 Base 表中；如果
已有表单包含额外字段或顺序异常，setup 会拒绝报告成功，也不会自动删除底层字段
或历史数据。

setup 会把旧表单问题“希望解决的问题”安全更新为“重点问题（可选）”；读取层仍兼容
旧名称，避免迁移期间丢失已有记录内容。
旧评级文本仍可作为命令输入，并映射为 A/B/C；无法安全转换字段类型的旧表会明确
失败，建议使用新的 `--table-name` 创建干净表单。

## 相关

- 操作流程：[`../feishu-loop.md`](../feishu-loop.md)
- 示例 goal：[`../goal.md`](../goal.md)
- 状态机单一事实源：[`feishu_worker/states.py`](feishu_worker/states.py)
- 架构说明：[`feishu_worker/ARCHITECTURE.md`](feishu_worker/ARCHITECTURE.md)
