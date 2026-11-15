---
name: open-knowledge-studio
description: Install or connect OKS, configure its personal/team libraries and host Skill, then guide a new user through Discuss, Goal and Learning in conversation.
---

# Open Knowledge Studio · 首次接入

用户只需说“请按 https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md 安装OKS。”，不必附加讨论、目标或团队配置要求；本契约负责补齐这些引导。

这是给AI读取的一句话安装入口。用户将此链接交给你，表示希望你代为完成必要检测、安装、配置与引导，不是让用户照抄整页命令。

先用现有CLI、文件操作和宿主已连接工具完成工作。交接里的行为要求优先由本Skill编排，不默认开发成员、邮件、任务状态机或新页面。只有现有能力确实阻塞验收，且无可靠替代路径时，才提出可复现问题和最小源码修复。安装不默认启用团队通知；第5节仅在已有团队交接或用户选择团队协作时执行。

- 云端入口：https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md
- 日常入口：程序附带的 `oh-my-oks`。
- 结果：复用或创建独立个人库，安装当前宿主能发现的入口，按需关联团队库，再用真实小任务完成对话教学。安装成功与教学完成分别报告。

## 1. 先检测，再问缺失的信息

检查操作系统、Python（3.12+）、Git、pipx或已有隔离环境、`oks --version`、`oks config show`，以及当前宿主与已安装Skill。命令不存在时按当前平台查找可用解释器，不假定一定叫python。

实例判定看用户提供路径、已有全局配置和`wiki/`等实际目录；不要求`_meta/`存在。已有实例先连接，不另建一套，也不把用户知识放进OKS源码仓库。已有交接先读指定Thread、当前Goal与实例约定，确认原任务和授权范围；消息中的“待接手”或旧回执不是当前执行事实。

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

失败时保存同一次命令、退出码与pipx日志，核对pipx实际创建环境所用解释器，不能以终端的`python --version`代替。实际版本低于要求时，先检查已安装解释器，再按本机help使用`pipx install --python <已核实的解释器绝对路径> open-knowledge-studio`。分别诊断Requires-Python、HTTP 403、认证、代理和TLS；`from versions: none`不能单独证明Python太新或缺wheel。只在日志指向镜像故障时单次用官方索引复测，不永久改镜像、不关闭TLS。

先检查本机`oks skills-install --help`。支持时安装当前宿主的全局入口，不要求当前目录是知识库：

```bash
oks skills-install --global --editor codex
# 其他已支持全局目标：claude、agents，按当前宿主选择一个。
```

Codex尊重CODEX_HOME，Claude使用其全局Skill目录。已有入口保留，返回preserved不代表已更新；比较内容，用户已授权覆盖时才用`--force`，该模式先备份现有包。不移除其他Skill，不改写全局AGENTS。

WorkBuddy等其他宿主先按当前官方说明及本机设置核对用户级Skill目录、项目覆盖规则和加载方式；不能假定本机支持`--editor workbuddy`。不支持时，从已安装包的资源或已核实commit的`assets/skills/oh-my-oks/`取得完整原包，以文件操作放到核实的全局或项目Skill目录，包含全部references，不能只复制SKILL.md。先比较已有包：相同则复用，自定义或多处冲突先展示差异；已获覆盖授权才完整备份后替换，不改全局Skill偏好。项目已有`oks-knowledge`只读入口不等于已有`oh-my-oks`教学入口；可并存，不改其只读规则。保留的项目同名定制入口若优先于全局包，应说明官方入口在该项目尚未启用，等待用户选择适用上下文或授权合并，不能以全局文件已复制冒充生效。记录来源版本、目标范围和文件摘要，这属于安装现有资源，不要求新增CLI目标。

同时检查`oks onboarding --help`是否可用；安装的核心Skill应包含references/onboarding.md。旧CLI缺少上述参数时，不伪造成功：先确认官方升级路径并检查升级后的help；需要源码版本时只用官方仓库固定commit并说明版本来源。先用`git ls-remote https://github.com/open-agent-power/open-knowledge-studio.git HEAD`取得官方commit，再按已核实的SHA安装`git+https://github.com/open-agent-power/open-knowledge-studio.git@<SHA>#subdirectory=cli`；pipx已安装官方包时可用`pipx install --force`刷新该包，原本是自定义源码安装时先说明替换影响。新命令尚未发布到所选分发渠道时，报告限制，不假定PyPI已包含main全部改动。

