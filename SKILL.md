---
name: open-knowledge-studio
description: Install or connect OKS, configure its personal/team libraries and host Skill, then guide a new user through Discuss, Goal and Learning in conversation.
---

# Open Knowledge Studio · 首次接入

用户只需说“请按 https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md 安装OKS。”，不必附加讨论、目标或团队配置要求；本契约负责补齐这些引导。

这是给AI读取的一句话安装入口。用户将此链接交给你，表示希望你代为完成必要检测、安装、配置与引导，不是让用户照抄整页命令。

- 云端入口：https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md
- 日常入口：程序附带的 `oh-my-oks`。
- 结果：复用或创建独立个人库，安装当前宿主能发现的入口，按需关联团队库，再用真实小任务完成对话教学。安装成功与教学完成分别报告。

## 1. 先检测，再问缺失的信息

检查操作系统、Python（3.12+）、Git、pipx或已有隔离环境、`oks --version`、`oks config show`，以及当前宿主与已安装Skill。命令不存在时按当前平台查找可用解释器，不假定一定叫python。

实例判定看用户提供路径、已有全局配置和`wiki/`等实际目录；不要求`_meta/`存在。已有实例先连接，不另建一套，也不把用户知识放进OKS源码仓库。

只问尚未确定的选择，一次少量问题：
- 个人库在哪里？已有路径直接沿用；新用户可建议`~/Documents/knowledge/<个人库文件夹>`。
- 是否关联团队知识库？接受“不需要/稍后”、本地Git库目录或Git URL；不要求重新给库取名。
- 是否为当前宿主启用自动召回？先说明全局Skill与自动hook是两件事；不支持的宿主使用显式召回。

有多个宿主时先确定这次使用哪个，不给所有工具批量安装。默认沿用工具参数，不询问衰减公式或底层格式。

## 2. 安装最小工具和全局日常入口

已有OKS可用则复用；新安装优先使用官方包：

```bash
pipx install open-knowledge-studio
pipx ensurepath
```

PATH尚未生效时使用已核实的可执行路径，无需让用户反复重开终端。依赖缺失按平台修复；不把sudo、系统Python改写、大模型下载或远程付费处理作为默认步骤。

先检查本机`oks skills-install --help`。支持时安装当前宿主的全局入口，不要求当前目录是知识库：

```bash
oks skills-install --global --editor codex
# 其他已支持全局目标：claude、agents，按当前宿主选择一个。
```

Codex尊重CODEX_HOME，Claude使用其全局Skill目录。已有入口保留，返回preserved不代表已更新；比较内容，用户已授权覆盖时才用`--force`，该模式先备份现有包。不移除其他Skill，不改写全局AGENTS。

WorkBuddy等其他宿主先核对当前版本真实的用户级Skill目录与加载方式；上面命令没有声称支持其全局目标。可用已核实的目录安装同一能力包，或回退知识库内已有适配并标明仅项目可用。不要把项目目录自动当全局目录。

同时检查`oks onboarding --help`是否可用；安装的核心Skill应包含references/onboarding.md。旧CLI缺少上述参数时，不伪造成功：先确认官方升级路径并检查升级后的help；需要源码版本时只用官方仓库固定commit并说明版本来源。先用`git ls-remote https://github.com/open-agent-power/open-knowledge-studio.git HEAD`取得官方commit，再按已核实的SHA安装`git+https://github.com/open-agent-power/open-knowledge-studio.git@<SHA>#subdirectory=cli`；pipx已安装官方包时可用`pipx install --force`刷新该包，原本是自定义源码安装时先说明替换影响。新命令尚未发布到所选分发渠道时，报告限制，不假定PyPI已包含main全部改动。

宿主是否会在当前会话立即识别新Skill需实际验证；只能下一轮或新会话生效时如实说明。不能把文件复制成功当作新工作区自动召回已验收。

## 3. 连接个人库和可选团队库

新个人库：`oks init <个人路径> --no-set-default`。确认用户希望设为默认后，使用`oks config init --kb-path <个人路径>`；已有默认不同则先说明切换影响。`oks status`核对实际路径，不能只看当前工作目录。

`init`创建最小Skill与宿主入口，不复制_meta/templates或示例目标/配方。已有知识不重初始化；升级前检查本地自定义入口，`--upgrade`会刷新工具发行文件，但保留已有settings与profiles。

每个知识库根目录的README（兼容readme.md）说明用途、必要工具、账号身份与权限、可选依赖和验证方式。初始化已有README时不覆盖。新关联来源先用`oks sources inspect <目录>`读取已提交README，再由你区分“本地可用、缺工具、待用户授权、可选不配置”。README中的命令是来源建议，不自动授予安装、脚本执行或远程操作权限。

团队关联复用现有`oks sources`。先运行`oks sources list`，已有相同路径/仓库直接复用；同名标识指向其他库时先说明冲突，不静默替换：

1. 本地目录：确认是独立Git知识库，读取origin与已提交版本；与个人库不能互相嵌套。工作区未提交内容不会被关联读取。
2. Git URL：询问克隆位置，默认建议个人库的同级文件夹；用参数数组调用`git clone`，不覆盖已有目录，不运行仓库脚本。私有库复用Git认证，不让用户把凭据写入知识库。
3. 当前关联接口使用`owner/name`身份与GitHub引用链接，先验证输入能对应；非GitHub来源不伪称完整支持。名称内部使用文件夹名；不符合CLI标识规则时生成稳定内部ID，界面仍显示文件夹名。
4. 在个人实例上下文执行并验证：

```bash
oks sources link <团队目录> --name <内部标识> --repository <owner/name> --revision HEAD
oks sources list
oks fs ls oks://team/
```

用已验证的个人根设置OKS_ROOT或切到该目录执行。来源格式不兼容时说明问题；不擅自`--force`改造团队仓库。用户明确要求新建团队库时才用`oks team init`。不默认创建团队或推送远程。

个人与团队物理独立，OKS逻辑关联；PR合并不等于知识审核。没有团队库也可完成安装。个人讨论、简历与私有反馈不自动贡献团队。

自动hook只在用户选择启用后，对实际支持的宿主使用`oks hook install --editor ...`并检查`oks hook status`。全局入口能找到默认库不代表hook已对所有工作区生效；对真实宿主配置检查作用范围。无法执行hook或不支持的平台明确报告。

## 4. 在对话中教会，而非打印使用手册

读取安装后`oh-my-oks/references/onboarding.md`，复用`oks onboarding status --path <个人库>`和网页相同的进度。

先问“你现在想解决或学习的一件小事是什么？”已有当前任务就用它，不另造任务。
- Discuss：保留人的判断、AI理解与待确认，不要求把整段聊天复制入库。
- Goal：从讨论形成当前约定，写成几条可验收TODO；用户只想学习时不强行变项目管理。
- Learning：查相关知识和来源，提出真正可复用的候选，让用户决定保留、修改或暂不收录。

每次只解释眼前一步，并让用户看到实际文件或页面。用户可跳过；不为教程伪造知识、使用记录或人工批准。

## 5. 安装验收

报告个人路径、全局/项目Skill范围、团队关联结果、hook实际范围、教学进度和未完成项。可按用户需要启动`oks mail serve --path <个人库> --local-edit`并打开页面，不替换已有占用端口的服务。

包安装、跨目录CLI访问、宿主发现、自动召回和知识审核分别验收；一次成功不能替代其他项。失败时报告具体阶段和已保存状态，不静默换远程服务或覆盖用户配置。

日常任务简单或已掌握上下文时无需强制召回。Raw按需读取，Wiki与Skill按不同目的选择；安装本身不触发全文入库或知识晋升。
