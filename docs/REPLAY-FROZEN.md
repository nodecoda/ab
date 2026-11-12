# 改语料之后的 frozen 回放

`verify-evidence.sh` 证明冻结物没变；这里证明**新生成物**还能回答同一批问题。
`replay-frozen.py` 不重算官方侧：它把 `oracle/<G|U>/<target>/` 里的
`queries.jsonl` 和 `official.answers.jsonl` 解出来，用当前 `.gisel` 重新生成
`inc`、重建 ours runner，再和冻结的官方答案逐条比较。

```sh
python3 replay-frozen.py TARGET \
  --tree /home/ubuntu/llvm/trees/explore \
  --build /home/ubuntu/llvm/builds/explore \
  --out /tmp/replay-TARGET --direction both
```

G 是 gisel 自己出的题，U 是上游规则出的题；两个方向都回放。已知的
`ref_asserted` / `unanswerable` 条数从冻结的 `diff.json` 读取，并用
`--allow-ref-asserts N` / `--expect-unanswerable N` 钉死；条数变了同样失败。

## 2026-11-12 结果：九 target、18 个方向全部一致

| target | G agree | U agree | ref_asserted | unanswerable | inc sha256 |
|---|---:|---:|---:|---:|---|
| x86 | 3,014 | 10,027 | 0 | 0 | `38b278dd2a10fe42` |
| aarch64 | 12,559 | 29,608 | 0 | 0 | `0f6dcf0a6b91f105` |
| riscv | 6,086 | 20,445 | 0 | 0 | `fe6427bdf480143c` |
| arm | 1,614 | 15,695 | 0 | 0 | `021a84797085030f` |
| mips | 1,647 | 11,396 | 9 | 0 | `fd4a51d952b822d6` |
| ppc | 94 | 2,177 | 0 | 1 | `c15f766bd2a16761` |
| m68k | 35 | 2,182 | 0 | 0 | `8d843f4f5775e63e` |
| wasm | 894 | 9,290 | 0 | 0 | `1293d7a53ab9a743` |
| spirv | 5,689 | 15,592 | 0 | 4 | `d874a0ff0274d944` |

U 的 aarch64 / spirv 两行是 2026-11-12 刷新题面后由 U A/B 重跑得到的数（同一份 inc）。

每个方向 `disagree=0`、`errors=0`、`missing_ref=0`、`missing_ours=0`。
`inc` sha 只说明“这次跑的是哪份产物”；语料一改就会变，回放的判据是答案，
不是 sha。

## 2026-11-12 复跑：三个 L4 target 在新 U 题面上再回放一次

U 题面刷新后（`oracle ac98717`），用当前 `inc` 对新的冻结答案重放：

```text
x86      G 3,014 / U 10,027      0 disagree
aarch64  G 12,559 / U 29,608     0 disagree
riscv    G 6,086 / U 20,445      0 disagree
```

同一天起，`EVIDENCE.json` 的这 6 条 `G/U` 记录带 `snapshot`（corpus +
features + inc）；`verify-evidence.sh` 会从 corpus 重新生成 `inc` 并比对，
所以“答案还绿、语料已经变了”这种漂移不再可能静默通过。

## 这次回放修掉的一个真问题

第一次跑 x86 时 `build-runner.sh` 里的 `check-pin.sh` 拒绝了树：ours 构建发生
在**已经替换构造函数**的树上，内容校验看到的是 `#include "…inc"`。结果是
G 路径在 `official_base` 按内容冻结之后就不能再跑（L1 走的是 `.so` 快照，所以
没暴露）。修法（本提交）：

- `ab.py` 在打补丁**之前**对还原树跑一次 `check-pin.sh`；
- `build_swap_runner(..., skip_pin=True)` 只用于 ours，构建时设
  `GIT_DSL_SKIP_PIN_CHECK=1`；
- `replay-frozen.py` 走同一条路。

官方侧的 pin 校验没有被放宽：它只是从“打补丁后的树”移到“还原后的树”。
