# 缺口清单：三根柱子对照最初的规划

> 2026-11-12 快照。规划原文在 `gisel/docs/PLAN-internal-authority.md`；这里只记
> “现在到哪了、还差什么”，不重复论证。数字全部来自 `EVIDENCE.json`
> （`VERIFY_FROZEN=1 ./verify-evidence.sh` → 59/59）和 `SCOPE.md §7`。

三根柱子：

1. **gisel**：`.gisel` → `inc`；`.gisel` → 无答案查询（`domain`、`cases`）。
2. **upstream-source**：从 pin 的上游规则区域出题（`U`、`U-full`）。
3. **ab**：两侧跑同一份查询，证明答案一致（`G` 证明 gisel 侧，`U` 证明上游侧）。

## 1 覆盖矩阵

| 目标 | G（cases） | D（domain） | U（采样） | U-full | MIR L1/L2 | L3 |
|---|---:|---:|---:|---:|:-:|:-:|
| x86 | 3,014 | 91,340 | 10,027 | 1,121,728 | ✓ | ✓ |
| aarch64 | 12,559 | 8,432,640 | 29,561 | 3,505,608 | ✓ | ✓ |
| riscv | 6,086 | 2,029,976 | 20,445 | 3,028,496 | ✓ | ✓ |
| arm | 1,614 | 9,296 | 15,695 | 1,769,782 | — | — |
| mips | 1,647 | 18,745 | 11,396 | 1,264,130 | — | — |
| ppc | 94 | 1,005 | 2,177 | 252,826 | — | — |
| m68k | 35 | 112 | 2,182 | 252,826 | — | — |
| wasm | 894 | 11,996 | 9,290 | 1,011,304 | — | — |
| spirv | 5,689 | 3,472,080 | 15,580 | 4,082,382 | — | — |

九个 target 都有 L0（`getAction`）+ D + U + U-full + 负控；只有三个有 MIR/llc 层。
说“九个 target 都对拍过”时，主语只能是 L0/D/U-full。

## 2 这一轮关掉的

| # | 缺口 | 处置 |
|---|---|---|
| C1 | `gisel` CI 从 2026-11-11 起是红的：`test_packaging_reads_the_package_version` 在 3.11/3.12 上报 `KeyError: 'version'`（3.10 走正则路径，所以本地绿） | `6b1d763` 修测试；顺手把 CI 的 lint / `gen --emit={inc,check,core}` 从 3 个语料扩到 `tests/corpus/*.gisel` |
| C2 | L3 只在日志里、没进 `EVIDENCE.json` | `1edf867`：`l3.py` + `kind: "lit"`，逐条 `(status, expected)`，80,596 条，0 变化 |

## 3 还缺的

按“价值 / 成本”排序。

### O1 MIR/llc 层只有 3/9

`mir_libs.SWAPPABLE = ("x86", "aarch64", "riscv")`。其余六个 target 的
`inc` 只在 L0 runner 里编译过，没有“换进真实 target、跑 `llc`”的证据。

- 为什么重要：X86 的 CTPOP 回归（L3 §6.3）说明 L0 全绿不等于下游不变。ARM /
  Mips / PPC 是真实后端，最值得补。
- 成本：每个 target 要写一个构造函数替换形态 + MIR 题面（上游 MIR 回放，
  或从查询合成）。中高。
- 建议：先 ARM（MIR 测试多、ABI 固定），再 PPC，再 Mips。

### O2 upstream-source 没有 CI

`import --all --check`（9/9）和 80 个测试只在本地跑。仓库没有
`.github/workflows/`。

- 成本：低。先跑 `pytest import/tests`（不需要 LLVM 构建）；`--check` 需要
  `git show <pin>:<path>`，CI 里做一次浅 fetch 即可，或者把失败留成本地门。
- 建议：先上 pytest 门，`--check` 单独一个 job（允许慢）。

### O3 “改 `.gisel` 之后”的回放流程不是命令

