# Backlog: what the evidence does not cover

This is not a wish list.  Each row is a known boundary of the current claims;
the evidence column says how we know, and the last column says why it is not
closed in this cohort.  New work goes here first; it is merged into a cohort
only at a real cut (release, claim change, adoption update).

| 项 | 现状 | 证据 | 为什么不在本 cohort |
|---|---|---|---|
| O9 域外起点（`s7`、`s31`、非常见 mem/imm） | 后继闭包覆盖声明域内；第一步没有问过域外起点 | `docs/GAPS.md` §3 O9；`docs/CLOSURE.md` | 需要一个独立于 gisel 的类型宇宙；属于能力扩展 |
| `Custom` action 体 | 动作名一致；C++ 体里的类型改写没有逐条验证 | `docs/GAPS.md` O9 边界；`SCOPE.md` §6 | 要逐 target 读 C++，成本高于本 cohort |
| 非 refine 的分区闭包 | X86 272 / RISC-V 2,864 / wasm32 302 已字节钉住；AArch64 2,671 只有 opt-in 测试 | `gisel/tests/artifacts/graph/*.json`；`gisel/tests/test_graph_closure_counts.py` | AArch64 非 refine 运行实测 9m22s；签名口径仍是 `--refine` |
| SPIR-V graph | `--max-states 200000` 下 `G_FLDEXP` 报 `unsupported_scale`，rc=2 | `gisel/docs/REPORT-graph.md` §SPIR-V | 需要按 opcode 剪枝，不是加时间上限 |
| 其余六个 target 的 L3 | 只有 x86 / aarch64 / riscv 跑过整套 `check-llvm` | `SCOPE.md` §7；`docs/REPORT-mir.md` §6 | 每轮全量 lit 成本高，先按 target 授予 |
| `run-u --drop-opcode` 包装脚本分支 | 分类器已测；包装器需要真实构建树 | `tests/README.md`；`tests/test_negative_scripts.py` | 要重构 builder 注入点，超出本 cohort |
| `import-cxx` 初稿漂移 | 每轮 `import --check` 证明与 pin 一致；pin 变化必须显式迁移 | `gisel-anchor/README.md`「pin 政策」；`pin/PIN.json` | 自动跟随上游会把“权威”换成“最新 main” |

## 引用规则

- “0 diff / 0 环 / 已覆盖”必须带命令和输入；没有输入指纹的结论只写成
  “当时快照”。
- 引用覆盖范围时按层说：L0 / D / U / U-full / MIR L1/L2/L3 的分母不同。
- 上游缺陷进 `gisel-anchor/docs/UPSTREAM-ISSUES.json`，规则遮蔽/未覆盖进
  `gisel-anchor/oracle/known-gaps/`，两者不混。
