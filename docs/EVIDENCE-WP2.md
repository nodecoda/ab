# WP2 evidence: the harness runs from its own checkout

日期：2026-11-10。这是迁移后的**第一次端到端对拍**，不是历史数字的转抄。

## 输入

| 项 | 值 |
|---|---|
| gisel | `3421d75`（WP2：移出 ab，保留指针） |
| upstream-source | `7f9ae6f`（WP1：importer + pin） |
| ab | `46cc6b7`（WP2：迁移 + `gisel.jsonl` 绑定） |
| LLVM 树 | `/home/ubuntu/llvm/trees/explore` @ `57587b095ee7` |
| pin | `9bfc850b9940` + 5 patches（`check-pin.sh` rc=0） |
| LLVM 构建 | `/home/ubuntu/llvm/builds/explore` |

## 结果（`--compare full`）

| target | queries | keys | agree | disagree | missing | unanswerable |
|---|---:|---:|---:|---:|---:|---:|
| X86 | 3,027 | 3,021 | 3,021 | 0 | 0 | 0 |
| AArch64 | 12,595 | 12,595 | 12,595 | 0 | 0 | 0 |
| RISC-V | 6,149 | 6,147 | 6,147 | 0 | 0 | 0 |

X86 的 3,027 → 3,021 与 RISC-V 的 6,149 → 6,147 是重复 key 合并（相同答案），
不是丢查询：`diff.json` 的 `ref`/`ours` 都是合并后的 key 数。

## 命令

```sh
cd /home/ubuntu/llvm/ab
./build-inc.sh <gisel>/tests/corpus/X86LegalizerInfo.gisel /tmp/ab-x86/x86.inc
./build-inc.sh <gisel>/tests/corpus/AArch64LegalizerInfo.gisel /tmp/ab-a64/a64.inc
./build-inc.sh <gisel>/tests/corpus/RISCVLegalizerInfo.gisel /tmp/ab-rv/rv.inc

./run-x86-end-to-end.sh     TREE BUILD /tmp/ab-x86/x86.inc /tmp/ab-x86/out
./run-aarch64-end-to-end.sh TREE BUILD /tmp/ab-a64/a64.inc /tmp/ab-a64/out
./run-riscv-end-to-end.sh   TREE BUILD /tmp/ab-rv/rv.inc   /tmp/ab-rv/out
```

## SHA256

| 产物 | sha256 |
|---|---|
| `x86.inc` | `c9b39260bb0e4cd69c36eb8846ad36d7d1628f09fd36cc06db4995b29f3df794` |
| `a64.inc` | `c02de72ab08d2e58588b776ecd0c2855c85e8e9d0b775999fa0309a7ee5c6ddb` |
| `rv.inc` | `0c993e1005c5c859577f00bdd6f5f98f7684f90496475aebb30cc8f095309c44` |
| `x86 diff.json` | `49ea4bfa855fb47f9a9f93d3b2768bfba634b696c9c97f3df86011643365ad00` |
| `a64 diff.json` | `b60422aac079114ef7f5b3d3cdf21945dc0eb168cf80b5b1c961bbf0721b4a77` |
| `rv diff.json` | `8101f60929996c5fcf4c4ce3ab42b13443692a8e82b8ed3faf2717da7d754de6` |

## 干净安装（gisel wheel）

本机默认 setuptools 59.6 / pip 22 太旧，直接 `pip wheel` 会得到空的
`UNKNOWN-0.0.0`。用隔离构建环境（setuptools 77）得到 `gisel-0.3.0`，装进
venv 后：

```sh
/tmp/gisel-venv/bin/python -c "from gisel import jsonl; print(jsonl.llt_text(('scalar',32)))"
# s32
GISEL_SRC=<venv site-packages> /tmp/gisel-venv/bin/python diff.py a.jsonl a.jsonl --json
# agree=1, disagree=0
```

wheel sha256：`604f53b3d3b24c53c68585aab6a4935fac63c1866680f2ca9a7064aa3669d449`。

## 未覆盖

- 本轮（WP2 时）只跑了 X86 / AArch64 / RISC-V；其余六个 target 已在
  2026-11-10 复跑，见下一节。
- 负控（注入错规则/错动作）属于 WP4，本轮未做。

## 九 target 的 G 侧复跑（2026-11-10）

