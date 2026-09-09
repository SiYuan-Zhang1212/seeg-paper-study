---
name: seeg-paper-study
description: SEEG / iEEG 文献精读全流程：找 PDF 并下载 → 找 GitHub 仓库并 git clone → 交叉阅读论文与代码 → 产出结构化中文笔记（被试与任务设计 / 数据收集 / 预处理 / 数据分析全流程）。当用户给出一篇 SEEG、iEEG、颅内脑电、单神经元或电极定位相关论文的标题、DOI、PDF、链接，或说"学习/精读/读一下/复现这篇文献""帮我整理这篇的任务设计/数据收集/预处理/分析流程""找一下这篇的代码/数据"时使用。
---

# SEEG 文献精读流水线

拿到一篇 SEEG / iEEG 文献，按固定七步走完，最后产出一份结构化中文笔记。每一步都有明确产出，不要跳步。

工作根目录 = 当前项目目录（默认 `/Users/zhangsiyuan/Documents/5th1st/SEEG-Sun-Glab`）。

## 目录约定

| 内容 | 位置 |
|---|---|
| PDF | 项目根目录，`<Year> <Journal>-<title-slug>.pdf` |
| 代码 | `reference-code/<作者或实验室>/<repo>/`，必须是 git clone |
| 精读笔记 | `notes/<short-title>.md`（不存在就创建） |
| 渲染的论文图 | `/tmp/seeg-paper-figs/` |

三个脚本都在 `~/.agents/skills/seeg-paper-study/scripts/`（下面简写为 `scripts/`）。

## 快速开始（一篇新论文的完整命令流）

```bash
S=~/.agents/skills/seeg-paper-study/scripts
P="/Users/zhangsiyuan/Documents/5th1st/SEEG-Sun-Glab"          # 项目根目录

# 1. PDF
python3 $S/paper_fetch.py resolve "<标题或DOI>"                 # 定 DOI、列 OA 候选
python3 $S/paper_fetch.py download "<标题或DOI>" --out "$P"     # 下载并验证

# 2. 代码
python3 $S/paper_fetch.py links "$P/<下载的.pdf>"               # 抽 github/zenodo/OSF 链接
git clone <repo> "$P/reference-code/<作者或实验室>/<repo>"       # 必须 clone，不要下 zip
python3 $S/repo_scan.py "$P/reference-code/<作者或实验室>/<repo>" --git

# 3. 阅读
python3 $S/pdf_text.py "$P/<下载的.pdf>" --render 1,2 --outdir /tmp/seeg-paper-figs
python3 $S/repo_scan.py "<repo>" --readme
python3 $S/repo_scan.py "<repo>" --ext .m,.py
python3 $S/repo_scan.py "<repo>" --grep "<参数关键词>" -i

# 4-7. 按 assets/note_template.md 写 notes/<short-title>.md
```

## 第 1 步：找 PDF 并下载

**已有本地 PDF**：`python3 scripts/pdf_text.py <pdf> --info` 确认页数、标题、DOI 对得上，直接进入第 3 步。

**只有标题 / DOI / 链接**：

```bash
python3 scripts/paper_fetch.py resolve "10.1073/pnas.2518523122"          # 或 "论文标题"
python3 scripts/paper_fetch.py download "10.1073/pnas.2518523122" --out "<项目根目录>"
```

- `resolve` 走 Crossref → Unpaywall → OpenAlex → Semantic Scholar → Europe PMC，并会把机构仓库落地页里的 PDF 挖出来。标题检索若出现同分（预印本/会议摘要/正式论文重复），按用户给的期刊、年份线索确认，最稳的是拿到 DOI 后重跑。
- `download` 只下开放获取版本，保存后用 PyMuPDF 验证页数、标题覆盖率、DOI 命中，不通过就换下一个候选。**不要用 Sci-Hub 等影子图书馆。**
- 全部失败（常见于 Nature 系付费墙）→ 把 DOI 和落地页链接给用户，请其用机构权限下载或直接把 PDF 放进项目目录。不要伪造成功。

## 第 2 步：找 GitHub 仓库并 clone

按可靠性从高到低：

1. **论文自己的可用性声明**（最可靠）：`python3 scripts/paper_fetch.py links <pdf>`，会抽出 github/zenodo/osf/figshare 链接和 "Data/Code Availability" 原文。
2. **作者/实验室主页**：`gh search repos "user:<github用户名>" --limit 20`；作者名可从论文首页或 Crossref 拿到。
3. **关键词搜索**（1–2 个有区分度的词，堆太多词会搜不到）：
   ```bash
   gh search repos "salient distractors" --limit 20 --json fullName,description
   gh api "search/repositories?q=hippocampus+ripple&per_page=20" --jq '.items[] | "\(.full_name) | \(.description)"'
   ```
