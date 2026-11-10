# U 方向证据：上游出题，两边作答

日期：2026-11-10。这是 `U ⊆ G` 方向的第一份端到端证据：题面由 **上游规则表**
生成（`upstream-source/oracle`），官方 runner 与 include 后的生成 runner 读同一份
JSONL。

## 输入

| 项 | 值 |
|---|---|
| gisel | `ff04df1`（本方向未改 gisel 库代码；inc 与 G 证据逐字节相同） |
| upstream-source | `6d242cb`（U4 为 `1f3edff`+filter；U5 加 6 个 runner 与题面） |
| ab | `d2742c2` + 本次 U5 提交 |
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

## U5：其余六个 target（2026-11-10）

U4 只覆盖了 X86 / AArch64 / RISC-V。这一轮把 U 方向接到剩下六个后端：
ARM / Mips / PPC / M68k / WebAssembly / SPIR-V。AMDGPU 按决定不接。

### 输入

```sh
cd /home/ubuntu/llvm/upstream-source
./oracle/scripts/gen-u.sh arm     /tmp/u-gen/arm-f2
./oracle/scripts/gen-u.sh mips    /tmp/u-gen/mips-f2
./oracle/scripts/gen-u.sh ppc     /tmp/u-gen/ppc-f2
./oracle/scripts/gen-u.sh m68k    /tmp/u-gen/m68k-f2
./oracle/scripts/gen-u.sh wasm    /tmp/u-gen/wasm-f2
./oracle/scripts/gen-u.sh spirv   /tmp/u-gen/spirv-f2
```

| target | 配置 | rules | witnessed | shadowed | unexercised | 全配置 unex | raw | kept | dropped | `queries.jsonl` sha256 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ARM | 7 | 741 | 741 | 0 | 0 | 0 | 15,639 | 15,639 | 0 | `776511b43b9313cc…` |
| Mips | 5 | 765 | 736 | 0 | 29 | 20 | 11,341 | 11,341 | 0 | `fbe3dc0cc679c55f…` |
| PPC | 1 | 49 | 49 | 0 | 0 | 0 | 2,192 | 2,176 | 16 | `28a3d06d26ac37c2…` |
| M68k | 1 | 33 | 33 | 0 | 0 | 0 | 2,180 | 2,180 | 0 | `2c86f80921633ccf…` |
| WebAssembly | 4 | 922 | 922 | 0 | 0 | 0 | 9,290 | 9,274 | 16 | `899579aa72313ce1…` |
| SPIR-V | 6 | 3,766 | 3,228 | 194 | 344 | 0 | 15,588 | 15,580 | 8 | `6f5e21ba295ac3cd…` |

`全配置 unex` 是“每个配置都没命中”的规则数；门禁按跨配置 `(opcode,
rule_index)` 并集判定（`CONTRACTS.md` §5）。SPIR-V 的 344 条 unexercised
全部是 `cross_config=witnessed`：它们被 feature 门控，在别的配置里命中过。

### 结果（正式）

```sh
cd /home/ubuntu/llvm/ab
./run-u-end-to-end.sh arm   /tmp/u-gen/arm-f2/queries.jsonl   /tmp/u-run/arm
./run-u-end-to-end.sh mips  /tmp/u-gen/mips-f2/queries.jsonl  /tmp/u-run/mips
./run-u-end-to-end.sh ppc   /tmp/u-gen/ppc-f2/queries.jsonl   /tmp/u-run/ppc2
./run-u-end-to-end.sh m68k  /tmp/u-gen/m68k-f2/queries.jsonl  /tmp/u-run/m68k2
./run-u-end-to-end.sh wasm  /tmp/u-gen/wasm-f2/queries.jsonl  /tmp/u-run/wasm2
./run-u-end-to-end.sh spirv /tmp/u-gen/spirv-f2/queries.jsonl /tmp/u-run/spirv
```

| target | queries | agree | disagree | unanswerable | 两侧答案文件 |
|---|---:|---:|---:|---:|---|
| ARM | 15,639 | 15,639 | 0 | 0 | 逐字节相同 |
| Mips | 11,341 | 11,341 | 0 | 0 | 逐字节相同 |
| PPC | 2,176 | 2,176 | 0 | 0 | 逐字节相同 |
| M68k | 2,180 | 2,180 | 0 | 0 | 逐字节相同 |
| WebAssembly | 9,274 | 9,274 | 0 | 0 | 逐字节相同 |
| SPIR-V | 15,580 | 15,580 | 0 | 0 | 逐字节相同 |

| target | `diff.json` sha256 | 生成 inc sha256 |
|---|---|---|
| ARM | `0fb6fab86099428c…` | `021a84797085030f…` |
| Mips | `d6be55ae41ce62bb…` | `fd4a51d952b822d6…` |
| PPC | `7c43016862fb07c5…` | `c15f766bd2a16761…` |
| M68k | `f3ecba717d4d05c7…` | `8d843f4f5775e63e…` |
| WebAssembly | `7f068a15a1bf43d2…` | `ac5307b57ce7c4ef…` |
| SPIR-V | `119c9f3ac4e41ba7…` | `a9037d2c63426a1a…` |

