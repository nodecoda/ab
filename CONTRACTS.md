# CONTRACTS：ab 的输入、输出与 runner 协议

状态：WP0 草案。规范版本：query/answer JSONL = `cases-format v0.1`（下称
**schema v1**）。canonical 副本在 gisel 仓库 `spec/cases-format.md`。
本项目不得单方面扩展字段。

## 1 query JSONL

```json
{"config":"x86-64-v3","name":"G_ADD","types":["s32"],"mem":null,"imms":[]}
```

- 必填五字段：`config`、`name`、`types`、`mem`、`imms`。
- `types`：LLT 文本（`s32`、`i32`、`f16`、`v4s32`、`nxv4s32`、`p0:64`）。
- `mem`：`null` / `[mty, align]` / `[mty, align, ordering, failure]`；
  二元组读入时补 `("NotAtomic","NotAtomic")`。
- `imms`：整数数组，缺省 `[]`。
- 标注字段（`kind`、`ruleset`、`rule`、`reason`、`source`）不参与 key，必须忽略。
- 行序无语义；同一 key 重复且答案冲突是错误（rc=2）。

## 2 key

```text
(config, name, types, mem, imms)
```

- 相等是**解析后的结构相等**，不是文本相等。
- `p0:*` 是通配，不等于 `p0:64`；runner 若把通配解析成具体宽度，必须同时改写
  查询文件，否则 key 对不上，只能算 `uncovered`。
- `mem` 归一成四元组后再比较。
- `types` 解析用 Core IR；`LLT_invalid` 不是类型，只作为答案哨兵。

## 3 answer JSONL

二选一，且必须原样回显 key 五字段（尤其 `types` 拼写）：

```json
{"config":"x86-64-v3","name":"G_ADD","types":["s32"],"mem":null,"imms":[],
 "action":"Legal","type_idx":0,"new_type":"LLT_invalid"}
```

```json
{"config":"x86-64-v3","name":"G_ADD","types":["s32"],"mem":null,"imms":[],
 "status":"unanswerable","reason":"asserted"}
```

- `action`：`Legal`、`Lower`、`Libcall`、`Custom`、`Unsupported`、
  `WidenScalar`、`NarrowScalar`、`FewerElements`、`MoreElements`、
  `ClampScalar`、`ClampMaxNumElements`、`Scalarize`、`Unmerge` 等。
- `type_idx`：被改写的 slot 下标；无改写为 `0`。
- `new_type`：改写后的 LLT；无新类型写哨兵 `"LLT_invalid"`。
- `status:"unanswerable"`：双方都拒绝回答；不计入 `agree`，也不算通过。
- 断言（SIGABRT）由 runner 自己转成
  `status:"unanswerable", reason:"asserted"`：runner 在 `getAction()` 外包了
  `sigsetjmp` 恢复点，进程内继续答下一题。真正的崩溃（SIGSEGV）仍由
  `run-queries.py` 重启并标记，已答行保留。

## 4 runner 协议

```sh
RUNNER --queries QUERIES.jsonl
```

- 答案写 stdout，一行一个 JSON 对象，逐行 flush（崩溃前的答案必须保留）。
- 进度/诊断写 stderr（`answered N queries`）。
- 坏输入、未知 opcode、坏 LLT：exit 2，不产生半行 JSON。
- `run-queries.py`：0 = 每条查询都有答案或信号型 `unanswerable`；2 = runner
  以非断言信号退出（缺库、用法错、构建坏）。exit 2 时仍写答案文件和
  `--report`，第一条未答查询标 `runner-error`，报告带 `failed_at`/`error`。
  “坏输入但 rc=0 且没有产物”不再是可能的状态。
- runner 必须是纯函数：同一查询、同一二进制、同一配置，答案相同。
- 构建元数据（二进制 sha256、target、config、inc sha256、pin commit）记录在
  run state 里，作为 `EVIDENCE.json` 的输入。

## 5 diff 协议

```sh
diff.py REF.jsonl OURS.jsonl [--queries QUERIES.jsonl] [--json]
        [--compare action|full] [--allow-ref-asserts N]
        [--expect-unanswerable N] [--details N]
```

`--queries` 是题面分母：两侧答案的 key 集必须与它完全相等。没有这个参数时
只能比较两侧的交集，两份被同样截断的答案会显示 `agree=N, disagree=0`；
所有生产调用点都必须传。

退出码：0 = 同 key 集且同答案；1 = 有差异、缺 key、`missing_in_both>0` 或
`unexpected>0`；2 = 坏行/重复 key 冲突/题面读不了。

判定字段（JSON 报告）：

| 字段 | 含义 |
|---|---|
| `ref` / `ours` | 两侧答案行数 |
| `matched` | 两侧都有的 key 数 |
| `agree` | 答案相同（含相同 `unanswerable`） |
| `unanswerable` | 两侧都 `unanswerable` 且理由相同 |
| `disagree` | 答案不同 |
| `missing_ref` / `missing_ours` | 单侧缺失的 key |
| `query_count` | `--queries` 的 key 数（未传为 null） |
| `missing_in_both` | 题面有、两侧答案都没有的 key 数（截断探测器） |
| `unexpected` | 答案有、题面没有的 key 数（越界探测器） |
| `ref_asserted` | 官方侧断言、我方有答案；只有显式 `--allow-ref-asserts` 才计为已知类 |
| `ref_asserted_by_site` | 上面这批的 `file:line`（fatal 消息则记消息）分布 |
| `ref_asserted_by_opcode` | 同一批按 opcode 的分布 |

归因分类固定为：`status` → `action` → `type_idx` → `new_type`（最粗优先）。

