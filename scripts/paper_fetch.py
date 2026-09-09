#!/usr/bin/env python3
"""Locate and download a paper's PDF, and pull code/data links out of it.

Subcommands
-----------
resolve   "TITLE or DOI"   -> DOI, journal, year, OA status, PDF candidates
download  "TITLE or DOI"   -> save best open-access PDF into --out, then verify it
links     PAPER.pdf        -> github / zenodo / osf / figshare / data-availability URLs

Examples
--------
python3 paper_fetch.py resolve "Neural evidence for attentional capture by salient distractors"
python3 paper_fetch.py download 10.1073/pnas.2518523122 --out "/path/to/SEEG-Sun-Glab"
python3 paper_fetch.py links "/path/to/repo/2025 PNAS-automaticity-....pdf"

Notes
-----
- Open access only. Paywalled papers are reported, never scraped from shadow libraries.
- Set a real contact email once:  export UNPAYWALL_EMAIL="you@lab.edu"
  (Unpaywall requires it; without it the script falls back to Europe PMC + Crossref only.)
- Verification uses PyMuPDF (import fitz). Install with: python3 -m pip install pymupdf
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
EMAIL = os.environ.get("UNPAYWALL_EMAIL", "").strip()

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
URL_RE = re.compile(r"https?://[^\s)\]}\"'<>]+")

JOURNAL_ALIASES = {
    "proceedings of the national academy of sciences": "PNAS",
    "proc. natl. acad. sci. u.s.a.": "PNAS",
    "nature neuroscience": "NatNeurosci",
    "nat. neurosci.": "NatNeurosci",
    "nature human behaviour": "NatHumBehav",
    "nat. hum. behav.": "NatHumBehav",
    "nature communications": "NatCommun",
    "nature": "Nature",
    "neuron": "Neuron",
    "brain": "Brain",
    "elife": "eLife",
    "the journal of neuroscience": "JNeurosci",
    "j. neurosci.": "JNeurosci",
    "cerebral cortex": "CerebCortex",
    "cereb. cortex": "CerebCortex",
    "current biology": "CurrBiol",
    "curr. biol.": "CurrBiol",
    "journal of cognitive neuroscience": "JOCN",
    "j. cogn. neurosci.": "JOCN",
    "science advances": "SciAdv",
    "sci. adv.": "SciAdv",
    "science": "Science",
    "neuroimage": "NeuroImage",
    "nature methods": "NatMethods",
    "nat. methods": "NatMethods",
    "epilepsia": "Epilepsia",
    "clinical neurophysiology": "ClinNeurophysiol",
    "annals of neurology": "AnnNeurol",
    "jama neurology": "JAMANeurol",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _request(url: str, timeout: int = 30):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url: str, timeout: int = 30, retries: int = 2):
    last: dict = {}
    for attempt in range(retries + 1):
        try:
            with _request(url, timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last = {"_http_error": exc.code, "_url": url}
            if exc.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return last
        except Exception as exc:  # noqa: BLE001 - report, don't crash the whole run
            last = {"_error": str(exc), "_url": url}
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            return last
    return last


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def title_ratio(a: str, b: str) -> float:
    """两个标题之间的相似度（用于 Crossref 候选排序）。"""
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def title_in_text(expected: str, haystack: str) -> float:
    """标题在长文本里的覆盖率：1.0 表示完整出现。

    不能直接用 SequenceMatcher.ratio(expected, page_text)：它按两个字符串总长归一化，
    标题即使完整出现也会因为正文太长而得到接近 0 的分数。
    """
    exp = normalize(expected)
    hay = normalize(haystack)
    if not exp:
        return 0.0
    if exp in hay:
        return 1.0
    match = difflib.SequenceMatcher(None, exp, hay).find_longest_match(0, len(exp), 0, len(hay))
    return match.size / len(exp)


def slugify(title: str, max_len: int = 90) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(title))
    return slug.strip("-")[:max_len].rstrip("-")


def journal_short(*names: str) -> str:
    for name in names:
        if not name:
            continue
        key = name.strip().lower()
        if key in JOURNAL_ALIASES:
            return JOURNAL_ALIASES[key]
        return re.sub(r"[^A-Za-z0-9]+", "", name)[:24] or "Journal"
    return "Journal"


def year_of(message: dict) -> str:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (message.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return str(parts[0][0])
    return "XXXX"


def first_author(message: dict) -> str:
    authors = message.get("author") or []
    if not authors:
        return ""
    a = authors[0]
    return " ".join(filter(None, [a.get("family", ""), a.get("given", "")])).strip()


def extract_doi(query: str) -> str | None:
    m = DOI_RE.search(query)
    return m.group(0).rstrip(".,;)") if m else None


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #
def crossref_search(query: str, rows: int = 5) -> list[dict]:
    url = (
        "https://api.crossref.org/works?rows=%d&select=DOI,title,container-title,"
        "short-container-title,issued,author,type&query.bibliographic=%s"
        % (rows, urllib.parse.quote(query))
    )
    data = get_json(url)
    if "message" not in data:
        return []
    return data["message"].get("items", [])


def crossref_meta(doi: str) -> dict:
    data = get_json("https://api.crossref.org/works/" + urllib.parse.quote(doi))
    return data.get("message", {}) if isinstance(data, dict) else {}


def unpaywall(doi: str) -> dict:
    if not EMAIL:
        return {}
    data = get_json(
        "https://api.unpaywall.org/v2/%s?email=%s"
        % (urllib.parse.quote(doi), urllib.parse.quote(EMAIL))
    )
    return data if isinstance(data, dict) and "is_oa" in data else {}


def europepmc(doi: str) -> dict:
    url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search?"
        "query=DOI:%22" + urllib.parse.quote(doi) + "%22&resultType=core&format=json"
    )
    data = get_json(url)
    results = ((data.get("resultList") or {}).get("result") or []) if isinstance(data, dict) else []
    return results[0] if results else {}


def openalex(doi: str) -> dict:
    data = get_json("https://api.openalex.org/works/doi:" + urllib.parse.quote(doi))
    return data if isinstance(data, dict) and "id" in data else {}


def semantic_scholar(doi: str) -> dict:
    data = get_json(
        "https://api.semanticscholar.org/graph/v1/paper/DOI:"
        + urllib.parse.quote(doi)
        + "?fields=title,openAccessPdf"
    )
    return data if isinstance(data, dict) and "title" in data else {}


def landing_page_pdfs(url: str, timeout: int = 25) -> list[str]:
    """抓取落地页，找 citation_pdf_url meta 或 .pdf 链接。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return []
    found: list[str] = []
    for match in re.finditer(
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', html, re.I
    ):
        found.append(match.group(1))
    for match in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, re.I):
        found.append(match.group(1))
    out = []
    for item in found:
        item = item.replace("&amp;", "&").strip()
        if item.startswith("//"):
            item = "https:" + item
        elif item.startswith("/"):
            item = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url)) + item
        elif not item.startswith("http"):
            item = urllib.parse.urljoin(url, item)
        if item not in out:
            out.append(item)
    return out


