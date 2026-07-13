---
title: 可复现性 checklist
tags:
- research
- reproducibility
- science
- ml
area: research
source: session/research-paper-figure-20260604
last_verified: 2026-06-04
type: strategy
status: active
importance: 0.7
confidence: 0.919
created: 2026-06-04
pinned: false
archived: false
access_count: 0
---



# 可复现性 checklist

## 投稿前必填（NeurIPS 风格）

### 数据
- [ ] 数据集名称 / 来源 / 版本号
- [ ] 预处理步骤完整描述
- [ ] 数据划分（train/val/test 比例 + 是否固定 random seed）
- [ ] 公开数据集：给 DOI / link；私有数据集：解释为什么不公开

### 代码
- [ ] 代码 link（GitHub / Zenodo with DOI）
- [ ] README 含一行命令复现主结果
- [ ] requirements.txt / environment.yml 含精确版本（pin）
- [ ] 主实验脚本（不只是 lib 代码）

### 实验
- [ ] 硬件描述（GPU 型号 / 内存 / CPU）
- [ ] 训练时间（h / 天）
- [ ] 随机种子（main + 至少 3 个 seed 跑平均）
- [ ] 超参数搜索范围 + 选定值的依据
- [ ] 评估 metric 完整定义（公式或 reference）

### 报告
- [ ] 均值 + 方差 / std（不能只报一次结果）
- [ ] 显著性检验（如适用）
- [ ] failure cases 也讨论（不只是成功 case）
- [ ] 计算资源消耗（论文末 appendix）

## 反模式（reviewer 一抓一个准）

- ❌ "Code will be released upon acceptance"（reviewer 已经厌烦这话）
- ❌ 只跑一个 seed 报点估计
- ❌ baseline 用自己实现 + 不公开（被怀疑刻意降）
- ❌ 主结果在 best seed 而非 mean
- ❌ 数据预处理 hand-wave（"we follow standard preprocessing"）
- ❌ requirements.txt 写 `torch>=1.0`（应该 pin 到 1.13.1）

## 工具推荐

- **WandB / MLflow**: 实验跟踪
- **DVC**: 数据版本控制
- **Hydra**: 配置管理
- **Docker**: 环境封装
- **Papers with Code**: 公开 model / leaderboard
- **Zenodo**: 给代码 DOI（投稿引用稳定）
