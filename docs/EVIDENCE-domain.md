# X86 domain: the full declared value space, both sides

This is the G-side completeness run. `cases` asks only the points a rule witness
justifies; `domain` asks every `(opcode, types, mem, imms)` the finite value
space enumerates, including combinations no rule mentions.

## Command

```sh
./run-x86-domain.sh TREE BUILD /tmp/ab-domain/x86-r2/X86LegalizerInfo.inc \
  /tmp/ab-domain/x86-r2/out
```

The script pins two numbers. A run that changes either fails instead of
quietly absorbing a new class:

- `EXPECTED_QUERIES=91340`
- `EXPECTED_UNANSWERABLE=648`

## Snapshot

```text
gisel     a90b091
ab        (this commit)
pin       (trees/explore @ 700e551)
queries   sha256 9e4324a2e9bfff091c955b1e7e957dd9aa67cc8f3cfc18b4f02ce5048abf1363  91,340 lines
answers   sha256 20b481d9bb7464f3bc865ffb8d57fc4ea2c8979d018b2418d30d0c1c6fc6cc34
          official and ours are byte-identical
runtime   libLLVMX86CodeGen.so.24.0git sha256 24bf2a52...
```

`runtime` is part of the provenance: the runner links the CodeGen library
dynamically, so the answer file is a function of that object too.
`verify-evidence.sh` prints a `WARN` when it no longer matches.

```json
{"agree": 91340, "answered_equal": 90692, "disagree": 0, "errors": 0,
 "matched": 91340, "missing_ref": 0, "missing_ours": 0,
 "unanswerable": 648, "ref_asserted": 0}
```

`agree` is "same observable result": 90,692 answered-and-equal plus 648 where
both sides assert. `answered_equal` is the strict count.

Domain shape: 4 configs × 113 opcodes × 24 types × 23 memory types = 95,172
points; the verifier-shape filter drops 3,832 of them (including every comparison
result that is not an integer), leaving 91,340. 648 of the survivors assert on
both sides before returning an action.

## The 648 unanswerable, by opcode

Both sides raise the same assertion, so these are not disagreements; they are
the part of the declared space where neither implementation can produce an
answer. They are pinned, not ignored. Every one of them was **observed**: the
runner called `getAction()`, the abort was caught in-process
(`query-recovery.h`), and the row was written as `unanswerable/asserted`.

| opcode | count | why |
|---|---:|---|
| `G_CTLZ` | 156 | a rule matches (slot 1 is a scalar) and mutates slot 0, a pointer |
| `G_CTPOP` | 156 | same |
| `G_CTTZ` | 156 | same |
| `G_CTTZ_ZERO_POISON` | 156 | same |
| `G_CONSTANT_FOLD_BARRIER` | 6 | memory-shape assertion |
| `G_FREEZE` | 6 | memory-shape assertion |
| `G_IMPLICIT_DEF` | 6 | memory-shape assertion |
| `G_PHI` | 6 | memory-shape assertion |
| **total** | **648** | |

## Why this used to say 1,418

Until 2026-11-11 the runner carried `isKnownUnanswerable()`, a table that wrote
`unanswerable` for `G_CTLZ/CTPOP/CTTZ/CTTZ_ZERO_POISON` whenever **slot 0** was
a pointer or pointer vector, without calling `getAction()`. It matched 1,152
shapes (288 per opcode). Replacing it with the real call splits that set in two:

| slot 1 | outcome | count |
|---|---|---:|
| scalar | abort (a rule fires and mutates slot 0) | 624 |
| scalar | `Unsupported` (no rule for that width/shape) | 168 |
| scalar | `WidenScalar` / `NarrowScalar` on slot 1 | 216 |
| pointer / pointer vector | `Unsupported` (no rule) | 144 |
| **matched by the old table** | | **1,152** |

