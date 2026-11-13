# W0 证据：门禁坏了会红

> 2026-11-12。对应规划 `2026-11-12-architecture-remediation.md` 的 M1。
> 证据绑定提交 `9c0391fff960f7f77064cfe6bcb0dcf71731f21b`。
> 基线文件：`src/gisel_ab/data/baseline-2026-11-12.json`
> sha256 `edd96ea3bb75b3d8f26918f8c1f787481ed1539d98bedfe8cb5c07ea80ad837e`。

## 1 结论

W0 的四件事已落地：

- `diff.py --queries`：题面是分母；缺 key（`missing_in_both`）和越界 key
  （`unexpected`）都 rc=1。
- `run-queries.py`：runner 非信号退出 rc=2，仍写答案和报告。
- 负控统一 rc：0=盲、1=抓到、2=输入错；只有 1 算成功。
- 基线快照：仓库 head、语料/产物/feature sha、target 注册表、EVIDENCE 计数。

## 2 A1–A5

### A1 两份答案被截到同一个前缀

命令与输出：

```text
query set mismatch: queries=4 ref=2 ours=2 missing_in_both=2 unexpected=0
rc=1
{ref:2, ours:2, query_count:4, missing_in_both:2, unexpected:0,
 agree:2, disagree:0}
```

旧行为是 `agree=2, disagree=0, rc=0`；现在分母把截断暴露出来。

### A2 一条题面两侧答案都没有

```text
query set mismatch: queries=3 ref=2 ours=2 missing_in_both=1 unexpected=0
rc=1
{query_count:3, missing_in_both:1, unexpected:0}
```

### A3 runner 以 exit 3 退出

```text
rc=2
runner: exit 3 on query 1
report: {queries:1, answered:0, failed_at:1, failed_queries:1,
         error:"runner: exit 3 on query 1"}
answer: {"...","status":"unanswerable","reason":"runner-error"}
```

答案文件和报告都写了；rc=2 不可能被下游当成完整答案。

### A4/A5 负控退出码

`env.sh:classify_negative_rc` 的表：

| 输入 rc | 含义 | 包装脚本返回 |
|---|---|---|
| 0 | 注入没被观察到（盲） | 1 |
| 1 | 抓到 | 0 |
| 2 | 输入/基础设施错 | 2 |
| 其他 | 按输入错处理 | 2 |

真实 m68k 负控（`run-g-negative.sh m68k G_MUL`）：

```text
rc=0
by_ruleset: {"M68k_G_ADD": 7}
covered_expected: ["M68k_G_ADD"]
g-negative m68k G_MUL: caught
```

真实坏输入（`run-g-negative.sh m68k NOT_AN_OPCODE`）：

```text
inject: ... does not build NOT_AN_OPCODE
input error: could not inject NOT_AN_OPCODE into ...
rc=2
```

盲路径由 `tests/test_negative_scripts.py` 用假 e2e（exit 0）锁住：脚本 rc=1，
消息 `control blind`。同一测试还锁住“rc=1 但没有 diff.json”必须 rc=2。

## 3 真实语料回归

### 3.1 九个 target 的 G 端到端（真实构建 + include）

| target | query_count | agree | answered_equal | ref_asserted | unanswerable | missing_in_both | unexpected | rc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| x86 | 3,014 | 3,014 | 3,014 | 0 | 0 | 0 | 0 | 0 |
| aarch64 | 12,559 | 12,559 | 12,559 | 0 | 0 | 0 | 0 | 0 |
| riscv | 6,086 | 6,086 | 6,086 | 0 | 0 | 0 | 0 | 0 |
| arm | 1,614 | 1,614 | 1,614 | 0 | 0 | 0 | 0 | 0 |
| mips | 1,656 | 1,647 | 1,647 | 9 | 0 | 0 | 0 | 0 |
| ppc | 94 | 94 | 93 | 0 | 1 | 0 | 0 | 0 |
| m68k | 35 | 35 | 35 | 0 | 0 | 0 | 0 | 0 |
| wasm | 894 | 894 | 894 | 0 | 0 | 0 | 0 | 0 |
| spirv | 5,689 | 5,689 | 5,685 | 0 | 4 | 0 | 0 | 0 |

mips 的 9 条是已知 `--allow-ref-asserts 9`；ppc 1 条、spirv 4 条是已知对称
unanswerable。九个 target 的 `missing_in_both` 和 `unexpected` 全为 0。

### 3.2 冻结 oracle 回放（不重建）

对 `evidence/{G,U}/<target>` 的官方/我方答案重跑
`diff.py --queries`，九个 target 全部 `missing_in_both=0, unexpected=0`。
`D/x86`（91,340 key）同样为 0/0。唯一 rc=1 是 `G/mips` 的 9 条已登记
ref-assert，不是新差异。

## 4 测试与静态检查

```text
ab:             160 passed, 23 subtests
gisel:          246 passed, 92 subtests
upstream-source:107 passed, 11 subtests
shellcheck -S warning ab/*.sh: rc=0
```

## 5 本轮未覆盖

- `run-u-end-to-end.sh --drop-opcode` 的真实构建路径（U 侧负控）。代码已按
  同一 rc 契约改写，但没有在真实 U 题面上重跑；冻结 U 答案的 `--queries`
  回归已通过。
- 九个 target 的 **U 侧**真实构建本轮没有重跑；G 侧九个已全跑。