WP2 当时只记录 X86 / AArch64 / RISC-V。语料补齐到九份以后，`run-<target>-end-to-end.sh`
已经能覆盖全部 target；这一轮把它们全部跑了一遍，并纳入 `EVIDENCE.json`
（`G/*` 九条；全清单 36 条：G 9 + G-neg 9 + U 9 + U-neg 9）。X86 / AArch64 / RISC-V 的三个数字与 WP2 原记录
完全一致，说明记录没有漂移。

| target | queries | keys | agree | disagree | unanswerable | ref_asserted | 两侧答案文件 |
|---|---:|---:|---:|---:|---:|---:|---|
| X86 | 3,027 | 3,021 | 3,021 | 0 | 0 | 0 | 逐字节相同 |
| AArch64 | 12,595 | 12,595 | 12,595 | 0 | 0 | 0 | 逐字节相同 |
| RISC-V | 6,149 | 6,147 | 6,147 | 0 | 0 | 0 | 逐字节相同 |
| ARM | 1,614 | 1,614 | 1,614 | 0 | 0 | 0 | 逐字节相同 |
| Mips | 1,656 | 1,656 | 1,647 | 0 | 0 | 9 | 仅 9 条断言行不同 |
| PPC | 94 | 94 | 94 | 0 | 1 | 0 | 逐字节相同 |
| M68k | 35 | 35 | 35 | 0 | 0 | 0 | 逐字节相同 |
| WebAssembly | 886 | 886 | 886 | 0 | 0 | 0 | 逐字节相同 |
| SPIR-V | 5,734 | 5,734 | 5,734 | 0 | 4 | 0 | 逐字节相同 |

口径说明：

- `keys < queries` 只出现在 X86（-6）和 RISC-V（-2），是同 key 合并，见上一节。
- Mips 的 9 条是**上游断言**：`MipsLegalizerInfo.cpp` 的 `customIf` 里
  `assert(QueryMemSize != 32 && "4 byte load and store are legal")` 对
  “4 字节 unaligned 访问 + 更宽的值槽”不成立，官方 runner abort、我们答
  `Custom`。这是上游缺陷，已落盘
  `admin/upstream-issues/2026-11-09-16-gisel-mips-4byte-unaligned-load-assert.md`；
  脚本用 `--allow-ref-asserts 9` 把它钉成已知类，新增断言会让 rc≠0。
- PPC 的 1 条与 SPIR-V 的 4 条是**两侧都断言/都不作答**（上游 `bitcastIf`、
  `changeElementSizeTo` 重载），对称地记 `unanswerable`，不是差异。

复跑命令（INC 用 `python3 -m gisel gen <corpus> --emit=inc` 生成）：

```sh
cd /home/ubuntu/llvm/ab
./run-x86-end-to-end.sh     TREE BUILD /tmp/g-run/x86/X86LegalizerInfo.inc /tmp/g-run/x86/out
./run-aarch64-end-to-end.sh TREE BUILD /tmp/g-run/a64/AArch64LegalizerInfo.inc /tmp/g-run/a64/out
./run-riscv-end-to-end.sh   TREE BUILD /tmp/g-run/rv/RISCVLegalizerInfo.inc   /tmp/g-run/rv/out
./run-arm-end-to-end.sh     TREE BUILD /tmp/g-run/arm/ARMLegalizerInfo.inc   /tmp/g-run/arm/out
./run-mips-end-to-end.sh    TREE BUILD /tmp/g-run/mips/MipsLegalizerInfo.inc /tmp/g-run/mips/out
./run-ppc-end-to-end.sh     TREE BUILD /tmp/g-run/ppc/PowerPCLegalizerInfo.inc /tmp/g-run/ppc/out
./run-m68k-end-to-end.sh    TREE BUILD /tmp/g-run/m68k/M68kLegalizerInfo.inc /tmp/g-run/m68k/out
./run-wasm-end-to-end.sh    TREE BUILD /tmp/g-run/wasm/WebAssemblyLegalizerInfo.inc /tmp/g-run/wasm/out
./run-spirv-end-to-end.sh   TREE BUILD /tmp/g-run/spirv/SPIRVLegalizerInfo.inc /tmp/g-run/spirv/out
./verify-evidence.sh        # 36/36 entries pass
```

SPIR-V 的查询数从 5,136 变成 5,734：`gisel cases` 在此之后开始拒绝 MIR 装不下的
类型元组（`9e59c9d`、`77bcb7b`）。新集合已复核：无重复 key、两遍 SHA 相同。
规则见证是 343/353（10 条 unexercised），不是“全部 witness”；数字见
`gisel/docs/REPORT-cases.md`。
