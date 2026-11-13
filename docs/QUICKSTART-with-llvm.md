# 有 LLVM 时：三层对拍怎么选

这条路径的前提是**一棵 pin 兼容的 LLVM 树和一个 ninja 构建**。它比
`gisel` 的免 LLVM 路径贵得多，所以先弄清你要哪一层，别用最贵的层回答最便宜的问题。

| 层 | 命令 | 回答什么问题 | 成本 |
|---|---|---|---|
| L0 | `ab.py run` | 给定 `(opcode, 类型, mem, 立即数)`，两侧的 `getAction()` 一样吗？ | 秒级/35 条，分钟级/3000 条 |
| MIR | `mir-replay.py` | 真实 `.mir` 走一遍 `llc -run-pass=legalizer`，两侧产物一样吗？ | 分钟级 |
| L3 | `l3.py run` + `compare` | 把 `check-llvm` 整个跑两遍，每条测试的结果一样吗？ | 小时级 |

规则翻译错了，L0 就会红；L0 绿而 MIR 红，说明差异在多步 legalization、custom
action 或下游 verifier，那已经超出“规则”的范围了；L3 是最后的整树回归。

## 0 先过 doctor（1 秒）

```sh
export AB_TREE=<workspace>/llvm-project
export AB_BUILD=<workspace>/build
python3 ab.py doctor
```

```
tree       ok   HEAD 700e551714cc (content matches official_base)
build      ok   /path/to/build (llc present)
10/10 ok, 0 failed
```

`tree` 这一项跑的是 `check-pin.sh`：`PIN.json` 冻结十二个文件的**内容**，
所以“main 里含有 pin 的 commit”不算数。没设环境变量时它直接告诉你要 export 什么。

## 1 出题

```sh
cd ../gisel
gisel cases --corpus m68k --out /tmp/m68k.cases.jsonl     # 35 条，规则感知
gisel domain --corpus m68k --out /tmp/m68k.domain.jsonl   # 112 条，规则无关
```

两者**互不包含**：`domain` 是全量声明值域（含非法组合），`cases` 是压缩后的
等价类/边界/域外代表点。做等价性对拍用 `cases`；做规模/覆盖率统计用 `domain`。

## 2 L0：一条命令的端到端对拍

```sh
cd ../gisel-ab
python3 ab.py run --target m68k \
  --tree "$AB_TREE" --build "$AB_BUILD" \
  --queries /tmp/m68k.cases.jsonl \
  --out /tmp/ab-m68k --state /tmp/ab-m68k-state
```

```
target=m68k compare=full queries=35 agree=35 disagree=0 unanswerable=0 ... rc=0
```

它做五件事：记基线 → 用官方树构建 runner 问一遍 → 换 `.inc` 重编再问一遍 →
逐条 `比较 (action, type_idx, new_type)` → `finally` 恢复并重编。
完整走查见 [TUTORIAL-m68k.md](TUTORIAL-m68k.md)。

`--compare action` 只比动作名，用于冒烟；验收默认 `full`。

## 3 MIR 层：真实 `.mir`

```sh
python3 ab.py mir-from-query --target m68k --queries /tmp/m68k.cases.jsonl \
  --out /tmp/mir-m68k
python3 ab.py mir-replay --target m68k --mir /tmp/mir-m68k \
  --tree "$AB_TREE" --build "$AB_BUILD" --out /tmp/mir-out
```

这一层的价值是覆盖**多步 legalization**：一条查询只问一步，MIR 会让 legalizer
自己迭代到收敛，顺带经过 verifier。差异归因仍靠 `--json` 里的 key。

## 4 L3：整树回归

```sh
python3 ab.py l3 run --out /tmp/l3
python3 ab.py l3 compare /tmp/l3 --json /tmp/l3/summary.json
```

`run` 在恢复后的树上跑一遍 lit，再换成我们的构造器跑一遍；`compare` 逐条
测试比对，**单边存在的测试也算差异**，不是只比总数。

## 5 负控：证明它会红

```sh
bash run-g-negative.sh m68k G_MUL /tmp/neg --tree "$AB_TREE" --build "$AB_BUILD"
# g-negative m68k G_MUL: caught
```

把 `G_MUL` 的规则链替换成 `.unsupported()`，差异必须出现，且必须全部归因到
被改的规则集（`unknown_keys=0`）。没有负控的“0 diff”不是结论。

## 6 结束后确认树已复原

```sh
python3 ab.py verify --target m68k --tree "$AB_TREE" --build "$AB_BUILD" \
  --state /tmp/ab-m68k-state
git -C "$AB_TREE" status --porcelain     # 应为空
```

`verify` 对有 baseline inc 的 target（X86）比 `.inc`，对没有的（M68k、RISCV）
比库的 sha。

## 7 “0 diff”到底证了什么

- 证到：在**这一批查询**上，两侧返回的动作逐条相同。
- 没证：规则集与上游规则链逐条等价；没证：所有真实 MIR 都一样；没证：性能。
- 范围由分母决定：`queries=35` 是 M68k 的全部 `cases`，`queries=3014` 是 X86 的
  全部 `cases`。换分母要重新说一遍结论。

## 8 常见失败

| 现象 | 原因 | 动作 |
|---|---|---|
| `doctor` 的 `tree` fail | 树不是 `official_base` 的内容 | 换冻结的树 |
| `doctor` 的 `tree` warn，有 modified files | 上次运行被强杀，swap 留在树里 | `git -C "$AB_TREE" status` 看到被改文件后 checkout 回去 |
| `baseline inc changed` | 换了树或重编了库 | 确认无误后 `--refresh-baseline`，并把证据重跑 |
| `locks` warn | 另一个 run 在跑 | 等它结束；锁随进程退出释放 |
