# tests

- `test_ab.py`：adapters、target 校验、action-only diff。
- `test_diff.py`：full-set 比较、`--queries` 三方 key 集、报告形状与退出码。
- `test_key_contract.py`：key 归一化冻结 + ab 与 `gisel.jsonl` 同一函数。
- `test_run_queries.py`：崩溃恢复、半行丢弃、非信号退出 rc=2 且仍写产物。
- `test_negative_rc.py` / `test_negative_scripts.py`：负控 0=盲、1=抓到、
  2=输入错；包装脚本不会把输入错当“抓到”。
- `test_replay_frozen.py`：冻结回放的 diff 参数与字段比对。
- `test_closure.py`、`test_l3.py`、`test_mir_*`、`test_attribution*`：其余层。
- `test_mir_replay.py::UnaccountedIsNotGreen`：timeout / unsupported_run 没有被
  比较，未用 `--expect-*` 钉住就是红，不是 `diff=0` 的绿。
- `test_leg_provenance.py`、`test_negative_scripts.py`：U / G-neg 腿显式接收
  `--tree` / `--build`，不再回落到默认路径。

`test_runner_protocol.py`：真实 runner 的坏 LLT / 坏 JSON rc=2，且先前答案
保留。它需要构建好的 runner，`AB_RUNNER=<path>` 时运行，CI 里 skip；harness
侧（半行、非信号退出）由 `test_run_queries.py` 覆盖。

仍待补：

- 负控包装脚本的 `run-u --drop-opcode` 分支（需要真实构建，当前只测分类器）。

domain 入口：`run-domain.sh TARGET` 是唯一公开入口。x86 / AArch64 / RISC-V
仍由各自的 `run-*-domain.sh` 实现，因为构建方式与 unanswerable 契约不同；
`run-domain.sh TARGET --plan` 只读打印 config / queries / unanswerable，
不 build、不跑查询。`test_domain_contracts.py` 锁住 plan 与 features 文件、
`data/domain.json` 的一致性。新加的 domain 脚本必须先读 `targets/`，
不再复制配置表。