def pdf_candidates(doi: str, up: dict, epmc: dict, oa: dict, s2: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    supp_re = re.compile(r"(moesm|supplement|supporting[-_]?information|/esm/|_si_)", re.I)

    def add(label: str, url: str | None):
        if not url or supp_re.search(url):
            return
        if url not in [u for _, u in out]:
            out.append((label, url))

    extra_landings: list[str] = []
    best = (up.get("best_oa_location") or {}) if up else {}
    add("unpaywall:best", best.get("url_for_pdf"))
    for loc in up.get("oa_locations") or []:
        add("unpaywall:" + loc.get("host_type", "?"), loc.get("url_for_pdf"))

    if oa:
        add("openalex:best", (oa.get("best_oa_location") or {}).get("pdf_url"))
        add("openalex:primary", (oa.get("primary_location") or {}).get("pdf_url"))
        for loc in oa.get("locations") or []:
            add("openalex:" + str(loc.get("host_type") or "?"), loc.get("pdf_url"))

    if s2:
        s2_url = (s2.get("openAccessPdf") or {}).get("url")
        if s2_url and re.search(r"\.pdf(\?|$)", s2_url, re.I):
            add("semanticscholar", s2_url)
        elif s2_url:
            extra_landings.append(s2_url)

    pmcid = epmc.get("pmcid") if epmc else None
    if pmcid and str(epmc.get("hasPDF", "")).upper() == "Y":
        add("europepmc", "https://europepmc.org/articles/%s?pdf=render" % pmcid)
        add("pmc", "https://www.ncbi.nlm.nih.gov/pmc/articles/%s/pdf/" % pmcid)

    if doi.startswith("10.48550/arxiv."):
        add("arxiv", "https://arxiv.org/pdf/" + doi.split("arxiv.", 1)[1])

    # 仓库/机构落地页里再挖一层（green OA 常见）
    landings: list[str] = []
    for loc in ((best,) if best else ()) + tuple(up.get("oa_locations") or []):
        url = loc.get("url_for_landing_page") or loc.get("url")
        if url and url not in landings:
            landings.append(url)
    for loc in (oa.get("locations") or []) if oa else []:
        url = loc.get("landing_page_url")
        if url and url not in landings:
            landings.append(url)
    for url in extra_landings:
        if url not in landings:
            landings.append(url)
    for landing in landings[:4]:
        host = urllib.parse.urlparse(landing).netloc[:24] or "landing"
        for pdf in landing_page_pdfs(landing)[:4]:
            add("landing:" + host, pdf)

    return out


def cmd_resolve(args: argparse.Namespace) -> int:
    query = args.query
    doi = extract_doi(query)

    if not doi:
        items = crossref_search(query)
        if not items:
            print("Crossref 没找到任何结果。请换关键词，或直接给 DOI / PDF。")
            return 2
        scored = []
        for item in items:
            title = (item.get("title") or [""])[0]
            scored.append((title_ratio(query, title), item))
        # 同分时优先正式期刊论文，避免选中 SSRN/bioRxiv 预印本
        scored.sort(
            key=lambda pair: (round(pair[0], 2), pair[1].get("type") == "journal-article"),
            reverse=True,
        )
        print("Crossref 候选：")
        for ratio, item in scored:
            print(
                "  %.2f  %s  [%s %s | %s]  %s"
                % (
                    ratio,
                    (item.get("title") or [""])[0],
                    (item.get("container-title") or ["?"])[0],
                    year_of(item),
                    item.get("type", "?"),
                    item.get("DOI"),
                )
            )
        best_ratio, best = scored[0]
        ties = [
            item for ratio, item in scored
            if round(ratio, 2) == round(best_ratio, 2) and item.get("DOI") != best.get("DOI")
        ]
        if ties:
            print(
                "\n⚠️ 有 %d 条同分记录（预印本 / 会议摘要 / 正式论文常见重复）。"
                % len(ties)
            )
            print("   按用户给的期刊、年份线索确认；确认后用 DOI 重跑最稳。")
        if best_ratio < 0.6:
            print("\n最高匹配度过低（%.2f），先确认候选再继续；可直接用 DOI 重新调用。" % best_ratio)
            return 2
        doi = best.get("DOI")
        print("\n选中：%s  (%.2f)" % (doi, best_ratio))

    meta = crossref_meta(doi)
    up = unpaywall(doi)
    epmc = europepmc(doi)
    oa = openalex(doi)
    s2 = semantic_scholar(doi)
    title = (meta.get("title") or [""])[0]

    print("\n=== 元信息 ===")
    print("标题   :", title or "(Crossref 无记录)")
    print("作者   :", first_author(meta) or "?")
    print("期刊   :", (meta.get("container-title") or ["?"])[0], "|", year_of(meta))
    print("DOI    :", doi)
    print("类型   :", meta.get("type", "?"))
    if up:
        print("OA     :", up.get("is_oa"), "|", up.get("oa_status"), "|", up.get("journal_name", ""))
    elif not EMAIL:
        print("OA     : (未查 Unpaywall，设置 UNPAYWALL_EMAIL 可获得更全结果)")
    if epmc:
        print(
            "EPMC   : pmcid=%s openAccess=%s hasPDF=%s"
            % (epmc.get("pmcid"), epmc.get("isOpenAccess"), epmc.get("hasPDF"))
        )
    print("建议文件名:", "%s %s-%s.pdf" % (year_of(meta), journal_short((meta.get("short-container-title") or [""])[0], (meta.get("container-title") or [""])[0]), slugify(title)))

    cands = pdf_candidates(doi, up, epmc, oa, s2)
    print("\n=== PDF 候选 ===")
    if not cands:
        print("没有开放获取 PDF。走人工：机构 VPN / 图书馆 / 直接问作者，或让用户提供 PDF。")
    for label, url in cands:
        print("  [%s] %s" % (label, url))
    print("\n下一步: python3 paper_fetch.py download \"%s\" --out <项目根目录>" % doi)
    return 0


# --------------------------------------------------------------------------- #
# download
# --------------------------------------------------------------------------- #
def verify_pdf(path: str, expected_title: str | None, doi: str | None = None) -> tuple[bool, str]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        size = os.path.getsize(path)
        return size > 20_000, "PyMuPDF 未安装，仅按大小判断 (%d bytes)" % size
    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        return False, "打不开: %s" % exc
    if doc.page_count == 0:
        return False, "0 页"
    head = "\n".join(doc[i].get_text("text") for i in range(min(2, doc.page_count)))[:30000]
    msg = "%d 页 | 首页: %s" % (doc.page_count, " ".join(head.split())[:160])

    if doi and normalize(doi) in normalize(head):
        return True, msg + " | DOI 命中"
    if expected_title:
        ratio = title_in_text(expected_title, head)
        msg += " | 标题覆盖率 %.2f" % ratio
        if ratio < 0.6:
            return False, msg + " (可能不是目标论文)"
    return True, msg


def cmd_download(args: argparse.Namespace) -> int:
    query = args.query
    doi = extract_doi(query)
    meta: dict = {}
    if not doi:
        items = crossref_search(query)
        if not items:
            print("Crossref 没找到结果，无法确定 DOI。")
            return 2
        items.sort(
            key=lambda it: (
                round(title_ratio(query, (it.get("title") or [""])[0]), 2),
                it.get("type") == "journal-article",
            ),
            reverse=True,
        )
        doi = items[0].get("DOI")
        meta = items[0]
    if not meta:
        meta = crossref_meta(doi)

    title = (meta.get("title") or [""])[0]
    year = year_of(meta)
    journal = journal_short(
        (meta.get("short-container-title") or [""])[0],
        (meta.get("container-title") or [""])[0],
    )
    fname = args.name or ("%s %s-%s.pdf" % (year, journal, slugify(title)))
    if not fname.lower().endswith(".pdf"):
        fname += ".pdf"
    out_dir = args.out or "."
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, fname)

    up = unpaywall(doi)
    epmc = europepmc(doi)
    oa = openalex(doi)
    s2 = semantic_scholar(doi)
    cands = pdf_candidates(doi, up, epmc, oa, s2)
    if not cands:
        print("没有开放获取 PDF。")
        print("人工路径：机构 VPN / 图书馆 / 邮件问作者 / 让用户把 PDF 拖进项目目录。")
        print("不要使用 Sci-Hub 等影子图书馆。")
        return 2

    print("目标: %s\nDOI : %s\n" % (dest, doi))
    for label, url in cands:
        print("尝试 [%s] %s" % (label, url))
        tmp = dest + ".part"
        try:
            origin = "{0.scheme}://{0.netloc}/".format(urllib.parse.urlparse(url))
            # 注意：Accept 里带 q= 权重会被 Europe PMC 的 WAF 判为机器人并返回 429，
            # 所以这里用最朴素的 */*。
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "*/*", "Referer": origin},
            )
            with urllib.request.urlopen(req, timeout=90) as resp, open(tmp, "wb") as fh:
                first = resp.read(5)
                if not first.startswith(b"%PDF"):
                    print("  -> 不是 PDF（返回了网页/登录页），换下一个")
                    os.remove(tmp)
                    continue
                fh.write(first)
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
        except urllib.error.HTTPError as exc:
            wait = exc.headers.get("Retry-After") if exc.headers else None
            print("  -> HTTP %s（%s）%s" % (exc.code, exc.reason, "，%s 秒后可重试" % wait if wait else ""))
            if os.path.exists(tmp):
                os.remove(tmp)
            continue
        except Exception as exc:  # noqa: BLE001
            print("  -> 失败: %s" % exc)
            if os.path.exists(tmp):
                os.remove(tmp)
            continue

        ok, msg = verify_pdf(tmp, title, doi)
        if not ok:
            print("  -> 验证不通过: %s" % msg)
            os.remove(tmp)
            continue
        os.replace(tmp, dest)
        print("  -> 已保存: %s" % dest)
        print("  -> 验证: %s" % msg)
        print("\n下一步: python3 pdf_text.py \"%s\"" % dest)
        print("        python3 paper_fetch.py links \"%s\"" % dest)
        return 0

    print("\n所有候选都失败了。让用户提供 PDF，或走机构权限。")
    return 2


