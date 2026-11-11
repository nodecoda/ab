# MIR/llc 层回归报告（L1/L2/L3）

> 本文件记录的是**工作台**（`ab`）的执行结果，不是 gisel 的功能报告；
> 边界见 `SCOPE.md` §6。这一层回答的问题是：
> “把官方 legalizer 换成 gisel 生成的 `.inc` 之后，`llc -run-pass=legalizer`
> 在 MIR 上的行为是否改变”。它和 L0 的 `getAction()` 对拍是两件事：
> L1 用上游自己写的 MIR（§2、§4），L2 用 gisel 查询合成的 MIR（§3）。

## 1 快照

| 项 | 值 |
|---|---|
| LLVM 树 | `/home/ubuntu/llvm/trees/explore` @ `700e551714ccb7357a191fd41837ff1b4784abf2`（跑完 restore 后 `git status` 干净） |
| 构建 | `/home/ubuntu/llvm/builds/explore`，RelWithDebInfo + assertions |
| `llc` | `bin/llc`，sha256 `ef74d1ab4964eff8a2b0444e2e5c623f352643d8672eb7bfbd39b6915bc78964` |
| gisel | `/home/ubuntu/llvm/gisel` @ `de8dbbf` |
| ab | 本仓库 @ `b42c98e` + 本报告（docs）提交 |

三份 `.inc`（`--prepare` 时由 `gisel gen --emit=inc` 生成，快照在
`<out>/inc/`）：

| target | inc | sha256 |
|---|---|---|
| x86 | `X86LegalizerInfo.inc` | `38b278dd2a10fe42fa699b3661fbee575657bf8e9cdb1399a0d031a7c05b1442` |
| aarch64 | `AArch64LegalizerInfo.inc` | `aea61ab511987a0ccfb06e88dff3d14f696b9e1382d69197551eb30534d824c6` |
| riscv | `RISCVLegalizerInfo.inc` | `fe6427bdf480143c3ec1d5b35ebba2bda637cce650d83db4f44e4cdcec520e06` |

两侧库（官方快照 / 替换后快照）：

| target | official `libLLVM<T>CodeGen.so` | ours |
|---|---|---|
| x86 | `24bf2a5254dc042e6e1145e926ee42a4dd4d613e3947694b6628f2871b4fe357` | `085928fa26a5e772ff250f045ad4874cd5e8cbbc8046fbeeb2406f7394a9c432` |
| aarch64 | `f696ec1edb12a16b8db2a959527f1f7eb56c2a1218fd9d5e06a2105c95f1d627` | `f696ec1edb12a16b8db2a959527f1f7eb56c2a1218fd9d5e06a2105c95f1d627` |
| riscv | `d44d873e01080f3007ecd57a52099fe54c6c43af9de12a8d3fd48d2b42bfff16` | `d44d873e01080f3007ecd57a52099fe54c6c43af9de12a8d3fd48d2b42bfff16` |

`provenance.json` 里记录两侧库与恢复后的基线库 sha。x86 的恢复重编是字节
可复现的（`baseline_lib_after_restore_sha256 == official_lib_sha256`）；
aarch64 / riscv 在独立重链后 `.so` 字节不同（`e49c03ec…` / `f32be744…`
对 `f696ec1e…` / `d44d873e…`），所以这两个 target 的恢复判据是源码字节
恢复 + L1 回放一致，而不是库字节相等。L3 结束重编回基线后，三库 sha 为
`24bf2a52…` / `e49c03ec…` / `f32be744…`，`isel-ctpop-vec.ll` 的
`-global-isel` RUN 探针 rc=0。

## 2 命令与结果

```sh
cd /home/ubuntu/llvm/ab
python3 mir-replay.py --layer upstream --target x86 --target aarch64 --target riscv \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l1-final5 --prepare --json
```

实测（`/tmp/mir-l1-final5/mir-report.json`）：整条命令 13 s（热构建下换源 +
三次单库重编 + 回放 + restore 重编；冷构建首次是 63 s）。x86 的 `.inc` 是
CTPOP 修正后的 `38b278dd…`，L1 结果与修正前相同。

```text
totals    all_run_lines=868  in_layer=624  same=611  both_abort=13
          diff=0  timeout=0  unsupported_run=0  out_of_layer=244  abort0=2

x86      files=93   in_layer=140  same=140  both_abort=0  diff=0  out_of_layer=19  abort0=0
aarch64  files=367  in_layer=214  same=201  both_abort=13 diff=0  out_of_layer=224  abort0=2
riscv    files=181  in_layer=270  same=270  both_abort=0  diff=0  out_of_layer=1  abort0=0
```

