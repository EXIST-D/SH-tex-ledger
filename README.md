# tex-ledger · LaTeX 写作与编译（编得过 · 找得准 · 改得稳 · 复得现）

面向「写作13｜LaTeX 写作与编译」：**文字与取舍由模型负责，编译、读日志、核对和记账由脚本负责**。脚本在项目的**副本**上按可复现的方式编译（一次跑出全部错误、跑 BibTeX / Biber、重复到交叉引用不再变化），把日志读成带文件和行号的根因（一个没闭合的括号只报一次，它引出的十几条错误折叠在下面，而不是“看第一条错误”），再用不需要 TeX 的静态检查交叉核对；确定性修复一次只应用一条并重新编译，**变差就撤回**；最后交付源码、PDF、构建报告（引擎、宏包版本、遍数、命令、两次干净构建的 PDF 哈希）、改动 diff、复现脚本和 `result.json`。

> 文中数字来自开发自测（真实 TeX Live 2026 + 自己植入缺陷的虚构项目），**不是平台成绩**；没有跑过 DeepSeek 官方 Harness，也没有做过「不加载 Skill 的基础 Agent」对照，因此不宣称相对基线的提升。

## 对应题面的四个问题
| 问题 | 做法 | 自查手段 |
|---|---|---|
| 编得过 | 副本编译 → 根因清单 → 逐条改 → `check` 重新编译，对比“已修复 / 新增 / 剩余”；`fix --safe` 的每条规则都经编译验证，变差即撤回 | `brief.md`、`check` 输出、构建状态 `success / partial / not_compiled` |
| 找得准 | 日志按括号重建文件栈，取 `l.N` 与上下文；“File ended while scanning”链接到静态检查找到的未闭合括号所在行；未定义命令按宏包分组；核心命令的“未定义”视为连锁反应 | 根因列表的 `likely starts at`、`+N consequences` |
| 改得稳 | 不删内容、不压日志、不 `\batchmode`；只改标记不改含义；每个改动进 `changes.md`（统一 diff）并说明规则；源码多文件结构与作者宏保持不变 | `changes.md`、`review_checklist.md` |
| 复得现 | 记录引擎与版本、宏包版本、命令与遍数、`SOURCE_DATE_EPOCH` / `FORCE_SOURCE_DATE`；两次干净构建比较 PDF 字节；生成 `repro/build.sh`、`Makefile`、`latexmkrc` | `build_report.md` 的 reproducible 行 |

另有模板对照与迁移（`template` / `adapt` / `use`，实验性：作者信息不映射，如实说明）。

## 目录
```
SKILL.md                    Agent 入口：何时用、七个步骤、质量规则、异常处理
README.md                   本文件
scripts/tx.py               命令行：run / diag / lint / check / fix / template / adapt / use / build
scripts/texrun.py           引擎定位与可复现编译（遍数、BibTeX / Biber、超时、哈希）
scripts/texlog.py           日志读取：文件栈、错误 / 警告分类、连锁折叠、宏包表
scripts/texsrc.py           静态检查与确定性修复（不需要 TeX）
references/                 全部诊断码与实测、工作流细节
examples/                   虚构论文项目 + 真实运行记录（run.txt）+ 最终交付物
GITHUB_URL.txt              作品的 GitHub 公开链接
dev/ （仅仓库）             33 个回归测试、20 个植入缺陷评测、示例生成脚本
```

## 依赖与安装
Python 3.9+，只用标准库（系统 Python 3.9.6 上跑通）。编译需要 TeX Live / MiKTeX / TinyTeX（pdflatex，可选 xelatex / lualatex / bibtex / biber）；**没有 TeX 时**只做静态检查，`fix` 拒绝应用无法验证的改动，`build` 如实报告 `not_compiled`。无需联网。

## 使用步骤
```bash
python3 scripts/tx.py run --case /input/case.json --out out      # 或 --src DIR|main.tex|project.zip；简报 out/brief.md
python3 scripts/tx.py check out/.work                            # 改完后重新编译：已修复 / 新增 / 剩余
python3 scripts/tx.py fix out/.work --safe                       # 确定性修复，逐条验证，变差撤回
python3 scripts/tx.py build out/.work --out out [--answers answers.json]
```

## 输出
`src/`（干净源码）、`<main>.pdf`、`build_report.md/json`（引擎、宏包版本、遍数、命令、PDF 哈希）、`changes.md`（原稿→交付的 diff + 已验证的修复）、`diagnostics.json`、`repro/`、`review_checklist.md`、`result.json`（按 `output_contract` 填字段，推导不出的置 `null` 并列在 `_meta.unfilled_fields`）。

## 实测（开发自测，不是平台成绩）
| 项 | 结果 |
|---|---|
| 回归测试 | `python3 dev/test_all.py`：33 个通过（日志解析、静态检查、安全修复、编译与可复现、保留 / 撤回、构建产物、契约字段、zip 输入、中文 ctex → xelatex、自定义 `.cls` 的模板迁移、无 TeX 模式、数据缺陷评测）；无 TeX 时编译类测试跳过 |
| 植入缺陷（20 个，一次一个，真实 TeX Live 2026） | 日志读取：说对问题 19 / 19，定位对（注入行 ±1 或经静态交叉链接）17 / 19；静态检查：发现 17 / 17、定位 17 / 17；只看日志第一条错误指到缺陷本行 10 / 19；两条路任一命中 20 / 20。规则是对着这批缺陷调出来的，数字偏乐观 |
| 示例 | `examples/`：虚构项目 10 处问题 → 基线构建 `failed`（10 个错误 → 4 个根因）→ `fix --safe` 保留 5 条、撤回 1 条（结构错误未修时 `label_after_caption` 让编译变差）→ 4 处人工修改 → 再次 `fix --safe` 保留 1 条 → 构建 `success`，两次干净构建 PDF 字节相同 |

## 限制（如实写在这里）
- 日志是**文字**：布局问题（图表挤在一起、字体不对）看不到，只能靠 overfull 列表和 `float_too_large` 提示；`status: success` 只说明编译干净，不说明排版好看。
- 折叠连锁错误是启发式：偶尔会把独立的错误折进去，`diag --all` 可看全部。
- 规则和阈值是在自己的 20 个缺陷与虚构项目上调的，对没见过的宏包 / 模板 / 奇怪的自定义宏效果未知。
- 模板迁移只做正文 / 标题 / 摘要 / 关键词，不映射作者与单位；本机没有 IEEEtran 等期刊模板，只用自定义 `.cls` 测过；本机没有 Biber，`biblatex` 路径只测到“缺少 Biber 如实报错”。
- 没有 Word / PDF 渲染对比，没有联网安装宏包。
- 构建的字节级一致只在同一台机器、同一 TeX 版本上验证。


## 示例文件的后缀
平台只接受部分文件类型作为 Skill 资源，所以示例里这些文件的名字后面加了 `.txt`：`examples/out/repro/Makefile`、`examples/out/repro/build.sh`、`examples/out/repro/latexmkrc`。去掉 `.txt` 就是脚本实际读写的文件名；脚本本身的输出文件名没有变。
