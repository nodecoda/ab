# WP4（G 侧）负控：注入错规则必须被抓到

日期：2026-11-10。这是 G 题面的负控，不等于 U 题面的负控（U 随 WP3 才存在）。

## 注入

只改一处：`X_G_ADD` 的第一条 legal 从

```text
legal in(slot(0), [X_s8, X_s16, X_s32])
```

改成

```text
legal in(slot(0), [X_s8])
```

其余语料不变。`gisel gen --emit=inc` 仍成功（63 rulesets / 328 rules），
说明这是一条**语法合法、语义错误**的规则，正是要抓的对象。

## 结果

| 项 | 值 |
|---|---|
| 注入 inc | `/tmp/ab-neg/x86-mutated.inc` |
| inc sha256 | `70ff0489bc1e65ac931ee8524956379a4bf0bc3bbb67e287037ce1edd02c776a` |
| 查询 | 3,027（3,021 key） |
| agree | 3,017 |
| disagree | **4** |
| 分类 | 4 × `action` |
| 首条 | `G_ADD` / `s16`：官方 `Legal`，我们 `ClampScalar`（`type_idx=0`, `new_type=s32`） |
| diff rc | **1** |
| diff.json sha256 | `72e1e4a31c21372d7fcf20df9e3ec2b9df5fa75d77844b3baadd7829b5b4b00d` |

命令：

```sh
cd /home/ubuntu/llvm/ab
./scripts/inc/build-inc.sh /tmp/ab-neg/mutated.gisel /tmp/ab-neg/x86-mutated.inc
./scripts/e2e/run-x86-end-to-end.sh TREE BUILD /tmp/ab-neg/x86-mutated.inc /tmp/ab-neg/out
# rc=1
```

结论：harness 能区分“语法能生成”和“规则正确”。G 侧的负控成立；负控不能
只证明 diff 会报错，还要证明它报在**预期的那条**规则上——这里是 `G_ADD s16`，
与注入位置一致。

## 九 target 的负控（2026-11-10）

上面那条是 X86 的手工变异。为了让九个 target 都有同样的负控，新增
`run-g-negative.sh TARGET OPCODE OUT`：用 `inject-missing-opcode.py` 把该
opcode 的整条 builder 链换成 `.unsupported()`，再调用该 target 的
`run-<target>-end-to-end.sh`（题面仍由**未变异**的语料生成，只有我们这一侧的
inc 变了）。归因用 `g-attribution.py`：G 题面的 `ruleset` 是语料里的 builder 名
（`X_G_ADD`），所以“期望集合”由带该 opcode 的查询反推。

| target | 注入 opcode | disagree | `by_ruleset` | unknown | outside | rc |
|---|---|---:|---|---:|---:|---:|
| X86 | `G_ADD` | 127 | `X_G_ADD 127` | 0 | 空 | 1 |
| AArch64 | `G_ZEXT` | 315 | `A_G_ZEXT 315` | 0 | 空 | 1 |
| RISC-V | `G_FPTOSI` | 140 | `R_G_FPTOSI 140` | 0 | 空 | 1 |
| ARM | `G_LOAD` | 71 | `A_G_LOAD 71` | 0 | 空 | 1 |
| Mips | `G_UITOFP` | 15 | `Mips_G_UITOFP 15` | 0 | 空 | 1 |
| PPC | `G_ZEXT` | 3 | `P_G_ZEXT 3` | 0 | 空 | 1 |
| M68k | `G_MUL` | 7 | `M68k_G_ADD 7` | 0 | 空 | 1 |
| WebAssembly | `G_CTLZ` | 56 | `Wasm_G_CTLZ 56` | 0 | 空 | 1 |
| SPIR-V | `G_TRUNC` | 83 | `Spv_G_TRUNC 83` | 0 | 空 | 1 |

两条口径说明：

- `disagree` 可能大于 `by_ruleset` 的总和：`diff.py` 默认只保留前 100 条明细。
  第一版就踩了这个坑（X86 127 条只归因了 100 条）。现在 helper 用
  `--details 200000` 重跑 diff，`g-attribution.py` 也会在明细不足时直接报错，
  不允许“看起来全归因了”。
- M68k 的查询属于语料里的 `M68k_G_ADD` builder（一个 builder 建多条算术），
  所以注入 `G_MUL` 后差异记在 `M68k_G_ADD` 名下。

复跑：

```sh
cd /home/ubuntu/llvm/ab
./scripts/negative/run-g-negative.sh x86     G_ADD     /tmp/g-neg/x86
./scripts/negative/run-g-negative.sh aarch64 G_ZEXT    /tmp/g-neg/a64
./scripts/negative/run-g-negative.sh riscv   G_FPTOSI  /tmp/g-neg/rv
./scripts/negative/run-g-negative.sh arm     G_LOAD    /tmp/g-neg/arm
./scripts/negative/run-g-negative.sh mips    G_UITOFP  /tmp/g-neg/mips
./scripts/negative/run-g-negative.sh ppc     G_ZEXT    /tmp/g-neg/ppc
./scripts/negative/run-g-negative.sh m68k    G_MUL     /tmp/g-neg/m68k
./scripts/negative/run-g-negative.sh wasm    G_CTLZ    /tmp/g-neg/wasm
./scripts/negative/run-g-negative.sh spirv   G_TRUNC   /tmp/g-neg/spirv
./scripts/verify-evidence.sh G-neg   # 9/9
```
