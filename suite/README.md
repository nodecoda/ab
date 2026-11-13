# 冻结套件（offline suite）

一个问题文件 + 一份**官方答案**，加上生成它们时的 pin。`suite.py check` 在
没有 LLVM 的机器上重新出答案并逐条比对。

```
suite/
└── m68k/
    ├── suite.json            schema、pin、每个输入的 sha256
    ├── queries.jsonl         无答案查询（`gisel cases` 的产物）
    └── official.answers.jsonl  官方 legalizer 当时的答案
```

## 为什么不是 gisel 的命令

比较属于工作台（`docs/SCOPE.md` §7：A/B *with* gisel, not *by* gisel）。
`gisel` 只负责出题和求值；`suite.py` 负责“把两边答案放一起看”。所以这条
检查放在 `ab`，且是纯 Python：不需要树、不需要构建、不需要网络。

## 检查什么

```sh
python3 suite.py check --target m68k     # 或 --all
python3 suite.py check --all --json
```

1. 三个输入（queries / answers / corpus / features）的 sha256 必须等于
   `suite.json` 记录的；不等就是快照漂移，退出码 2——这不是规则差异，
   而是“你在拿旧答案回答新题目”。
2. `gisel gen --emit=core` + `gisel eval` 用当前语料重新回答同一批查询。
3. 用 `diff.py` 的 full-set 契约比较：多一条、少一条、动作不同都算失败。

退出码：0 全部一致，1 有差异，2 快照或环境坏了。

## 证到什么

- 证到：当前语料在这批查询上复现了官方当时的动作序列——规则、谓词、
  求值语义一起被钉住了。
- 没证：emitter、MIR、以及这批查询之外的任何点。

## 加一个 target

1. 在能跑对拍的机器上出题并对拍：

   ```sh
   gisel cases --corpus <target> --out queries.jsonl
   python3 ab.py run --target <target> --tree "$AB_TREE" --build "$AB_BUILD" \
     --queries queries.jsonl --out /tmp/<target>-ab --state /tmp/<target>-state
   ```

2. 把 `queries.jsonl` 和 `/tmp/<target>-ab/official.answers.jsonl` 放进
   `suite/<target>/`，写 `suite.json`（照着 `m68k` 抄，sha 用 `sha256sum`
   算，`pin`/`official_base` 来自 `baseline/provenance.json` 和 `PIN.json`）。
3. `python3 suite.py check --target <target>` 必须 0 差异；有差异说明语料
   和这份官方答案不属于同一个 pin，先查清再入库。

大 target 的答案是分钟级到小时级的一次性成本；`x86`（3,014 条）、
`aarch64`（9,632 条）、`riscv`（19,512 条）还没入库。
