# Browser Provider

用户已登录浏览器作为只读采集能力。Chrome 扩展阻塞中。

## 当前状态：blocked

Chrome 进程和 native host 正常，但 Default profile 未安装目标桥接扩展。
Chrome Web Store 页面显示该扩展无法下载。

## 连接后使用

Agent 通过 Chrome CDP 读取：
- DOM snapshot → 正文提取
- 页面截图 → agent-runtime 视觉理解
- 不导出 Cookie 或浏览器 Profile
- 不点赞、评论、关注或发送消息

## 安全边界

- 登录、扫码、验证码只能由用户操作
- 不绕过 CAPTCHA、付费墙或 DRM
- 不自动安装任何扩展或框架
