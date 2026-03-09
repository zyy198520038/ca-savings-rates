#!/usr/bin/env python3
"""
抓取 RateHub 与 HighInterestSavings.ca 的储蓄利率，汇总后取 Top 3，生成静态页。
依赖环境变量 FIRECRAWL_API_KEY。
"""
import os
import re
import json
from datetime import datetime
from config import SOURCES, BANK_WHITELIST, BANK_LINKS

try:
    from firecrawl import Firecrawl
except ImportError:
    Firecrawl = None


def scrape_url(url: str) -> str:
    """用 Firecrawl 抓取 URL，返回 markdown。"""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise SystemExit("请设置环境变量 FIRECRAWL_API_KEY")
    if Firecrawl is None:
        raise SystemExit("请安装: pip install firecrawl-py")

    app = Firecrawl(api_key=api_key)
    result = app.scrape(url, formats=["markdown"])
    if hasattr(result, "markdown"):
        return (result.markdown or "").strip()
    if isinstance(result, dict):
        data = result.get("data") or result
        return (data.get("markdown") or "").strip()
    return ""


def _extract_markdown_link(text: str) -> str | None:
    """从 Markdown [text](url) 中提取 url，若有多个取第一个。"""
    m = re.search(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", text)
    return m.group(2) if m else None


def _resolve_bank_link(row: dict) -> str:
    """优先使用银行官方营销页：若 BANK_LINKS 能匹配到则用，否则用解析到的 link。"""
    name = (row.get("bank_product") or "").lower()
    for key in sorted(BANK_LINKS.keys(), key=lambda x: -len(x)):
        if key in name:
            return BANK_LINKS[key]
    return row.get("link") or row.get("source_url", "")


def parse_ratehub(md: str, source_url: str) -> list[dict]:
    """解析 RateHub 页面的利率表格。表格列: Provider | Interest rates | Fees | Insurance"""
    rows = []
    in_table = False
    header_skip = True
    for line in md.splitlines():
        line = line.strip()
        if "| Provider | Interest rates |" in line or "| Provider | Interest rates |" in line.replace(" ", ""):
            in_table = True
            header_skip = True
            continue
        if in_table and line.startswith("|") and "---" in line:
            header_skip = False
            continue
        if in_table and line.startswith("|") and header_skip is False:
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 2:
                provider_cell = parts[0]
                provider = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", provider_cell).strip()
                rate_str = parts[1]
                rate_val, condition = parse_rate_string(rate_str)
                if rate_val is not None:
                    link = _extract_markdown_link(provider_cell)
                    if not link or "ratehub" in link.lower():
                        link = source_url
                    row = {
                        "bank_product": provider,
                        "rate": rate_val,
                        "rate_display": rate_str,
                        "condition": condition,
                        "source": "RateHub",
                        "source_url": source_url,
                        "link": link,
                    }
                    row["link"] = _resolve_bank_link(row)
                    rows.append(row)
        if in_table and (line.startswith("## ") or "Historical" in line or "Our guide" in line):
            in_table = False
        if in_table and not line.startswith("|") and line and "---" not in line:
            in_table = False
    return rows


def parse_highinterestsavings(md: str, source_url: str) -> list[dict]:
    """解析 HighInterestSavings.ca 的表格。列: Brand | Account | Rate | ...；Account 列含 [text](url) 时取银行链接。"""
    rows = []
    in_table = False
    for line in md.splitlines():
        line = line.strip()
        if "| [Brand]" in line or "| Brand |" in line or (line.startswith("|") and "Account" in line and "Rate" in line):
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" in line:
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) >= 3:
                brand = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', parts[0]).strip()
                account_cell = parts[1]
                account = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', account_cell).strip()
                rate_raw = parts[2]
                m = re.search(r'\[?(\d+\.?\d*)\s*%\]?', rate_raw)
                if m:
                    rate_val = float(m.group(1))
                    link = _extract_markdown_link(account_cell) or source_url
                    row = {
                        "bank_product": f"{brand} {account}",
                        "rate": rate_val,
                        "rate_display": f"{rate_val}%",
                        "condition": "常规利率",
                        "source": "HighInterestSavings.ca",
                        "source_url": source_url,
                        "link": link,
                    }
                    row["link"] = _resolve_bank_link(row)
                    rows.append(row)
        if in_table and not line.startswith("|") and line and "CU =" not in line:
            in_table = False
    return rows