# --------------------------------------------------------------------------- #
# links
# --------------------------------------------------------------------------- #
def pdf_full_text(path: str) -> str:
    import fitz

    doc = fitz.open(path)
    return "\n".join(page.get_text("text") for page in doc)


def url_clean_text(text: str) -> str:
    """把被排版拆断的 URL 拼回去。

    PDF 里 URL 常见两种破坏：(1) 软连字符/零宽字符；(2) 换行断在 URL 标点后。
    只在“URL 标点（-/_.=+&?%#）后换行”时拼接，避免把正文句子粘到 URL 尾巴上
    （比如把 "…deeplearning.\\nFor more" 拼成 "…deeplearning.For"）。
    """
    text = re.sub(r"[\u00ad\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"(?<=[-_/=+&?%#])\s*\n\s*(?=[A-Za-z0-9])", "", text)
    # 句号既可能是 URL 断点，也可能是句子结尾：只在下一行以小写/数字开头时拼
    text = re.sub(r"(?<=\.)\s*\n\s*(?=[a-z0-9])", "", text)
    return text


def cmd_links(args: argparse.Namespace) -> int:
    raw = pdf_full_text(args.pdf)
    text = url_clean_text(raw)
    urls: list[str] = []
    for found in URL_RE.findall(text):
        url = found.rstrip(".,;:)]}\"'")
        if url not in urls:
            urls.append(url)

    buckets = {
        "代码仓库 (github/gitlab)": r"^https?://(www\.)?(github|gitlab)\.com/",
        "代码/数据归档 (zenodo/osf/figshare/dryad/g-node)": r"^https?://(www\.)?(zenodo|osf|figshare|datadryad|dryad|gin|g-node)\.",
        "预印本 (biorxiv/medrxiv/arxiv)": r"^https?://(www\.)?(biorxiv|medrxiv|arxiv)\.org/",
    }
    print("=== 可用性声明（含 availability 的段落） ===")
    lines = raw.splitlines()
    shown: set[int] = set()
    for i, line in enumerate(lines):
        if re.search(r"availability", line, re.I):
            for j in range(i, min(len(lines), i + 8)):
                if j in shown:
                    continue
                shown.add(j)
                print("  %s" % " ".join(lines[j].split()))
            print("  ---")
    if not shown:
        print("  (没找到 availability 段落，去正文里搜 'data' / 'code' / 'github')")

    print("\n=== 链接 ===")
    for label, pattern in buckets.items():
        hits = [u for u in urls if re.match(pattern, u)]
        print("[%s] %d 个" % (label, len(hits)))
        for u in hits:
            print("   ", u)
    others = [u for u in urls if not any(re.match(p, u) for p in buckets.values())]
    print("[其他链接] %d 个（前 15）" % len(others))
    for u in others[:15]:
        print("   ", u)
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_res = sub.add_parser("resolve", help="标题或 DOI -> DOI/元信息/PDF 候选")
    p_res.add_argument("query")
    p_res.set_defaults(func=cmd_resolve)

    p_dl = sub.add_parser("download", help="下载开放获取 PDF 并验证")
    p_dl.add_argument("query")
    p_dl.add_argument("--out", default=".", help="保存目录（默认当前目录）")
    p_dl.add_argument("--name", default=None, help="覆盖文件名")
    p_dl.set_defaults(func=cmd_download)

    p_lk = sub.add_parser("links", help="从 PDF 里抽代码/数据链接")
    p_lk.add_argument("pdf")
    p_lk.set_defaults(func=cmd_links)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
