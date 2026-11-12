# 缺口清单：三根柱子对照最初的规划

> 2026-11-12 快照。规划原文在 `gisel/docs/PLAN-internal-authority.md`；这里只记
> “现在到哪了、还差什么”，不重复论证。数字全部来自 `EVIDENCE.json`
> （`VERIFY_FROZEN=1 ./verify-evidence.sh` → 76/76）和 `SCOPE.md §7`。

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
| m68k | 35 | 112 | 2,182 | 252,826 | L2 | — |
| wasm | 894 | 11,996 | 9,290 | 1,011,304 | L2 | — |
| spirv | 5,689 | 3,472,080 | 15,580 | 4,082,382 | L2 | — |

九个 target 都有 L0（`getAction`）+ D + U + U-full + 负控；MIR/llc 层覆盖九个：
x86 / aarch64 / riscv 有 L1+L2+L3，arm / mips / ppc 有 L1+L2（PPC 的 L1 名义），
m68k / wasm / spirv 有 L2。
PPC 的 L1 只有一条 `legalize-ret.mir`，文件里没有 generic 指令，负控（G_ADD）
抓不到差异；它的真实覆盖来自 L2：71 条查询生成的 MIR，`G_FADD` 负控能抓到。

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
| C10 | O1：MIR/llc 层只覆盖 7/9，arm/mips 缺 L2，m68k/wasm/spirv 没有 MIR | 2026-11-12 补齐：arm 1,141、mips 1,311、m68k 25、wasm 588、spirv 2,625 条，diff 全 0，负控全部抓到；`VERIFY_FROZEN=1 ./verify-evidence.sh MIR` 22/22 |
| C11 | O6：pin 漂移没有政策 | `upstream-source` 明确“只跟 pin”：`README.md` + `PIN.json` 的 comment 写死四步显式迁移；不建自动同步 job（见该仓库 README「pin 政策」） |

## 3 还缺的

按“价值 / 成本”排序。

### O7 一条龙的 vertical slice（已关闭）

`vertical.py --target {riscv,x86,aarch64}` 把 G/U/负控/domain/MIR L1/L2
串成一条命令，每一步都对 `data/<target>-contract.json` 复核。x86 与
aarch64 的 contract 与冻结副本（`oracle/<target>-vertical/`）已提交，
CI 用 `--verify-only --frozen` 在没有构建树和 `/tmp` 的机器上重放。

AArch64 速记：G 12,559 / U 29,608 / domain 8,432,640（双端断言 351,504）/
L1 214 runs / L2 8,576 runs，全部 disagree 0。负控 G_ZEXT 315、G_ICMP 216。

- 旧 `riscv_vertical.py` 保留为薄壳，命令不变。

### O8 AArch64 的 U 题面在 universe 修复之前冻结（已刷新）

`oracle ac98717` 修掉了 3-slot opcode 的短 types 组合（ArrayRef 越界），
但 `oracle/U/aarch64` 还是修复前的 29,561 条。2026-11-12 重新生成
（29,608 条，A/B agree 29,608 / disagree 0），并同步刷新 `U-neg/aarch64`。

其余 target 的 U 冻结物是否早于 `ac98717` 没有逐一下结论；按“只跟 pin”的
政策，这属于证据迁移，动哪个 target 就在哪次改动里一并刷新并在 commit
信息里写明。

### O9 多步 / 动态 legalize 的等价性没有证明

L1/L2 只看一遍 `-run-pass=legalizer`；L3 用真实 IR 覆盖了三个 target 的下游，
但仍是“上游写进测试的形状”。任意 IR 上的多步等价没有证据。

- 这是边界，不是待办；写进 `PLAN` §10 即可。

## 4 按级别的结论

| 级别 | 谁够得上 | 还差 |
|---|---|---|
| L4（内部权威） | x86 / aarch64 / riscv | 静态闭包 + frozen 回放 + CI 都齐；仍缺动态 `legalize` 的多步等价（边界，见 O9） |
| L3 以下 | 其余六个 | 没有 L3；L0/D/U-full/L2 已齐 |

L4 是**分 target 授予**的，不是一个总开关；九个 target 共享的只有 L0/D/U-full。
