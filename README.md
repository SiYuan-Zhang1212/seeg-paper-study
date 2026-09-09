# seeg-paper-study

一个面向 **SEEG / iEEG 文献精读** 的 Agent Skill：给定一篇颅内脑电相关论文（标题 / DOI / PDF / 链接），自动走完「验证 PDF → 找公开代码仓库 → 交叉阅读论文与代码 → 产出结构化中文精读笔记」的完整流程。

## 它解决什么问题

读一篇 SEEG / iEEG 论文时，真正费时间的不是摘要，而是把**被试与任务设计、数据采集、预处理、分析全流程**四块还原清楚，并且判断**代码能不能复现、论文与代码哪里对不上**。这个 skill 把这件事变成固定七步，每步都有明确产出。

## 目录结构

```
SKILL.md                      # 技能主文件（七步流程 + 硬规则 + 交付要求）
assets/note_template.md       # 精读笔记骨架（8 个章节）
references/seeg_checklist.md  # 追问清单（交付前逐条自查）
scripts/paper_fetch.py        # 定 DOI、列开放获取候选、下载并验证 PDF、抽取代码/数据链接
scripts/pdf_text.py           # PyMuPDF 读全文/指定页/grep/渲染图
scripts/repo_scan.py          # 仓库结构扫描、README、按扩展名/关键词检索（自动处理 GBK）
```

## 使用方式

把本目录放到你的 Agent skills 目录下（例如 `~/.agents/skills/seeg-paper-study/`），然后让 Agent 处理一篇论文即可：

> 帮我精读这篇 SEEG 论文：`10.1038/s41591-021-01480-w`

Agent 会加载 `seeg-paper-study` skill 并按其流程执行。

### 脚本单独使用

```bash
# 1) 定 DOI / 找开放获取版本 / 下载
python3 scripts/paper_fetch.py resolve "论文标题或 DOI"
python3 scripts/paper_fetch.py download "10.1073/pnas.2518523122" --out ./papers

# 2) 抽取论文里的代码/数据链接与可用性声明
python3 scripts/paper_fetch.py links ./papers/xxx.pdf

# 3) 读 PDF
python3 scripts/pdf_text.py ./papers/xxx.pdf --pages 1-3,7
python3 scripts/pdf_text.py ./papers/xxx.pdf --grep "cluster|permutation" -i --context 2
python3 scripts/pdf_text.py ./papers/xxx.pdf --render 1,2 --outdir /tmp/figs

# 4) 扫描代码仓库
python3 scripts/repo_scan.py ./reference-code/author/repo --git
python3 scripts/repo_scan.py ./reference-code/author/repo --readme
python3 scripts/repo_scan.py ./reference-code/author/repo --grep "baseline|zscore" -i
```

## 三条硬规则

1. **每个结论都有出处**：论文页码/图号，或 `文件:行号`；没有出处就写「论文未说明」。
2. **三件事分开写**：论文说了什么 / 代码实际做了什么 / 代码没公开什么；三者不一致时全部记录并标注。
3. **找不到就写「未公开」**：不猜、不编、不用别的论文的代码顶替。

## 依赖

- Python 3.9+：`PyMuPDF`（pdf_text.py）、`requests`（paper_fetch.py）
- 可选：`gh` CLI（搜索 GitHub 仓库）、`git`

## 说明

本 skill 由实际使用中迭代而来，笔记模板与追问清单针对 SEEG/iEEG 的常见坑（参考方式、坏道判定、癫痫样活动剔除、时间轴对齐）设计。欢迎按自己的流程改造。
