# examples/ — 可复制案例与协议样例

这里放**可复制的样例**，不是框架的一部分：

- `assets/` 是产品（打包给每个用户的实例模板）
- `examples/` 是示范（想用就 copy 到你自己的实例里改）

分开的好处是框架仓保持干净，示例可以独立迭代——增加或修改案例不会改变 Core，
也不会进入安装包。每个完整场景在自己的目录中说明目标、材料和验收方式；本页只说明
`examples/` 的边界，不维护第二份案例目录。

## 关于评测数据集

`datasets/recall-v1.example.yaml` **只是格式示例，不能当真值集用**。
有意义的评测需要你自己的查询和你自己知识库里的正确答案——
别人的数据集测不出你的召回质量。

```bash
cp examples/datasets/recall-v1.example.yaml eval/datasets/mine.yaml
# 编辑：query 换成你真的会问的问题，relevant 换成你知道的正确页面
oks eval recall eval/datasets/mine.yaml --output eval/runs/baseline.json
```

## 关于个人画像与 goal

`goals/`、`projects/`、`users/` 下的内容是**维护者的真实使用记录**，
留在这里当范例——展示一个用了几个月的 goal / 画像长什么样，比空模板有参考价值。

空模板在 `assets/profiles/` 里，`oks init` 会自动物化到你的实例。
