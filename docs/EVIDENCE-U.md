# U 方向证据：上游出题，两边作答

日期：2026-11-10；AArch64 / RISC-V 两行于 2026-11-11 随新题面刷新。这是
`U ⊆ G` 方向的端到端证据：题面由 **上游规则表**生成（`upstream-source/oracle`），
官方 runner 与 include 后的生成 runner 读同一份 JSONL。

## 输入

| 项 | 值 |
|---|---|
| gisel | `de8dbbf`（X86 / AArch64 / RISC-V 行）；`ff04df1`（其余 target 行） |
| upstream-source | `a725a7e`（X86 / AArch64）；`7b39841`（RISC-V）；`6d242cb`（其余） |
| ab | 本次 AArch64 提交 |
| LLVM 树 | `/home/ubuntu/llvm/trees/explore` @ `57587b0` → `700e551`（见“发现”） |
| pin | `9bfc850b` + 5 patches（`check-pin.sh` rc=0） |
| LLVM 构建 | `/home/ubuntu/llvm/builds/explore` |

题面生成：

```sh
cd /home/ubuntu/llvm/upstream-source
./oracle/scripts/gen-u.sh x86     /tmp/u-gen/x86d
./oracle/scripts/gen-u.sh aarch64 /tmp/u-gen/a64d
./oracle/scripts/gen-u.sh riscv   /tmp/u-gen/rvb2
```

| target | raw | kept | dropped | `queries.jsonl` sha256 |
|---|---:|---:|---:|---|
| X86 | 10,059 | 10,027 | 32 | `bb5d041ab5c0b4a3…` |
| AArch64 | 30,126 | 29,561 | 565 | `260728bb73cf4db3…` |
| RISC-V | 20,533 | 20,445 | 88 | `14a196f5b25d5652…` |

`dropped` 是上游自己就不能作答的形状（`known-unanswerable` / `parse-error` /
`asserted`，逐条带 reason）。2026-11-11 刷新后 Mips / PPC / WebAssembly / SPIR-V
的 dropped 全部是 `asserted`：新题面里的 `nxv*`、指针当标量、`v32s8` 等形状
撞上上游断言，runner 逐条隔离后只丢命中的那一条。它们两边都不作答，所以不进入分母，也不计入
`unanswerable`。契约见 `CONTRACTS.md` §3.1。

## 结果（正式）

```sh
cd /home/ubuntu/llvm/ab
./run-u-end-to-end.sh x86     /tmp/u-gen/x86d/queries.jsonl     /tmp/u-run/x86d
./run-u-end-to-end.sh aarch64 /tmp/u-gen/a64d/queries.jsonl  /tmp/u-run/a64d
./run-u-end-to-end.sh riscv   /tmp/u-gen/rvb2/queries.jsonl     /tmp/rv-vertical4/u
```

| target | queries | agree | disagree | unanswerable | 两侧答案文件 |
|---|---:|---:|---:|---:|---|
| X86 | 10,027 | 10,027 | 0 | 0 | 逐字节相同 |
| AArch64 | 29,561 | 29,561 | 0 | 0 | 逐字节相同 |
| RISC-V | 20,445 | 20,445 | 0 | 0 | 逐字节相同 |

“答案文件逐字节相同”比 `disagree=0` 更强：`diff.json` 只比 key → action，
`official.answers.jsonl` 与 `ours.answers.jsonl` 全文件相同说明两边连答案行的
编码都没有分歧。

| 产物 | sha256 |
|---|---|
| X86 `diff.json` | `e6913f4250537b66…` |
| AArch64 `diff.json` | `89d3fd10273e5f2d…` |
| RISC-V `diff.json` | `a149257031db7285…` |
| X86 `X86LegalizerInfo.inc` | `38b278dd2a10fe42…` |
| AArch64 `AArch64LegalizerInfo.inc` | `aea61ab511987a0c…` |
| RISC-V `RISCVLegalizerInfo.inc` | `0c993e1005c5c859…` |

三行都在 2026-11-11 用 gisel `de8dbbf` 重新生成了 inc，SHA 与
`EVIDENCE-WP2.md` 的 2026-11-10 快照不同：`076c622` 把“带 `when` 的
`same_as`”改成上游自己的 `minScalarEltSameAsIf` 拼写，三个 target 的 inc 都随之
改变。A/B 用的是新 inc，`disagree=0` 照旧。