def parse_rate_string(s: str) -> tuple[float | None, str]:
    """从 '4.60% for the first 3 months' 提取数字和条件说明。"""
    m = re.search(r"(\d+\.?\d*)\s*%", s)
    if not m:
        return None, ""
    rate = float(m.group(1))
    condition = []
    if re.search(r"first\s+(\d+)\s+months?", s, re.I):
        mo = re.search(r"first\s+(\d+)\s+months?", s, re.I)
        if mo:
            condition.append(f"首{mo.group(1)}个月促销")
    if re.search(r"new\s+funds?", s, re.I) or "新资金" in s:
        condition.append("需新资金")
    if re.search(r"new\s+(?:account|customer)", s, re.I) or "新开户" in s:
        condition.append("需新开户")
    if "*" in s or "terms apply" in s.lower():
        condition.append("条款适用")
    return rate, "；".join(condition) if condition else "见官网"


def dedupe_and_sort(rows: list[dict]) -> list[dict]:
    """按 (bank_product, rate) 去重保留最高率，再按利率排序。"""
    by_key = {}
    for r in rows:
        key = (r["bank_product"].lower(), r.get("source", ""))
        if key not in by_key or by_key[key]["rate"] < r["rate"]:
            by_key[key] = r
    out = list(by_key.values())
    out.sort(key=lambda x: -x["rate"])
    return out


def filter_whitelist(rows: list[dict]) -> list[dict]:
    if not BANK_WHITELIST:
        return rows
    allowed = [b.lower() for b in BANK_WHITELIST]
    return [r for r in rows if any(a in r["bank_product"].lower() for a in allowed)]


def build_html(top3: list[dict], updated_at: str) -> str:
    """生成单页 HTML，适合 GitHub Pages。"""
    rows_html = ""
    for i, r in enumerate(top3, 1):
        cond = r.get("condition") or "—"
        rows_html += f"""
        <tr>
          <td>{i}</td>
          <td><strong>{r["bank_product"]}</strong></td>
          <td>{r["rate"]}%</td>
          <td>{cond}</td>
          <td><a href="{r["link"]}" target="_blank" rel="noopener">去官网</a></td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CA">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>加拿大高息储蓄 Top 3</title>
  <style>
    body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
    h1 {{ font-size: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border: 1px solid #ddd; padding: 0.6rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .meta {{ color: #666; font-size: 0.9rem; margin-bottom: 1rem; }}
  </style>
</head>
<body>
  <h1>🇨🇦 加拿大高息储蓄 Top 3</h1>
  <p class="meta">数据来自 RateHub、HighInterestSavings.ca，仅供参考。更新时间：{updated_at}</p>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>银行/产品</th>
        <th>利率</th>
        <th>条件</th>
        <th>官网</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""


def main():
    all_rows = []
    for src in SOURCES:
        url = src["url"]
        name = src["name"]
        print(f"正在抓取 {name}: {url}")
        try:
            md = scrape_url(url)
        except Exception as e:
            print(f"  失败: {e}")
            continue
        if src["parser"] == "ratehub":
            rows = parse_ratehub(md, url)
        elif src["parser"] == "highinterestsavings":
            rows = parse_highinterestsavings(md, url)
        else:
            rows = []
        print(f"  解析到 {len(rows)} 条")
        all_rows.extend(rows)

    merged = dedupe_and_sort(all_rows)
    merged = filter_whitelist(merged)
    top3 = merged[:3]

    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(top3, updated_at)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已写入 {out_path}，Top 3 条数: {len(top3)}")

    # 同时写一份 JSON 供调试或后续扩展
    data_path = os.path.join(os.path.dirname(__file__), "top3.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": updated_at, "top3": top3}, f, ensure_ascii=False, indent=2)
    print(f"已写入 {data_path}")


if __name__ == "__main__":
    main()
