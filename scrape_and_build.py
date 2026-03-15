#!/usr/bin/env python3
"""
抓取 RateHub 与 HighInterestSavings.ca 的储蓄利率，汇总后取 Top 3，生成静态页。
依赖环境变量 FIRECRAWL_API_KEY。
"""
import argparse
import os
import re
import json
from datetime import datetime
from urllib.parse import urlparse
from config import SOURCES, GIC_SOURCES, BANK_WHITELIST, BANK_LINKS, GIC_LINKS, BANK_TIER, FORMSPREE_FORM_ID, COFFEE_URL, SITE_URL

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


def _get_bank_tier(name: str) -> str:
    """根据银行/产品名返回类型（六大行 / 知名银行/直销 / 信贷/中小机构 / 其他）。"""
    if not name:
        return "其他"
    lower = name.lower()
    for key in sorted(BANK_TIER.keys(), key=lambda x: -len(x)):
        if key in lower:
            return BANK_TIER[key]
    return "其他"


# 类型列前端 i18n 用 key；与 BANK_TIER 中文标签对应
TIER_LABEL_TO_KEY = {
    "六大行": "six",
    "知名银行/直销": "known",
    "信贷/中小机构": "credit",
    "其他": "other",
}

# GIC 期限列前端 i18n：解析器输出 1年/2年/…，映射为 key 与默认英文
TERM_LABEL_TO_KEY = {
    "1年": "1y",
    "2年": "2y",
    "3年": "3y",
    "4年": "4y",
    "5年": "5y",
}
TERM_KEY_DEFAULT = {"1y": "1 year", "2y": "2 years", "3y": "3 years", "4y": "4 years", "5y": "5 years"}


def _get_bank_tier_key(name: str) -> str:
    """返回类型 key（six / known / credit / other）供前端 i18n。"""
    return TIER_LABEL_TO_KEY.get(_get_bank_tier(name), "other")


# 条件列：按「；」拆分后每段的翻译，用于前端 applyLang
CONDITION_PART_TRANSLATIONS = {
    "见官网": {"en": "See site", "zh": "见官网", "fr": "Voir le site", "es": "Ver sitio", "pa": "ਸਾਈਟ ਦੇਖੋ"},
    "需新开户": {"en": "New account required", "zh": "需新开户", "fr": "Nouveau compte requis", "es": "Cuenta nueva requerida", "pa": "ਨਵਾਂ ਖਾਤਾ ਲੋੜੀਂਦਾ"},
    "需新资金（老户打新钱）": {"en": "New funds required", "zh": "需新资金（老户打新钱）", "fr": "Nouveaux fonds requis", "es": "Nuevos fondos requeridos", "pa": "ਨਵੇਂ ਫੰਡ ਲੋੜੀਂਦੇ"},
    "条款适用": {"en": "Terms apply", "zh": "条款适用", "fr": "Conditions applicables", "es": "Aplican términos", "pa": "ਸ਼ਰਤਾਂ ਲਾਗੂ"},
    "常规利率": {"en": "Standard rate", "zh": "常规利率", "fr": "Taux standard", "es": "Tasa estándar", "pa": "ਮਿਆਰੀ ਦਰ"},
    "—": {"en": "—", "zh": "—", "fr": "—", "es": "—", "pa": "—"},
    "首3个月": {"en": "First 3 months", "zh": "首3个月", "fr": "3 premiers mois", "es": "Primeros 3 meses", "pa": "ਪਹਿਲੇ 3 ਮਹੀਨੇ"},
    "首4个月": {"en": "First 4 months", "zh": "首4个月", "fr": "4 premiers mois", "es": "Primeros 4 meses", "pa": "ਪਹਿਲੇ 4 ਮਹੀਨੇ"},
    "首5个月": {"en": "First 5 months", "zh": "首5个月", "fr": "5 premiers mois", "es": "Primeros 5 meses", "pa": "ਪਹਿਲੇ 5 ਮਹੀਨੇ"},
    "首6个月": {"en": "First 6 months", "zh": "首6个月", "fr": "6 premiers mois", "es": "Primeros 6 meses", "pa": "ਪਹਿਲੇ 6 ਮਹੀਨੇ"},
    "首12个月": {"en": "First 12 months", "zh": "首12个月", "fr": "12 premiers mois", "es": "Primeros 12 meses", "pa": "ਪਹਿਲੇ 12 ਮਹੀਨੇ"},
    # 解析器可能输出的「限时首N个月」长文案，保证与所选语言一致
    "限时首3个月（是否需新开户或新资金请以官网为准）": {"en": "First 3 months (see site for new account/funds rules)", "zh": "限时首3个月（是否需新开户或新资金请以官网为准）", "fr": "3 premiers mois (voir le site pour conditions)", "es": "Primeros 3 meses (ver sitio para condiciones)", "pa": "ਪਹਿਲੇ 3 ਮਹੀਨੇ (ਨਵਾਂ ਖਾਤਾ/ਫੰਡ ਲਈ ਸਾਈਟ ਦੇਖੋ)"},
    "限时首4个月（是否需新开户或新资金请以官网为准）": {"en": "First 4 months (see site for new account/funds rules)", "zh": "限时首4个月（是否需新开户或新资金请以官网为准）", "fr": "4 premiers mois (voir le site pour conditions)", "es": "Primeros 4 meses (ver sitio para condiciones)", "pa": "ਪਹਿਲੇ 4 ਮਹੀਨੇ (ਨਵਾਂ ਖਾਤਾ/ਫੰਡ ਲਈ ਸਾਈਟ ਦੇਖੋ)"},
    "限时首5个月（是否需新开户或新资金请以官网为准）": {"en": "First 5 months (see site for new account/funds rules)", "zh": "限时首5个月（是否需新开户或新资金请以官网为准）", "fr": "5 premiers mois (voir le site pour conditions)", "es": "Primeros 5 meses (ver sitio para condiciones)", "pa": "ਪਹਿਲੇ 5 ਮਹੀਨੇ (ਨਵਾਂ ਖਾਤਾ/ਫੰਡ ਲਈ ਸਾਈਟ ਦੇਖੋ)"},
    "限时首6个月（是否需新开户或新资金请以官网为准）": {"en": "First 6 months (see site for new account/funds rules)", "zh": "限时首6个月（是否需新开户或新资金请以官网为准）", "fr": "6 premiers mois (voir le site pour conditions)", "es": "Primeros 6 meses (ver sitio para condiciones)", "pa": "ਪਹਿਲੇ 6 ਮਹੀਨੇ (ਨਵਾਂ ਖਾਤਾ/ਫੰਡ ਲਈ ਸਾਈਟ ਦੇਖੋ)"},
    "限时首12个月（是否需新开户或新资金请以官网为准）": {"en": "First 12 months (see site for new account/funds rules)", "zh": "限时首12个月（是否需新开户或新资金请以官网为准）", "fr": "12 premiers mois (voir le site pour conditions)", "es": "Primeros 12 meses (ver sitio para condiciones)", "pa": "ਪਹਿਲੇ 12 ਮਹੀਨੇ (ਨਵਾਂ ਖਾਤਾ/ਫੰਡ ਲਈ ਸਾਈਟ ਦੇਖੋ)"},
}


