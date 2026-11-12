# 缺口清单：三根柱子对照最初的规划

> 2026-11-12 快照。规划原文在 `gisel/docs/PLAN-internal-authority.md`；这里只记
> “现在到哪了、还差什么”，不重复论证。数字全部来自 `EVIDENCE.json`
> （`VERIFY_FROZEN=1 ./verify-evidence.sh` → 70/70）和 `SCOPE.md §7`。

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
| arm | 1,614 | 9,296 | 15,695 | 1,769,782 | L1+L2 | — |
| mips | 1,647 | 18,745 | 11,396 | 1,264,130 | L1+L2 | — |
| ppc | 94 | 1,005 | 2,177 | 252,826 | L1（名义）+ L2 | — |
| m68k | 35 | 112 | 2,182 | 252,826 | — | — |
| wasm | 894 | 11,996 | 9,290 | 1,011,304 | — | — |
| spirv | 5,689 | 3,472,080 | 15,580 | 4,082,382 | — | — |

九个 target 都有 L0（`getAction`）+ D + U + U-full + 负控；MIR/llc 层覆盖六个：
x86 / aarch64 / riscv 有 L1+L2+L3，arm / mips / ppc 有 L1+L2（PPC 的 L1 名义）。
PPC 的 L1 只有一条 `legalize-ret.mir`，文件里没有 generic 指令，负控（G_ADD）
抓不到差异；它的真实覆盖来自 L2：71 条查询生成的 MIR，`G_FADD` 负控能抓到。
m68k / wasm / spirv 还没有 MIR。说“九个 target 都对拍过”时，主语只能是
L0/D/U-full。

## 2 这一轮关掉的

| # | 缺口 | 处置 |
|---|---|---|
| C1 | `gisel` CI 从 2026-11-11 起是红的：`test_packaging_reads_the_package_version` 在 3.11/3.12 上报 `KeyError: 'version'`（3.10 走正则路径，所以本地绿） | `6b1d763` 修测试；顺手把 CI 的 lint / `gen --emit={inc,check,core}` 从 3 个语料扩到 `tests/corpus/*.gisel` |
| C2 | L3 只在日志里、没进 `EVIDENCE.json` | `1edf867`：`l3.py` + `kind: "lit"`，逐条 `(status, expected)`，80,596 条，0 变化 |
| C3 | upstream-source 没有 CI | `ada7db3`：`import-tests`（80 passed）与 `import-check`（pin 的 partial clone，7 MB，九目标 `--check` 16 s）两个 job；run `43146080543` 绿 |
| C4 | `graph` 的闭包审计默认不成立 | `gisel f1472b2`：`--check-closure` 改为默认开启（`--no-check-closure` 显式退出）；四个大 target 默认 rc=1，`--refine` 后 rc=0。spec/README/REPORT 同步 |
| C5 | ours 构建在已打补丁的树上跑 `check-pin.sh`，x86/a64/riscv 的 G 路径在内容冻结后失效 | `ab.py` 改为打补丁前校验还原树，`build_swap_runner(..., skip_pin=True)` 只跳过 ours；官方侧校验没有放宽 |
| C6 | 改 `.gisel` 后没有 frozen 回放命令（原 O3） | `replay-frozen.py`：九 target × G/U 共 18 个方向逐条一致；见 `docs/REPLAY-FROZEN.md` |
| C7 | `agree` 把“谁都没答”算成一致 | 对外报 `answered_equal`；U-full 表加列（AArch64 3,475,458 → 3,440,142）；`EVIDENCE.json` 的 28 个答案类条目钉住该字段 |
| C8 | U-full 的展开题面没有冻结，容易被读成丢文件 | `verify-evidence.sh` 在跑 U-full 时打印 NOTE：只冻结 universe + expand 命令，展开文件按需生成 |
| C9 | `run-x86-end-to-end.sh` 在打补丁后建 ours runner，同样被 `check-pin.sh` 拒绝 | ours 的 build 设 `GIT_DSL_SKIP_PIN_CHECK=1`；official build 仍在还原树上校验。实测整条脚本 rc=0、3,014 条 agree |

## 3 还缺的

按“价值 / 成本”排序。

### O1 MIR/llc 层覆盖 7/9（m68k/wasm/spirv 缺 MIR）

2026-11-12 补了 ARM / PPC / Mips 的构造函数替换（`swap-source-ctor.py` 的
`arm`/`ppc`/`mips` 条目，`mir_libs.SWAPPABLE` 同步），用 pin 树的上游 MIR 回放：

| target | files | 有意义 run | same | diff | 负控 |
|---|---:|---:|---:|---:|---|
| ARM | 16 | 43 | 43 | 0 | `G_MERGE_VALUES` → 4 diff |
| Mips | 63 | 72 | 72 | 0 | `G_ADD` → 15 diff |
| PPC L1 | 1 | 1 | 1 | 0 | `G_ADD` → **0 diff（未被抓到）** |
| PPC L2 | 71 | 71 | 70 + 1 both-abort | 0 | `G_FADD` → 1 diff |
| ARM L2 | 1,141 | 1,141 | 1,141 | 0 | `G_LOAD` → 64 diff |
| Mips L2 | 1,311 | 1,311 | 1,311 | 0 | `G_LOAD` → 105 diff |

ARM 的 ctor 有两个规则之外的结构：Thumb1 提前返回、`setFCmpLibcalls*` 数据表
（importer 明确标记为 skipped）。替换体保留这两段，否则 soft-float 配置会
在 `getFCmpLibcalls` 断言崩溃（第一次跑就是这样抓到 4 条 SIGABRT，修完才 43/43）。

- 为什么重要：X86 的 CTPOP 回归（L3 §6.3）说明 L0 全绿不等于下游不变。
- 还差：m68k / wasm / spirv 没有 MIR。SPIR-V 的图上规模此前已超过 AArch64，
  先确认 llc 能否跑它。
- 建议：先评估 m68k/wasm（题面小、配置少），SPIR-V 单独排期。

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

### O9 多步 / 动态 legalize 的等价性没有证明

L1/L2 只看一遍 `-run-pass=legalizer`；L3 用真实 IR 覆盖了三个 target 的下游，
但仍是“上游写进测试的形状”。任意 IR 上的多步等价没有证据。

- 这是边界，不是待办；写进 `PLAN` §10 即可。

## 4 按级别的结论

| 级别 | 谁够得上 | 还差 |
|---|---|---|
| L4（内部权威） | x86 / aarch64 / riscv | 静态闭包 + frozen 回放 + CI 都齐；仍缺动态 `legalize` 的多步等价（边界，见 O9） |
| L3 以下 | 其余六个 | O1（m68k/wasm/spirv 的 MIR；L1/L2 已齐） |

L4 是**分 target 授予**的，不是一个总开关；九个 target 共享的只有 L0/D/U-full。
