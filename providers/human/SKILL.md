# Human Provider

人工提供的证据。当所有自动化路径不可用或需要人工确认时使用。

## 适用场景

- 平台反爬挑战（验证码）
- 需要登录后才能看到的内容
- 用户想要自己控制内容的完整度
- 任何 `status: awaiting_human` 的降级终点

## 证据标注

所有人工证据标注 `agent_judgment: human_supplied`。
