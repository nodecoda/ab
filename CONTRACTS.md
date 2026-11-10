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
- 外部 runner 崩溃（SIGABRT/SIGSEGV）由 `run-queries.py` 转成
  `status:"unanswerable", reason:"asserted"`，并保留已答行。

## 4 runner 协议

```sh
RUNNER --queries QUERIES.jsonl
```

- 答案写 stdout，一行一个 JSON 对象，逐行 flush（崩溃前的答案必须保留）。
- 进度/诊断写 stderr（`answered N queries`）。
- 坏输入、未知 opcode、坏 LLT：exit 2，不产生半行 JSON。
- runner 必须是纯函数：同一查询、同一二进制、同一配置，答案相同。
- 构建元数据（二进制 sha256、target、config、inc sha256、pin commit）记录在
  run state 里，作为 `EVIDENCE.json` 的输入。

## 5 diff 协议

```sh
diff.py REF.jsonl OURS.jsonl [--json] [--compare action|full]
        [--allow-ref-asserts N] [--expect-unanswerable N] [--details N]
```

退出码：0 = 同 key 集且同答案；1 = 有差异或缺 key；2 = 坏行/重复 key 冲突。

判定字段（JSON 报告）：

| 字段 | 含义 |
|---|---|
| `ref` / `ours` | 两侧答案行数 |
| `matched` | 两侧都有的 key 数 |
| `agree` | 答案相同（含相同 `unanswerable`） |
| `unanswerable` | 两侧都 `unanswerable` 且理由相同 |
| `disagree` | 答案不同 |
| `missing_ref` / `missing_ours` | 单侧缺失的 key |
| `ref_asserted` | 官方侧断言、我方有答案；只有显式 `--allow-ref-asserts N` 才计为已知类 |

归因分类固定为：`status` → `action` → `type_idx` → `new_type`（最粗优先）。

## 6 负控

至少两类：

1. 注入错动作（把某条规则的 action 改掉）；
2. 注入错变异（改 `new_type` 选择）。

负控必须使 `diff` rc=1 且 `disagree>0`；抓不到则 gate 失败，不允许冻结。

## 7 版本演进

- schema v1 的改动先改 gisel `spec/cases-format.md` 并升版本。
- key 五元组是破坏性契约：三个项目同一 release 对齐。
- ab 的 key 实现必须有契约测试：固定 fixture 下与 `gisel.answers.key` 逐 key 相等。