恒等式由程序自检：`runs == same + both_abort + diff + timeout +
unsupported_run`，且 `runs + out_of_layer == all_run_lines`。

- `both_abort`（13）：两侧都以相同输出非零退出。13 条全部是 AArch64 的
  `not ... llc` 负向用例（`legalize-inttoptr-xfail-*.mir`、`setf8-*-nzcv.mir`
  一类，上游自己期望失败）；它们一致，但不是“成功变换”，所以单独计数。
  报告里这 13 条都带 `expect_failure: true`。
- `out_of_layer`（244）：RUN 行里没有 `-run-pass=legalizer`（例如同文件里的
  `-run-pass=irtranslator` 段）。这一层不回答它们，也不静默丢。
- 确定性：把同一份快照回放两遍（`/tmp/mir-det1`、`/tmp/mir-det2`，去掉
  `generated_at`/`elapsed_seconds` 后逐字段比较），`mir-report.json`
  完全相同。
- `diff` 是 0。

## 3 L2：查询生成 MIR

L1 的题面是上游自己写的 MIR。L2 把 gisel 的无答案查询变成最小 MIR，再跑同一个
回放。它比 L1 多回答一个问题：“gisel 认为值得区分的类型组合，在 llc 里是否也
一致”；代价是这些 MIR 由我们合成，形状是否“真实”需要单独交代（§3.6）。

### 3.1 命令

```sh
# 一、查询 -> MIR（自检：解析 + 机器验证器）
python3 mir-from-query.py --target aarch64 --queries /tmp/a64.cases.jsonl \
  --out /tmp/mir-a64 --preflight-llc $BUILD/bin/llc \
  --preflight-lib /tmp/mir-l1-final5/official/aarch64

# 二、回放（快照官方库、换源重建、恢复基线）
python3 mir-replay.py --layer generated --mir /tmp/mir-a64 --target aarch64 \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l2-a64 --prepare

# 或者一条命令
python3 ab.py mir --target aarch64 --queries /tmp/a64.cases.jsonl \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/l2-a64
```

三个 target 的查询文件由 gisel 生成：

```sh
cd /home/ubuntu/llvm/gisel
python3 -m gisel cases tests/corpus/X86LegalizerInfo.gisel \
  --features tests/cases/x86-features.json --out /tmp/x86.cases.jsonl
python3 -m gisel cases tests/corpus/AArch64LegalizerInfo.gisel \
  --features tests/cases/features.json --out /tmp/a64.cases.jsonl
python3 -m gisel cases tests/corpus/RISCVLegalizerInfo.gisel \
  --features tests/cases/riscv-features.json --out /tmp/rv.cases.jsonl
```

### 3.2 分母

| target | 查询 | 建成 MIR | `unbuildable_shape` | `unbuildable_type` | `config_unrealizable` |
|---|---:|---:|---:|---:|---:|
| x86 | 3,014 | 2,390 | 590 | 34 | 0 |
| aarch64 | 12,226 | 8,774 | 3,344 | 108 | 0 |
| riscv | 6,086 | 4,203 | 732 | 66 | 1,085 |

恒等式 `built + shape + type + config == queries` 由程序自检。RISC-V 的 1,085
条全部来自 `ristretto` 配置：LLVM 没有同名 subtarget feature，`-mattr` 表达
不了，因此显式记 `config_unrealizable`，不做近似。

`unbuildable_shape` 的头部原因（aarch64）：操作数类型必须同时是向量/标量
（684）、位宽不匹配的 bitcast（252）、`G_BUILD_VECTOR` 元素类型不匹配（144）。

### 3.3 结果

| target | 文件 | `same` | `both_abort` | `diff` | `timeout` | 其中 `abort0` 复查 |
|---|---:|---:|---:|---:|---:|---:|
| x86 | 2,390 | 2,374 | 16 | **0** | 0 | 1,558 |
| aarch64 | 8,774 | 7,874 | 837 | **0** | 63 | 4,250 |
| riscv | 4,203 | 4,050 | 151 | **0** | 2 | 2,265 |

快照（`provenance.json` 与 `sha256sum`）：

| 项 | 值 |
|---|---|
| 树 | `700e551714cc`，跑完 `git status` 干净 |
| `llc` | `ef74d1ab4964eff8…` |
| inc x86 / aarch64 / riscv | `38b278dd…` / `aea61ab5…` / `fe6427bd…` |
| 官方库 x86 / a64 / rv | `24bf2a52…` / `e49c03ec…` / `f32be744…` |
| ours 库 x86 / a64 / rv | `085928fa…` / `f696ec1e…` / `d44d873e…` |