So 528 of the 1,152 were **answerable**; the table's predicate was an
over-approximation of "this aborts". Those 528 points had never actually been
compared in this run — both sides were written as `unanswerable` by the same
table, which made a blind spot look like agreement.

The remaining 770 − 528 = 242 of the old 1,418 came from answers that today's
build does not reproduce (e.g. `G_CONSTANT`, `G_OR`, `G_ICMP` used to assert and
now return an action). The query set is unchanged (same sha256), so this is
build drift: the runner links `libLLVMX86CodeGen.so` from the build directory,
and that object was rebuilt after the old answers were written. That is why
`runtime` is now recorded.

## What this does and does not prove

Proves: for every declared point that both sides can answer, the generated
`include` returns the same `(status, action, type_idx, new_type)` as the pinned
upstream constructor.

Does not prove: that the domain covers types the upstream verifier accepts but
the domain never enumerates (e.g. widths not in the type universe), nor
anything about the reverse direction (upstream rules missing from `.gisel`).
Those are the U direction and the strict-coverage numbers.

## AArch64 domain：9 个配置，全量 A/B

```sh
./run-aarch64-domain.sh TREE BUILD \
  /tmp/ab-domain/inc/AArch64LegalizerInfo.inc /tmp/ab-domain/a64-domain-r5
```

两个钉数（`EXPECTED_UNANSWERABLE=39056`、`EXPECTED_REF_ASSERTS=1696`）已写进
脚本默认值，环境变量仍可覆盖。

快照：

```text
gisel    c90f3c3（含 atomicrmw ptype 修复；形状表随后迁到 be22962，题面不变）
tree     700e551714cc
inc      c02de72a…（117 rule sets, 741 rules）
runner   official e6925965… / ours 07c459f1…（带 assert_site）
runtime  libLLVMAArch64CodeGen.so sha256 e49c03ec…
题面     9 配置 × 936,960 = 8,432,640 条（queries sha 8f03a48d…，与 r4 相同）
耗时     约 91 s/配置（两个 runner 并行），9 配置约 14 分钟
站点      每个配置 39,024 same + 32 mismatch + 0 missing
```

| 配置 | queries | agree | 其中双端断言 | 官方断言/我方作答 | disagree |
|---|---:|---:|---:|---:|---:|
| baseline | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| small-cm | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| fullfp16 | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| sve | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| bf16 | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| cssc | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| rcpc3 | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| lse | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| outline-atomics | 936,960 | 935,264 | 39,056 | 1,696 | 0 |
| **合计** | **8,432,640** | **8,417,376** | **351,504** | **15,264** | **0** |

`agree` 含双端断言：935,264 = 896,208 条真的答了且一致 + 39,056 条两边都断言。
（2026-11-11：atomicrmw 的地址槽改为固定指针后，每配置少 23,520 条非法点；
这 23,520 条原先都是答了且一致的，所以 unanswerable / ref_asserted 不变。）

### 39,056 条双端断言，崩在哪里

2026-11-11 起 runner 记录每次 abort 的 `file:line`：`__assert_fail` 和
`llvm_unreachable_internal` 用 `-rdynamic` 接管，`report_fatal_error` 走
fatal-error handler；答案行多一个 `"assert_site"` 字段。`diff.py
--assert-sites` 把“两边都不可答”细分成“崩在同一处 / 崩在不同处 / 没有站点”。

baseline 实测（`/tmp/ab-domain/a64-domain-r5`，9 个配置的分布相同）：