分别记录文件安装、宿主列出、显式调用、自动触发四种证据。通过宿主实际入口调用`oh-my-oks`，让其按当前任务只展示第一步并等待用户；这只能证明本次显式入口。只能下一轮或新会话生效时如实说明；无法进入该宿主时标未验证，用户提供的回复标明证据来源。不从设置字段、列表截断或重启推断根因，不把读文件或doctor检查当作真实调用。doctor失败要区分入口、只读约束与未审核Wiki；未建Wiki不要求伪造审核，格式误报也保留原结果。

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

若`oks sources list`因YAML日期等序列化错误失败，保留命令和错误，不改团队原文规避。可只读检查当前实例`settings/sources.yaml`，结合`git rev-parse`/`git show`与实际可用的`oks fs ls/read`逐项验证关联、已提交版本和正文。替代路径通过不等于失败命令已修复；没有可靠读取路径时报告阻塞，不默认升级成产品改造。

个人与团队物理独立，OKS逻辑关联；PR合并不等于知识审核。没有团队库也可完成安装。个人讨论、简历与私有反馈不自动贡献团队。

自动hook只在用户选择启用后，对实际支持的宿主使用`oks hook install --editor ...`并检查`oks hook status`。全局入口能找到默认库不代表hook已对所有工作区生效；对真实宿主配置检查作用范围。无法执行hook或不支持的平台明确报告。

## 4. 在对话中教会，而非打印使用手册

读取安装后`oh-my-oks/references/onboarding.md`，复用`oks onboarding status --path <个人库>`和网页相同的进度。

先问“你现在想解决或学习的一件小事是什么？”已有当前任务就用它，不另造任务。
- Discuss：保留人的判断、AI理解与待确认，不要求把整段聊天复制入库。
- Goal：从讨论形成当前约定，写成几条可验收TODO；用户只想学习时不强行变项目管理。
- Learning：查相关知识和来源，提出真正可复用的候选，让用户决定保留、修改或暂不收录。

每次只解释眼前一步，并让用户看到实际文件或页面。人的判断引用真实表达，AI推测放待确认；未经用户表达，不替他选择学习目标或生成永久偏好。用户可跳过、暂停后续接，跳过与完成分别记录；本机`onboarding skip`若只支持整段教学，不能用它代替只跳过Learning，可在现有进度记录中注明。已有completed与对话证据矛盾时先核对，不因标记而跳过。需更正记录时说明依据并保留原件。Learning候选须由用户决定保留、修改或暂不收录，不自动晋升Wiki。

## 5. 有团队交接时，编排现有能力

以下是Agent遵守的协作约定，不是新增CLI功能或后台服务。沿用一个Goal保存TODO与验收条件，Mail保存交接和回执，Records保存证据；不要另建一份独立任务清单。只把本次选定的简短约定和Goal/Thread入口补入已获准修改的实例README，保留已有内容；缺少写权限时留本地草稿。后续会话通过日常Skill读取实例约定，不依赖安装会话的记忆。README不授予外部操作权限。

### 成员与可选提醒