`EVIDENCE.json` 里记录完整的 sha256 和重跑命令；`verify-evidence.sh` 逐项校验。

### 负控

| target | 注入 | disagree | `by_ruleset` | `unknown_keys` | rc |
|---|---|---:|---|---:|---:|
| ARM | `G_LOAD`（该 builder 同时建 `G_STORE`） | 148 | `G_LOAD 74 / G_STORE 74` | 0 | 1 |
| Mips | `G_CTPOP` | 55 | `G_CTPOP 55` | 0 | 1 |
| PPC | `G_SUB`（同时建 `G_ADD`） | 12 | `G_ADD 6 / G_SUB 6` | 0 | 1 |
| M68k | `G_MUL`（同一 builder 建五条算术） | 35 | `G_ADD 7 / G_AND 7 / G_MUL 7 / G_SUB 7 / G_UDIV 7` | 0 | 1 |
| WebAssembly | `G_SELECT` | 48 | `G_SELECT 48` | 0 | 1 |
| SPIR-V | `G_UMIN`（12 条 opcode 共用一个 builder） | 798 | 12 个 ruleset，各 64–67 | 0 | 1 |

六个 `outside_expected` 都为空：所有差异都落在被注入的 ruleset 内。

### 这一轮修掉的题面缺口

`oracle/src/universe.py` 有三处是**真实缺口**，不是为了让数字好看：

1. SPIR-V 用 14 个地址空间（`SPIRV_POINTER_AS = range(14)`）；其余 target 仍是
   `POINTER_AS = [0,1,2,3,4]`。
2. `COHERENT_SHAPES` / `VECTOR_ELEMS` 补 `("scalar", 1)`：SPIR-V 规则大量点名
   `vNs1`，之前的向量集合没有 i1 元素。修后 ARM `G_SELECT` 的 7 条未覆盖归零。
3. `_coherent_combos` 增加“值 + 掩码”（`(value, s1)`）和 `(ptr_i, ptr_j)` 两类
   组合，且放在 `type_slots >= 2` 块的前部——放末尾会被 `limit` 截断，第一版就是
   这样，导致 `G_MEMCPY` / `G_LOAD` 没有被覆盖。

### known gaps

| target | 条数 | 内容 |
|---|---:|---|
| ARM / PPC / M68k / WebAssembly | 0 | 全部规则 witness 过 |
| Mips | 4 | `G_ANYEXT`/`G_SEXT`/`G_TRUNC`/`G_ZEXT` 的 rule 0 是上游占位 `.legalIf([](){return false;})`，永远不可命中；干活的是后面的 `maxScalar` |
| SPIR-V | 1 | `G_BITCAST` rule 6：第二条 `getActionDefinitionsBuilder(G_BITCAST)` 链的 `legal` 被第一条链的 `custom true` 永久遮蔽 |

最初给 Mips 写了 9 条 gap，其中 5 条（`G_UADDE`/`G_UADDO`/`G_UMULO`/`G_USUBE`/
`G_USUBO`）实际已经 witness，门禁报 `stale-gap-entry`，已删掉——这正是 allowlist
应该起的作用。

### 发现：`bf16` 的归因连接键

SPIR-V 负控第一次跑出 `unknown_keys=60`。原因不是规则差异，而是
`u-attribution.py` 把 diff 的键连回题面时，只把 `float` 折叠成整数，没折叠 `bf16`：
runner 回显 LLT 时把 `v16bf16` 写成 `v16s16`，题面里还是 `v16bf16`，于是这 60 条
差异看起来“没人问过”。

修法：`_runner_type` 增加 `("bf16",) -> ("scalar", 16)`，并加
`tests/test_attribution.py` 锁住 `f32` / `bf16` / 指针三种折叠。修后重跑六个负控，
全部 `unknown_keys=0`。

## 复核

```sh
cd /home/ubuntu/llvm/ab && ./verify-evidence.sh
# PASS G/x86 … PASS U-neg/spirv, 36/36 entries pass（G 9 + G-neg 9 + U 9 + U-neg 9）
```

`EVIDENCE.json` 记录每个产物的 sha256、查询数、期望的 `disagree`/`unanswerable`
以及重跑命令；`verify-evidence.sh` 逐项复核，缺产物按失败处理。

## 未覆盖

- 已做 9 个 target：X86 / AArch64 / RISC-V（U4）+ ARM / Mips / PPC / M68k /
  WebAssembly / SPIR-V（U5）。AMDGPU 按决定不接。
- 覆盖门禁是跨配置口径，`(opcode, rule_index)` 并集是覆盖下界；逐条 gap 在
  `upstream-source/oracle/known-gaps/<target>.json`（X86 6 条 shadowed，
  AArch64 88、RISC-V 28 条 unexercised/shadowed）。
- U 方向证明“上游规则 gisel 没漏”，不证明“gisel 每题都答对”；后者由 G 方向
  与 `disagree=0` 共同承担。