def _condition_parts_and_default(cond: str) -> tuple[list[str], str]:
    """把条件按「；」拆分，返回 (parts 列表, 英文默认拼接)。"""
    raw = (cond or "—").strip()
    parts = [p.strip() for p in raw.split("；") if p.strip()]
    if not parts:
        parts = ["—"]
    trans = CONDITION_PART_TRANSLATIONS
    default_en = "; ".join(trans.get(p, {}).get("en", p) for p in parts)
    return parts, default_en


def _newsletter_condition_for_lang(cond: str, lang: str) -> str:
    """邮件正文中条件列按 lang 翻译。"""
    raw = (cond or "—").strip()
    parts = [p.strip() for p in raw.split("；") if p.strip()]
    if not parts:
        parts = ["—"]
    trans = CONDITION_PART_TRANSLATIONS
    sep = "；" if lang == "zh" else "; "
    return sep.join((trans.get(p, {}).get(lang, trans.get(p, {}).get("en", p)) for p in parts))


# 邮件正文与主题的 i18n（en/zh/fr/es/pa）
NEWSLETTER_I18N = {
    "en": {
        "title": "Big Six Top 3 — Canada High-Interest Savings",
        "meta_note": "Data from RateHub, HighInterestSavings.ca. For reference only.",
        "th_bank": "Bank / Product",
        "th_type": "Type",
        "th_rate": "Rate",
        "th_condition": "Condition",
        "th_link": "Link",
        "tier_six": "Big Six",
        "link_go": "Go to site →",
        "gic_cta_line": "We also have GIC rates on the site.",
        "visit_site_btn": "Visit site",
        "footer": "You received this because you subscribed. Reply to unsubscribe.",
        "newsletter_subject": "Big Six Top 3 — Canada High-Interest Savings · {date}",
    },
    "zh": {
        "title": "六大行 Top 3 — 加拿大高息储蓄",
        "meta_note": "数据来自 RateHub、HighInterestSavings.ca，仅供参考。",
        "th_bank": "银行/产品",
        "th_type": "类型",
        "th_rate": "利率",
        "th_condition": "条件",
        "th_link": "链接",
        "tier_six": "六大行",
        "link_go": "去官网 →",
        "gic_cta_line": "网站上还有 GIC 定存利率，可前往查看。",
        "visit_site_btn": "访问网站",
        "footer": "本邮件由订阅推送发送，退订请回复说明。",
        "newsletter_subject": "六大行 Top 3 — 加拿大高息储蓄 · {date}",
    },
    "fr": {
        "title": "Six grandes Top 3 — Épargne à intérêt élevé (Canada)",
        "meta_note": "Données de RateHub, HighInterestSavings.ca. À titre indicatif.",
        "th_bank": "Banque / Produit",
        "th_type": "Type",
        "th_rate": "Taux",
        "th_condition": "Condition",
        "th_link": "Lien",
        "tier_six": "Six grandes",
        "link_go": "Site →",
        "gic_cta_line": "Nous avons aussi les taux GIC sur le site.",
        "visit_site_btn": "Visiter le site",
        "footer": "Reçu suite à votre abonnement. Répondez pour vous désabonner.",
        "newsletter_subject": "Six grandes Top 3 — Épargne à intérêt élevé (Canada) · {date}",
    },
    "es": {
        "title": "Seis grandes Top 3 — Ahorros con alto interés (Canadá)",
        "meta_note": "Datos de RateHub, HighInterestSavings.ca. Solo referencia.",
        "th_bank": "Banco / Producto",
        "th_type": "Tipo",
        "th_rate": "Tasa",
        "th_condition": "Condición",
        "th_link": "Enlace",
        "tier_six": "Seis grandes",
        "link_go": "Ir al sitio →",
        "gic_cta_line": "También tenemos tasas GIC en el sitio.",
        "visit_site_btn": "Visitar sitio",
        "footer": "Recibiste esto por suscripción. Responde para darte de baja.",
        "newsletter_subject": "Seis grandes Top 3 — Ahorros alto interés (Canadá) · {date}",
    },
    "pa": {
        "title": "ਛੇ ਵੱਡੇ ਟਾਪ 3 — ਕੈਨੇਡਾ ਉੱਚ-ਬਿਆਜ ਬੱਚਤ",
        "meta_note": "RateHub, HighInterestSavings.ca ਤੋਂ ਡਾਟਾ। ਸਿਰਫ਼ ਹਵਾਲਾ।",
        "th_bank": "ਬੈਂਕ / ਉਤਪਾਦ",
        "th_type": "ਕਿਸਮ",
        "th_rate": "ਦਰ",
        "th_condition": "ਸ਼ਰਤ",
        "th_link": "ਲਿੰਕ",
        "tier_six": "ਛੇ ਵੱਡੇ",
        "link_go": "ਸਾਈਟ 'ਤੇ ਜਾਓ →",
        "gic_cta_line": "ਸਾਈਟ 'ਤੇ GIC ਦਰਾਂ ਵੀ ਹਨ।",
        "visit_site_btn": "ਸਾਈਟ 'ਤੇ ਜਾਓ",
        "footer": "ਗਾਹਕੀ ਕਾਰਨ ਪ੍ਰਾਪਤ। ਗਾਹਕੀ ਰੱਦ ਕਰਨ ਲਈ ਜਵਾਬ ਦਿਓ।",
        "newsletter_subject": "ਛੇ ਵੱਡੇ ਟਾਪ 3 — ਕੈਨੇਡਾ ਉੱਚ-ਬਿਆਜ ਬੱਚਤ · {date}",
    },
}


def _resolve_gic_link(bank_product: str, fallback_url: str) -> tuple[str, bool]:
    """返回 (url, is_official)：若 GIC_LINKS 匹配到则用官网，否则用 fallback（比价页）。"""
    if not bank_product:
        return fallback_url, False
    lower = (bank_product or "").lower()
    for key in sorted(GIC_LINKS.keys(), key=lambda x: -len(x)):
        if key in lower:
            return GIC_LINKS[key], True
    return fallback_url, False


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


def parse_ratehub_gic(md: str, source_url: str) -> list[dict]:
    """解析 RateHub best-gic-rates 页表格：Provider | 1-year GIC | 2-year | 3-year | 4-year | 5-year | Minimum investment。
    每行拆成 5 条（1～5 年期），返回 list[dict] 每项含 bank_product, rate, term_label, term_years, min_investment, link。
    """
    rows = []
    in_table = False
    term_labels = ["1年", "2年", "3年", "4年", "5年"]
    term_years_list = [1, 2, 3, 4, 5]
    for line in md.splitlines():
        line = line.strip()
        # 表头可能空格不同，兼容 "Provider" + "1-year" + "5-year"
        if "Provider" in line and "1-year" in line and "5-year" in line and "|" in line:
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" in line:
            continue
        if in_table and line.startswith("|"):
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 6:
                continue
            provider = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", parts[0]).strip()
            if not provider or "Provider" in provider or provider == "---":
                continue
            min_inv = parts[6] if len(parts) > 6 else "—"
            for i in range(5):
                col_idx = i + 1
                if col_idx >= len(parts):
                    break
                rate_str = parts[col_idx]
                m = re.search(r"(\d+\.?\d*)\s*%", rate_str)
                if not m:
                    continue
                rate_val = float(m.group(1))
                rows.append({
                    "bank_product": provider,
                    "rate": rate_val,
                    "term_label": term_labels[i],
                    "term_years": term_years_list[i],
                    "min_investment": min_inv,
                    "source": "RateHub GIC",
                    "source_url": source_url,
                    "link": source_url,
                })
        if in_table and line.startswith("## "):
            in_table = False
    return rows