## 负控（必须有）

把某个 opcode 的整条 builder 链替换成 `.unsupported()`，要求 `disagree` 全部
落在被注入的 ruleset 内。这里注入的是 **opcode 级**而不是单条规则：生成的 inc
是 builder 链，单条规则的身份在生成后就没了，删单条只能测出注入器自己的工作。

| target | 注入 | disagree | `by_ruleset` | `unknown_keys` | rc |
|---|---|---:|---|---:|---:|
| X86 | `G_SUB`（该 builder 同时建 `G_ADD`） | 164 | `G_ADD 82 / G_SUB 82` | 0 | 1 |
| AArch64 | `G_ICMP` | 216 | `G_ICMP 216` | 0 | 1 |
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
那次修改没有动 emitter，所以当时的 inc SHA 不变，G 侧证据仍然有效。后来的
`076c622` 换成了上游 `minScalarEltSameAsIf` 拼写，inc SHA 才变（见上表）。

修后 AArch64 29,359 条 → `disagree=0`，0 unanswerable；2026-11-11 用新题面扩到
29,561 条，复跑仍是 0。这条差异是 U 方向**自己抓到的**：G 方向的题面由 gisel
生成，永远不会问到这个形状。

## U5：其余六个 target（2026-11-10，2026-11-11 刷新）

U4 只覆盖了 X86 / AArch64 / RISC-V。这一轮把 U 方向接到剩下六个后端：
ARM / Mips / PPC / M68k / WebAssembly / SPIR-V。AMDGPU 按决定不接。

### 输入

```sh
cd /home/ubuntu/llvm/upstream-source
./oracle/scripts/gen-u.sh arm     /tmp/u-gen/armd
./oracle/scripts/gen-u.sh mips    /tmp/u-gen/mipsd
./oracle/scripts/gen-u.sh ppc     /tmp/u-gen/ppcd
./oracle/scripts/gen-u.sh m68k    /tmp/u-gen/m68kd
./oracle/scripts/gen-u.sh wasm    /tmp/u-gen/wasmd
./oracle/scripts/gen-u.sh spirv   /tmp/u-gen/spirvd
```

| target | 配置 | rules | witnessed | shadowed | unexercised | 全配置 unex | raw | kept | dropped | `queries.jsonl` sha256 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ARM | 7 | 741 | 741 | 0 | 0 | 0 | 15,695 | 15,695 | 0 | `513988b78d814e34…` |
| Mips | 5 | 765 | 736 | 0 | 29 | 20 | 11,406 | 11,396 | 10 | `83c4c42543a67856…` |
| PPC | 1 | 49 | 49 | 0 | 0 | 0 | 2,196 | 2,177 | 19 | `8bac7868d2999f3f…` |
| M68k | 1 | 33 | 33 | 0 | 0 | 0 | 2,182 | 2,182 | 0 | `63456e3502ba8e63…` |
| WebAssembly | 4 | 922 | 922 | 0 | 0 | 0 | 9,362 | 9,290 | 72 | `9324c30ae1ef593b…` |
| SPIR-V | 6 | 3,766 | 3,228 | 194 | 344 | 0 | 15,596 | 15,580 | 16 | `9f2156afc668e418…` |

`全配置 unex` 是“每个配置都没命中”的规则数；门禁按跨配置 `(opcode,
rule_index)` 并集判定（`CONTRACTS.md` §5）。SPIR-V 的 344 条 unexercised
全部是 `cross_config=witnessed`：它们被 feature 门控，在别的配置里命中过。

### 结果（正式）

```sh
cd /home/ubuntu/llvm/ab
./run-u-end-to-end.sh arm   /tmp/u-gen/armd/queries.jsonl   /tmp/u-run/armd
./run-u-end-to-end.sh mips  /tmp/u-gen/mipsd/queries.jsonl  /tmp/u-run/mipsd
./run-u-end-to-end.sh ppc   /tmp/u-gen/ppcd/queries.jsonl   /tmp/u-run/ppcd
./run-u-end-to-end.sh m68k  /tmp/u-gen/m68kd/queries.jsonl  /tmp/u-run/m68kd
./run-u-end-to-end.sh wasm  /tmp/u-gen/wasmd/queries.jsonl  /tmp/u-run/wasmd
./run-u-end-to-end.sh spirv /tmp/u-gen/spirvd/queries.jsonl /tmp/u-run/spirvd
```

