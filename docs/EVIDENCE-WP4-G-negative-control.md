# WP4（G 侧）负控：注入错规则必须被抓到

日期：2026-11-10。这是 G 题面的负控，不等于 U 题面的负控（U 随 WP3 才存在）。

## 注入

只改一处：`X_G_ADD` 的第一条 legal 从

```text
legal in(slot(0), [X_s8, X_s16, X_s32])
```

改成

```text
legal in(slot(0), [X_s8])
```

其余语料不变。`gisel gen --emit=inc` 仍成功（63 rulesets / 328 rules），
说明这是一条**语法合法、语义错误**的规则，正是要抓的对象。

## 结果

| 项 | 值 |
|---|---|
| 注入 inc | `/tmp/ab-neg/x86-mutated.inc` |
| inc sha256 | `70ff0489bc1e65ac931ee8524956379a4bf0bc3bbb67e287037ce1edd02c776a` |
| 查询 | 3,027（3,021 key） |
| agree | 3,017 |
| disagree | **4** |
| 分类 | 4 × `action` |
| 首条 | `G_ADD` / `s16`：官方 `Legal`，我们 `ClampScalar`（`type_idx=0`, `new_type=s32`） |
| diff rc | **1** |
| diff.json sha256 | `72e1e4a31c21372d7fcf20df9e3ec2b9df5fa75d77844b3baadd7829b5b4b00d` |

命令：

```sh
cd /home/ubuntu/llvm/ab
./build-inc.sh /tmp/ab-neg/mutated.gisel /tmp/ab-neg/x86-mutated.inc
./run-x86-end-to-end.sh TREE BUILD /tmp/ab-neg/x86-mutated.inc /tmp/ab-neg/out
# rc=1
```

结论：harness 能区分“语法能生成”和“规则正确”。G 侧的负控成立；负控不能
只证明 diff 会报错，还要证明它报在**预期的那条**规则上——这里是 `G_ADD s16`，
与注入位置一致。
