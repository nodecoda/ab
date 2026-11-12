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

仍待补：

- `test_runner_protocol.py`：真实 runner 的逐行 flush 与坏 LLT rc=2；
- 负控包装脚本的 `run-u --drop-opcode` 分支（需要真实构建，当前只测分类器）。

已记录的延期：`run-domain.sh` 与 `run-{x86,aarch64,riscv}-domain.sh` 仍是四份
入口（640 行），只有通用那份读 `targets/`。合并需要重跑 8.4M 条 domain，暂缓；
新加的 domain 脚本必须先读 `targets/`，不再复制配置表。