4. **找不到就写"未公开"**，不要拿相似论文的代码冒充。

clone 到约定位置并记录版本：

```bash
git clone <url> "reference-code/<作者或实验室>/<repo>"
python3 scripts/repo_scan.py "reference-code/<作者或实验室>/<repo>" --git
```

必须 `git clone`，不要下载 zip 或网页上的单个文件：只有带 `.git` 的克隆才能记录 commit、才能复现当时版本。`--git` 的输出（remote + commit hash）要写进笔记。如果仓库巨大（>1GB 数据），可以 `git clone --filter=blob:none`，但要在笔记里注明是部分克隆。

## 第 3 步：阅读 PDF 与代码

**PDF**（PyMuPDF）：

```bash
python3 scripts/pdf_text.py <pdf>                                     # 全文，带页码
python3 scripts/pdf_text.py <pdf> --pages 1-3,7                       # 指定页
python3 scripts/pdf_text.py <pdf> --grep "cluster|permutation" -i --context 2
python3 scripts/pdf_text.py <pdf> --render 1,2,5 --outdir /tmp/seeg-paper-figs
```

`--render` 出来的 PNG 用 Read 工具看。**任务时间轴、电极位置图、分析流程图必须看图**——这些信息文字层经常丢失或顺序错乱，只读文本会漏掉设计的关键部分。

**代码**：

```bash
python3 scripts/repo_scan.py <repo> --readme                  # 先读说明
python3 scripts/repo_scan.py <repo> --ext .m,.py              # 结构 + 行数 + 编码
python3 scripts/repo_scan.py <repo> --grep "baseline|zscore" -i   # 自动解码 GBK
python3 scripts/repo_scan.py <repo> --show Code/TF/TF_2_prac.m
```

- 作者共享的 MATLAB 脚本常是 **GBK/GB2312**，直接 grep 会静默返回空。`repo_scan.py` 会按 utf-8 → gbk → latin-1 解码并标出编码。
- 阅读顺序：README → 实验/任务脚本 → 预处理 → 各分析脚本。
- 边读边建"**论文图 ↔ 代码文件:行号**"对应表，这是整份笔记最有价值的部分。

## 第 4–7 步：整理笔记

按 `assets/note_template.md` 的骨架写 `notes/<short-title>.md`，四节分别对应：

- **被试与任务设计**：被试量/病因/电极与脑区、条件与 trial 数、trial 时间轴表、行为结果、任务代码位置。
- **数据收集**：采集设备/采样率/参考、触发与事件对齐、电极定位流程（CT/MRI、配准软件）、行为数据、数据文件清单、公开范围。
- **预处理**：逐步流程 + 每步参数 + 代码位置，特殊步骤（如癫痫样活动剔除）、输出几套数据集、与 Methods 的差异。
- **数据分析全流程**：每个分析一个子节，固定写清 目的/对应图 → 输入数据 → 方法步骤 → 关键参数 → 输出 → 代码位置 → 与论文的一致性。

写这四节时逐节对照 `references/seeg_checklist.md` 的追问清单，避免漏项。用户如果说"一节一节来"，就写完一节停下等确认，不要一次全推。

## 硬规则

1. **每个结论都有出处**：论文页码/图号，或 `文件:行号`。没有出处就写"论文未说明"。
2. **三件事分开写**：论文说了什么 / 代码实际做了什么 / 代码没公开什么。三者不一致时全部记录并标注（例：Methods 说置换检验重跑 SVM，代码实际是打乱已保存的预测值）。
3. **时间对齐写成等式**：t=0 对应哪个事件、epoch 窗、基线窗、论文图时间轴如何换算到代码变量（如 `tm = 3200:4:5200` ⇒ 图里 cue=0）。这是最容易错的地方。
4. **参数只从代码或 Methods 抄**，不要把领域惯例当成这篇论文的做法。
5. **找不到就写"未公开"**，不猜、不编、不用别的论文顶替。
6. 代码边界同样重要：明确列出"仓库里没有"的关键步骤（如小波变换、响应触点筛选），这类缺口直接决定我们能不能复现。

## 交付

完成后给出：

1. 笔记文件路径（可点击）。
2. 口头小结：这篇做了什么、代码能复现到什么程度、哪些关键步骤没公开、对我们（SEEG-Sun-Glab）有什么用。
3. 若用户要，再导出飞书文档（lark-doc skill）或做分享 slides（lark-slides skill）——不要主动做。

## 自检

- [ ] PDF 已验证是目标论文（页数/标题/DOI）
- [ ] 代码是 git clone，笔记里有 remote + commit hash
- [ ] 四节齐全，每节都有代码位置或明确写"未公开"
- [ ] trial 时间轴表完整，t=0 定义明确
- [ ] 每个分析都有参数 + 代码位置 + 对应论文图
- [ ] 未公开/需联系作者的部分单独列出
