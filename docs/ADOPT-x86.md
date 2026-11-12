# ADOPT-x86：把 x86 规则换成 gisel 生成的 inc

> 2026-11-12。上游 LLVM 树不是 gisel 的仓库；这是一次“采用”，不是 gisel 的功能。
> 证据口径见 `PLAN-internal-authority.md` §7、§9。

## 1 采用点

| 项 | 值 |
|---|---|
| fork 仓库 | `github.com/nodecoda/llvm-project` |
| 分支 | `explore/x86-adopt` |
| commit | `4b8a026249c2`（父提交 `700e551714cc` = pin 基线 `explore/06-review-fixes`） |
| 改动 | `llvm/lib/Target/X86/GISel/X86LegalizerInfo.cpp`：构造函数体 621 行 → `#include "X86LegalizerInfo.inc"` |
| 新增 | `llvm/lib/Target/X86/GISel/X86LegalizerInfo.inc`（生成物，入库） |
| 未动 | `legalizeCustom` 及其后全部代码；`llvm/unittests/Target/X86/X86LegalizerInfoReference.cpp`（冻结参照） |

## 2 生成物来自哪里

```sh
python3 -m gisel gen /home/ubuntu/llvm/gisel/tests/corpus/X86LegalizerInfo.gisel \
    --emit=inc --out X86LegalizerInfo.inc
```

- gisel：`e6811cd`
- corpus：`X86LegalizerInfo.gisel`，sha256 `934a935659e7aff3b0d8cec3a33b013846a12683d776cb4d7156507ef2b78f70`
- inc：sha256 `38b278dd2a10fe42fa699b3661fbee575657bf8e9cdb1399a0d031a7c05b1442`

`inc_sha256` 与 `gisel/tests/artifacts/x86.inc`、`ab/EVIDENCE.json` 里 `G/x86`、`U/x86`
条目的 `snapshot.inc_sha256` 完全相同。也就是说：fork 里编译的那份 inc，就是
证据绑定的那份，不是“另一个输出”。

## 3 验证

树在 `explore/x86-adopt` 上，增量构建后：

```text
libLLVMX86CodeGen.so.24.0git  085928fa26a5e772ff250f045ad4874cd5e8cbbc8046fbeeb2406f7394a9c432
```

这个 sha 与 `ab` MIR-L3 记录里“swap 三构造器后”的 x86 库 sha **逐位相同**
（`/tmp/l3-final3/l3-provenance.json` → `libs.swapped.x86`）。不是相似，是同一个二进制。

| 检查 | 命令 | 结果 |
|---|---|---|
| 全量回归 | `llvm-lit -sv --resultdb-output=... build/test` | 80,596 条逐条比较，`only_in_*`/`changed` 全空；80,655 discovered / 64,916 passed / 15,534 unsupported / 146 xfail，与官方轮完全一致 |
| G 题面回放 | 冻结 `oracle/G/x86` + 本分支 runner | agree 3,014 / disagree 0 |
| U 题面回放 | 冻结 `oracle/U/x86` + 本分支 runner | agree 10,027 / disagree 0 |
| 参照 runner | `./build-runner.sh TREE BUILD /tmp/runner-x86-reference reference` | sha256 `6b2b6af0a02058a4ec5a4c4630ddadee0b822da9b0df44e04524e5934254f619`；轮换后仍答官方答案 |

回放用的 ours runner：`/tmp/x86-adopt/runner.shipping`，
`GIT_DSL_SKIP_PIN_CHECK=1`（树是采用后的，pin 校验对象是参照系，不是本分支）。

## 4 三个待定项的决定

| 问题 | 决定 | 理由 |
|---|---|---|
| inc 是否入库 | **入库**，与 `.cpp` 同一个 commit | 采用分支要能独立构建；生成物就是输入。sha 与 gisel 产物绑定，不会被“悄悄重新生成” |
| 由谁生成 | **人工**，命令写进 commit message 与本文档；CI 侧只有 gisel 仓库的 `verify-evidence.sh` 会从 corpus 重生成并比对 | 采用分支不在 LLVM 项目 CI 里；强行加生成 job 等于把 gisel 塞进上游构建。漂移检测靠 sha 对比，一条命令 |
| 怎么回滚 | `git revert 4b8a026249c2` | 只有一个 commit，无构建系统改动、无其它文件依赖该 inc |

漂移检测（改规则前后都跑）：

```sh
sha256sum llvm/lib/Target/X86/GISel/X86LegalizerInfo.inc \
          /home/ubuntu/llvm/gisel/tests/artifacts/x86.inc
```

两个 sha 不同，说明 fork 里的规则和 gisel 的产物不是一份——要么有意的采用更新，
要么有人手改了生成物。前者要跟着更新 gisel 仓库，后者必须拒绝。

## 5 采用之后怎么改规则

照 `PLAN-internal-authority.md` §9：改 `.gisel` → 重生成 inc → 对 frozen oracle
跑 G/U + 负控（`replay-frozen.py x86 --direction both`）→ 通过才进 fork。
参照系由 `X86LegalizerInfoReference.cpp`（树内）与 `/tmp/runner-x86-reference`
（构建物，sha 见 §3）保留；两者都不随采用分支改变。

## 6 没证明什么

- 这是 x86 一个 target 的采用，不是“全部 target 已切换”。
- 动态 `legalize` 的多步等价仍未证明（`GAPS.md` O9）；本分支的静态闭包结论仍带
  “refine 后”前缀。
- 采用分支只换规则表；loop、custom action、memdesc、`verify` 都还是上游代码。
