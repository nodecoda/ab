# tests

- `test_ab.py`：adapters、target 校验、action-only diff（17 个用例）。
- `test_diff.py`：full-set 比较的报告形状与退出码（8 个用例）。
- `test_key_contract.py`：key 归一化冻结 + ab 与 `gisel.jsonl` 同一函数（3 个用例）。

仍待补：

- `test_key_contract.py`：固定类型拼写 fixture，ab 的 key 与
  `gisel.answers.key` 逐 key 相等；
- `test_runner_protocol.py`：坏输入 rc=2、逐行 flush、崩溃恢复；
- `negative_control`：注入错动作/错变异必须被抓到。