`--allow-ref-asserts` 接受三种形式：`N` 钉总数；`site=count,...` 钉每个站点；
`@file.json` 从 JSON 对象读站点表。钉站点是默认建议：总数不变、站点重排
（一个旧断言消失、一个新断言顶上）在只钉总数时看不出来。

## 6 负控

至少两类：

1. 注入错动作（把某条规则的 action 改掉）；
2. 注入错变异（改 `new_type` 选择）。

负控必须使 `diff` rc=1 且 `disagree>0`；抓不到则 gate 失败，不允许冻结。
`EVIDENCE.json` 里负控的 `expect.disagree` 是精确值，不是下限；
`by_ruleset` 必须非空，且只能落在注入的 ruleset 上。

统一退出码（`env.sh:classify_negative_rc`）：

| rc | 含义 | 包装脚本返回 |
|---|---|---|
| 0 | diff 仍一致，注入没被观察到（blind） | 1 |
| 1 | 被抓到，且归因落在被注入的 ruleset | 0 |
| 2 | 输入/基础设施错（文件坏、构建挂、没有 diff.json） | 2 |
| 其他 | 一律按输入错处理，不算“抓到” | 2 |

负控只会把 rc=1 当成功；崩溃、缺文件、runner 非断言退出都不会伪装成证据。

## 7 版本演进

- schema v1 的改动先改 gisel `spec/cases-format.md` 并升版本。
- key 五元组是破坏性契约：三个项目同一 release 对齐。
- ab 的 key 实现必须有契约测试：固定 fixture 下与 `gisel.answers.key` 逐 key 相等。

## 8 MIR/llc 报告（`mir-report.json`）

L1/L2 的产物，字段固定：

```json
{"schema": 1, "layer": "upstream", "generated_at": "...",
 "llc": "...", "llc_sha256": "...",
 "expect": {"timeouts": null, "unsupported": null},
 "unaccounted": [],
 "totals": {"runs": 0, "same": 0, "both_abort": 0, "diff": 0,
            "timeout": 0, "unsupported_run": 0},
 "targets": {"x86": {"files": 0, "runs": 0, "same": 0, "both_abort": 0,
                     "diff": 0, "timeout": 0, "unsupported_run": 0}},
 "inputs": {"official_libs": {"x86": "sha256"}, "ours_libs": {"x86": "sha256"}},
 "files": [{"target": "x86", "path": "...", "runs": [
            {"run": "llc ...", "status": "same", "official_rc": 0,
             "ours_rc": 0, "detail": null}]}]}
```

恒等式（测试必须锁）：

```text
runs == same + both_abort + diff + timeout + unsupported_run
targets[*].runs 之和 == totals.runs
```

- `same`：两侧 rc=0 且 stdout/stderr 相同。
- `both_abort`：两侧 rc!=0 且 stdout/stderr 相同；一致，但单独计数。
- `diff`：任何一侧的输出或 rc 不同。
- `timeout`：任一侧超过 `--timeout`。
- `unsupported_run`：RUN 行不是可重放的 `llc` 调用（例如 `FileCheck` 单独行）。

`timeout` 和 `unsupported_run` 是**没有被比较**的输入，不是“一致”。默认两者
非零就是 rc=1；只有 `--expect-timeouts N` / `--expect-unsupported N` 显式钉住
同一个数字才允许继续。新增一个 timeout 因此是回归，不是分母变大。`unaccounted`
列出没钉住的桶，`expect` 记录这次的钉值。

退出码：0 = `diff == 0`、`unaccounted == []` 且负控未触发；
1 = 有 `diff`、单边 abort、未钉住的 timeout/unsupported、或负控没抓到；
2 = 输入/参数/库错误。

## 9 MIR 形状表（`data/mir-shapes.jsonc`）

这是 `ab` 的产品数据，不是脚本里的临时 dict。

- `schema`：1。
- 每条 entry 必须带 `source`，指向 `GenericOpcodes.td`、MIR 语法文档或上游测试；
  没有 `source` 的条目在加载时拒绝（同 `gisel/contract.py` 的规矩）。
- 条目只描述“如何把一条查询写成合法 MIR”，不描述合法性答案。
- 不进入 gisel wheel，不属于 `.gisel` 语法，不改变四个出口。


## 10 证据 manifest（`EVIDENCE.json` / `evidence.schema.json`）

`evidence.py verify` 是执行器，`evidence.schema.json` 是契约。每条 entry 必须
带 `kind`，校验规则按 kind 分开：

| kind | 必须的产物 | 关键检查 |
|---|---|---|
| `answers` | `diff.json`（+ 答案文件） | 记录值、`answered_equal = agree - unanswerable`、`missing_in_both=unexpected=0` |
| `neg` | `diff.json`、`attribution.json` | `disagree` 精确相等；`by_ruleset` 非空且只含注入项 |
| `summary` | `summary.json` | 每配置聚合值与 `assert_sites` |
| `mir` | `mir-report.json` | bucket 恒等式、每 target、llc sha、恢复基线 |
| `lit` | 两轮 per-test JSONL | 重新计算状态，不信 `identical` |
| `closure` | `data/closure/<target>-<seed>.json` | `ok`、`stuck=0`、`disagree=[]`、`ours_only=0` |
| `adopt` | gisel 的 `<t>.inc` + `docs/ADOPT.md` | inc sha、分支/commit/lib sha 在文档里 |

`verify-evidence.sh [DIRECTION]` 只做转发；`VERIFY_FROZEN=1` 时只读
`oracle/` 和 `data/closure/`，并显式打印 `official_build not checked (frozen)`。
非 frozen 模式缺构建目录是失败，不会 SKIP。

`adopt-check.sh` 会 `git fetch --depth=1` 三个采用分支，比较分支内 `.inc` 的
sha 与 gisel 产物；这是唯一需要网络的证据检查。