| assert_site | 条数 | 说明 |
|---|---:|---|
| `LowLevelType.h:511` | 38,416 | 全部是 `G_EXTRACT_VECTOR_ELT` 的三个槽都是标量：`getElementType()` 的 `assert(isVector())` |
| `LowLevelType.h:151` | 322 | `G_CTPOP/CTLZ/CTTZ/CTLS` 与移位的浮点/指针操作数：`UNREACHABLE Wrong SizeInBits for IEEE Floating point!` |
| `LowLevelType.h:429` | 234 | 同一批 opcode，mutation 对指针调用 `changeElementSize`：`invalid to directly change element size for pointers` |
| `LegalizerInfo.cpp:200` | 52 | `G_FPTOSI/FPTOUI`：规则给出 `mutationIsSane` 不接受的 mutation |
| 两侧不同（见下） | 32 | `G_FPTOSI/FPTOUI` 可伸缩向量：官方 `report_fatal_error`，我方 `LegalizerInfo.cpp:200` |
| 没有站点 | 0 | 接管后不再有“崩了但不知道在哪”的行 |

即 **39,024 / 39,056（99.92%）两边崩在同一个 `file:line`**。这比“两边都没答”
强：同一套规则、同一条断言路径。

32 条“不同站点”全部是 `G_FPTOSI`/`G_FPTOUI`（各 16 条，可伸缩向量目标）。
官方死在 `TypeSize::operator ScalarTy()` 的隐式转换（`report_fatal_error`），
我方死在 `assert(mutationIsSane(...))`。根因在生成谓词：上游写
`Query.Types[0].getSizeInBits() > 64`，我方 `bits_of()` 落成
`getKnownMinValue() > 64`，于是多走了一步 `narrowScalarIf`。两边都没有给出
动作，所以不进 `disagree`；它被单列，见 `gisel/spec/contract.md` §4。

### 1,696 条官方单侧断言（我方有答案）

2026-11-11 复跑 baseline（936,960 条，`/tmp/site-demo/out/baseline`），`diff.json`
新增的 `ref_asserted_by_site` / `ref_asserted_by_opcode` 把它归成一类：

| ref assert_site | 条数 |
|---|---:|
| `fatal:cannot implicitly convert a scalable size to a fixed-width size` | 1,696 |

| opcode | 条数 |
|---|---:|
| `G_ANYEXT` / `G_SEXT` / `G_ZEXT` | 各 496 |
| `G_TRUNC` | 192 |
| `G_UNMERGE_VALUES` | 16 |

这些点本身不是合法 IR（anyext 两侧总位宽不等），官方死在 `TypeSize` 的
可伸缩隐式转换，我方答 `Legal`。它不是规则翻译差异，所以不进 `disagree`；
现在用站点钉死：`--allow-ref-asserts 'fatal:cannot implicitly convert a scalable size to a fixed-width size=1696'`，改一个数就 rc=1
（实测 `=1600` → `moved ... expected 1600, seen 1696`）。

### 契约对账（可复算）

```sh
cd /home/ubuntu/llvm/gisel
python3 tools/reconcile-contract.py \
  /tmp/ab-domain/a64-domain-r5/baseline/queries.jsonl \
  /tmp/ab-domain/a64-domain-r5/baseline/ours.answers.jsonl
```

```text
observed unanswerable  39056
predicted (verifier)  227875
predicted (crash)      38416
crash - observed           0
observed - crash         640
verifier - observed   188819
```

`predicted_crash`（带 `"sound": true` 的检查，实测零误伤）是
`observed` 的子集，差 0；`observed - crash` 就是下表除 `:511` 以外的 640 条；
`verifier - observed` 说明“verifier 会拒绝”远不等于“legalizer 答不了”——
18.9 万条这样的题上游照样给出动作（多为 `Unsupported`）。这条差集就是
`spec/contract.md` §3 里 C8 口径被修正的原因。

`LowLevelType.h:511` 那 38,416 条同时说明一件事：**`unanswerable` 的主体
不是上游缺陷，是一条缺失的形状规则**——`G_EXTRACT_VECTOR_ELT` 的源必须是
向量（`MachineVerifier.cpp:2020`），域里没有这条过滤。补上它，每配置的
`unanswerable` 会从 39,056 降到 640；因为这改变所有分母，本轮只测量、不改表。

### 那 1,696 条是什么