- 按收件人读取`profiles/users/`中的稳定ID、完整`mail_identity`、姓名/别名、有效状态及必要邮箱。精确ID优先；必要时只扫描消歧字段，不全量输出通讯录。未知、同名/别名冲突或停用时不猜收件人；邮箱变更不改内部身份，不给普通Agent身份套人类成员规则。
- 将解析出的精确Mail身份交给已有`oks mail send/reply`；广播先列有效成员和人数，只按用户明确范围展开，`@all`仍是Agent/session语义。读取用`mail thread`，读完才`mail read`，已读不表示接手。共享Mail的创建/回复也须在明确发消息授权内；没有授权先备草稿。
- 邮箱提醒用宿主已连接的邮件工具或现有适配器；先查能力及所选渠道配置，再确认收件地址、具体提醒和服务在授权内。缺邮箱、无渠道、缺凭据、未授权分别记录，已获准的本地交接仍能保存。`--notify`是本地通知请求，不是邮件，不默认开发或安装邮件服务。
- Settings沿用现有渠道格式；如工具没有格式，可在现有settings下保存由Agent读取的渠道、目的地、手动/明确授权触发策略和凭据引用，注明不会被CLI自动执行。账号密钥只通过可信环境或连接器使用，禁止写入Git、Mail、日志。提醒只含必要摘要与相对交接定位，不发送整库、原始日志或机器路径。
- Records中按“消息ID＋稳定成员ID＋渠道”保存投递结果：状态、尝试次数、时间、目标/配置版本、提供商回执或脱敏错误；不保存秘密。损坏记录或与实际消息/收件人不一致时停止，不重置历史。先查已有成功记录（提供商明确accepted也阻止重发，最终投递与已读另记）；再指定唯一派送者，并通过现有工具的幂等键或同机排他锁防并发。拿到锁后重新读记录，先持久记录发送中，再调用工具，最后记录真实结果并释放自己的锁。不能可靠互斥时停止派送，不用一句文字约定冒充跨机器去重。
- 明确的暂时失败才在原授权范围内有限重试，默认总计最多3次；地址/服务变更需重新核对授权。超时、中断或结果不明记为unknown，遗留sending也先按结果不明核对；先查提供商，不盲目重发或自动清除残留锁。服务接受、本人已读、任务接手分别记录；没有真实测试邮箱证据就不标真实投递通过。

### 负责人、约定与回执

复用`oks task --help`中实际存在的start/show/checkpoint/refresh/handoff/complete；不调用不存在的成员、协作或记录导入命令。用已核实的OKS_ROOT指定任务所在实例；Mail中支持`--path`的命令使用线程所在团队库；`mail thread`按OKS_ROOT取库，不能混成个人收件箱。第一次读取后的接手和实施顺序也先备回执，有发送授权才写入原Thread。当前身份未参与旧线程时，thread/reply可能返回not found；在已有读取授权内，可读指定消息原文或用`mail snapshot --agent <已核实成员> --path <团队库>`核对其投影，不标成自己的已读。确有发信授权时，以自身身份`mail send --thread <原ID> --from <自身ID> --to <明确收件人>`接续，后续再reply；不冒用负责人身份，当前身份的thread输出也不代表完整历史。

Goal记录负责人、验收条件及稳定任务标识；执行Agent、阶段和通知进度写入现有checkpoint与Mail回执，会话/机器绑定留本机。路由和角色都是声明，不是身份认证。四阶段按以下真实事件记录，不能声称CLI强制执行了这套约定：

| 阶段 | 依据与动作 |
| --- | --- |
| 待接手 | 收到交接但尚未明确接受；已读或提醒不改变阶段 |
| 进行中 | 指定负责人/授权执行者明确接手当前Goal版本，保存回执 |
| 待验收 | 提交结果、命令退出码、相对证据路径与摘要；自测通过仍待负责人审核 |
| 完成 | 负责人明确验收该版本与证据后记录批准依据，再使用现有task complete；不因此批准Wiki |

先`task show`取当前revision、目标版本与artifact_issues，写进度使用`task checkpoint`的`--revision/--progress/--next/--artifact`。Goal或已选Wiki变化时先核对差异，确认接受后再refresh；产物变化须核对新文件，再checkpoint重新捕获摘要，`--artifact`列出本次应保留的全部产物，不能用refresh代替。约定过期导致checkpoint被拒绝时，保留旧快照，在原Thread及证据记录中说明变更阻塞，不为更新进度而擅自refresh。重新提交对应版本，不复用旧批准。新任务可用`handoff prepare`与`mail delegate --agreement`保存约定，再`handoff check`。旧Thread普通send/reply不支持agreement时，把Goal相对路径、版本/摘要与证据定位写在原线程正文；`--evidence-ref`仅使用现有schema支持的类型（trace/run/capability/bundle/commit用type与id，candidate/wiki用type与path），不捏造goal类型或假冒Wiki。逐项核对版本，不新建线程冒充原回执，不对无约定旧消息伪报handoff check通过。reply的身份须核对本机既有身份设置及实际输出，不捏造`--from`等参数。

