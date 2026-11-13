# SCOPE：gisel-ab 做什么，不做什么

## 1 做

| 功能 | 输入 | 输出 |
|---|---|---|
| runner 构建 | 目标源 + 我们的 `.inc` | 可执行 runner + 构建元数据 |
| 跑查询 | query JSONL | answer JSONL（逐行 flush；断言在进程内标记，崩溃后由 run-queries 标记） |
| 全量比较 | 两份 answer JSONL | `agree/disagree/missing/unanswerable` + 退出码 |
| 归因 | 差异 key + 两侧答案 + 规则标注 | 分类报告（status/action/type_idx/new_type） |
| 负控 | 注入错规则/错动作 | 必须被抓到的证据 |
| 冻结 | 上述结果 | `EVIDENCE.json` + `verify-evidence.sh` |

## 2 不做

| 不做 | 归属 |
|---|---|
| 生成 G 题面 | gisel（`cases` / `domain`） |
| 生成 U 题面 | gisel-anchor（`oracle`） |
| 解析/翻译 LLVM C++ 规则 | gisel-anchor（`import`） |
| 修改 `.gisel` 或 `inc` 生成器 | gisel |
| 把对拍结论说成 gisel 的能力 | 文档规范（gisel `docs/SCOPE.md`） |

## 3 L0 比较语义（固定）

L0 只比 `getAction()` 这一个点：
`(opcode, types, mem, imms) -> (action, type_idx, new_type)`。

- L0 不读 MIR、不跑 `llc`、不比机器码。真实 MIR 层的语义见 §6，两层分开计数。
- `--compare action`：粗门，只比动作名。
- `--compare full`：验收门，动作 + `type_idx` + `new_type`。
- `agree` = **可观测状态相同**：两边都答且答案相同，或者两边都在返回前断言。
  `unanswerable` 是这个集合的子集计数，单独输出，不混进 `disagree`。
- `answered_equal = agree - unanswerable`：真正给出答案且一致的对数。
- 恒等式：`agree + ref_asserted + disagree == matched`（只有对称断言计入
  `agree`；单边断言必须由 `--allow-ref-asserts N` 钉住，否则算差异）。
- “通过”不等于“agree 很大”：对称断言的数量由 `--expect-unanswerable N`
  钉死，数变了就是失败。
- 一侧缺失 key 即失败；不允许“取交集”冒充全量。

## 4 退出码

| 码 | 含义 |
|---|---|
| 0 | 同 key 集、同答案（允许的 `unanswerable` 已按参数钉住） |
| 1 | 有差异、缺 key，或负控没抓到 |
| 2 | 输入不可读、坏行、重复 key 冲突、参数错误 |

## 5 边界

- 允许调 gisel CLI；允许 import `gisel.answers` 的 key 读取器（带契约测试）。
- 不得 import `gisel.cases` / `gisel.eval` 作为长期依赖；迁移时抽掉。
- 不得把 ab 的 Python 模块放进 gisel wheel。
- 不接 AMDGPU。

## 6 MIR/llc 层（L1/L2/L3）

L0 证明“规则翻译对了”；§6 证明“换掉规则后，`llc` 在真实 MIR 上的行为没变”。
两层不是互相替代：L0 的分母是类型笛卡尔积，MIR 层的分母是真实指令。

### 6.1 L1：上游 MIR 回放

- 题面：树里 `llvm/test/CodeGen/<T>/**/*.mir` 且 RUN 行含 `-run-pass=legalizer`。
- 两侧：同一个 `bin/llc`，用 `LD_LIBRARY_PATH` 选官方库或 ours 库。
- 判据：对每条 RUN 行比较 `(rc, stdout, stderr)`；另跑一遍 `llvm-lit` 作为粗门。
- 分桶必须显式：`same`、`both_abort`、`diff`、`timeout`、`unsupported_run`。
  `both_abort` 是“两侧都非零且输出相同”，单独打印；`unsupported_run` 不允许静默丢。

### 6.2 L2：查询生成 MIR

- 题面：`gisel cases` 的无答案 JSONL，经 `mir-from-query.py` 变成最小 MIR。
  入口是 `ab.py mir`（先建 MIR，再跑回放）。
