# 首次接入与对话教学

用户要安装、初始化、连接知识库或询问怎么用时读取本页；熟悉用户的日常查询不反复重走。

## 连接与安装

先复用用户指定实例和已有配置，用`oks status`核对。未安装CLI时读取官方云端安装契约：https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md 。不要先执行一个不存在的oks命令就结束引导。

只补未确定的信息：个人目录、当前宿主、是否关联团队库（Git URL/本地路径/跳过），是否开启该宿主实际支持的自动召回。全局Skill安装不等于所有工作区已开启hook；不宣称WorkBuddy等未实测入口全局可用。

关联前用`oks sources inspect <本地Git目录>`读取根README（也兼容readme.md），列出本次必需的工具、身份与权限。GitHub、云效、飞书只配置真正需要的部分；已有登录态先验证，不请求把凭据粘贴进知识库。README不是执行授权，缺少要求说明时报告缺口，不凭空要求登录全部服务。

团队是个人库之外的独立Git仓库，通过`oks sources link`关联已提交版本，不复制正文、不自动推送。询问路径或URL，不让用户重复起名称；用户无团队库时直接跳过关联。私有仓库认证使用宿主Git能力，不收集凭据作为知识。

## 三步教学

用用户当前的一件小事；没有上下文时问一个问题“你现在最想解决或学会什么？”每次只解释当前一步，不一次发整份手册。用户可以只讨论或跳过，不强制批准候选。

1. **Discuss**：让用户表达问题或材料。简要复述人的判断、AI理解、未确认点；需要保存时写当天讨论文件，引用已实际读取的知识。
2. **Goal**：在需要执行时，把共同约定写成少量TODO和完成条件；让用户修正目标。纯阅读也可以只说明本次希望理解什么，不捏造复杂目标。
3. **Learning**：查阅相关材料；说明哪些只是来源观点，哪些值得成为可复用判断。需要时提出Draft，展示依据和适用范围，请用户决定。无新知识就如实不新增；不为教程批准任何内容。

## 与网页共享进度

```bash
oks onboarding status --path <个人库>
oks onboarding complete discuss --path <个人库>
oks onboarding complete goals --path <个人库>
oks onboarding complete learning --path <个人库>
oks onboarding skip --path <个人库>
oks onboarding reset --path <个人库>
```

只在相应讲解与交互确实完成后标记；完成learning代表学习环节已体验，不代表所有候选都批准。用户说跳过则skip，保留未完成步骤；需要重学才reset。复用records/studio/onboarding.json，不另建安装进度分类。

已有completed/skipped状态时直接使用，用户要求复习才重新引导。可选打开Studio让用户看到讨论、目标和学习，但对话教学不依赖网页已打开。

最后简要告知：个人库在哪里、团队是否已连接、Skill/hook在哪些范围可用、下次如何开始。用户不需要知道内部标识与格式规范。