| target | queries | agree | disagree | unanswerable | 两侧答案文件 |
|---|---:|---:|---:|---:|---|
| ARM | 15,695 | 15,695 | 0 | 0 | 逐字节相同 |
| Mips | 11,396 | 11,396 | 0 | 0 | 逐字节相同 |
| PPC | 2,177 | 2,177 | 0 | 0 | 逐字节相同 |
| M68k | 2,182 | 2,182 | 0 | 0 | 逐字节相同 |
| WebAssembly | 9,290 | 9,290 | 0 | 0 | 逐字节相同 |
| SPIR-V | 15,580 | 15,580 | 0 | 0 | 逐字节相同 |

| target | `diff.json` sha256 | 生成 inc sha256 |
|---|---|---|
| ARM | `343b2af6ced87311…` | `021a84797085030f…` |
| Mips | `3cf0017bb5406852…` | `fd4a51d952b822d6…` |
| PPC | `12ce6309a3d1791f…` | `c15f766bd2a16761…` |
| M68k | `7fde218ddf37faa5…` | `8d843f4f5775e63e…` |
| WebAssembly | `183d96b449d260b8…` | `1293d7a53ab9a743…` |
| SPIR-V | `9078a76da68b9af9…` | `a9037d2c63426a1a…` |

`EVIDENCE.json` 里记录完整的 sha256 和重跑命令；`verify-evidence.sh` 逐项校验。

### 负控

| target | 注入 | disagree | `by_ruleset` | `unknown_keys` | rc |
|---|---|---:|---|---:|---:|
| ARM | `G_LOAD`（该 builder 同时建 `G_STORE`） | 148 | `G_LOAD 74 / G_STORE 74` | 0 | 1 |
| Mips | `G_CTPOP` | 40 | `G_CTPOP 40` | 0 | 1 |
| PPC | `G_SUB`（同时建 `G_ADD`） | 12 | `G_ADD 6 / G_SUB 6` | 0 | 1 |
| M68k | `G_MUL`（同一 builder 建五条算术） | 35 | `G_ADD 7 / G_AND 7 / G_MUL 7 / G_SUB 7 / G_UDIV 7` | 0 | 1 |
| WebAssembly | `G_SELECT` | 36 | `G_SELECT 36` | 0 | 1 |
| SPIR-V | `G_UMIN`（12 条 opcode 共用一个 builder） | 784 | 12 个 ruleset，各 57–67 | 0 | 1 |

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

## 全量题面（`oracle universe --limit 0`，2026-11-11）

前面每轮 U 都是限额题面（AArch64 2,400 个候选）。这一轮把候选宇宙整个展开，专门
回答“gisel 有没有漏接上游规则”：题面只由上游规则字面量生成，gisel 不参与。

```sh
cd /home/ubuntu/llvm/upstream-source
python3 -m oracle universe --arity /tmp/u-gen/a64d/arity.jsonl \
    --out /tmp/u-full2/aarch64-all.jsonl --target aarch64 --limit 0
python3 -m oracle expand --universe /tmp/u-full2/aarch64-all.jsonl \
    --configs baseline,small-cm,bf16,lse,rcpc3,outline-atomics,cssc,fullfp16,sve \
    --out /tmp/u-full2/aarch64-full.jsonl
cd /home/ubuntu/llvm/ab
./run-u-end-to-end.sh aarch64 /tmp/u-full2/aarch64-full.jsonl /tmp/u-run/full2-a64 \
    --allow-ref-asserts 30150 --allow-unanswerable 35316
```

X86 用 `C0,C1,C2,C3`，RISC-V 用 `rv64gc,rv32gc,rv64gcv,rv32gcv,rv64zbb,rv64zfh,
ristretto,rv32zilsd`；`gen-u.sh --full` 一条命令产出同一份 `universe.full.jsonl`。

