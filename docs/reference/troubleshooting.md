---
title: 故障排除
nav_order: 3
parent: 参考手册
---
# 故障排除

## `oks` 命令找不到

`pipx ensurepath` 后重新打开终端（PATH 需重载）。

## `oks --version` 过旧

```bash
pipx upgrade open-knowledge-studio
```

## `oks recall` 返回空

新实例的 `wiki/` 为空是正常的。先确认当前知识库路径正确，再按[第一次知识循环](../first-knowledge-loop.html)收录材料、提出候选并由人审核。保存到 Raw 不等于已经形成可复用知识。

## hook 不注入会话

`oks hook status` 确认安装路径；重启 Agent host（hook 在启动时读配置）。

## `oks ingest run` 报缺能力

重提取器是 opt-in：

```bash
oks capability install <watch|document|pdf|formula> --yes
```

纯 `.md` / `.txt` 只需 `document`；URL 取决于来源。

## pip 拒绝安装（externally-managed）

PEP 668：用 `pipx`，不要裸 `pip`。

## 镜像滞后于 PyPI

`pipx install open-knowledge-studio --pip-args="-i https://pypi.org/simple"`
