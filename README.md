# ab

对拍工作台：任意 query JSONL + 两个 runner（官方 / 我们）→ answers → diff →
归因 → 负控。它不生成题面、不翻译规则、不修改 gisel。

```text
query JSONL ──> official runner ──> official answers ─┐
     │                                                 ├─> diff ─> verdict/attribution
     └─────────> ours runner ─────> ours answers ──────┘
```

输入题面由两个上游方提供，ab 只消费：

- `gisel cases` / `gisel domain` → G 题面；
- `upstream-source oracle` → U 题面。

## 状态

| WP | 内容 | 状态 |
|---|---|---|
| WP0 | 骨架、`SCOPE.md`、`CONTRACTS.md` | 完成 |
| WP2 | `tools/ab/*` 从 gisel 迁入，抽 key 契约，改 `test_scope.py` | 待做 |
| WP4 | G/U 组合、负控、`EVIDENCE.json`、`verify-evidence.sh` | 待做 |

## 布局（WP2 迁入后，保持扁平，不改文件名）

```text
CONTRACTS.md            与 gisel / upstream-source 的接口契约
SCOPE.md                做什么、不做什么
diff.py                 比较两个答案文件（0/1/2）
attribute.py            差异归因
ab.py                   编排：构建、跑、diff、报告
run-queries.py          runner 的崩溃恢复（asserted -> unanswerable）
query_runner_common.h   runner 公共实现
*_query_runner.cpp      各 target 入口
*_generated_ctor.cpp    各 target 的测试构造器
build-*.sh              runner 构建
run-*-end-to-end.sh     端到端一条命令
targets/*.json          target 适配器（strategy、inc 名、query 数）
tests/                  key 契约测试、diff 单测
```

## 依赖方向

```text
ab -> gisel CLI (gen/eval)         允许
ab -> gisel.answers (key 契约)     允许，必须有契约测试
ab -> gisel.cases / gisel.eval     迁移时抽掉；不得成为长期依赖
gisel -> ab                        禁止
```