| target | universe | queries | agree | `ref_asserted` | disagree | 两侧都断言 | `diff.json` sha256 |
|---|---:|---:|---:|---:|---:|---:|---|
| X86 | 280,432 | 1,121,728 | 1,121,728 | 0 | 0 | 1,272 | `0b33032b76d5340f…` |
| AArch64 | 389,512 | 3,505,608 | 3,475,458 | 30,150 | 0 | 35,316 | `523ae4973b4d6821…` |
| RISC-V | 378,562 | 3,028,496 | 3,028,496 | 0 | 0 | 6,008 | `1c53c0d99c2c1008…` |

| target | `queries.full.jsonl` sha256 | 生成 inc sha256 | 两侧答案文件 |
|---|---|---|---|
| X86 | `843060d986ff2da0…` | `38b278dd2a10fe42…` | 逐字节相同 |
| AArch64 | `963e2403e07d9282…` | `0f6dcf0a6b91f105…` | 不同（30,150 行是 `ref_asserted`） |
| RISC-V | `226aa1fff262a542…` | `fe6427bdf480143c…` | 逐字节相同 |

`agree` 含“两侧都断言”的点（diff 的 accounting 是 `agree + ref_asserted +
disagree == matched`）。`--allow-ref-asserts N` 把“上游先断言、我们答出”单独
计类，`--allow-unanswerable N` 锁住“两侧都断言”的条数；两个数都按实测值钉死，
漂了就 rc=1。

### 上游为什么会断言（65,466 条，全部在 AArch64）

| 断言点 | 条数 | 形状 |
|---|---:|---|
| `fatal: cannot implicitly convert a scalable size to a fixed-width size` | 29,151 | `G_ANYEXT/G_SEXT/G_ZEXT`（各 5,535）、`G_MERGE_VALUES` 4,932、`G_UNMERGE_VALUES` 4,788、`G_TRUNC` 1,215 |
| `LowLevelType.h:511`（`getElementType` 用在非向量上） | 18,405 | `G_EXTRACT_VECTOR_ELT` 15,057、`G_FCMP` 1,755、`G_ICMP` 1,602 |
| `LowLevelType.h:429`（`changeElementSize` 用在指针向量上） | 9,999 | `G_CTPOP/G_CTTZ/G_CTLZ/G_CTLS`、`G_PTR_ADD`、移位三条 |
| `LegalizerInfo.cpp:200`（`mutationIsSane`） | 6,291 | `G_SHUFFLE_VECTOR` 6,111、`G_CONCAT_VECTORS` 72、`G_FPTOSI*` 27 |
| `LLT::getNumElements()` on scalable | 1,260 | `G_VECREDUCE_SMAX/SMIN/UMAX/UMIN` |
| `LowLevelType.h:151` / `:470` | 333 / 27 | 移位与 `G_VECREDUCE_AND/OR/XOR` |

其中 35,316 条两侧都断言（计入 `unanswerable`），30,150 条上游断言、我方答出
（`ref_asserted`）。

2026-11-11 重跑后 `diff.json` 直接给出 `ref_asserted_by_site`（只统计这 30,150 条），
机器分类取代了手工漏斗：

| `ref_asserted` 站点 | 条数 |
|---|---:|
| `fatal:cannot implicitly convert a scalable size to a fixed-width size` | 28,863 |
| `fatal:Possible incorrect use of LLT getNumElements for scalable vect…` | 1,260 |
| `LowLevelType.h:470` | 27 |

按 opcode：`G_ANYEXT/G_SEXT/G_ZEXT` 各 5,535、`G_MERGE_VALUES` 4,932、
`G_UNMERGE_VALUES` 4,788、`G_TRUNC` 1,215、移位三条各 369、
`G_VECREDUCE_SMAX/SMIN/UMAX/UMIN` 各 315、`G_VECREDUCE_AND/OR/XOR` 各 9、
`G_FPTOSI/FPTOUI`（含 `_SAT`）各 54。
这三个站点已写进 `EVIDENCE.json` 的 `expect.ref_asserted_by_site`，
`verify-evidence.sh` 逐个比对。这些形状大多不是合法 MIR（`anyext` 两侧位宽不等、指针向量做
标量位宽操作），所以不进入分母；两类都单独计数，不混进 `agree`。已记录在
`/home/ubuntu/admin/upstream-issues/`（#12、#13、#18）。