### 3.4 负控（三个 target 各一条）

```sh
python3 mir-replay.py --layer generated --mir /tmp/mir-a64 --target aarch64 \
  --tree … --build … --out /tmp/mir-l2-a64-neg --prepare \
  --negative-control G_ADD
```

| target | 结果 |
|---|---|
| x86 | `diff=181`，caught |
| aarch64 | `diff=1228`，caught |
| riscv | `diff=255`，caught |

### 3.5 把「假通过」变成真检查的三处修正

L2 第一版在两个 target 上都报 `diff=0`，但那三个 0 都是假的：

1. **被测指令被 legalizer 当成死代码删掉。** legalizer 入口会
   `isTriviallyDead` 清理无人使用的指令。第一版 MIR 里被测指令的 def 没有
   使用者，于是 `G_ADD` 在三条库上都被删掉，输出只剩 `RET`，任何规则改动都
   看不见——负控因此“没抓到”。现在每个 def 都挂一个 `COPY` sink；`COPY` 不是
   pre-isel generic opcode，legalizer 既不合法化也不删除它。
2. **`-global-isel-abort=1` 掩盖了 abort 之后的工作。** 两侧都在第一条无法
   合法化的指令上报错时，`(rc, stdout, stderr)` 相同只能说明“都拒绝了”。
   这些 run 现在用 `-global-isel-abort=0` 复查一次：未合法化的指令会打印出来，
   两侧可以按实际做过的变换比较。仍两侧同崩（断言）才留在 `both_abort`。
   这就是表里的 `abort0` 一列。
3. **崩溃输出里的库路径与 target 行号。** RISC-V 第一版有 22 条 `diff`，差异
   只有 `RISCVLegalizerInfo.cpp:1004` vs `:200`（我们的 include 让行号位移）
   和 `…/official/riscv/lib…so` vs `…/ours/riscv/lib…so`。现在只归一化
   `lib/Target/**` 下的行号与两侧快照库路径；`lib/CodeGen` 的行号仍然比较，
   所以“同一函数里不同位置崩”还是 diff。

### 3.6 L2 自己没覆盖的部分

- **显式跳过的 opcode**：`G_PHI`（需要多块 CFG 且没有 legalizer 规则可问）、
  `G_BRJT`/`G_JUMP_TABLE`（需要 jump-table 描述符）、`G_BLOCK_ADDR`（需要
  指向被测函数自身的 `blockaddress`）、`G_PTRAUTH_GLOBAL_VALUE`（需要
  ptrauth 全局）。理由写在 `mir-from-query.py` 的 `SKIP` 里，计入
  `unbuildable_shape`。
- **`both_abort` 的来源**：x86 16 条是 `G_ICMP s9` / `G_UADDE` 在
  legalizer 内的断言；aarch64 837 条主要是奇数列向量（`v3s8`、`v5s8`、
  `v7s8`…）撞上的 `mutationIsSane` 断言；riscv 151 条是 `G_VASTART`/
  `G_VSCALE` 一类断言。两侧输出相同，说明规则翻译没差，但这些问题在这层
  没有答案。
- **`timeout` 的来源**：aarch64 63 条全是 3 列向量（`v3i32`/`v3f32`/`v3s32`），
  legalizer 在 `-run-pass=legalizer` 上不终止（6 s 内打出 29 万行
  “Increase number of elements”）。真实 IR 路径不会产生这种形状
  （IRTranslator 会在翻译期就拆成 4 列 + build，见
  `store <3 x float> undef` 的正常编译），所以这是我们合成 MIR 的边界，
  不是 IR 可达的缺陷；但它确实是上游 legalizer 在合法 MIR 上的不终止，
  已记为候选 issue。riscv 2 条同类。

## 4 L1 负控

```sh
python3 mir-replay.py --layer upstream --target x86 \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l1-neg5 --prepare --negative-control G_ADD --json
```

结果（`/tmp/mir-l1-neg5/mir-report.json`）：`in_layer=140 same=116 diff=24`，打印
`negative-control G_ADD: caught (diff=24)`，退出码 0。
即：把 `G_ADD` 的一条规则改坏，回放能在 24 条 RUN 上看到差异。没有这条，
`diff=0` 不能排除“回放根本没接通”。

## 5 这一轮修掉的假差异

### 5.1 崩溃输出里的地址