| opcode | 条数 |
|---|---:|
| `G_ANYEXT` | 496 |
| `G_SEXT` | 496 |
| `G_ZEXT` | 496 |
| `G_TRUNC` | 192 |
| `G_UNMERGE_VALUES` | 16 |

例子：`G_ANYEXT bf16 → nxv16i8`

```text
official: LLVM ERROR: cannot implicitly convert a scalable size to a
          fixed-width size in `TypeSize::operator ScalarTy()`   → asserted
ours:     Legal
```

这些点本身不是合法 IR（anyext 要求两侧总位宽相同，bf16 与可伸缩向量的最小
位宽无法相等），上游的谓词在返回动作前就崩了，所以“答案”只由崩溃路径决定。
我们的生成规则不复现这条崩溃路径，于是给出了动作。`diff.py` 把它单列为
`ref_asserted`，并用 `--allow-ref-asserts 1696` 逐配置钉死：**数量变了就失败**，
不会把新的单边断言混进 `agree`。

### 这些点为什幺进不来（IR 侧证据）

`CastInst::castIsValid`（`llvm/lib/IR/Instructions.cpp:3481`）对
`trunc`/`zext`/`sext` 的要求是：

```text
SrcEC == DstEC                  // 标量不能转向量，元素数必须相同
两侧都是 integer / int-vector   // bf16、f16、f32、f64 不是
元素位宽严格变小（trunc）/ 变大（ext）
```

1,696 条逐条分类（baseline；另外 8 个配置的形状集合与它相同）：

| opcode | 源不是整数 | 目标不是整数 | 元素数/kind 不一致 | 位宽方向不对 | 合计 |
|---|---:|---:|---:|---:|---:|
| `G_ANYEXT` | 40 | 112 | 328 | 16 | 496 |
| `G_SEXT` | 40 | 112 | 328 | 16 | 496 |
| `G_ZEXT` | 40 | 112 | 328 | 16 | 496 |
| `G_TRUNC` | 40 | 0 | 136 | 16 | 192 |
| `G_UNMERGE_VALUES` | — | — | — | 16（可伸缩源，已知最小值无法求和） | 16 |

`G_ANYEXT` 不来自 IR：IR 没有 `anyext` 指令。它只来自 call lowering 的
`extendOpFromFlags` 和 legalizer 的 `widenScalarSrc`；两者都从源形状派生目标
（标量→标量、向量→同 lane 向量），同样造不出上面的形状。`IRTranslator` 里没有
任何 `G_ANYEXT` 的产生点。

所以这 1,696 条只有在**手写 MIR** 或**直接调 `getAction()`**（也就是我们的
runner）时才可达；从 IR 编译过来的 MIR 不会出现它们。

这条差异不是规则翻译错误，也不能算“我们比上游对”：它只说明两边对非法形状的
崩溃面不同。真正要守的是它必须恒定。

## RISC-V domain：8 个配置，全量 A/B

```sh
./run-riscv-domain.sh TREE BUILD \
  /tmp/ab-domain/inc/RISCVLegalizerInfo.inc /tmp/ab-domain/rv-domain-r6
```

按配置钉的 `EXPECTED_UNANSWERABLE_MAP` 与 `EXPECTED_PER_CONFIG=253747` 已写进
脚本默认值。

快照：

```text
gisel    a90b091（含 2026-11-11 的 atomicrmw ptype 修复）
tree     700e551714cc
inc      0c993e10…（96 rule sets, 402 rules）
runner   official b363f146… / ours f2040222…
runtime  libLLVMRISCVCodeGen.so sha256 f32be744…
题面     8 配置 × 253,747 = 2,029,976 条
耗时     约 21 s/配置
```

