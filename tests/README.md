# tests（WP2）

迁入 `tests/test_ab.py`（17 个用例：adapters、query 校验、action-only diff）。

新增：

- `test_key_contract.py`：固定类型拼写 fixture，ab 的 key 与
  `gisel.answers.key` 逐 key 相等；
- `test_runner_protocol.py`：坏输入 rc=2、逐行 flush、崩溃恢复；
- `negative_control`：注入错动作/错变异必须被抓到。