AArch64 两条 XFAIL 用例在第一次跑时被判成 `diff`，差异只有栈帧地址和
`basic block: %bb.0  (0x...)`。`mir-replay.py` 现在在比较前统一把
`0x[0-9a-fA-F]+` 归一化成 `0x?`，并在 `not ...` 行上记录
`expect_failure: true`。地址之外的真实差异仍然会进 `diff`（有单测钉住）。

### 5.2 gisel 把整组规则提升成 `if (gate)` 之后，`same_as` 拼错

RISC-V `legalizer-info-validation.mir` 的 run3/run4 曾报：

```text
ours:      .. type index coverage check SKIPPED: user-defined predicate detected
official:  .. the first uncovered type index: 2, OK
```

根因在 gisel 的 `.inc`：RISC-V 的 `G_CTLZ` / `G_CTPOP` 规则写成
`when R_hasStdExtZbb`，emitter 把这个 feature gate 提升成外层
`if (R_hasStdExtZbb) { ... }`（这是对的；上游就是按 subtarget 分支出不同的
builder 链），但块内的 `same_as(0)` 仍按“有 guard”拼成
`.minScalarEltSameAsIf(always, ...)`。上游在那个分支里写的是
`.scalarSameSizeAs(1, 0)`。

两者的**语义**相同，差别只在覆盖登记：`*EltSameAsIf` 走
`widenScalarIf`/`narrowScalarIf`，会 `markAllIdxsAsCovered()`；而
`minScalarSameAs`/`maxScalarSameAs` 只登记它点名的两个下标。诊断因此不同。

修法（gisel 侧，`gisel/backend/llvm_inc.py`）：guard 被提升消费掉之后，
残余谓词是字面 `true` 时按无 guard 拼写；AArch64 那种真正写了
`when true`、且没有提升的规则仍然拼 `*EltSameAsIf(always, ...)`
（上游 AArch64 `G_CTPOP` 就是这么写的）。改完 `riscv.inc` 的 sha 从
`3ff3e84e…` 变为 `fe6427bd…`，X86/AArch64 的 `.inc` 不变。

### 5.3 重定向的目标被当成输入文件

AArch64 `legalize-load-store-vector.mir` 的第一条 RUN 写成
`... %s 2> %t.err | FileCheck %s`。旧解析把 `2>` 去掉后把 `%t.err` 留成了
第二个输入文件，`llc` 以 rc=1 报“找不到文件”，两侧输出了同一份错误，于是
**被记成 `both_abort`（一致）而不是它真的跑过**。同类的 `2>%t` 形式（X86
两条）在另一个方向上也差点被误判。

现在 `drop_redirects()` 同时处理 `2> file`、`2>file`、`2>&1`、`< file`，
把操作符和它的目标一起丢掉。修完后这条 RUN 从 `both_abort` 变成 `same`
（rc=0），X86 两条仍是 `same`。这类“解析错误伪装成一致”是 L1 最危险的
失败模式，所以负控之外又补了四条 RUN 解析单测。

## 6 L3：全量 check-llvm

前两层只换单个 target 的 CodeGen 库、只比 legalizer 那一遍。L3 换三个 target
的库，把整个 `check-llvm` 跑一遍，回答“真实 IR 进 llc 之后，下游有没有变化”。

### 6.1 命令

```sh
BUILD=/home/ubuntu/llvm/builds/explore
TREE=/home/ubuntu/llvm/trees/explore
GISEL=/home/ubuntu/llvm/gisel
AB=/home/ubuntu/llvm/ab

# 一、基线轮（树 @ 700e5517，git status 干净）
cd $BUILD && ninja -j32 check-llvm        # > /tmp/l3-baseline.log

# 二、组合轮：三个 inc 同时替换
cd $AB
python3 swap-source-ctor.py apply --target x86 --build $BUILD --inc $GISEL/tests/artifacts/x86.inc
python3 swap-source-ctor.py apply --target aarch64 --tree $TREE --inc $GISEL/tests/artifacts/aarch64.inc
python3 swap-source-ctor.py apply --target riscv --tree $TREE --inc $GISEL/tests/artifacts/riscv.inc
cd $BUILD && ninja -j32 check-llvm        # > /tmp/l3-combined2.log

# 三、恢复
cd $AB
python3 swap-source-ctor.py restore --target x86 --build $BUILD
python3 swap-source-ctor.py restore --target aarch64 --tree $TREE
python3 swap-source-ctor.py restore --target riscv --tree $TREE
cd $BUILD && ninja -j32
```

### 6.2 结果