规划 §7/§9 要求：改语料 → 重生成 `inc` → 对 frozen oracle 跑 G/U + 负控。
现在 `verify-evidence.sh` 证明的是“冻结物没变”，不是“新产物和冻结的官方答案
一致”。`riscv_vertical.py --frozen` 只覆盖 RISC-V。

- 成本：中。把 frozen `official.answers.jsonl` 当参照，跑新 `inc`，比较；
  九个 target 的 runner 都是现成的。
- 建议：做成 `ab/replay-frozen.sh TARGET`，先在 RISC-V 上验证，再推广。

### O4 `graph --check-closure` 默认不成立

不带 `--refine` 时闭包违例 > 0（X86 277、AArch64 2,671、RISC-V 2,864、Wasm
302）；`--refine` 后四个大 target 全 0（`REPORT-graph`）。所以“0 环”默认是
“代表点商图上 0 环”，不是完整结论。

- 成本：低（改默认值或只改文档）。
- 建议：保持默认关闭，但把 `cycles=0` 的输出里强制打印“closure 未验证”；
  或在 `--check-closure` 失败时 rc=1 成为默认。**这个口径要你拍板。**

### O5 `agree` 里含“谁都没答”

L0 的 `agree` 是“可观测状态相同”，**包含双侧都断言**（`unanswerable`）。
U-full/aarch64 的 3,475,458 条 `agree` 里有 35,316 条是谁都没答；
单侧断言（`ref_asserted` 30,150）不算 `agree`，但标题数字仍是 `agree`。
`answered_equal = agree - unanswerable` 才是“真给出答案且一致”。

- 成本：低。
- 建议：对外一律报 `answered_equal`，`agree` 只作恒等式的一环。

### O6 pin 漂移没有自动检测

pin 停在 `9bfc850b`，带 6 个 PR；其中 #237753、#238306 已在 2026-11 合入上游。
现在只有“官方侧内容变了 → `check-pin.sh` 报错”，没有“上游 main 动了 → 重新
导入并 diff 语料”。规划 §9 要求二选一：定期同步，或明确只跟 pin。

- 成本：中。一个 job 把 pin 前移到最近 tag，跑 `import-cxx --all --check`，
  语料 diff 作为报告。
- 建议：先写“只跟 pin”的政策进 `PIN.json`/`CORPORA.md`，把同步当独立任务。

### O7 只有 RISC-V 有一条龙的 vertical slice

`riscv_vertical.py` 把 G/U/负控/D/MIR/证据串成一条命令；x86、aarch64 没有。
这是可用性缺口，不是证据缺口。

- 成本：低（复用脚本，参数化 target）。
- 建议：在 O1 补 MIR 之后一起做，否则只是把现有步骤换个壳。

### O8 U-full 的展开题面没有冻结

冻结的是 `universe.jsonl`（1–19 MB）+ 展开命令；展开后的
1.1M–4.1M 条查询按需生成（144–473 MB）。`EVIDENCE.json` 记了 sha 和命令。

- 不是缺陷，是取舍；但“重放证据”需要先跑 expand。
- 建议：`verify-evidence.sh` 打印这一条提示，别让读者以为丢文件了。

### O9 多步 / 动态 legalize 的等价性没有证明

L1/L2 只看一遍 `-run-pass=legalizer`；L3 用真实 IR 覆盖了三个 target 的下游，
但仍是“上游写进测试的形状”。任意 IR 上的多步等价没有证据。

- 这是边界，不是待办；写进 `PLAN` §10 即可。

## 4 按级别的结论

| 级别 | 谁够得上 | 还差 |
|---|---|---|
| L4（内部权威） | x86 / aarch64 / riscv | O3（改语料后的 frozen 回放流程） |
| L3 以下 | 其余六个 | O1（MIR/llc）、O2（上游 CI） |

L4 是**分 target 授予**的，不是一个总开关；九个 target 共享的只有 L0/D/U-full。
