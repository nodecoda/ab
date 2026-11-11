# SCOPE：ab 做什么，不做什么

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
| 生成 U 题面 | upstream-source（`oracle`） |
| 解析/翻译 LLVM C++ 规则 | upstream-source（`import`） |
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

- 基线一轮 + 组合替换一轮：`ninja all` 后 `ninja check-llvm`。
- 判据是与**本次基线**逐条相同，不是“0 failed”。
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
