# MIR/llc 层回归报告（L1）

> 本文件记录的是**工作台**（`ab`）的执行结果，不是 gisel 的功能报告；
> 边界见 `SCOPE.md` §6。这一层回答的问题是：
> “把官方 legalizer 换成 gisel 生成的 `.inc` 之后，`llc -run-pass=legalizer`
> 在真实 MIR 上的行为是否改变”。它和 L0 的 `getAction()` 对拍是两件事。

## 1 快照

| 项 | 值 |
|---|---|
| LLVM 树 | `/home/ubuntu/llvm/trees/explore` @ `700e551714ccb7357a191fd41837ff1b4784abf2`（跑完 restore 后 `git status` 干净） |
| 构建 | `/home/ubuntu/llvm/builds/explore`，RelWithDebInfo + assertions |
| `llc` | `bin/llc`，sha256 `ef74d1ab4964eff8a2b0444e2e5c623f352643d8672eb7bfbd39b6915bc78964` |
| gisel | `/home/ubuntu/llvm/gisel` @ `4d7e5ec` + 本次未提交改动（§4） |
| ab | 本仓库 @ `fd8e0b9` + 本次未提交改动 |

三份 `.inc`（`--prepare` 时由 `gisel gen --emit=inc` 生成，快照在
`<out>/inc/`）：

| target | inc | sha256 |
|---|---|---|
| x86 | `X86LegalizerInfo.inc` | `93f5d025c758f0cd5f56bdeed06aed3f006d9b7bba3b27211008a3502fef0cdd` |
| aarch64 | `AArch64LegalizerInfo.inc` | `aea61ab511987a0ccfb06e88dff3d14f696b9e1382d69197551eb30534d824c6` |
| riscv | `RISCVLegalizerInfo.inc` | `fe6427bdf480143c3ec1d5b35ebba2bda637cce650d83db4f44e4cdcec520e06` |

两侧库（官方快照 / 替换后快照）：

| target | official `libLLVM<T>CodeGen.so` | ours |
|---|---|---|
| x86 | `24bf2a5254dc042e6e1145e926ee42a4dd4d613e3947694b6628f2871b4fe357` | `def224480f80433e004d4589f4046b020848d3ab5b0409fa1054e7d5927fc823` |
| aarch64 | `e49c03ec2f82ab2a4be80deb57e5ef5dca76daf7065b2498234730cd5cc64c02` | `f696ec1edb12a16b8db2a959527f1f7eb56c2a1218fd9d5e06a2105c95f1d627` |
| riscv | `f32be744460c8155b7f96ebb9bc8b10655ecf05426fc38627ba6c575bf418eb4` | `d44d873e01080f3007ecd57a52099fe54c6c43af9de12a8d3fd48d2b42bfff16` |

`provenance.json` 里每个 target 都有 `baseline_lib_after_restore_sha256`
与 `official_lib_sha256` 相等、`baseline_lib_restored_exactly: true`，
以及替换前后的源码 sha 相等。

## 2 命令与结果

```sh
cd /home/ubuntu/llvm/ab
python3 mir-replay.py --layer upstream --target x86 --target aarch64 --target riscv \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l1-final4 --prepare --json
```

实测（`/tmp/mir-l1-final4/mir-report.json`）：整条命令 13 s（热构建下换源 +
三次单库重编 + 回放 + restore 重编；冷构建首次是 63 s）。

```text
totals    all_run_lines=868  in_layer=624  same=611  both_abort=13
          diff=0  timeout=0  unsupported_run=0  out_of_layer=244

x86      files=93   in_layer=140  same=140  both_abort=0  diff=0  out_of_layer=19
aarch64  files=367  in_layer=214  same=201  both_abort=13 diff=0  out_of_layer=224
riscv    files=181  in_layer=270  same=270  both_abort=0  diff=0  out_of_layer=1
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

## 3 负控

```sh
python3 mir-replay.py --layer upstream --target x86 \
  --tree /home/ubuntu/llvm/trees/explore --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/mir-l1-neg3 --prepare --negative-control G_ADD --json
```

结果：`in_layer=140 same=116 diff=24`，打印
`negative-control G_ADD: caught (diff=24)`，退出码 0。
即：把 `G_ADD` 的一条规则改坏，回放能在 24 条 RUN 上看到差异。没有这条，
`diff=0` 不能排除“回放根本没接通”。

## 4 这一轮修掉的两个假差异

### 4.1 崩溃输出里的地址

AArch64 两条 XFAIL 用例在第一次跑时被判成 `diff`，差异只有栈帧地址和
`basic block: %bb.0  (0x...)`。`mir-replay.py` 现在在比较前统一把
`0x[0-9a-fA-F]+` 归一化成 `0x?`，并在 `not ...` 行上记录
`expect_failure: true`。地址之外的真实差异仍然会进 `diff`（有单测钉住）。

### 4.2 gisel 把整组规则提升成 `if (gate)` 之后，`same_as` 拼错

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

### 4.3 重定向的目标被当成输入文件

AArch64 `legalize-load-store-vector.mir` 的第一条 RUN 写成
`... %s 2> %t.err | FileCheck %s`。旧解析把 `2>` 去掉后把 `%t.err` 留成了
第二个输入文件，`llc` 以 rc=1 报“找不到文件”，两侧输出了同一份错误，于是
**被记成 `both_abort`（一致）而不是它真的跑过**。同类的 `2>%t` 形式（X86
两条）在另一个方向上也差点被误判。

现在 `drop_redirects()` 同时处理 `2> file`、`2>file`、`2>&1`、`< file`，
把操作符和它的目标一起丢掉。修完后这条 RUN 从 `both_abort` 变成 `same`
（rc=0），X86 两条仍是 `same`。这类“解析错误伪装成一致”是 L1 最危险的
失败模式，所以负控之外又补了四条 RUN 解析单测。

## 5 未覆盖

- **L2（查询生成 MIR）未做**：没有 `mir-from-query.py`，也没有
  `data/mir-shapes.jsonc`。这一层的分母（能变成合法 MIR 的查询）目前是空的。
- **L3（`ninja all` + `ninja check-llvm`）未跑**：本报告只有单库替换的 L1。
- **多步 legalize 与 result 层面的等价性**：L1 只看
  `-run-pass=legalizer` 的输出文本；同一份 MIR 上两侧一致，不等于任意 IR 上
  最终 downsteam 结果一致。这条要靠 L3 的 check-llvm 补。
- **非 `x86/aarch64/riscv` 的 target**：`mir_libs.SWAPPABLE` 目前只有这三个
  （构造函数可替换）。ARM/MIPS/PPC/M68k/WebAssembly/SPIR-V 只有 L0 适配器。
- **`-mtriple` 之外的 config 轴**：回放用的是 MIR 文件自带的
  `-mtriple`/`-mattr`；没有按 gisel 的配置矩阵重跑 L1。

## 6 复现

```sh
python3 -m unittest discover -q -s tests        # ab: 77 tests
cd /home/ubuntu/llvm/gisel && python3 -m unittest discover -q -s tests  # 243 tests
```

产物：`/tmp/mir-l1-final2/{provenance.json,mir-report.json,official/,ours/,inc/}`，
负控：`/tmp/mir-l1-neg3/mir-report.json`。
