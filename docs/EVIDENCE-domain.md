# X86 domain: the full declared value space, both sides

This is the G-side completeness run. `cases` asks only the points a rule witness
justifies; `domain` asks every `(opcode, types, mem, imms)` the finite value
space enumerates, including combinations no rule mentions.

## Command

```sh
./run-x86-domain.sh TREE BUILD /tmp/g/x86.inc /tmp/g/x86-domain
```

The script pins two numbers. A run that changes either fails instead of
quietly absorbing a new class:

- `EXPECTED_QUERIES=91340`
- `EXPECTED_UNANSWERABLE=1418`

## Snapshot

```text
gisel    5a19746
ab       6fb6114
pin      (trees/explore @ 700e551)
queries  sha256 9e4324a2e9bfff091c955b1e7e957dd9aa67cc8f3cfc18b4f02ce5048abf1363  91,340 lines
answers  sha256 eab1a282ef0a5ced8b4de05b08dd35e0774deca28626eb1bb86f140e663928eb
         official and ours are byte-identical
```

```json
{"agree": 91340, "disagree": 0, "errors": 0, "matched": 91340,
 "missing_ref": 0, "missing_ours": 0, "unanswerable": 1418, "ref_asserted": 0}
```

Domain shape: 4 configs × 113 opcodes × 24 types × 23 memory types = 95,172
points; the verifier-shape filter drops 3,832 of them (including every comparison
result that is not an integer), leaving 91,340. 1,418 of the survivors assert on
both sides before returning an action.

## The 1,418 unanswerable, by opcode

Both sides raise the same assertion, so these are not disagreements; they are
the part of the declared space where neither implementation can produce an
answer. They are pinned, not ignored.

| opcode | count | why |
|---|---:|---|
| `G_CTLZ` | 288 | value type checked after result type; the declared space contains type pairs the verifier rejects |
| `G_CTPOP` | 288 | same |
| `G_CTTZ` | 288 | same |
| `G_CTTZ_ZERO_POISON` | 288 | same |
| `G_OR` | 40 | vector/scalar shape assertion |
| `G_CONSTANT_FOLD_BARRIER` | 34 | memory-shape assertion |
| `G_FREEZE` | 34 | memory-shape assertion |
| `G_IMPLICIT_DEF` | 34 | memory-shape assertion |
| `G_PHI` | 34 | memory-shape assertion |
| `G_ICMP` | 32 | result-type assertion |
| `G_FPTRUNCSTORE` | 33 | memory-shape assertion |
| `G_CONSTANT` | 23 | memory-shape assertion |
| `G_FRAME_INDEX` | 2 | memory-shape assertion |
| **total** | **1,418** | |

The four 288s are the only systematic class: the domain enumerates every type
for every slot, and these four opcodes assert on pairs the verifier forbids
before the legalizer can answer. That is a property of asking the full domain,
not a gap in the rules.

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
EXPECTED_UNANSWERABLE=39056 EXPECTED_REF_ASSERTS=1696 \
  ./run-aarch64-domain.sh TREE BUILD \
    /tmp/ab-domain/inc/AArch64LegalizerInfo.inc /tmp/ab-domain/a64-domain-r3
```

快照：

```text
gisel    a90b091
tree     700e551714cc
inc      c02de72a…（117 rule sets, 741 rules）
runner   official 685a0239… / ours c2052969…
题面     9 配置 × 960,480 = 8,644,320 条
耗时     约 87 s/配置（两个 runner 并行），9 配置约 13 分钟
```

| 配置 | queries | agree | 其中双端断言 | 官方断言/我方作答 | disagree |
|---|---:|---:|---:|---:|---:|
| baseline | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| small-cm | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| fullfp16 | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| sve | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| bf16 | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| cssc | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| rcpc3 | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| lse | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| outline-atomics | 960,480 | 958,784 | 39,056 | 1,696 | 0 |
| **合计** | **8,644,320** | **8,629,056** | **351,504** | **15,264** | **0** |

`agree` 含双端断言：958,784 = 919,728 条真的答了且一致 + 39,056 条两边都断言。

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

这条差异不是规则翻译错误，也不能算“我们比上游对”：它只说明两边对非法形状的
崩溃面不同。真正要守的是它必须恒定。

## RISC-V domain：8 个配置，全量 A/B

```sh
EXPECTED_UNANSWERABLE_MAP='{"rv64gc":1074,"rv32gc":1074,"rv64gcv":1074,
 "rv32gcv":1074,"rv64zbb":642,"rv64zfh":1074,"ristretto":642,"rv32zilsd":1074}' \
  ./run-riscv-domain.sh TREE BUILD \
    /tmp/ab-domain/inc/RISCVLegalizerInfo.inc /tmp/ab-domain/rv-domain-r5
```

快照：

```text
gisel    a90b091
tree     700e551714cc
inc      0c993e10…（96 rule sets, 402 rules）
runner   official b363f146… / ours f2040222…
题面     8 配置 × 270,967 = 2,167,736 条
耗时     约 21 s/配置
```

| 配置 | queries | agree | 其中双端断言 | ref_asserted | disagree |
|---|---:|---:|---:|---:|---:|
| rv64gc | 270,967 | 270,967 | 1,074 | 0 | 0 |
| rv32gc | 270,967 | 270,967 | 1,074 | 0 | 0 |
| rv64gcv | 270,967 | 270,967 | 1,074 | 0 | 0 |
| rv32gcv | 270,967 | 270,967 | 1,074 | 0 | 0 |
| rv64zbb | 270,967 | 270,967 | 642 | 0 | 0 |
| rv64zfh | 270,967 | 270,967 | 1,074 | 0 | 0 |
| ristretto | 270,967 | 270,967 | 642 | 0 | 0 |
| rv32zilsd | 270,967 | 270,967 | 1,074 | 0 | 0 |
| **合计** | **2,167,736** | **2,167,736** | **7,728** | **0** | **0** |

两个 `642` 配置是 `rv64zbb` 和 `ristretto`：feature 改变了哪些形状会走到断言，
所以 `unanswerable` 按配置钉，而不是钉一个总数。两边答案文件在这 8 个配置上
逐字节相同（`official.answers.jsonl` 与 `ours.answers.jsonl` 同 sha）。

## 全量跑暴露的三个工具缺陷（都已修）

### 1. `run-queries.py` 是 O(n²)

旧实现每次 runner 断言，就把“剩余全部查询”重写进临时文件再重启。AArch64
baseline 的 960,480 条里有 39,056 次断言，重写量随断言数线性增长、总成本二次。
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
key：270,967 条查询只剩 255,313 个 key，15,654 条被 `diff.py` 静默合并。
修法是答案行原样回显查询的类型/内存拼写，只让 `new_type` 用 LLVM 拼写。
修后每个配置都是 270,967 个 key；这也是上表 `queries` 与 `agree` 能对齐的原因。

## 结论

- AArch64：8,644,320 个声明点，`disagree=0`；351,504 条双端断言，
  15,264 条上游断言/我方作答，全部按配置钉死。
- RISC-V：2,167,736 个声明点，`disagree=0`；7,728 条双端断言，0 条单边断言。
- 两个 target 的全量 domain 都不需要拿 `cases` 的数字冒充：题面、答案、
  钉数、sha 都在这里。
