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

## 3 比较语义（固定）

只比 `getAction()` 这一个点：`(opcode, types, mem, imms) -> (action, type_idx, new_type)`。

- 不比 MIR，不跑 `llc`，不比机器码。
- `--compare action`：粗门，只比动作名。
- `--compare full`：验收门，动作 + `type_idx` + `new_type`。
- `unanswerable` 单列，不计入 `agree`，也不算通过。
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