| 配置 | queries | agree | 其中双端断言 | ref_asserted | disagree |
|---|---:|---:|---:|---:|---:|
| rv64gc | 253,747 | 253,747 | 1,074 | 0 | 0 |
| rv32gc | 253,747 | 253,747 | 1,074 | 0 | 0 |
| rv64gcv | 253,747 | 253,747 | 1,074 | 0 | 0 |
| rv32gcv | 253,747 | 253,747 | 1,074 | 0 | 0 |
| rv64zbb | 253,747 | 253,747 | 642 | 0 | 0 |
| rv64zfh | 253,747 | 253,747 | 1,074 | 0 | 0 |
| ristretto | 253,747 | 253,747 | 642 | 0 | 0 |
| rv32zilsd | 253,747 | 253,747 | 1,074 | 0 | 0 |
| **合计** | **2,029,976** | **2,029,976** | **7,728** | **0** | **0** |

每配置少 17,220 条：同样是 atomicrmw 地址槽从 24 类型收窄成 `p0`，被删掉的都是答了且一致的点。

两个 `642` 配置是 `rv64zbb` 和 `ristretto`：feature 改变了哪些形状会走到断言，
所以 `unanswerable` 按配置钉，而不是钉一个总数。两边答案文件在这 8 个配置上
逐字节相同（`official.answers.jsonl` 与 `ours.answers.jsonl` 同 sha）。

## 全量跑暴露的三个工具缺陷（都已修）

### 1. `run-queries.py` 是 O(n²)

旧实现每次 runner 断言，就把“剩余全部查询”重写进临时文件再重启。AArch64
baseline 的 960,480 条里有 39,056 次断言（当时的题面；atomicrmw 收窄后是 936,960），重写量随断言数线性增长、总成本二次。
改成 2,000 行一块 + 流式答案文件后，50k 样本从 60.8 s 降到 55.3 s（答案逐字节
相同）；分块本身不是瓶颈，但先把二次项拿掉了。

### 2. 每次 abort 都被内核送去 apport，约 80 ms

本机 `core_pattern` 是 `|/usr/share/apport/apport …`，`RLIMIT_CORE=0` 也挡不住
piped core。20 次 abort 从 13 ms 变成 1.95 s。runner 在 `main` 里
`prctl(PR_SET_DUMPABLE, 0)` 后，50k 样本 55.3 s → 11.1 s，答案不变
（`/var/crash` 也不再新增报告）。

### 3. 每次 abort 重启进程，约 10 ms

runner 启动要加载共享库并为全部配置建 subtarget/legalizer。AArch64 domain 的
断言密度把吞吐压到 ~380 条/秒，全量 9 个配置要几小时。改成在 `getAction()`
外包 `sigsetjmp`、`SIGABRT` 时 `siglongjmp` 回来，把该题写成
`status:"unanswerable"` 后继续答下一题：50k 样本 11.1 s → 1.64 s，与原
“重启式”答案逐 key 一致（550 条 unanswerable 不变）。真正的 SIGSEGV 仍由
`run-queries.py` 重启兜底。

### 4. 答案行回写类型时合并了 RISC-V 的查询 key

旧 runner 用 `lltStr(parsed)` 回写 `types`。RISC-V 没有开 extended LLT，
`f16` 和 `s16` 在 LLVM 侧都是 `scalar(16)`，于是两个不同查询写成同一个答案
key：270,967 条查询只剩 255,313 个 key，15,654 条被 `diff.py` 静默合并（那时的题面；收窄后是 253,747）。
修法是答案行原样回显查询的类型/内存拼写，只让 `new_type` 用 LLVM 拼写。
修后每个配置都是 270,967 个 key（现在 253,747）；这也是上表 `queries` 与 `agree` 能对齐的原因。

## 结论

- AArch64：8,432,640 个声明点，`disagree=0`；351,504 条双端断言，
  15,264 条上游断言/我方作答，全部按配置钉死。
- RISC-V：2,029,976 个声明点，`disagree=0`；7,728 条双端断言，0 条单边断言。
- 两个 target 的全量 domain 都不需要拿 `cases` 的数字冒充：题面、答案、
  钉数、sha 都在这里。