| 轮次 | Total Discovered | Passed | XFAIL | Failed | 耗时（含构建） |
|---|---:|---:|---:|---:|---:|
| 基线（`/tmp/l3-baseline.log`） | 80,655 | 64,916 | 146 | **0** | 10m27s |
| 组合（`/tmp/l3-combined2.log`） | 80,655 | 64,916 | 146 | **0** | 3m38s |

组合轮只重编了 57 个目标（三个 CodeGen 库 + 依赖），测试本身 189.63 s。
两轮的 Skipped（59）与 Unsupported（15,534）也逐项相同。

### 6.3 第一次组合轮抓到的真实回归（已修）

第一次组合轮（`/tmp/l3-combined.log`）是 **1 failed**：

```text
LLVM :: CodeGen/X86/isel-ctpop-vec.ll
LLVM ERROR: unable to legalize instruction: %1:_(<4 x s32>) = G_CTPOP %0:_(<4 x s32>)
  (-mattr=+avx512f,+avx512vpopcntdq,+avx512bitalg -global-isel，无 VLX)
```

- 根因：X86 语料按 pin `9bfc850b9940` 的构造函数生成，该 commit 早于
  PR 235976；工作树里已经有合并后的 `462829fdac83`。于是官方 llc 接受
  VPOPCNTDQ 的 128/256 位向量 CTPOP，而我们的 `.inc` 仍要求 VLX。
  这正是 L3 要抓的“L1/L2 的 MIR 语料碰不到”的下游差异。
- 修法：按 PR 235976 重写语料里的 `X_G_CTPOP`（VPOPCNTDQ 全宽度 +
  BITALG 的字节/半字向量），同步重写 `upstream-source` 的
  `deviation_x86_ctpop`。`x86.inc` 从 `93f5d025…` 变为 `38b278dd…`，
  X86 查询从 3,019 变为 3,014（`x86-features.json` 新增
  `Subtarget.hasBITALG(): false`，保持旧行为，分母仍可比较）。
- 复跑：组合轮 0 failed，数字与基线逐项相同（上表）。
- 恢复：三库 sha 回到 `24bf2a52…` / `e49c03ec…` / `f32be744…`，
  `git status` 干净于 `700e551714cc`，`isel-ctpop-vec.ll` 探针 rc=0。

### 6.4 L3 证明了什么、没证明什么

- 证明了：三个 target 的 legalizer 构造函数换成 gisel 产物后，上游 80,655
  个 lit 测试的可观测结果不变（同一失败集合为空）。
- 没证明：类型组合层面的完备性。`check-llvm` 只跑上游写进测试的形状；
  新增的类型组合仍靠 L2 的合成 MIR 和 L0 的 `getAction()` 对拍。
- 两轮之间上游源码没有改动（同一 commit `700e5517`），差异只来自三个
  `.inc`；组合轮结束后已把源码与构建都恢复到基线。

## 7 未覆盖

- **多步 legalize 与 result 层面的等价性**：L1/L2 只看
  `-run-pass=legalizer` 的输出文本；L3 用 `check-llvm` 补了“真实 IR 的下游
  可观测结果”，但仍不是任意 IR 上的语义证明。
- **非 `x86/aarch64/riscv` 的 target**：`mir_libs.SWAPPABLE` 与 L3 组合轮都只有
  这三个（构造函数可替换）。ARM/MIPS/PPC/M68k/WebAssembly/SPIR-V 只有 L0 适配器。
- **`-mtriple` 之外的 config 轴**：回放用的是 MIR 文件自带的
  `-mtriple`/`-mattr`；没有按 gisel 的配置矩阵重跑 L1。

## 8 复现

```sh
python3 -m unittest discover -q -s tests        # ab: 103 tests
cd /home/ubuntu/llvm/gisel && python3 -m unittest discover -q -s tests  # 243 tests
```

产物：

| 层 | 正常 | 负控 |
|---|---|---|
| L1 | `/tmp/mir-l1-final5/` | `/tmp/mir-l1-neg5/` |
| L2 x86 | `/tmp/mir-l2-x86/` | `/tmp/mir-l2-x86-neg/` |
| L2 aarch64 | `/tmp/mir-l2-a64/` | `/tmp/mir-l2-a64-neg/` |
| L2 riscv | `/tmp/mir-l2-rv/` | `/tmp/mir-l2-rv-neg/` |

MIR 题面本身在 `/tmp/mir-{x86,a64,rv}/<target>/`（`index.jsonl` 记每条查询
落到 `built` 还是哪个 `unbuildable_*` 桶）。L3 的日志是
`/tmp/l3-baseline.log` 与 `/tmp/l3-combined2.log`（首轮失败留档在
`/tmp/l3-combined.log`）。
