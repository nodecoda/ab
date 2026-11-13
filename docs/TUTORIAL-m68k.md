# 十分钟：用 M68k 走一遍规则对拍

这条路径的对象是**想自己验证这套东西成不成立的人**。选 M68k 不是因为它是重点
target，而是因为它小到能在一次茶歇里跑完：13 条规则、35 条查询、单配置、
一次对拍 30 秒。X86 是 3,014 条查询，同样的流程，只是慢得多。

跑完你会得到四个数字：`cases=35`、`agree=35`、`disagree=0`、负控
`disagreements=7`。前三个说明“我们的规则和 pin 的上游在这 35 个点上一模一样”，
第四个说明“如果规则真的错了，这套机制抓得住”。

## 0 前提

```
<workspace>/
├── llvm-project/      官方树（内容必须等于 PIN.json 的 official_base）
├── gisel/             规则 DSL：出题、生成 inc
├── gisel-anchor/      PIN.json、importer、oracle
└── ab/                这个工作台
```

另外需要一个按该树配置好的 ninja 构建目录（`build.ninja` 和 `bin/llc` 都在）。
没有构建的环境不受影响：`gisel` 本体不需要 LLVM，这里只是对拍需要。

```sh
export AB_TREE=<workspace>/llvm-project
export AB_BUILD=<workspace>/build
```

## 1 先让 doctor 说“可以”（约 1 秒）

```sh
python3 ab.py doctor
```

期望最后一行 `10/10 ok, 0 failed`，退出码 0。它会检查 Python、`gisel`、
`PIN.json`、树、构建、ninja、磁盘、上一次运行的 ledger 和锁。

树那一项不是比 HEAD，而是跑 `check-pin.sh`：`PIN.json` 冻结了十二个文件的
**内容**，所以哪怕你的 main 含 pin 的 commit，只要 legalizer 内容不同就会被拒绝。
这一条挡掉的是“以为在对 pin，其实在对 main”。

失败时每条都带 `fix:`，例如没设环境变量：

```
tree       fail AB_TREE is not set
                fix: export AB_TREE=/path/to/llvm-project (a pin-compatible checkout); --tree overrides it
```

## 2 出题（约 0.2 秒）

```sh
cd ../gisel
python3 -m gisel cases --corpus m68k --out /tmp/m68k.cases.jsonl
```

```
/tmp/m68k.cases.jsonl: cases=35 equivalence=14 boundary=11 outside=10
rules=13 witnessed=11 shadowed=2 unexercised=0
```

这 35 条是**问题**，不带答案。三类各自的意思：

| 类 | 条数 | 覆盖什么 |
|---|---:|---|
| equivalence | 14 | 每个等价类一个代表点；类由谓词取值向量切分 |
| boundary | 11 | 类边界：宽度、lane 数、标量/向量交界 |
| outside | 10 | 域外一档：落到 `unsupported` 或兜底的那些查询 |

`unexercised=0` 说明没有一条规则是“生成了题却没被问到”的。`ill-formed=2`
是形状过滤掉的类型元组（例如 `G_STORE` 的 mem 组合），不是漏题。

`--corpus m68k` 是糖：等价于 `tests/corpus/M68kLegalizerInfo.gisel` 加
`tests/cases/m68k-features.json`。装上 wheel 之后也能用同一个名字。

## 3 生成要替换的规则（约 0.1 秒）

```sh
python3 -m gisel gen tests/corpus/M68kLegalizerInfo.gisel \
  --emit=inc --out /tmp/m68k.inc
```

```
/tmp/m68k.inc: 6 rule sets, 13 rules
```

这个 `.inc` 就是“我们的规则”。对拍时它被 `#include` 进上游的
`M68kLegalizerInfo.cpp`，于是同一个 LLVM 构建里有两套 legalizer：官方的和我们的。

## 4 对拍（约 30 秒）

```sh
cd ../gisel-ab
python3 ab.py run --target m68k \
  --tree "$AB_TREE" --build "$AB_BUILD" \
  --queries /tmp/m68k.cases.jsonl \
  --out /tmp/ab-m68k --state /tmp/ab-m68k-state
```

```
target=m68k compare=full queries=35 agree=35 disagree=0 unanswerable=0 missing_ref=0 missing_ours=0 rc=0
official=/tmp/ab-m68k/official.answers.jsonl
ours=/tmp/ab-m68k/ours.answers.jsonl
diff=/tmp/ab-m68k/diff.json
```

它在做的事：

1. 记下基线（树的 HEAD、官方库 sha）到 `state/baseline/provenance.json`；
2. 用官方树构建一个 query runner，问 35 条，写 `official.answers.jsonl`；
3. 把 `.inc` 换进去，重编库，再问同样 35 条，写 `ours.answers.jsonl`；
4. 逐条比 `(action, type_idx, new_type)`，写 `diff.json`；
5. 无论成败，`finally` 里恢复原文件并重编，退出前打印 `verify` 能查的状态。

`agree=35 disagree=0` 的含义要读准：**在这 35 个点上，两侧返回的动作完全相同**。
它不证明“九千条真实 MIR 也一样”，那是 L3（`l3.py`，跑 `check-llvm`）的事。

## 5 负控：证明这套机制不是永远说“一样”（约 31 秒）

一个只会在正确输入上说 OK 的对拍没有价值。负控把 `G_MUL` 的规则链替换成
`.unsupported()`，再跑一遍；对拍必须报差异，而且差异必须只来自那一个规则集：

```sh
bash run-g-negative.sh m68k G_MUL /tmp/ab-m68k-neg \
  --tree "$AB_TREE" --build "$AB_BUILD"
```

```
 "disagree": 7,
 "expected_rulesets": ["M68k_G_ADD"],
 "unknown_keys": 0
g-negative m68k G_MUL: caught
```

`disagree=7` 是“抓到了”，`unknown_keys=0` 是“没有解释不了的差异”，
`expected_rulesets` 是归因结果：这 7 条都落在被改动的规则集上。

## 6 确认树已经复原（约 1 秒）

```sh
python3 ab.py verify --target m68k --tree "$AB_TREE" --build "$AB_BUILD" \
  --state /tmp/ab-m68k-state
git -C "$AB_TREE" status --porcelain    # 应为空
```

```
lib=...libLLVMM68kCodeGen.so.24.0git sha256=24cacf3969a019bf baseline=24cacf3969a019bf OK
```

`verify` 对没有 generated baseline inc 的 target（M68k、RISCV 这类）比的是库的
sha；对 X86 这类有 baseline inc 的比的是 `.inc`。

## 7 出错时先看这三条

| 现象 | 原因 | 动作 |
|---|---|---|
| `doctor` 的 `tree` 失败，说 "carries content the corpus was not imported from" | `AB_TREE` 指到了 main，不是 `official_base` | 换到冻结的官方树 |
| `doctor` 的 `tree` 是 `warn`，有 modified files | 上一次运行被 `kill -9`，swap 留在树上 | 不要删锁；`git -C "$AB_TREE" status` 看到被改的文件后 `git checkout --` 它们 |
| `locks` 是 `warn` | 另一个 run 正在跑 | 等它结束；锁随进程退出释放 |

## 8 时间账（本机实测）

| 步骤 | 耗时 |
|---|---:|
| doctor | 1 s |
| `gisel cases` | 0.2 s |
| `gisel gen --emit=inc` | 0.1 s |
| `ab.py run`（含两次编译） | 30 s |
| 负控 | 31 s |
| `verify` + `git status` | 1 s |

第一次跑还要加上 runner 的首次编译；之后命中缓存。无论哪种，都在十分钟内。
