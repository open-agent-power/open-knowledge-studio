# 飞书 E2E 状态

日期：2026-07-29

状态：`partial`（部分通过）

本页修正飞书相关验收表述。飞书是可选的私有控制面，用于采集、状态和审核。非飞书场景的 OKS CLI 闭环不依赖飞书。

## 当前真值表

| 断言 | 状态 | 含义 |
|---|---|---|
| `api_form_submission_to_raw` | `passed` | API 创建的记录可以进入 Worker 路径并到达 Raw/Candidate。 |
| `public_form_human_submission` | `not_run` | 真人打开公开表单并提交 URL/附件，尚未在已记录运行中验证。 |
| `candidate_private_message_notification` | `passed` | Candidate 审核通知可以发送给审核者。 |
| `review_consumer_startup` | `passed` | 事件消费者可以启动并暴露就绪状态。 |
| `review_websocket_connected` | `passed` | 观察到 WebSocket 连接。 |
| `native_review_event_delivery` | `failed` | 在记录的限时窗口内，未收到任何原生审核事件。 |
| `reconcile_review_recovery` | `passed` | 恢复机制可以补救遗漏的审核状态。 |
| `feishu_e2e` | `partial` | 完整的实时事件链路未被证明。 |

## 边界

采集和审核是两条独立路径：

- 采集路径：公开表单 -> 多维表格记录 -> Worker -> 提取器 -> Raw -> Candidate。
- 审核路径：Candidate 私信 -> 用户审批 -> 飞书 `im.message.receive_v1` 事件 -> Worker 关联 -> Wiki 晋升。

`im.message.receive_v1` 与公开表单采集无关。Agent 可以启动和监控监听进程，但不能替代飞书开发者后台的管理员配置。WebSocket 连接不等于事件送达。

`reconcile-review` 在网络中断、进程重启或事件遗漏时仍然有用。仅靠 reconcile 成功的流程必须保持 `partial`，不能标记为 `passed`。

## 下一次有效飞书测试

下一次飞书验收测试必须使用专用的测试多维表格和运行时凭据。应证明：

1. 真人打开公开表单。
2. 真人提交 URL 或附件。
3. Worker 认领该记录。
4. 仅安装所需的提取器。
5. 生成 Raw 和 Candidate。
6. 用户回复明确的批准。
7. 原生实时事件送达，无需手动提供 message_id。
8. Wiki 晋升、搜索、召回、lint 均完成。

全部八项断言通过之前，飞书状态保持 `partial`。
