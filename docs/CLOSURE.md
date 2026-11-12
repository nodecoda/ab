# CLOSURE：多步 legalize 的等价，靠“后继闭包”而不是靠猜

> 2026-11-12。工作台脚本 `closure.py`；对应缺口 `GAPS.md` O9。
> 一句话：**一步答案相同 + 后继函数相同 + 状态集对后继封闭 ⇒ 整个循环相同**
> （归纳）。这里把第三步变成可执行的：从种子出发，把每个非终结答案的
> `new_type` 变成下一条查询，跑到不动点。

## 1 证明结构

设状态 `s = (config, opcode, types, mem, imms)`，`A_g(s)` / `A_u(s)` 是两侧的
`getAction`，`succ(s) = s[type_idx := new_type]`。

已知（L0 对拍）：对测试集 `S` 里每个 `s`，`A_g(s) = A_u(s)`，比较的是完整三元组
`(action, type_idx, new_type)`，不是只比动作名。

要的是：从某个起点 `s0` 出发的循环轨迹 `s0, s1, s2, ...` 上，两侧每一步都相同。

`closure.py` 做的事：

1. 种子 `S0`（`cases` 或 `domain` 题面）；
2. 两侧各答一遍，逐条比 `(action, type_idx, new_type)`；
3. 对每个非终结答案取 `succ`，`succ ∉ S` 就加入下一轮；
4. 不动点停止。此时 `S` 对 `succ` 封闭：**任何从 `S` 里的起点出发的循环，
   轨迹都留在 `S` 里**，于是归纳成立。

所以 `S` 不是抽样集，是“循环能走到的状态集”本身。它不是“所有可能的 IR 起点”；
边界见 §5。

## 2 两个种子，缺一不可

| 种子 | 是什么 | 关键拼写 |
|---|---|---|
| `G`（`cases`） | 规则感知的等价类代表点 | 指针用通配 `p0:*`，带 corpus 的 mem/imms |
| `D`（`domain`） | 声明类型笛卡尔积（按配置） | 指针是具体宽度 `p0:64` |

key 的相等是结构相等，`p0:* ≠ p0:64`，所以两个集合的并集才覆盖两侧的拼写。

x86 实测：`G` 闭包 3,370 个状态，`D` 闭包 92,132 个，交集只有 1,175。
拿 `D` 当“超集”去省掉 `G` 是错的。

## 3 结果（2026-11-12，pin 700e551714cc）

### 3.1 种子 = G（cases）

| target | 种子 | 新增 | 总计 | 轮数 | 后继边 | 回访 | stuck | 双端断言 | 单边 | disagree |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| x86 | 3,014 | 356 | 3,370 | 3 | 1,577 | 1,221 | 0 | 0 | 0 | **0** |
| aarch64 | 12,559 | 2,827 | 15,386 | 4 | 7,244 | 4,417 | 0 | 36 | 0 | **0** |
| riscv | 6,086 | 261 | 6,347 | 3 | 1,368 | 1,107 | 0 | 0 | 0 | **0** |

### 3.2 种子 = D（domain，每 target 冻结的配置）

| target | 种子（配置） | 新增 | 总计 | 轮数 | 后继边 | 回访 | stuck | 双端断言 | 单边 | disagree |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| x86 | 91,340（C0–C3） | 792 | 92,132 | 2 | 29,941 | 29,149 | 0 | 648 | 0 | **0** |
| aarch64 | 936,960（baseline） | 7,109 | 944,069 | 4 | 241,625 | 234,516 | 0 | 39,062 | 1,696 | **0** |
| riscv | 253,747（rv64gc） | 318 | 254,065 | 2 | 13,388 | 13,070 | 0 | 1,074 | 0 | **0** |

三处读法：

- **双端断言**数与原 domain 证据逐位对得上：x86 648、riscv 1,074、aarch64
  39,056（种子）＋ 6（新增状态）＝ 39,062。closure 没有把断言吞掉。