利用现有Studio的Goal正文、进度、下一步、产物和Mail线程展示简短摘要，例如“负责人…；执行者…；任务待验收；通知未配置；已读未知；对方同步未知”，并附实际回执/证据引用。摘要来自当前记录；显示未知和证据时点，不因按钮点击更新成功状态。当前Studio路由身份看不到原Thread时，保留该限制，用已核实的投影/原文供核对，不通过增加收件人或伪装身份使页面看似通过；不新增顶层菜单或独立状态系统。

### 同步、共享与可选云端

- 区分本地已保存、Git已提交、远端推送成功、接收方已同步。缓存上游引用不是实时远端查询，发送者推送不能证明对方收到；接收方在自己的团队上下文显式同步、核对commit后才能报告。固定revision保持固定，HEAD跟随当前本地已提交版本；读取不会替用户pull。
- 查询使用只读Git命令。先核对本机`team sync`行为；会暂存/提交或rebase/autostash的命令不能用于查询或无差别共享。需要同步时，审阅准确文件清单，保留无关修改和暂存状态；按具体授权提交，拉取采用ff-only，遇脏工作区或分叉先报告。push、PR或发布另需明确授权，不因本次安装自动执行。
- 共享Goal、必要Mail正文/回执和相对证据；检查实际Mail前置信息及附件中的机器绝对路径、origin_session_id、origin_machine_id、账号凭据。含机器信息的消息不得直接发布；保留本地原件，生成不含这些信息的共享副本并验证仍可读取。副本仍放`mail/messages/<原message_id>.md`，保留现有行式前置信息（to单行、evidence_refs单行JSON），不重新用通用YAML改写；保持message/thread/收件人/版本不变，不重发生成新ID。只提交审核后的共享文件；已有消息正文可直接恢复线程，不为查看而伪造或覆盖接收方state投影。运行sessions、锁、临时通知、原始日志和整个.oks不共享；已读与验收的必要事实可在审核后的回执中共享，不能据发送者记录推定收件方已读。
- 不全量复制task handoff输出或内部task JSON，它们可能含机器上下文。接收端从共享Goal、Mail和证据重建本机任务，用稳定task/thread标识接续；重复同步不再发送同一交接。并发冲突保留双方正文及回执，明确解决后续接，不自动覆盖或静默重置记录。文件更新采用临时文件、flush/fsync及原子替换。
- 飞书/腾讯文档只在用户选定且已有可用工具时做单向摘要留痕。执行前按消息与目标查既有远端ID/链接，避免重复创建；结果不明先查询，失败保留本地交接，Records写真实链接/版本/错误。没有适配器则标待支持，不默认开发集成、不声称两端可任意修改同一任务。

## 6. 安装与交接验收

报告个人路径、全局/项目Skill范围、团队关联结果、hook实际范围、教学进度和未完成项。可按用户需要启动`oks mail serve --path <个人库> --local-edit`并打开页面，不替换已有占用端口的服务。

包安装、跨目录CLI访问、宿主发现、自动召回和知识审核分别验收；一次成功不能替代其他项。失败时报告具体阶段和已保存状态，不静默换远程服务或覆盖用户配置。

若任务是验收，逐项保留通过/失败/未测试/待支持及证据：环境与安装来源版本、原始命令和退出码、前后摘要、实际宿主行为及人员确认来源。至少覆盖无团队、已有个人库/Skill、依赖和权限失败；团队交接另覆盖同名、缺邮箱、缺渠道、正常投递、失败重试、重复/并发及跨库读取。只有真正没有安装过的隔离系统加新Agent、仅给一句话入口才算干净环境端到端；临时目录/新venv只是程序补验。模拟邮件、Agent演练和文案检查分别标明，不能代替真实发信、人工教学或收件端同步。

沿用原交接Thread，准备简短回执列出实施范围、逐项结果、未支持项、实际变更与测试证据。共享证据须接收方实际可访问；本机备份和日志只作本地索引。发送、推送或发布未获明确授权时保持草稿；修改了Skill不等于TODO已经执行并验收。

日常任务简单或已掌握上下文时无需强制召回。Raw按需读取，Wiki与Skill按不同目的选择；安装本身不触发全文入库或知识晋升。