### 发现一：题面生成器给了 3 槽 opcode 2 个类型（已修）

第一版全量 AArch64 有 4,344 条 `ArrayRef.h:247`：`_coherent_combos` 的向量对
分支直接 append 2 元组，没有按 `type_slots` 补长。3 槽 opcode 收到 2 个类型，
上游规则读 `Query.Types[2]` 就越界。

修法（`upstream-source/oracle/src/universe.py`）：三处向量对分支改成按槽数补长，
并在函数末尾加一道 `len(c) == type_slots` 兜底；`oracle/tests/test_universe.py`
新增两条回归（每个 target × 1–4 槽，combo 长度必须等于槽数）。修后 AArch64 的
`unanswerable` 从 39,660 降到 35,316，题面里不再有畸形查询。

### 发现二：`vec_of(num_elems(scalable))` 丢了 scalable（已修）

全量题面第一次跑出 **30,159** 条 AArch64 差异：30,150 条是上面的上游断言，
**9 条是真 bug**（9 个配置各一条）：

```text
G_SHUFFLE_VECTOR types=["nxv2p0:64","nxv2p0:64"]
官方: Bitcast        → nxv2s64
我方: assert         LegalizerInfo.cpp:200 (mutationIsSane)
```

上游（`AArch64LegalizerInfo.cpp:1369`）写的是
`LLT::vector(DstTy.getElementCount(), LLT::integer(64))`，保留 scalable。语料把它
导成了 `vec_of(num_elems(slot(0)), ty(A_i64))`，而 `vec_of` 渲染成
`LLT::fixed_vector`，于是 `nxv2p0` 变成 `v2s64`（位宽减半），`mutationIsSane`
直接断言。

修法不需要扩语法：`elt_type_to(slot(0), ty(A_i64))` 渲染成
`changeElementType`，与上游表达式逐字等价。改动落在三处：

- `gisel/tests/corpus/AArch64LegalizerInfo.gisel:900` 换成 `elt_type_to`；
- `upstream-source/import/import-cxx.py`：`LLT::vector(X.getElementCount(), T)`
  一律导成 `elt_type_to`，不再落 `vec_of(num_elems(X), T)`；
- `gisel/tests/test_artifacts.py` 两条回归：求值保持 scalable；生成的 inc 必须出现
  `changeElementType` 且该行没有 `fixed_vector`。

先把 9 个形状单独抽出来验证（每个配置一条，共 9 条）：

```sh
./run-u-end-to-end.sh aarch64 /tmp/a64-nine-queries.jsonl /tmp/u-run/a64-nine
# disagree=0 unanswerable=0, rc=0
```

再跑全量：`disagree` 30,159 → 0。`AArch64LegalizerInfo.inc` 现在 SHA 是
`0f6dcf0a6b91f105…`（本文前面表格里的 `aea61ab5…` 是修复前的快照）。G 方向与
D 方向的 AArch64 题面都不含 `nxv2p0` 的 `G_SHUFFLE_VECTOR`，所以那两批冻结证据的
答案不变。

## 复核

```sh
cd /home/ubuntu/llvm/ab && VERIFY_FROZEN=1 ./verify-evidence.sh
# PASS G/x86 … PASS MIR-L3/check-llvm, 59/59 entries pass
# （G 9 + G-neg 9 + U 9 + U-neg 9 + D 9 + U-full 9 + MIR 5）
```

`VERIFY_FROZEN=1` 只读仓库里的 `oracle/`，不读 /tmp。CI 跑的就是这一条
（`.github/workflows/ci.yml`），所以冻结物和 manifest 一旦对不上，push 就会红。

`EVIDENCE.json` 记录每个产物的 sha256、查询数、期望的 `disagree`/`unanswerable`
以及重跑命令；`verify-evidence.sh` 逐项复核，缺产物按失败处理。

## U-full 扩到 9 个 target（2026-11-12）

`U` 是压缩题面（每条规则一个 witness 加采样），`U-full` 是把 oracle 的
universe 按**每个配置**原样展开。六个 target 的 universe 用与 `U` 相同的
limit（spirv 4000，其余 1200）现生成，展开后逐条跑两侧：