- **aarch64 的 1,696 条单边断言**就是 `EVIDENCE-domain.md` 里钉死的那一类
  （`fatal: cannot implicitly convert a scalable size to a fixed-width size`），
  用 `--allow-ref-asserts 1696` 钉住；数变了就失败。
- **stuck = 0**：没有“变异没改变类型”的状态，所以循环不会原地打转。

### 3.3 其余六个 target（同样两个种子）

| target | G 种子 | G 新增 | G 总计 | D 种子 | D 新增 | D 总计 | 轮数 G/D | 双端断言 G/D | 单边 | disagree |
|---|---:|---:|---:|---:|---:|---:|:-:|---:|---:|---:|
| arm | 1,614 | 11 | 1,625 | 9,296 | 0 | 9,296 | 2/1 | 0 / 0 | 0 | **0** |
| mips | 1,656 | 0 | 1,656 | 18,745 | 0 | 18,745 | 1/1 | 0 / 0 | 9 | **0** |
| ppc | 94 | 1 | 95 | 1,005 | 0 | 1,005 | 2/1 | 1 / 3 | 0 | **0** |
| m68k | 35 | 2 | 37 | 112 | 0 | 112 | 2/1 | 0 / 0 | 0 | **0** |
| wasm | 894 | 150 | 1,044 | 11,996 | 24 | 12,020 | 3/2 | 0 / 132 | 0 | **0** |
| spirv | 5,689 | 259 | 5,948 | 3,472,080 | 432 | 3,472,512 | 2/2 | 8 / 900 | 0 | **0** |

- `mips` 的 9 条单边断言是冻结 `G` 证据里已有的那一类（`G_LOAD` 值类型为
  `s64`/`s33`/`s63`、mem 为 `s32`/align 8），`--allow-ref-asserts 9` 与原证据同数。
- 六个 target 的 `D` 种子由 `run-domain.sh` 同一条路径生成（`gisel domain` 逐配置），
  条数与 `data/domain.json` 的钉数逐一相等；`domain` 打印的 “dropped ill-formed”
  是生成期就丢掉的点，不进题面。
- 六个 target 的 G/D 并集没有单独量（需要两侧 key 拼写的交集）；三个 L4 target
  的并集在 §3.4。

### 3.4 并集（三个 L4 target）

| target | G | D | 交集 | 并集 |
|---|---:|---:|---:|---:|
| x86 | 3,370 | 92,132 | 1,175 | **94,327** |
| aarch64 | 15,386 | 944,069 | 704 | **958,751** |
| riscv | 6,347 | 254,065 | 256 | **260,156** |

并集就是这三个 target 实测覆盖的循环状态集，disagree 全 0。

九个 target 合起来：`G` 种子 31,641 条、新增 3,867 条；`D` 种子 4,795,281 条、
新增 8,675 条。全部 0 disagree、0 stuck。

## 4 复现

```sh
# 种子（冻结题面）
python3 -c "import gzip,pathlib; pathlib.Path('seed.jsonl').write_bytes(
  gzip.decompress(open('oracle/G/x86/queries.jsonl.gz','rb').read()))"

# 两侧 runner：x86 用 ctor runner（官方 ctor 在库里，ours 在可执行文件里），
# aarch64/riscv 用 build-<t>-runner.sh 的 official/ours 对
./build-x86-ctor-runner.sh TREE BUILD gisel/tests/artifacts/x86.inc OUT/x86
./build-aarch64-runner.sh  TREE BUILD gisel/tests/artifacts/aarch64.inc OUT/a64

python3 closure.py --target x86 --seed seed.jsonl \
    --official OUT/x86.official --ours OUT/x86.ours --out /tmp/closure-x86
```

2026-11-12 的 runner 与种子：