def parse_rate_string(s: str) -> tuple[float | None, str]:
    """从 '4.60% for the first 3 months' 提取数字和条件说明；尽量区分新开户/新资金/仅限时。"""
    m = re.search(r"(\d+\.?\d*)\s*%", s)
    if not m:
        return None, ""
    rate = float(m.group(1))
    raw = s.strip()
    # 明确写出的条件
    need_new_account = bool(re.search(r"new\s+(?:account|customer|client)", s, re.I) or "新开户" in s)
    need_new_funds = bool(re.search(r"new\s+funds?", s, re.I) or "新资金" in s or "new money" in s.lower())
    first_n_months = re.search(r"first\s+(\d+)\s+months?", s, re.I)
    terms_apply = "*" in s or "terms apply" in s.lower() or "conditions apply" in s.lower()

    parts = []
    if need_new_account:
        parts.append("需新开户")
    if need_new_funds:
        parts.append("需新资金（老户打新钱）")
    if first_n_months:
        n = first_n_months.group(1)
        if parts:
            parts.append(f"首{n}个月")
        else:
            # 原文只写了「首 N 个月」没写是否新户/新钱，说明里写清楚以官网为准
            parts.append(f"限时首{n}个月（是否需新开户或新资金请以官网为准）")
    if terms_apply:
        parts.append("条款适用")

    condition = "；".join(parts) if parts else "见官网"
    return rate, condition


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


def _escape(s: str) -> str:
    """简单转义 HTML。"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _logo_url(link: str) -> str:
    """从官网 link 提取域名，返回 logo 地址（Google favicon，兼容性好）；若为比价站则返回空。"""
    if not link or not link.startswith("http"):
        return ""
    host = (urlparse(link).netloc or "").lower()
    if "ratehub" in host or "highinterestsavings" in host:
        return ""
    domain = host.lstrip("www.") if host.startswith("www.") else host
    if not domain:
        return ""
    # Google favicon 可跨站加载，Clearbit 常被拦截
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"


def _formspree_action() -> str:
    """Formspree 表单提交地址；未配置时用 # 避免报错。"""
    fid = (FORMSPREE_FORM_ID or "").strip()
    if fid:
        return f"https://formspree.io/f/{fid}"
    return "#"


def _savings_row_html(i: int, r: dict) -> str:
    """单行储蓄表格 HTML；带 data-label、独立 Logo 列、可 i18n 的类型与条件。"""
    cond = r.get("condition") or "—"
    rate_note = r.get("rate_display", "").strip()
    cond_parts, cond_default_en = _condition_parts_and_default(cond)
    cond_parts_js = json.dumps(cond_parts)
    if rate_note and rate_note != f'{r["rate"]}%':
        cond_cell = f'<span class="i18n-condition" data-condition-parts="{_escape(cond_parts_js)}" data-condition-fallback="{_escape(cond_default_en)}">{_escape(cond_default_en)}</span><br><span class="cond-raw" title="Source">{_escape(rate_note)}</span>'
    else:
        cond_cell = f'<span class="i18n-condition" data-condition-parts="{_escape(cond_parts_js)}" data-condition-fallback="{_escape(cond_default_en)}">{_escape(cond_default_en)}</span>'
    tier_key = _get_bank_tier_key(r["bank_product"])
    tier_default = {"six": "Big Six", "known": "Known banks", "credit": "Credit unions", "other": "Other"}.get(tier_key, "Other")
    logo_src = _logo_url(r.get("link") or "")
    if logo_src:
        logo_cell = f'<img src="{_escape(logo_src)}" alt="" class="bank-logo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add(\'no-logo\')"><span class="logo-placeholder">—</span>'
    else:
        logo_cell = '<span class="logo-placeholder">—</span>'
    return f"""
        <tr>
          <td data-label="#">{i}</td>
          <td data-label="Logo" class="td-logo">{logo_cell}</td>
          <td data-label="Bank"><strong>{_escape(r["bank_product"])}</strong></td>
          <td class="i18n-tier" data-tier-key="{tier_key}" data-label="Type">{tier_default}</td>
          <td data-label="Rate">{r["rate"]}%</td>
          <td data-label="Condition">{cond_cell}</td>
          <td data-label="Link"><a href="{_escape(r["link"])}" target="_blank" rel="noopener" class="i18n-link-official">Go to site</a></td>
        </tr>"""


def _gic_row_html(r: dict) -> str:
    """单行 GIC 表格 HTML；链接优先官网，带 data-label、独立 Logo 列、可 i18n 的类型与期限。"""
    term_label = r.get("term_label", "")
    term_key = TERM_LABEL_TO_KEY.get(term_label)
    if term_key:
        term_cell = f'<span class="i18n-term" data-term-key="{term_key}">{TERM_KEY_DEFAULT.get(term_key, term_label)}</span>'
    else:
        term_cell = _escape(term_label or "—")
    tier_key = _get_bank_tier_key(r.get("bank_product", ""))
    tier_default = {"six": "Big Six", "known": "Known banks", "credit": "Credit unions", "other": "Other"}.get(tier_key, "Other")
    link, is_official = _resolve_gic_link(r.get("bank_product", ""), r.get("link", ""))
    link_text = "Go to site" if is_official else "Compare"
    link_cls = "i18n-link-official" if is_official else "i18n-link-compare"
    logo_src = _logo_url(link)
    if logo_src:
        logo_cell = f'<img src="{_escape(logo_src)}" alt="" class="bank-logo" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.classList.add(\'no-logo\')"><span class="logo-placeholder">—</span>'
    else:
        logo_cell = '<span class="logo-placeholder">—</span>'
    return f"""
        <tr>
          <td data-label="Term">{term_cell}</td>
          <td data-label="Logo" class="td-logo">{logo_cell}</td>
          <td data-label="Bank"><strong>{_escape(r["bank_product"])}</strong></td>
          <td class="i18n-tier" data-tier-key="{tier_key}" data-label="Type">{tier_default}</td>
          <td data-label="Rate">{r["rate"]}%</td>
          <td data-label="Min. investment">{_escape(r.get("min_investment", "—"))}</td>
          <td data-label="Link"><a href="{_escape(link)}" target="_blank" rel="noopener" class="{link_cls}">{link_text}</a></td>
        </tr>"""