```sh
cd /home/ubuntu/llvm/upstream-source
oracle/out/<t>-dump --dump-arity /tmp/u-full2/<t>/arity.jsonl
python3 -m oracle universe --arity ... --target <t> --limit <limit> --out .../universe.jsonl
python3 -m oracle expand --universe .../universe.jsonl --configs <cfg,...> --out .../queries.jsonl
cd /home/ubuntu/llvm/ab && ./run-u-end-to-end.sh <t> .../queries.jsonl <out> [pins]
```

| target | 查询 | agree | 双端断言 | 单边断言 | disagree | 证据 |
|---|---:|---:|---:|---:|---:|---|
| m68k | 252,826 | 252,826 | 0 | 0 | 0 | `U-full/m68k` |
| arm | 1,769,782 | 1,769,782 | 0 | 0 | 0 | `U-full/arm` |
| wasm | 1,011,304 | 1,011,304 | 4,868 | 0 | 0 | `U-full/wasm` |
| ppc | 252,826 | 252,268 | 924 | 558 | 0 | `U-full/ppc` |
| mips | 1,264,130 | 1,263,380 | 0 | 750 | 0 | `U-full/mips` |
| spirv | 4,082,382 | 4,082,136 | 1,464 | 246 | 0 | `U-full/spirv` |

合计新增 8,633,250 条，`disagree=0`。断言分布：

- **wasm 4,868 条双端断言**：`LowLevelType.h:429`（4,404）与
  `LowLevelType.h:151`（464），两侧死在同一个点，属于题面自身触发上游断言。
- **ppc 924 条双端断言**（`LegalizerInfo.cpp:200`）+ **558 条单边断言**，
  单边全部是 `cannot implicitly convert a scalable size to a fixed-width size`。
- **mips 750 条单边断言**：720 条同上，30 条在
  `MipsLegalizerInfo.cpp:133`（`assert(QueryMemSize <= Size && "Scalar can't
  hold MemSize")`）——query 的 mem 比标量槽宽，上游在断言处就停了，我们照规则
  给出 WidenScalar。
- **spirv 1,464 条双端断言 + 246 条单边断言**（`getNumElements` on scalable）。

### 抓到的真差异：SPIR-V 400 条

第一轮在 spirv 上出现 400 条 `disagree`，全部是 `G_FREM` / `G_SDIV` /
`G_SREM` / `G_UDIV` / `G_UREM` 的 `nxv3` 查询：上游答 `Custom`，我们答
`FewerElements`（scalar 16）。

根因不在 SPIR-V 规则本身，而在 importer 对
`numElementsNotPow2(0)` 的翻译：上游是
`isFixedVector() && !isPowerOf2(getNumElements())`，翻译只保留了后半句，
于是这条 `scalarize` 也吃下了 scalable vector（known-min 3 也不是 2 的幂）。
修法两处：`import/import-cxx.py` 补回 `is_fixed_vector` 守卫，SPIR-V 语料
重新生成。修后 400 条全部 `agree`。

两个副作用要记住：

1. `G/spirv` 的 case 数从 5,734 降到 5,689——这条规则不再声称 scalable
   vector，它的 witness 点随之减少；证据已按新题面重跑并冻结。
2. `D/spirv`（domain，3,472,080 条）**没有抓到**这个问题：domain 的类型轴
   只来自声明值域，里面没有 scalable vector。这正是 U-full 存在的理由——
   domain 测“规则无关的声明空间”，U-full 测“上游 universe 的每个配置”。

## 未覆盖

- 已做 9 个 target：X86 / AArch64 / RISC-V（U4）+ ARM / Mips / PPC / M68k /
  WebAssembly / SPIR-V（U5）。AMDGPU 按决定不接。
- 覆盖门禁是跨配置口径，`(opcode, rule_index)` 并集是覆盖下界；逐条 gap 在
  `upstream-source/oracle/known-gaps/<target>.json`（X86 6 条 shadowed，
  AArch64 59、RISC-V 13 条 unexercised/shadowed）。
- U 方向证明“上游规则 gisel 没漏”，不证明“gisel 每题都答对”；后者由 G 方向
  与 `disagree=0` 共同承担。
