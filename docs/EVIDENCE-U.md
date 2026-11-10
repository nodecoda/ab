# U 方向证据：上游出题，两边作答

日期：2026-11-10。这是 `U ⊆ G` 方向的第一份端到端证据：题面由 **上游规则表**
生成（`upstream-source/oracle`），官方 runner 与 include 后的生成 runner 读同一份
JSONL。

## 输入

| 项 | 值 |
|---|---|
| gisel | `3421d75`（本方向未改 gisel 库代码；inc 与 G 证据逐字节相同） |
| upstream-source | `1f3edff` + 本次 filter/gen-u 提交 |
| ab | `61b71bf` + 本次 U 脚本提交 |
| LLVM 树 | `/home/ubuntu/llvm/trees/explore` @ `57587b0` → `700e551`（见“发现”） |
| pin | `9bfc850b` + 5 patches（`check-pin.sh` rc=0） |
| LLVM 构建 | `/home/ubuntu/llvm/builds/explore` |

题面生成：

```sh
cd /home/ubuntu/llvm/upstream-source
./oracle/scripts/gen-u.sh x86     /tmp/u-gen/x86b
./oracle/scripts/gen-u.sh aarch64 /tmp/u-gen/aarch64
./oracle/scripts/gen-u.sh riscv   /tmp/u-gen/rvb
```

| target | raw | kept | dropped | `queries.jsonl` sha256 |
|---|---:|---:|---:|---|
| X86 | 10,100 | 10,100 | 0 | `dabe88a9cf5a0acf…` |
| AArch64 | 29,708 | 29,359 | 349 | `b1951a33f9f04ccb…` |
| RISC-V | 20,277 | 20,239 | 38 | `e15c7ccfbe0bccc5…` |

`dropped` 是上游自己就不能作答的形状（`known-unanswerable` / `parse-error` /
`asserted`，逐条带 reason）。它们两边都不作答，所以不进入分母，也不计入
`unanswerable`。契约见 `CONTRACTS.md` §3.1。

## 结果（正式）

```sh
cd /home/ubuntu/llvm/ab
./run-u-end-to-end.sh x86     /tmp/u-gen/x86b/queries.jsonl     /tmp/u-run/x86b
./run-u-end-to-end.sh aarch64 /tmp/u-gen/aarch64/queries.jsonl  /tmp/u-run/a64
./run-u-end-to-end.sh riscv   /tmp/u-gen/rvb/queries.jsonl      /tmp/u-run/rv
```

| target | queries | agree | disagree | unanswerable | 两侧答案文件 |
|---|---:|---:|---:|---:|---|
| X86 | 10,100 | 10,100 | 0 | 0 | 逐字节相同 |
| AArch64 | 29,359 | 29,359 | 0 | 0 | 逐字节相同 |
| RISC-V | 20,239 | 20,239 | 0 | 0 | 逐字节相同 |

“答案文件逐字节相同”比 `disagree=0` 更强：`diff.json` 只比 key → action，
`official.answers.jsonl` 与 `ours.answers.jsonl` 全文件相同说明两边连答案行的
编码都没有分歧。

| 产物 | sha256 |
|---|---|
| X86 `diff.json` | `1577ba8fe1a37d2a…` |
| AArch64 `diff.json` | `63b057e366690a15…` |
| RISC-V `diff.json` | `9d5504aae5166481…` |
| X86 `X86LegalizerInfo.inc` | `c9b39260bb0e4cd6…` |
| AArch64 `AArch64LegalizerInfo.inc` | `c02de72ab08d2e58…` |
| RISC-V `RISCVLegalizerInfo.inc` | `0c993e1005c5c859…` |

inc 的 SHA 与 `EVIDENCE-WP2.md` 完全相同：本方向只改了 runner 的读入侧，没有
动生成器。

## 负控（必须有）

把某个 opcode 的整条 builder 链替换成 `.unsupported()`，要求 `disagree` 全部
落在被注入的 ruleset 内。这里注入的是 **opcode 级**而不是单条规则：生成的 inc
是 builder 链，单条规则的身份在生成后就没了，删单条只能测出注入器自己的工作。

| target | 注入 | disagree | `by_ruleset` | `unknown_keys` | rc |
|---|---|---:|---|---:|---:|
| X86 | `G_SUB`（该 builder 同时建 `G_ADD`） | 166 | `G_ADD 83 / G_SUB 83` | 0 | 1 |
| AArch64 | `G_ICMP` | 225 | `G_ICMP 225` | 0 | 1 |
| RISC-V | `G_ADD`（同时建 `G_SUB`） | 140 | `G_ADD 70 / G_SUB 70` | 0 | 1 |

`attribution.json` 的 `outside_expected` 三项都为空。

## 发现：AArch64 生成语义不等价（已修）

第一轮 AArch64 跑出 **18 条**差异（2 个形状 × 9 配置）：

| 形状 | 官方 | 我们 |
|---|---|---|
| `G_ICMP (v2s32, p0:32)` | `Custom` | assert |
| `G_FCMP (nxv4f32, s8)` | `Unsupported` | assert |

两处都落在语料同一构造：`widen(slot(0), same_as(1)) when (…)`，即上游的
`minScalarEltSameAsIf`。上游先比两个槽的标量位宽、再调用户谓词；gisel 的 core
shim `coreMinScalarSameAs` 把顺序写反了。两个形状里两侧位宽相等（32 vs 32、
8 vs 32），上游直接短路，谓词从不执行；我们先把谓词跑起来，`elem_of(slot(1))`
对 `p0` / `s8` 调 `getElementType()`，`LLT` 断言。

修法在 shim 层（`trees/explore` @ `700e551`）：`coreMinScalarSameAs` /
`coreMaxScalarSameAs` 改成与上游同序，并加单测锁住“守卫必须在结构条件之后”。
`.gisel` 语法、语料、emitter 都没动，inc SHA 不变，所以 G 侧证据仍然有效。

修后 AArch64 29,359 条 → `disagree=0`，0 unanswerable。这条差异是 U 方向
**自己抓到的**：G 方向的题面由 gisel 生成，永远不会问到这个形状。

## 复核

```sh
cd /home/ubuntu/llvm/ab && ./verify-evidence.sh
# PASS G/x86 … PASS U-neg/riscv, 9/9 entries pass
```

`EVIDENCE.json` 记录每个产物的 sha256、查询数、期望的 `disagree`/`unanswerable`
以及重跑命令；`verify-evidence.sh` 逐项复核，缺产物按失败处理。

## 未覆盖

- 只做了 X86 / AArch64 / RISC-V；其余 6 个 target 见计划 U5。AMDGPU 按决定不接。
- 覆盖门禁是跨配置口径，`(opcode, rule_index)` 并集是覆盖下界；逐条 gap 在
  `upstream-source/oracle/known-gaps/<target>.json`（X86 6 条 shadowed，
  AArch64 88、RISC-V 28 条 unexercised/shadowed）。
- U 方向证明“上游规则 gisel 没漏”，不证明“gisel 每题都答对”；后者由 G 方向
  与 `disagree=0` 共同承担。