- 形状表 `data/mir-shapes.jsonc` 决定哪些查询能变成真题；不可表达的查询进
  `unbuildable_shape` / `unbuildable_type`，config 找不到等价 triple/mattr 的进
  `config_unrealizable`，三者分别计数。`G_PHI`/`G_BRJT`/`G_JUMP_TABLE`/
  `G_BLOCK_ADDR`/`G_PTRAUTH_GLOBAL_VALUE` 显式跳过，理由写在 `SKIP` 表里。
- **每条被测指令的每个 def 都要挂一个 `COPY` sink**。legalizer 入口会
  `isTriviallyDead` 删掉无人使用的指令；没有 sink 时被测指令在三条库上都
  被删掉，输出恒等，任何规则改动都看不见（L2 第一版就是这么假通过的）。
  `COPY` 不是 pre-isel generic opcode，legalizer 既不合法化它也不删它。
- **preflight 用 `-run-pass=none`**：它只回答“这份 MIR 本身是否良构”（解析 +
  机器验证器）。legalizer 在 preflight 里崩掉不算坏题——两侧一样崩，属于
  `both_abort`；把 legalizer 的断言当成“形状非法”会让 `both_abort` 被误记成
  `unbuildable_shape`。
- **两侧都拒绝时用 `-global-isel-abort=0` 复查**：`abort=1` 会在第一条无法
  合法化的指令上直接报错，掩盖后面的 MIR。复查后仍两侧同崩（断言）才留在
  `both_abort`，否则按 `same`/`diff` 计，并记 `mode: abort0` 与
  `abort0_compared` 计数。
- **崩溃输出归一化**：地址、两侧快照库路径、以及 `lib/Target/**` 里的行号
  （我们的 include 会让它们位移）都不参与比较；`lib/CodeGen` 等未打补丁的
  核心行号仍然比较。
- 判据与 L1 相同；额外要求
  `built + unbuildable_shape + unbuildable_type + config_unrealizable == 输入查询数`。
- config 自检：`mir-config-check.py` 要求每个 gisel 配置名在
  `data/mir-configs.json` 里要么有 `mattr`、要么显式标成不可实现，并验证
  `llc` 接受该 triple/flags；它**不**证明特征真值一致，那由 L2 回放本身证明。

### 6.3 L3：全量 check-llvm

- `./l3.py run --out DIR` 跑基线轮、换三个构造函数、组合轮、恢复重编，写
  `DIR/l3-provenance.json`；`./l3.py compare DIR --json DIR/l3-summary.json`
  做逐条对比。
- 判据是与**本次基线**逐条相同，不是“0 failed”，也不是五个汇总数相同：
  `PASS->XFAIL` 与 `XFAIL->PASS` 互换在两份汇总里完全抵消。
- 逐条数据取 lit 的 `--resultdb-output`（`(status, expected)`）；
  `--xunit-xml-output` 把 XFAIL 打印成普通通过用例，不够用。
  ResultDB 不含 EXCLUDED/SKIPPED（本次 59 条），Skipped 数由日志钉住。
- 组合轮的三个库必须与基线**不同**：`.inc` 没接上时两轮读的是同一个库，
  汇总照样全绿。`verify-evidence.sh` 把这一条当失败。
- 换源一律走源码替换（`swap-source-ctor.py --tree`）：上游没有
  `X86LegalizerInfo.inc`，往构建目录拷一个谁都不 include 的文件不产生任何
  依赖，`ninja` 不会重编。
- 失败必须拆单 target 归因，不允许用重跑掩盖。

### 6.4 退出码与负控

| 码 | 含义 |
|---|---|
| 0 | 所有可运行项一致，负控未触发 |
| 1 | 有 diff / 单边 abort / 负控没抓到 / config 自检失败 |
| 2 | 输入不可读、坏 RUN 行、缺库、参数错误 |

负控固定两类：注入错 opcode（`inject-missing-opcode.py`）必须让 L1 出现 diff；
注入错 config 映射必须让 L2 的 config 自检失败。

### 6.5 不变量

- L1/L2 只跑 `-run-pass=legalizer`，不生成机器码；L3 跑整套测试。
- 不往源码树写产物；所有报告在 `--out`。
- 换源/构建必须持锁，`restore` + 重建基线库是收工硬门。
- `0 diff` 只说明“两侧一致”，不说明“规则正确”。