def build_html(top3: list[dict], top3_six: list[dict], top3_known: list[dict], gic_top: list[dict], gic_top_six: list[dict], gic_top_known: list[dict], updated_at: str) -> str:
    """生成单页 HTML：储蓄与 GIC 均支持下拉筛选（全部 / 六大行 / 知名银行）。"""
    rows_all = "".join(_savings_row_html(i, r) for i, r in enumerate(top3, 1))
    rows_six = "".join(_savings_row_html(i, r) for i, r in enumerate(top3_six, 1))
    rows_known = "".join(_savings_row_html(i, r) for i, r in enumerate(top3_known, 1))
    rows_all_js = json.dumps(rows_all)
    rows_six_js = json.dumps(rows_six)
    rows_known_js = json.dumps(rows_known)

    gic_all_js = gic_six_js = gic_known_js = json.dumps("")
    gic_section = ""
    if gic_top:
        gic_all = "".join(_gic_row_html(r) for r in gic_top)
        gic_six = "".join(_gic_row_html(r) for r in gic_top_six)
        gic_known = "".join(_gic_row_html(r) for r in gic_top_known)
        gic_all_js = json.dumps(gic_all)
        gic_six_js = json.dumps(gic_six)
        gic_known_js = json.dumps(gic_known)
        gic_section = f"""
  <section class="gic-section">
  <h2 data-i18n="gic_title">📌 GIC rates (non-registered, top 3 per term)</h2>
  <p class="meta" data-i18n="gic_meta">Data from RateHub GIC.</p>
  <table>
    <thead>
      <tr>
        <th data-i18n="th_term">Term</th>
        <th>Logo</th>
        <th data-i18n="th_bank">Bank / Product</th>
        <th data-i18n="th_type">Type</th>
        <th data-i18n="th_rate">Rate</th>
        <th data-i18n="th_min_inv">Min. investment</th>
        <th data-i18n="th_link">Link</th>
      </tr>
    </thead>
    <tbody id="gic-tbody">
      {gic_six}
    </tbody>
  </table>
  </section>"""
    else:
        gic_url = "https://www.ratehub.ca/gics/best-gic-rates"
        gic_section = f"""
  <section class="gic-section">
  <h2 data-i18n="gic_title">📌 GIC rates (non-registered, top 3 per term)</h2>
  <p class="meta"><span data-i18n="gic_no_data_before">No GIC table this run. See </span><a href="{gic_url}" target="_blank" rel="noopener" style="color:var(--accent);"><span data-i18n="gic_no_data_link">RateHub GIC</span></a>.</p>
  </section>"""

    coffee_html = ""
    if COFFEE_URL:
        coffee_html = f"""
  <section class="coffee">
    <h2 data-i18n="coffee_title">☕ Buy me a coffee</h2>
    <div class="coffee-visual">
      <img src="assets/coffee-cup.png" alt="" width="240" height="auto" loading="lazy">
    </div>
    <p class="meta" data-i18n="coffee_desc">Like this site? Tip me via Stripe.</p>
    <a href="{_escape(COFFEE_URL)}" target="_blank" rel="noopener" class="coffee-btn" data-i18n="coffee_btn">Tip</a>
  </section>"""

    condition_part_translations_js = json.dumps(
        {lang: {k: v[lang] for k, v in CONDITION_PART_TRANSLATIONS.items()} for lang in ["en", "zh", "fr", "es", "pa"]}
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Canada High-Interest Savings &amp; GIC Top 3</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0c0c0e;
      --bg-elevated: #161618;
      --bg-hover: #1c1c1f;
      --border: #2a2a2e;
      --text: #e4e4e7;
      --text-muted: #a1a1aa;
      --accent: #f97316;
      --accent-hover: #fb923c;
      --link: #f97316;
      --link-hover: #fdba74;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      max-width: 920px;
      margin: 0 auto;
      padding: 2rem 1.25rem;
      line-height: 1.6;
      min-height: 100vh;
    }}
    h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 0.5rem;
    }}
    h2 {{
      font-size: 1.2rem;
      font-weight: 600;
      border-bottom: 2px solid var(--accent);
      padding-bottom: 0.35rem;
      margin-top: 0;
      margin-bottom: 0.5rem;
    }}
    .meta {{
      color: var(--text-muted);
      font-size: 0.875rem;
      margin-bottom: 0.75rem;
    }}
    .meta strong {{ color: var(--text); }}
    #tier-filter {{
      background: var(--bg-elevated);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.5rem 2rem 0.5rem 0.75rem;
      font-size: 0.9rem;
      font-family: inherit;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%23a1a1aa' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10l-5 5z'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 0.6rem center;
    }}
    #tier-filter:hover, #tier-filter:focus {{
      border-color: var(--accent);
      outline: none;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      margin-top: 1rem;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
    }}
    th, td {{
      padding: 0.75rem 0.85rem;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      background: var(--bg-elevated);
      font-weight: 600;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--text-muted);
    }}
    tbody tr {{
      background: var(--bg-elevated);
      transition: background 0.15s ease;
    }}
    tbody tr:hover {{
      background: var(--bg-hover);
    }}
    tbody tr:last-child td {{ border-bottom: none; }}
    td {{ font-size: 0.9rem; }}
    td a {{
      color: var(--link);
      text-decoration: none;
      font-weight: 500;
    }}
    td a:hover {{ color: var(--link-hover); }}
    .cond-main {{ display: block; }}
    .cond-raw {{ font-size: 0.8em; color: var(--text-muted); margin-top: 0.15rem; }}
    .td-logo {{
      width: 48px;
      text-align: left;
      vertical-align: middle;
    }}
    .td-logo .bank-logo {{
      width: 32px;
      height: 32px;
      border-radius: 8px;
      object-fit: contain;
      background: var(--bg);
      display: inline-block;
    }}
    .td-logo .logo-placeholder {{ color: var(--text-muted); font-size: 0.9rem; }}
    .td-logo .bank-logo ~ .logo-placeholder {{ display: none; }}
    .td-logo.no-logo .bank-logo {{ display: none !important; }}
    .td-logo.no-logo .logo-placeholder {{ display: inline !important; }}
    @media (max-width: 768px) {{
      thead {{ display: none; }}
      table {{ display: block; border: none; margin-top: 0.5rem; }}
      tbody {{ display: block; }}
      tr {{
        display: block;
        background: var(--bg-elevated);
        border: 1px solid var(--border);
        border-radius: 12px;
        margin-bottom: 1rem;
        padding: 1rem 1.25rem;
        transition: border-color 0.15s ease;
      }}
      tr:hover {{ border-color: var(--accent); }}
      td {{
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.5rem 0;
        border: none;
        font-size: 0.9rem;
      }}
      td::before {{
        content: attr(data-label);
        font-weight: 600;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        color: var(--text-muted);
        min-width: 4.5em;
        flex-shrink: 0;
      }}
      td:first-child {{ padding-top: 0; }}
      td:last-child {{ padding-bottom: 0; }}
      .bank-cell {{ margin-left: 0; }}
      .bank-logo {{ width: 36px; height: 36px; }}
      body {{ padding: 1rem; }}
      .subscribe input, .subscribe textarea {{ max-width: 100%; }}
    }}
    .subscribe {{
      margin-top: 2.5rem;
      padding: 1.5rem;
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 12px;
    }}
    .subscribe h2 {{ margin-bottom: 0.5rem; }}
    .subscribe p {{ color: var(--text-muted); font-size: 0.9rem; margin: 0.5rem 0; }}
    .subscribe label {{ display: block; margin-bottom: 0.25rem; font-size: 0.9rem; }}
    .subscribe input, .subscribe textarea {{
      width: 100%;
      max-width: 320px;
      padding: 0.6rem 0.75rem;
      margin-top: 0.25rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      font-family: inherit;
      font-size: 0.9rem;
    }}
    .subscribe input::placeholder, .subscribe textarea::placeholder {{ color: var(--text-muted); opacity: 0.8; }}
    .subscribe input:focus, .subscribe textarea:focus {{
      outline: none;
      border-color: var(--accent);
    }}
    .subscribe button {{
      margin-top: 0.75rem;
      padding: 0.6rem 1.25rem;
      background: var(--accent);
      color: #0c0c0e;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.9rem;
      font-family: inherit;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    .subscribe button:hover {{ background: var(--accent-hover); }}
    .gic-section {{ margin-top: 2.5rem; }}
    .gic-section h2 {{ margin-top: 0; }}
    .lang-bar {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 1.25rem;
      flex-wrap: wrap;
    }}
    .lang-bar .lang-label {{ color: var(--text-muted); font-size: 0.85rem; margin-right: 0.25rem; }}
    .lang-bar select {{
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.4rem 0.6rem;
      color: var(--text);
      font-size: 0.95rem;
      font-family: inherit;
      cursor: pointer;
      min-width: 10rem;
    }}
    .lang-bar select:hover, .lang-bar select:focus {{ border-color: var(--accent); outline: none; }}
    .bottom-actions {{ display: flex; align-items: stretch; gap: 1.5rem; flex-wrap: wrap; margin-top: 2.5rem; }}
    .bottom-actions .subscribe, .bottom-actions .coffee {{ flex: 1; min-width: 280px; margin-top: 0; }}
    .coffee {{ padding: 1.5rem; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; display: flex; flex-direction: column; }}
    .coffee h2 {{ margin-bottom: 0.5rem; margin-top: 0; }}
    .coffee .meta {{ margin-bottom: 0.5rem; }}
    .coffee-visual {{ position: relative; margin: 1.25rem auto 1rem; width: 260px; flex: 1; min-height: 140px; display: flex; align-items: center; justify-content: center; background-color: #161618; }}
    .coffee-visual::before {{ content: ""; position: absolute; inset: 0; background-color: #161618; z-index: 0; }}
    .coffee-visual img {{ position: relative; z-index: 1; display: block; width: 240px; height: auto; max-width: 100%; }}
    .coffee .coffee-btn {{
      display: inline-block;
      width: fit-content;
      margin-top: 0.75rem;
      padding: 0.6rem 1.25rem;
      background: var(--accent);
      color: #0c0c0e;
      font-weight: 600;
      border: none;
      border-radius: 8px;
      text-decoration: none;
      font-size: 0.9rem;
      font-family: inherit;
      cursor: pointer;
      transition: background 0.15s ease;
    }}
    .coffee .coffee-btn:hover {{ background: var(--accent-hover); }}
    footer.page-footer {{
      margin-top: 3rem;
      padding-top: 1.25rem;
      border-top: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 0.8rem;
      line-height: 1.5;
      text-align: center;
    }}
    footer.page-footer p {{ margin: 0.25rem 0; }}
  </style>
</head>
<body>
  <div class="lang-bar">
    <span class="lang-label" data-i18n="lang_label">Language</span>
    <select id="lang-select" aria-label="Language">
      <option value="en">🇺🇸 English</option>
      <option value="zh">🇨🇳 中文</option>
      <option value="fr">🇫🇷 Français</option>
      <option value="es">🇪🇸 Español</option>
      <option value="pa">🇮🇳 ਪੰਜਾਬੀ</option>
    </select>
  </div>
  <h1 data-i18n="h1">🇨🇦 Top 3 High-Interest Savings (Canada)</h1>
  <p class="meta"><span data-i18n="meta_source">Data from RateHub, HighInterestSavings.ca. Updated:</span> {updated_at}</p>
  <p class="meta" data-i18n="meta_type">Types: <strong>Big Six</strong>=RBC/TD/BMO/Scotiabank/CIBC/National Bank; <strong>Known</strong>=direct/online banks.</p>
  <p class="meta"><span data-i18n="filter_label">Filter (savings & GIC):</span> <select id="tier-filter">
    <option value="all" data-i18n-opt="opt_all">All Top 3</option>
    <option value="six" selected data-i18n-opt="opt_six">Big Six Top 3</option>
    <option value="known" data-i18n-opt="opt_known">Known banks Top 3</option>
  </select></p>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Logo</th>
        <th data-i18n="th_bank">Bank / Product</th>
        <th data-i18n="th_type">Type</th>
        <th data-i18n="th_rate">Rate</th>
        <th data-i18n="th_condition">Condition</th>
        <th data-i18n="th_link">Link</th>
      </tr>
    </thead>
    <tbody id="savings-tbody">
      {rows_six}
    </tbody>
  </table>
  {gic_section}
  <script>
  (function(){{
    var savingsR={{'all':{rows_all_js},'six':{rows_six_js},'known':{rows_known_js}}};
    var gicR=null;
    var gicTbody=document.getElementById('gic-tbody');
    if(gicTbody) gicR={{'all':{gic_all_js},'six':{gic_six_js},'known':{gic_known_js}}};
    function applyFilter(v){{
      document.getElementById('savings-tbody').innerHTML=savingsR[v]||savingsR['all'];
      if(gicR&&gicTbody) gicTbody.innerHTML=gicR[v]||gicR['all'];
      if(window.applyLang) window.applyLang(document.documentElement.lang||'en');
    }}
    document.getElementById('tier-filter').onchange=function(){{ applyFilter(this.value); }};
  }})();
  </script>
  <div class="bottom-actions">
  <section class="subscribe">
    <h2 data-i18n="subscribe_title">📧 Weekly email</h2>
    <p class="meta" data-i18n="subscribe_desc">Get Top 3 in your inbox every Monday.</p>
    <form action="{_formspree_action()}" method="POST" id="subscribe-form">
      <input type="hidden" name="lang" id="sub-lang" value="en">
      <p>
        <label for="sub-email" data-i18n="email_label">Your email</label>
        <input id="sub-email" type="email" name="email" required placeholder="your@email.com">
      </p>
      <p>
        <label for="sub-message" data-i18n="message_label">Message (optional)</label>
        <textarea id="sub-message" name="message" rows="3" placeholder="Optional"></textarea>
      </p>
      <button type="submit" data-i18n="submit_btn">Subscribe</button>
    </form>
  </section>
  {coffee_html}
  </div>
  <footer class="page-footer" role="contentinfo">
    <p data-i18n="footer_copyright">© 2025 Canada Savings Top 3. All rights reserved.</p>
    <p data-i18n="footer_disclaimer">Rates and data are for reference only. Not investment or legal advice.</p>
  </footer>
  <script>
  var conditionPartTranslations = {condition_part_translations_js};
  var i18n={{
    en:{{ h1:"🇨🇦 Top 3 High-Interest Savings (Canada)", meta_source:"Data from RateHub, HighInterestSavings.ca. Updated:", meta_type:"Types: <strong>Big Six</strong>=RBC/TD/BMO/Scotiabank/CIBC/National Bank; <strong>Known</strong>=direct/online banks.", filter_label:"Filter (savings & GIC):", opt_all:"All Top 3", opt_six:"Big Six Top 3", opt_known:"Known banks Top 3", th_bank:"Bank / Product", th_type:"Type", th_rate:"Rate", th_condition:"Condition", th_link:"Link", th_term:"Term", th_min_inv:"Min. investment", tier_six:"Big Six", tier_known:"Known banks", tier_credit:"Credit unions", tier_other:"Other", term_1y:"1 year", term_2y:"2 years", term_3y:"3 years", term_4y:"4 years", term_5y:"5 years", gic_title:"📌 GIC rates (non-registered, top 3 per term)", gic_meta:"Data from RateHub GIC.", gic_no_data_before:"No GIC table this run. See ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 Weekly email", subscribe_desc:"Get Top 3 in your inbox every Monday.", email_label:"Your email", message_label:"Message (optional)", submit_btn:"Subscribe", coffee_title:"☕ Buy me a coffee", coffee_desc:"Like this site? Tip me via Stripe.", coffee_btn:"Tip", lang_label:"Language", link_go:"Go to site", link_compare:"Compare", footer_copyright:"© 2025 Canada Savings Top 3. All rights reserved.", footer_disclaimer:"Rates and data are for reference only. Not investment or legal advice." }},
    zh:{{ h1:"🇨🇦 活期/短期高息储蓄 Top 3", meta_source:"数据来自 RateHub、HighInterestSavings.ca，仅供参考。更新时间：", meta_type:"类型说明：<strong>六大行</strong>=加拿大六大商业银行（RBC/TD/BMO/Scotiabank/CIBC/National Bank），<strong>知名银行/直销</strong>=常见直销或网络银行，<strong>其他</strong>=未分类。", filter_label:"筛选（储蓄与 GIC 同步）：", opt_all:"全部 Top 3", opt_six:"六大行 Top 3", opt_known:"知名银行/直销 Top 3", th_bank:"银行/产品", th_type:"类型", th_rate:"利率", th_condition:"条件", th_link:"官网", th_term:"期限", th_min_inv:"最低投资", tier_six:"六大行", tier_known:"知名银行/直销", tier_credit:"信贷/中小机构", tier_other:"其他", term_1y:"1年", term_2y:"2年", term_3y:"3年", term_4y:"4年", term_5y:"5年", gic_title:"📌 GIC 定存利率（非注册，各期限 Top 3）", gic_meta:"数据来自 RateHub GIC，仅供参考。", gic_no_data_before:"本次未解析到 GIC 表格。请查看 ", gic_no_data_link:"RateHub GIC 比价页", subscribe_title:"📧 每周邮件订阅", subscribe_desc:"输入邮箱，每周一收到本期 Top 3 推送。", email_label:"您的邮箱", message_label:"留言（选填）", submit_btn:"订阅", coffee_title:"☕ 请我喝杯咖啡", coffee_desc:"喜欢这个网站？可以通过 Stripe 打赏我。", coffee_btn:"打赏", lang_label:"语言", link_go:"去官网", link_compare:"比价页", footer_copyright:"© 2025 加拿大储蓄 Top 3。保留所有权利。", footer_disclaimer:"利率与数据仅供参考，不构成投资或法律建议。" }},
    fr:{{ h1:"🇨🇦 Top 3 Épargne à intérêt élevé (Canada)", meta_source:"Données de RateHub, HighInterestSavings.ca. Mis à jour :", meta_type:"Types : <strong>Six grandes</strong>=RBC/TD/BMO/Scotiabank/CIBC/BNC ; <strong>Connues</strong>=banques en ligne.", filter_label:"Filtrer (épargne et GIC) :", opt_all:"Tous Top 3", opt_six:"Six grandes Top 3", opt_known:"Banques connues Top 3", th_bank:"Banque / Produit", th_type:"Type", th_rate:"Taux", th_condition:"Condition", th_link:"Lien", th_term:"Terme", th_min_inv:"Min. invest.", tier_six:"Six grandes", tier_known:"Banques connues", tier_credit:"Caisses", tier_other:"Autre", term_1y:"1 an", term_2y:"2 ans", term_3y:"3 ans", term_4y:"4 ans", term_5y:"5 ans", gic_title:"📌 Taux GIC (non enregistré, top 3 par terme)", gic_meta:"Données de RateHub GIC.", gic_no_data_before:"Pas de tableau GIC. Voir ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 Infolettre", subscribe_desc:"Recevez le Top 3 chaque lundi.", email_label:"Votre courriel", message_label:"Message (optionnel)", submit_btn:"S'abonner", coffee_title:"☕ Offrez-moi un café", coffee_desc:"Vous aimez ? Vous pouvez me remercier via Stripe.", coffee_btn:"Don", lang_label:"Langue", link_go:"Site", link_compare:"Comparer", footer_copyright:"© 2025 Canada Savings Top 3. Tous droits réservés.", footer_disclaimer:"Taux et données à titre indicatif uniquement. Pas un conseil en investissement ou juridique." }},
    es:{{ h1:"🇨🇦 Top 3 Ahorros con alto interés (Canadá)", meta_source:"Datos de RateHub, HighInterestSavings.ca. Actualizado:", meta_type:"Tipos: <strong>Seis grandes</strong>=RBC/TD/BMO/Scotiabank/CIBC/National Bank; <strong>Conocidos</strong>=bancos en línea.", filter_label:"Filtrar (ahorros y GIC):", opt_all:"Todos Top 3", opt_six:"Seis grandes Top 3", opt_known:"Bancos conocidos Top 3", th_bank:"Banco / Producto", th_type:"Tipo", th_rate:"Tasa", th_condition:"Condición", th_link:"Enlace", th_term:"Plazo", th_min_inv:"Min. inversión", tier_six:"Seis grandes", tier_known:"Conocidos", tier_credit:"Cajas", tier_other:"Otro", term_1y:"1 año", term_2y:"2 años", term_3y:"3 años", term_4y:"4 años", term_5y:"5 años", gic_title:"📌 Tasas GIC (no registrado, top 3 por plazo)", gic_meta:"Datos de RateHub GIC.", gic_no_data_before:"Sin tabla GIC. Ver ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 Correo semanal", subscribe_desc:"Recibe el Top 3 cada lunes.", email_label:"Tu correo", message_label:"Mensaje (opcional)", submit_btn:"Suscribir", coffee_title:"☕ Invítame un café", coffee_desc:"¿Te gusta? Puedes apoyarme por Stripe.", coffee_btn:"Propina", lang_label:"Idioma", link_go:"Ir al sitio", link_compare:"Comparar", footer_copyright:"© 2025 Canada Savings Top 3. Todos los derechos reservados.", footer_disclaimer:"Tasas y datos solo de referencia. No son asesoramiento legal o de inversión." }},
    pa:{{ h1:"🇨🇦 ਟਾਪ 3 ਉੱਚ-ਬਿਆਜ ਬੱਚਤ (ਕੈਨੇਡਾ)", meta_source:"RateHub, HighInterestSavings.ca ਤੋਂ ਡਾਟਾ। ਅੱਪਡੇਟ:", meta_type:"ਕਿਸਮਾਂ: <strong>ਛੇ ਵੱਡੇ</strong>=RBC/TD/BMO/Scotiabank/CIBC/National Bank; <strong>ਜਾਣੇ-ਪਛਾਣੇ</strong>=ਔਨਲਾਈਨ ਬੈਂਕ।", filter_label:"ਫਿਲਟਰ (ਬੱਚਤ ਅਤੇ GIC):", opt_all:"ਸਭ ਟਾਪ 3", opt_six:"ਛੇ ਵੱਡੇ ਟਾਪ 3", opt_known:"ਜਾਣੇ-ਪਛਾਣੇ ਟਾਪ 3", th_bank:"ਬੈਂਕ / ਉਤਪਾਦ", th_type:"ਕਿਸਮ", th_rate:"ਦਰ", th_condition:"ਸ਼ਰਤ", th_link:"ਲਿੰਕ", th_term:"ਮਿਆਦ", th_min_inv:"ਘੱਟੋ-ਘੱਟ ਨਿਵੇਸ਼", tier_six:"ਛੇ ਵੱਡੇ", tier_known:"ਜਾਣੇ-ਪਛਾਣੇ", tier_credit:"ਕ੍ਰੈਡਿਟ ਯੂਨੀਅਨ", tier_other:"ਹੋਰ", term_1y:"1 ਸਾਲ", term_2y:"2 ਸਾਲ", term_3y:"3 ਸਾਲ", term_4y:"4 ਸਾਲ", term_5y:"5 ਸਾਲ", gic_title:"📌 GIC ਦਰਾਂ (ਗੈਰ-ਰਜਿਸਟਰਡ)", gic_meta:"RateHub GIC ਤੋਂ ਡਾਟਾ।", gic_no_data_before:"ਇਸ ਰਨ ਵਿੱਚ GIC ਟੇਬਲ ਨਹੀਂ। ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 ਹਫ਼ਤਾਵਾਰੀ ਈਮੇਲ", subscribe_desc:"ਹਰ ਸੋਮਵਾਰ ਟਾਪ 3 ਆਪਣੇ ਇਨਬਾਕਸ ਵਿੱਚ ਲਓ।", email_label:"ਤੁਹਾਡਾ ਈਮੇਲ", message_label:"ਸੁਨੇਹਾ (ਵਿਕਲਪਿਕ)", submit_btn:"ਗਾਹਕ ਬਣੋ", coffee_title:"☕ ਮੈਨੂੰ ਕੌਫੀ ਪਿਲਾਓ", coffee_desc:"ਸਾਈਟ ਪਸੰਦ ਹੈ? Stripe ਰਾਹੀਂ ਟਿਪ ਕਰ ਸਕਦੇ ਹੋ।", coffee_btn:"ਟਿਪ", lang_label:"ਭਾਸ਼ਾ", link_go:"ਸਾਈਟ 'ਤੇ ਜਾਓ", link_compare:"ਤੁਲਨਾ ਕਰੋ", footer_copyright:"© 2025 Canada Savings Top 3. ਸਾਰੇ ਅਧਿਕਾਰ ਰਾਖਵੇਂ।", footer_disclaimer:"ਦਰਾਂ ਅਤੇ ਡਾਟਾ ਸਿਰਫ਼ ਹਵਾਲੇ ਲਈ। ਨਿਵੇਸ਼ ਜਾਂ ਕਾਨੂੰਨੀ ਸਲਾਹ ਨਹੀਂ।" }}
  }};
  function applyLang(lang){{
    if(!i18n[lang]) lang='en';
    document.documentElement.lang=lang;
    document.querySelectorAll('[data-i18n]').forEach(function(el){{ var k=el.dataset.i18n; if(i18n[lang][k]) el.innerHTML=i18n[lang][k]; }});
    document.querySelectorAll('[data-i18n-opt]').forEach(function(el){{ var k=el.dataset.i18nOpt; if(i18n[lang][k]) el.textContent=i18n[lang][k]; }});
    document.querySelectorAll('.i18n-link-official').forEach(function(el){{ el.textContent=i18n[lang].link_go||'Go to site'; }});
    document.querySelectorAll('.i18n-link-compare').forEach(function(el){{ el.textContent=i18n[lang].link_compare||'Compare'; }});
    document.querySelectorAll('.i18n-tier').forEach(function(el){{ var k=el.dataset.tierKey; if(k&&i18n[lang]['tier_'+k]) el.textContent=i18n[lang]['tier_'+k]; }});
    document.querySelectorAll('.i18n-term').forEach(function(el){{ var k=el.dataset.termKey; if(k&&i18n[lang]['term_'+k]) el.textContent=i18n[lang]['term_'+k]; }});
    document.querySelectorAll('.i18n-condition').forEach(function(el){{ var parts=[]; try{{ parts=JSON.parse(el.dataset.conditionParts||'[]'); }}catch(e){{}} var sep=lang==='zh'?'；':'; '; var tr=conditionPartTranslations[lang]||{{}}; el.innerHTML=parts.map(function(p){{ return tr[p]||p; }}).join(sep)||el.dataset.conditionFallback||'—'; }});
    var langSel=document.getElementById('lang-select'); if(langSel) langSel.value=lang;
    var subLang=document.getElementById('sub-lang'); if(subLang) subLang.value=lang;
    try{{ localStorage.setItem('ca-savings-lang',lang); }}catch(e){{}}
  }}
  window.applyLang=applyLang;
  var saved=localStorage.getItem('ca-savings-lang');
  applyLang(saved&&i18n[saved]?saved:'en');
  var langSel=document.getElementById('lang-select'); if(langSel) langSel.addEventListener('change',function(){{ applyLang(this.value); var subLang=document.getElementById('sub-lang'); if(subLang) subLang.value=this.value; }});
  var subForm=document.getElementById('subscribe-form'); if(subForm) subForm.addEventListener('submit',function(){{ var subLang=document.getElementById('sub-lang'); var sel=document.getElementById('lang-select'); if(subLang&&sel) subLang.value=sel.value; }});
  </script>
</body>
</html>"""


def build_newsletter_html(lang: str, top3_six: list[dict], updated_at: str, site_url: str) -> str:
    """生成邮件正文 HTML：仅六大行 Top 3，无 GIC 表；含 GIC 说明与「访问网站」按钮。"""
    t = NEWSLETTER_I18N.get(lang) or NEWSLETTER_I18N["en"]
    rows_html = ""
    for i, r in enumerate(top3_six, 1):
        cond = _escape(_newsletter_condition_for_lang(r.get("condition") or "—", lang))
        link = _escape(r.get("link") or "")
        tier_label = _escape(t.get("tier_six", "Big Six"))
        link_go = _escape(t.get("link_go", "Go to site →"))
        rows_html += f"""
    <tr>
      <td style="padding:8px 12px; border-bottom:1px solid #eee; font-size:15px;">{i}</td>
      <td style="padding:8px 12px; border-bottom:1px solid #eee; font-size:15px;"><strong>{_escape(r["bank_product"])}</strong></td>
      <td style="padding:8px 12px; border-bottom:1px solid #eee; font-size:14px; color:#555;">{tier_label}</td>
      <td style="padding:8px 12px; border-bottom:1px solid #eee; font-size:15px;">{r["rate"]}%</td>
      <td style="padding:8px 12px; border-bottom:1px solid #eee; font-size:14px; color:#555;">{cond}</td>
      <td style="padding:8px 12px; border-bottom:1px solid #eee;"><a href="{link}" style="color:#0066cc; text-decoration:none;">{link_go}</a></td>
    </tr>"""
    th_bank = _escape(t.get("th_bank", "Bank / Product"))
    th_type = _escape(t.get("th_type", "Type"))
    th_rate = _escape(t.get("th_rate", "Rate"))
    th_condition = _escape(t.get("th_condition", "Condition"))
    th_link = _escape(t.get("th_link", "Link"))
    gic_cta = _escape(t.get("gic_cta_line", "We also have GIC rates on the site."))
    visit_btn = _escape(t.get("visit_site_btn", "Visit site"))
    footer = _escape(t.get("footer", "You received this because you subscribed. Reply to unsubscribe."))
    title = _escape(t.get("title", "Big Six Top 3 — Canada High-Interest Savings"))
    meta_note = _escape(t.get("meta_note", "Data from RateHub, HighInterestSavings.ca. For reference only."))
    site_url_esc = _escape(site_url)
    return f"""<!DOCTYPE html>
<html lang="{lang}-CA">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0; font-family: system-ui, -apple-system, sans-serif; font-size:15px; line-height:1.5; color:#333;">
  <div style="max-width:560px; margin:0 auto; padding:24px 16px;">
    <h1 style="margin:0 0 8px 0; font-size:20px;">🇨🇦 {title}</h1>
    <p style="margin:0 0 20px 0; font-size:13px; color:#888;">{updated_at} · {meta_note}</p>
    <table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr style="background:#f6f6f6;">
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">#</th>
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">{th_bank}</th>
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">{th_type}</th>
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">{th_rate}</th>
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">{th_condition}</th>
          <th style="padding:8px 12px; text-align:left; font-size:13px; color:#666;">{th_link}</th>
        </tr>
      </thead>
      <tbody>
{rows_html}
      </tbody>
    </table>
    <p style="margin:20px 0 12px 0; font-size:14px; color:#555;">{gic_cta}</p>
    <p style="margin:0 0 24px 0;"><a href="{site_url_esc}" style="display:inline-block; padding:10px 20px; background:#0066cc; color:#fff; text-decoration:none; border-radius:6px; font-size:15px;">{visit_btn}</a></p>
    <p style="margin:24px 0 0 0; font-size:12px; color:#999;">{footer}</p>
  </div>
</body>
</html>"""


def load_subscribers() -> list[dict]:
    """从 subscribers.json 读取订阅列表。支持旧格式 ["a@b.com"]（视为 en）与新格式 [{"email":"a@b.com","lang":"zh"}]。"""
    path = os.path.join(os.path.dirname(__file__), "subscribers.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    valid_langs = {"en", "zh", "fr", "es", "pa"}
    for e in data:
        if isinstance(e, dict):
            email = (e.get("email") or "").strip().lower()
            lang = (e.get("lang") or "en").strip().lower()
            if lang not in valid_langs:
                lang = "en"
            if email and "@" in email:
                out.append({"email": email, "lang": lang})
        else:
            email = str(e).strip().lower()
            if email and "@" in email:
                out.append({"email": email, "lang": "en"})
    return out


def send_newsletter_emails(top3_six: list[dict], updated_at: str, site_url: str) -> None:
    """按订阅者语言分别生成正文与主题，用 Resend 发送。"""
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = (os.environ.get("RESEND_FROM_EMAIL") or "").strip()
    print("  [发信] RESEND_API_KEY 已设置" if api_key else "  [发信] RESEND_API_KEY 未设置")
    print("  [发信] RESEND_FROM_EMAIL 已设置" if from_email else "  [发信] RESEND_FROM_EMAIL 未设置")
    if not api_key or not from_email:
        print("  跳过邮件推送（未设置 RESEND_API_KEY 或 RESEND_FROM_EMAIL）")
        return
    subscribers = load_subscribers()
    print(f"  [发信] 订阅人数: {len(subscribers)}")
    if not subscribers:
        print("  订阅列表为空，跳过邮件")
        return
    try:
        import resend
        resend.api_key = api_key
    except ImportError:
        print("  未安装 resend，跳过邮件推送")
        return
    html_cache: dict[str, str] = {}
    date_str = updated_at[:10]
    for sub in subscribers:
        to = sub["email"]
        lang = sub.get("lang", "en")
        if lang not in html_cache:
            html_cache[lang] = build_newsletter_html(lang, top3_six, updated_at, site_url)
        t = NEWSLETTER_I18N.get(lang) or NEWSLETTER_I18N["en"]
        subject = (t.get("newsletter_subject") or "Big Six Top 3 — Canada High-Interest Savings · {date}").format(date=date_str)
        try:
            resend.Emails.send({
                "from": from_email,
                "to": [to],
                "subject": subject,
                "html": html_cache[lang],
            })
            print(f"  已发送: {to} ({lang})")
        except Exception as e:
            print(f"  发送失败 {to}: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview-newsletter", action="store_true", help="Write newsletter HTML per language to newsletter_preview_*.html, do not send email")
    args = parser.parse_args()

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
    top3_six = [r for r in merged if _get_bank_tier(r["bank_product"]) == "六大行"][:3]
    top3_known = [r for r in merged if _get_bank_tier(r["bank_product"]) == "知名银行/直销"][:3]

    # GIC：抓取、解析、按期限取各 Top 3
    gic_rows = []
    for src in GIC_SOURCES:
        url = src["url"]
        name = src["name"]
        print(f"正在抓取 {name}: {url}")
        try:
            md = scrape_url(url)
        except Exception as e:
            print(f"  失败: {e}")
            continue
        if src["parser"] == "ratehub_gic":
            rows = parse_ratehub_gic(md, url)
        else:
            rows = []
        print(f"  解析到 {len(rows)} 条 GIC")
        gic_rows.extend(rows)

    gic_top = []
    gic_top_six = []
    gic_top_known = []
    if gic_rows:
        gic_rows.sort(key=lambda r: (r.get("term_years", 0), -r["rate"]))
        for term_y in (1, 2, 3, 4, 5):
            term_rows = [r for r in gic_rows if r.get("term_years") == term_y]
            gic_top.extend(term_rows[:3])
            term_six = [r for r in term_rows if _get_bank_tier(r.get("bank_product", "")) == "六大行"]
            gic_top_six.extend(term_six[:3])
            term_known = [r for r in term_rows if _get_bank_tier(r.get("bank_product", "")) == "知名银行/直销"]
            gic_top_known.extend(term_known[:3])
    print(f"GIC 各期限 Top 3 共 {len(gic_top)} 条")

    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(top3, top3_six, top3_known, gic_top, gic_top_six, gic_top_known, updated_at)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已写入 {out_path}，储蓄 Top 3: {len(top3)}，GIC: {len(gic_top)} 条")

    data_path = os.path.join(os.path.dirname(__file__), "top3.json")
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": updated_at, "top3": top3, "gic_top": gic_top}, f, ensure_ascii=False, indent=2)
    print(f"已写入 {data_path}")

    site_url = SITE_URL
    if args.preview_newsletter:
        for lang in ["en", "zh", "fr", "es", "pa"]:
            html = build_newsletter_html(lang, top3_six, updated_at, site_url)
            p = os.path.join(os.path.dirname(__file__), f"newsletter_preview_{lang}.html")
            with open(p, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"已写入 {p}")
    else:
        send_newsletter_emails(top3_six, updated_at, site_url)


if __name__ == "__main__":
    main()
