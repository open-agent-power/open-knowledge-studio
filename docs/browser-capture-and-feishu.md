# 浏览器登录态捕获与飞书移动入口

> 讨论日期：2026-07-15
>
> 状态：方向设计，尚未进入实现
> 前提：继续遵守 Raw“只提取、排序、打包、保留证据和暴露失败”的边界。

## 1. 要解决的问题

本地文件已经可以交给可注册 Raw Adapter 处理，但用户在现实中更多通过抖音、B站、视频号、微信公众号、AI 对话网页等平台接触信息。这些平台可能存在登录态、动态渲染、临时签名、设备指纹、验证码、分片媒体和平台规则限制。

核心判断：浏览器扩展可以显著降低“后端拿不到用户正在看的内容”的问题，但不能让反爬和平台规则消失。

## 2. 两个入口的职责

### 2.1 浏览器扩展：桌面端登录态捕获器

浏览器扩展在用户明确点击后读取当前页面已经呈现给用户的内容，优先采集：

- URL、标题、作者和发布时间；
- 可见 DOM、正文和用户选区；
- 页面已有字幕、章节和时间定位；
- 页面内嵌的结构化数据；
- 当前页面截图或用户选择的证据区域；
- 用户填写的保存原因、评论和关注点。

第一版使用 `activeTab + scripting + storage`，避免默认申请 `<all_urls>`。扩展只发送提取结果，不导出、不上传 Cookie、Token 或完整浏览会话。

`declarativeNetRequest` 适合阻止、重定向或修改网络请求与部分请求头，不应被描述为通用的响应正文读取能力。读取响应正文需要更重的 DevTools/debugger 能力或脆弱的页面脚本注入，因此不作为第一版默认路线。

### 2.2 飞书机器人：移动端收件箱与控制入口

飞书机器人负责：

- 接收用户主动分享的链接、图片、视频、文件和评论；
- 下载飞书消息中可直接取得的资源；
- 生成 Capture 记录并返回处理状态；
- 将需要登录态的链接标记为待补全；
- 在桌面扩展完成捕获后，将结果与原飞书消息绑定。

飞书机器人收到链接并不意味着后端拥有用户浏览器登录态。只把链接发给机器人时，后端仍可能遇到 412、验证码、Cookie 缺失、临时签名和平台风控。

## 3. 推荐架构

```text
                 用户主动保存
                       │
          ┌────────────┼────────────┐
          │            │            │
     浏览器扩展     飞书机器人     本地文件
     桌面登录态     移动端收件箱   用户直接提供
          │            │            │
          └────────────┼────────────┘
                       ↓
                Capture Envelope
       来源、正文、字幕、截图、评论、获取方式
                       ↓
                  Source Adapter
       通用网页 / B站 / 抖音 / 飞书 / 本地文件
                       ↓
              Agent-selected Raw Adapter
                       ↓
           Raw Markdown + Evidence + Assets
```

Capture Envelope 至少包含：

```json
{
  "source_url": "https://example.com/item",
  "captured_at": "2026-07-15T00:00:00+08:00",
  "platform": "example",
  "acquisition_method": "browser_active_tab",
  "title": "页面标题",
  "content": "用户实际看到并主动保存的内容",
  "locators": [],
  "assets": [],
  "human_context": {
    "save_reason": "为什么保存",
    "comment": "用户补充的思考"
  }
}
```

该 Envelope 是来源获取层的交接格式，不替代 Raw v0.1，也不包含 Cookie、Token、账号密码或浏览器指纹。

## 4. 移动端链接的三级回退

### A：机器人可以直接取得

普通网页、官方 API/RSS、用户直接发送的图片/文件/小视频可以立即进入 Raw Pipeline。

### B：只能取得部分信息

保存 URL、标题、平台、分享时间、用户评论和可见预览，并明确记录证据不完整。

### C：必须依赖登录态

机器人返回“链接已保存，等待桌面登录态补全”。用户以后在已登录浏览器中打开页面并点击扩展，系统按 URL、消息 ID 或 Capture ID 补全同一条记录。

## 5. 不采用的做法

- 不上传或集中保存用户 Cookie；
- 不静默遍历浏览历史；
- 不默认全量监听网络响应；
- 不后台批量下载平台视频；
- 不绕过验证码、DRM、付费或访问权限；
- 不把“用户能看见”误认为“平台允许程序批量复制和长期保存”；
- 不让平台抓取逻辑进入 Raw 核心。

## 6. 实施顺序

1. 先保持当前 Level-1 Raw Adapter 稳定；
2. 做最小浏览器扩展：点击后获取 URL、标题、正文、选区、截图和保存原因；
3. 设计本地 Bridge，将 Capture Envelope 交给 Agent 选择的 Raw Adapter；
4. 增加一个真实存在字幕的 B站登录态样本；
5. 再接入飞书机器人，完成链接/文件/评论接收和待补全绑定；
6. 最后按真实缺口增加抖音、视频号等平台 Adapter。

## 7. 参考边界

- Chrome `activeTab`：<https://developer.chrome.com/docs/extensions/develop/concepts/activeTab>
- Chrome 扩展权限：<https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions>
- Chrome `declarativeNetRequest`：<https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest>
- Chrome `debugger`：<https://developer.chrome.com/docs/extensions/reference/api/debugger>
- 飞书接收消息：<https://open.feishu.cn/document/server-docs/im-v1/message/events/receive>
- 飞书获取消息资源：<https://open.feishu.cn/document/server-docs/im-v1/message/get-2?lang=zh-CN>

一句话结论：浏览器扩展是“用户主动授权的登录态捕获器”，飞书机器人是“移动端收件箱”，二者最终都把标准化 Capture 交给同一组可注册 Raw Adapter。