```text
x86     runner.official f339cabd7bf5b04a…   runner.ours 2fa20f4913810339…
aarch64 runner.official e692596525aa8027…   runner.ours 2978e07465498f62…
riscv   runner.official f213119b8c730aff…   runner.ours 1e9a064e4e24bbab…
seed G  x86 f6923a396fd43038… aarch64 63e072063fd00d34… riscv 4f027ac85ffdf778…
seed D  x86 9e4324a2e9bfff09… aarch64 8f03a48d309b15ad… riscv a0fbcbb43829f28a…
```

运行时间：x86 11 s（D）/ 0.5 s（G），riscv 34 s / 6 s，aarch64 2m23s / 2 s。

其余六个 target（2026-11-12，同一棵树，`build-<t>-runner.sh` 生成 runner）：

```text
arm    runner.official 0958b8aaad99d46e…  runner.ours c02249bd4c55a756…
mips   runner.official b0db6d254e24644c…  runner.ours 615bbe40d252834e…
ppc    runner.official bab6bfea592346de…  runner.ours 3c61baab06760058…
m68k   runner.official 5345edc062c99761…  runner.ours 9463fc8d0daef646…
wasm   runner.official 801c6eca8b5bea4b…  runner.ours 4d5434b92b11b704…
spirv  runner.official 530123a4c034852f…  runner.ours 9b2b1bc42f18988b…

seed G  arm 9fcccfb5e8125c06… mips 8405f772d77de0c7… ppc 675e59e9e632fa96…
        m68k e765e396ca57cd3f… wasm 3442ddeedad10e38… spirv 583af2c0019af248…
seed D  arm b25d2ecca6dfa625… mips cbe4901993c1a47d… ppc 7941062a8667ef7f…
        m68k 27358b87337549d4… wasm 5f1449f30ab09e1e… spirv b7a2f00906eef8bf…
```

spirv 的 `D` 种子 3,472,080 条，一轮 ~2 分钟；六 target 合计约 9 分钟。
`closure.py` 的退出码：0 = 全部一致且钉数匹配，1 = 有分歧或钉数不匹配，2 = 用法/IO。

## 5 证明了什么，没证明什么

**证明了**：对 `G` 与 `D` 的并集里的每个起点，循环的每一步两侧都给出相同的
`(action, type_idx, new_type)`；后继不变、集合封闭、没有 stuck。所以对这些起点，
**多步 legalize 的结果相同**，不是“跑过一遍没出事”。

**没证明**：

1. **起点在并集之外**。任意 IR 可以有 `s7`、`s31` 这类宽度，mem 描述符和立即数
   也不保证在 corpus 里。这些起点既不在 `G` 里也不在 `D` 里，第一步就没被问过。
   `s7 → widen → s8` 之后的状态在集合里，但第一步不在。
2. **`Custom` 动作体**。动作名一致只说明“要进 `legalizeCustom`”，里面是手写 C++，
   不在这套规则表里；`Custom` 之后的类型改写不可见。
3. **MIR 层的副作用**。这条链只谈 `getAction` 循环；生成的指令、寄存器、CSE、
   死代码删除在 L1/L2/L3。
4. **分区闭包**（`graph --check-closure` 那条）仍然不成立（未 refine 时
   X86 277 / AArch64 2,671 / RISCV 2,864 / Wasm 302）。closure 绕开了“同一类里
   不同成员会不会有不同后继”的问题，直接问具体状态；两者回答的是不同问题，不能互相替代。

## 6 和 `graph` 的关系

| | `gisel graph` | `ab closure.py` |
|---|---|---|
| 单位 | 类（谓词签名） | 具体状态（LLT 文本） |
| 回答 | 商图上有没有环、闭包成不成立 | 循环实际走到的状态上，两侧答案是否相同 |
| 依赖 | 只用 gisel 的 eval | 两个真实构建 |
| 失败意味着 | 分区选得不对，需要 refine | 规则翻译错了，或题面有洞 |

两个都跑，才既有结构证据又有行为证据。
