---
title: Smoke First — 先跑最小验证再跑完整测试
tags:
- debugging
- test
- smoke
- strategy
area: computing
source: session/agentuniverse-pr598
type: strategy
status: active
importance: 0.7
confidence: 0.91
created: '2026-07-11'
pinned: false
archived: false
access_count: 0
---


# Smoke First

## 招式

跑完整测试套件之前，先用 1 行命令验证目标类能实例化。
2 秒排除"根本跑不起来"的问题，不用等 60 秒的测试套件失败。

## Python smoke

```bash
# 能否实例化？（catches missing abstract method）
python -c "from module.path import ClassName; ClassName()" 2>&1 | head -5

# 检查未实现的抽象方法
python -c "
import inspect, module.path
for name, val in inspect.getmembers(module.path.ClassName):
    if getattr(val, '__isabstractmethod__', False):
        print(f'MISSING: {name}')
"
```

## Java smoke

```bash
# 编译 + 检查 abstract
mvn compile -pl module -q 2>&1 | grep -i "abstract"
```

## TypeScript smoke

```bash
# 类型检查
npx tsc --noEmit 2>&1 | grep "has no implementation"
```

## 实战案例

**PR #598**：`HuggingFaceHubLLM` 没实现 `get_num_tokens()`。12 个 test 全部 `TypeError: Can't instantiate abstract class`。如果先跑 smoke（1 行命令，2 秒），就不用等 12 个 test 逐个失败。

## 决策树

```
改了代码
  → smoke instantiation（2s）
    → 失败 → 修抽象方法，不用跑 test
    → 成功 → 跑完整测试套件
```

## 关联

- CI Triage：`ci-triage.md`
- Run-tests skill：`plugins/autpilot-coding/skills/run-tests/SKILL.md`