## 7 覆盖范围（哪些 target 跑到哪一层）

不是每个 target 都跑满了所有层。分母不同，结论就不同；引用时按层说，别把 3
个 target 的结果说成 9 个。

| 层 | 内容 | target | 题面规模（实测） | 证据位置 |
|---|---|---|---|---|
| L0 G | gisel 出题，两侧答 `getAction()` | 9 个 | x86 3,014 / aarch64 12,559 / riscv 6,086 / arm 1,614 / mips 1,647 / ppc 94 / m68k 35 / wasm 894 / spirv 5,734 | `EVIDENCE.json` `G/*` |
| L0 U | gisel-anchor 出题（采样） | 9 个 | x86 10,027 / aarch64 29,561 / riscv 20,445 / arm 15,695 / mips 11,396 / ppc 2,177 / m68k 2,182 / wasm 9,290 / spirv 15,580 | `EVIDENCE.json` `U/*` |
| L0 负控 | 注入错 opcode / 错谓词 | 9 个 | 每个 target 一组 | `EVIDENCE.json` `G-neg/*`、`U-neg/*` |
| D | 规则无关的声明值域全量对拍 | 9 个 | x86 91,340 / aarch64 8,432,640 / riscv 2,029,976 / spirv 3,472,080 / mips 18,745 / wasm 11,996 / arm 9,296 / ppc 1,005 / m68k 112（agree；unanswerable 另计） | `EVIDENCE.json` `D/*` |
| U-full | 上游题面按全部配置展开 | 9 个 | x86 1,121,728 / aarch64 3,505,608 / riscv 3,028,496 / spirv 4,082,382 / arm 1,769,782 / mips 1,264,130 / wasm 1,011,304 / m68k 252,826 / ppc 252,826 | `EVIDENCE.json` `U-full/*` |
| MIR L1 | 上游 `-run-pass=legalizer` MIR 回放 | x86, aarch64, riscv, arm, mips, ppc（名义） | x86/a64/rv 624 条 RUN（611 same + 13 双端 abort）；arm 43、mips 72、ppc 1（无 generic 指令）；diff 全 0 | `docs/REPORT-mir.md` §2、§6.6 |
| MIR L2 | 由查询合成 MIR 回放 | 九个 target | 21,128 建成（20,016 same + 1,047 双端 abort + 65 timeout，diff 0） | `docs/REPORT-mir.md` §3、§6.6–§6.9、`data/riscv-contract.json` |
| MIR L3 | `ninja check-llvm` 全量 | x86, aarch64, riscv 组合 | 80,655 个 lit 测试（逐条比 80,596） | `EVIDENCE.json` `MIR-L3/check-llvm`、`docs/REPORT-mir.md` §6 |

约束：

- 9 个 target 都有 L0（G/U/负控）、D（domain 全量）和 U-full；九个都有 MIR L2（其中六个有 L1），只有 x86、aarch64、riscv 有 L3。说“9 个 target 都对拍过”时，主语可以是 L0、D 或 U-full；说 MIR L3
  时主语必须是那三个。
- 3 个 target 的 domain 有双端断言需要单独解释：SPIR-V 900 条（G_SPLAT_VECTOR，
  两侧死在不同的断言点，见 `docs/EVIDENCE-domain.md` §5）、WebAssembly 132 条、
  PowerPC 3 条；它们都按配置钉死，不是 `disagree`。
- `targets/*.json` 的 `query_count` 是**当前生成器的输出**，由
  `./refresh-counts.py --check` 校验；它不等于 `EVIDENCE.json` 里某次冻结运行
  的条数（证据绑定的是它自己的 queries 文件与 sha）。
- MIR 的 **L1**（`MIR-L1/upstream`）、**L2**
  （`MIR-L2/*`，九个 target）和 **L3**
  （`MIR-L3/check-llvm`）都进了 `EVIDENCE.json`；L3 的证据是两轮
  `(status, expected)` 的逐条记录，`verify-evidence.sh` 会从冻结的 per-test
  文件重算比较结果，并拒绝“换了 `.inc` 但库没变”的组合轮。
- 对照最初的规划还缺什么，见 `docs/GAPS.md`（三根柱子、按价值排序）。
