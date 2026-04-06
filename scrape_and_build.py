#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
from config import (
    SOURCES, GIC_SOURCES, BANK_WHITELIST, BANK_LINKS, GIC_LINKS, BANK_TIER,
    FORMSPREE_FORM_ID, COFFEE_URL, SITE_URL,
    PROPERTY_METRO_URL_TEMPLATE, PROPERTY_AREAS_URL, PROPERTY_AREAS, PROPERTY_TYPES,
)

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


def _extract_markdown_link(text: str):
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
        "re_section_title": "Vancouver Real Estate Snapshot",
        "re_data_note": "Source: Greater Vancouver REALTORS® & FVREB monthly stats. MLS® HPI.",
        "re_composite": "Composite Benchmark",
        "re_detached": "Detached",
        "re_attached": "Attached",
        "re_apartment": "Apartment",
        "re_yoy": "YoY",
        "re_sales": "Sales",
        "re_vs_avg": "vs 10yr avg",
        "re_top_gainer": "Top Gainer",
        "re_top_loser": "Top Loser",
        "re_no_data": "Real estate data not available this week.",
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
        "re_section_title": "温哥华房市快讯",
        "re_data_note": "数据来源：Greater Vancouver REALTORS® 及 FVREB 月度统计，MLS® HPI。",
        "re_composite": "综合基准价",
        "re_detached": "独立屋",
        "re_attached": "联排",
        "re_apartment": "公寓",
        "re_yoy": "年涨跌",
        "re_sales": "成交套数",
        "re_vs_avg": "vs 10年均值",
        "re_top_gainer": "涨幅最大",
        "re_top_loser": "跌幅最大",
        "re_no_data": "本周暂无最新房产数据。",
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
        "re_section_title": "Aperçu immobilier Vancouver",
        "re_data_note": "Source : Greater Vancouver REALTORS® & FVREB stats mensuelles. MLS® HPI.",
        "re_composite": "Prix de référence composite",
        "re_detached": "Maison détachée",
        "re_attached": "Maison en rangée",
        "re_apartment": "Appartement",
        "re_yoy": "Var. annuelle",
        "re_sales": "Ventes",
        "re_vs_avg": "vs moy. 10 ans",
        "re_top_gainer": "Meilleure hausse",
        "re_top_loser": "Meilleure baisse",
        "re_no_data": "Données immobilières non disponibles cette semaine.",
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
        "re_section_title": "Resumen inmobiliario Vancouver",
        "re_data_note": "Fuente: Greater Vancouver REALTORS® y FVREB estadísticas mensuales. MLS® HPI.",
        "re_composite": "Precio referencia compuesto",
        "re_detached": "Casa independiente",
        "re_attached": "Casa adosada",
        "re_apartment": "Apartamento",
        "re_yoy": "Var. anual",
        "re_sales": "Ventas",
        "re_vs_avg": "vs prom. 10 años",
        "re_top_gainer": "Mayor subida",
        "re_top_loser": "Mayor bajada",
        "re_no_data": "Datos inmobiliarios no disponibles esta semana.",
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
        "re_section_title": "ਵੈਨਕੂਵਰ ਰੀਅਲ ਅਸਟੇਟ ਸਨੈਪਸ਼ਾਟ",
        "re_data_note": "ਸਰੋਤ: Greater Vancouver REALTORS® ਅਤੇ FVREB ਮਾਸਿਕ ਅੰਕੜੇ। MLS® HPI.",
        "re_composite": "ਕੰਪੋਜ਼ਿਟ ਬੈਂਚਮਾਰਕ",
        "re_detached": "ਡਿਟੈਚਡ",
        "re_attached": "ਟਾਊਨਹਾਊਸ",
        "re_apartment": "ਅਪਾਰਟਮੈਂਟ",
        "re_yoy": "ਸਾਲਾਨਾ ਬਦਲਾਅ",
        "re_sales": "ਵਿਕਰੀ",
        "re_vs_avg": "vs 10 ਸਾਲ ਔਸਤ",
        "re_top_gainer": "ਸਭ ਤੋਂ ਵੱਧ ਵਾਧਾ",
        "re_top_loser": "ਸਭ ਤੋਂ ਵੱਧ ਗਿਰਾਵਟ",
        "re_no_data": "ਇਸ ਹਫ਼ਤੇ ਰੀਅਲ ਅਸਟੇਟ ਡਾਟਾ ਉਪਲਬਧ ਨਹੀਂ।",
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


def parse_rate_string(s: str):
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


def build_html(top3: list[dict], top3_six: list[dict], top3_known: list[dict], gic_top: list[dict], gic_top_six: list[dict], gic_top_known: list[dict], updated_at: str, property_html: str = "") -> str:
    """生成单页 HTML：全局 shell（语言切换、Tab 导航、订阅、咖啡）+ 各 Tab 内容。"""
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

    subscribe_html = f"""
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
  </section>"""

    condition_part_translations_js = json.dumps(
        {lang: {k: v[lang] for k, v in CONDITION_PART_TRANSLATIONS.items()} for lang in ["en", "zh", "fr"]}
    )

    re_tab = f'<li><button class="tab-btn" data-tab="realestate" data-i18n="tab_realestate">🏠 Real Estate</button></li>' if property_html else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title data-i18n="site_title">New Immigrant Info Hub</title>
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
    /* ── Tab nav ── */
    .site-header {{ margin-bottom: 1.5rem; }}
    .site-header h1 {{ margin-bottom: 0.25rem; }}
    .tab-nav {{ list-style: none; margin: 1rem 0 0; padding: 0; display: flex; gap: 0.5rem; flex-wrap: wrap; border-bottom: 2px solid var(--border); }}
    .tab-nav li {{ margin-bottom: -2px; }}
    .tab-btn {{
      background: none; border: none; border-bottom: 2px solid transparent;
      color: var(--text-muted); font-family: inherit; font-size: 0.95rem; font-weight: 500;
      padding: 0.5rem 1rem; cursor: pointer; transition: color 0.15s, border-color 0.15s;
    }}
    .tab-btn:hover {{ color: var(--text); }}
    .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
    .tab-panel {{ display: none; padding-top: 1.5rem; }}
    .tab-panel.active {{ display: block; }}
    /* ── Real estate cards ── */
    .re-cards {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 1rem; margin: 1rem 0; }}
    .re-card {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; text-align: center; }}
    .re-card-icon {{ font-size: 1.75rem; margin-bottom: 0.4rem; }}
    .re-card-label {{ font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.5rem; }}
    .re-card-sales {{ font-size: 1.1rem; font-weight: 600; }}
    .re-card-price {{ font-size: 1.4rem; font-weight: 700; color: var(--accent); margin: 0.25rem 0; }}
    .re-card-yoy {{ font-size: 0.85rem; margin-bottom: 0.2rem; }}
    .re-card-meta {{ font-size: 0.8rem; color: var(--text-muted); }}
    .re-summary-meta {{ margin-top: 0.5rem; }}
    /* ── Insight banner ── */
    .re-insight {{ background: var(--bg-elevated); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px; padding: 1rem 1.25rem; margin: 1rem 0; }}
    .re-insight-title {{ font-size: 0.85rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.5rem; }}
    .re-insight-list {{ margin: 0; padding: 0 0 0 1.1rem; list-style: disc; }}
    .re-insight-list li {{ font-size: 0.9rem; color: var(--text); margin-bottom: 0.3rem; line-height: 1.5; }}
    /* ── Market tags ── */
    .re-market-tag {{ display: inline-block; font-size: 0.72rem; font-weight: 600; padding: 0.15rem 0.5rem; border-radius: 4px; margin-left: 0.3rem; vertical-align: middle; }}
    .re-buyer {{ background: rgba(96,165,250,0.15); color: #60a5fa; }}
    .re-seller {{ background: rgba(249,115,22,0.15); color: #f97316; }}
    .re-balanced {{ background: rgba(74,222,128,0.15); color: #4ade80; }}
    /* ── Opportunity cards ── */
    .re-opp-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin: 1rem 0 1.5rem; }}
    .re-opp-card {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px; padding: 0.9rem 1rem; }}
    .re-opp-icon {{ font-size: 1.3rem; margin-bottom: 0.25rem; }}
    .re-opp-label {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.35rem; }}
    .re-opp-finding {{ font-size: 0.92rem; font-weight: 700; color: var(--text); margin-bottom: 0.2rem; }}
    .re-opp-desc {{ font-size: 0.78rem; color: var(--text-muted); line-height: 1.4; }}
    .re-opp-buyers {{ border-left: 3px solid #60a5fa; }}
    .re-opp-value {{ border-left: 3px solid #4ade80; }}
    .re-opp-momentum {{ border-left: 3px solid #06b6d4; }}
    .re-opp-correction {{ border-left: 3px solid #f97316; }}
    @media (max-width: 640px) {{ .re-opp-grid {{ grid-template-columns: 1fr 1fr; }} }}
    /* ── Snapshot 4-card grid ── */
    .re-snap-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.75rem; margin: 1rem 0 1.5rem; }}
    .re-snap-card {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px; padding: 0.9rem 1rem; }}
    .re-snap-overview {{ border-left: 3px solid var(--accent); }}
    .re-snap-title {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.6rem; }}
    .re-snap-row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 0.5rem; font-size: 0.8rem; margin-bottom: 0.35rem; }}
    .re-snap-label {{ color: var(--text-muted); flex-shrink: 0; }}
    .re-snap-val {{ text-align: right; }}
    .re-snap-icon {{ font-size: 1.5rem; text-align: center; margin-bottom: 0.3rem; }}
    .re-snap-type {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); text-align: center; margin-bottom: 0.4rem; }}
    .re-snap-price {{ font-size: 1.25rem; font-weight: 700; color: var(--accent); text-align: center; margin-bottom: 0.15rem; }}
    .re-snap-yoy {{ font-size: 0.82rem; text-align: center; margin-bottom: 0.4rem; }}
    .re-snap-meta {{ font-size: 0.78rem; color: var(--text-muted); text-align: center; margin-bottom: 0.2rem; }}
    .re-snap-sar {{ font-size: 0.78rem; text-align: center; color: var(--text-muted); }}
    @media (max-width: 640px) {{ .re-snap-grid {{ grid-template-columns: 1fr 1fr; }} }}
    /* ── Inventory row ── */
    .re-inventory-row {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0.75rem 0 1.5rem; }}
    .re-inv-item {{ font-size: 0.9rem; color: var(--text-muted); }}
    .re-inv-item strong {{ color: var(--text); }}
    /* ── Leaderboard controls ── */
    .re-lb-controls {{ margin-bottom: 0.75rem; }}
    .re-lb-top-row {{ display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 0.75rem; }}
    .re-lb-period-nav {{ display: flex; gap: 0.375rem; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px; padding: 3px; }}
    .re-lb-period {{
      background: none; border: none; border-radius: 7px;
      color: var(--text-muted); font-family: inherit; font-size: 0.84rem; padding: 0.3rem 0.75rem;
      cursor: pointer; transition: all 0.15s; white-space: nowrap;
    }}
    .re-lb-period:hover {{ color: var(--text); }}
    .re-lb-period.active {{ background: var(--accent); color: #0c0c0e; font-weight: 700; }}
    .re-lb-filter {{ display: flex; gap: 0.4rem; flex-wrap: wrap; }}
    .re-lb-btn {{
      background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text-muted); font-family: inherit; font-size: 0.82rem; padding: 0.35rem 0.75rem;
      cursor: pointer; transition: all 0.15s;
    }}
    .re-lb-btn:hover {{ border-color: var(--accent); color: var(--text); }}
    .re-lb-btn.active {{ background: var(--accent); border-color: var(--accent); color: #0c0c0e; font-weight: 600; }}
    .lb-src {{ display: inline-block; font-size: 0.65rem; font-weight: 700; padding: 0.1rem 0.3rem; border-radius: 4px; vertical-align: middle; margin-left: 0.25rem; line-height: 1.4; }}
    .lb-src-gvr {{ background: #1a3a5c; color: #7ec8f0; }}
    .lb-src-fvreb {{ background: #1a3a2a; color: #6fd89a; }}
    /* ── Leaderboard card ── */
    .re-leaderboard-card {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; min-width: 0; }}
    .re-leaderboard-title {{ font-size: 0.95rem; font-weight: 700; margin-bottom: 0.15rem; }}
    .re-leaderboard-sub {{ font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.75rem; }}
    .re-lb-scroll {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
    .re-lb-table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; white-space: nowrap; }}
    .re-lb-table th {{ background: var(--bg); color: var(--text-muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em; padding: 0.4rem 0.5rem; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
    .re-lb-table td {{ padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    .re-lb-table tr:last-child td {{ border-bottom: none; }}
    .re-lb-table tbody tr:hover {{ background: var(--bg-hover); }}
    .lb-rank {{ color: var(--text-muted); font-size: 0.75rem; width: 1.5rem; }}
    .lb-area {{ white-space: nowrap; font-size: 0.83rem; }}
    .lb-type {{ font-size: 0.78rem; color: var(--text-muted); white-space: nowrap; }}
    .lb-price {{ font-size: 0.83rem; font-weight: 600; white-space: nowrap; }}
    .lb-yoy,.lb-mom,.lb-ppsf {{ font-size: 0.82rem; text-align: right; white-space: nowrap; }}
    /* ── Area filter & detail ── */
    .re-area-filter {{ display: flex; gap: 0.4rem 0.5rem; flex-wrap: wrap; align-items: center; margin: 1rem 0 0.75rem; }}
    .re-area-group-label {{ width: 100%; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-top: 0.5rem; }}
    .re-area-btn {{
      background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text-muted); font-family: inherit; font-size: 0.82rem; padding: 0.35rem 0.75rem;
      cursor: pointer; transition: all 0.15s;
    }}
    .re-area-btn:hover {{ border-color: var(--accent); color: var(--text); }}
    .re-area-btn.active {{ background: var(--accent); border-color: var(--accent); color: #0c0c0e; font-weight: 600; }}
    /* ── Area detail panel ── */
    .re-area-detail {{ background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 1.25rem; margin-bottom: 1.5rem; display: none; }}
    .re-area-detail.visible {{ display: block; }}
    .re-area-detail-title {{ font-size: 1rem; font-weight: 700; margin-bottom: 1rem; }}
    .re-area-type-cards {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 0.75rem; }}
    /* ── Area mini card (amc) ── */
    .re-amc {{ background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; text-align: left; }}
    .amc-label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 0.4rem; }}
    .amc-price {{ font-size: 1.1rem; font-weight: 700; color: var(--accent); margin: 0.2rem 0; }}
    .amc-stat {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; margin-top: 0.3rem; }}
    .amc-stat-label {{ color: var(--text-muted); font-size: 0.75rem; }}
    /* ── Type filter (legacy, for table view) ── */
    .re-type-filter {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 1rem 0 0.5rem; }}
    .re-type-btn {{
      background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 8px;
      color: var(--text-muted); font-family: inherit; font-size: 0.85rem; padding: 0.4rem 0.85rem;
      cursor: pointer; transition: all 0.15s;
    }}
    .re-type-btn:hover {{ border-color: var(--accent); color: var(--text); }}
    .re-type-btn.active {{ background: var(--accent); border-color: var(--accent); color: #0c0c0e; font-weight: 600; }}
    .re-area-table {{ table-layout: auto; }}
    /* ── Unified area cards ── */
    .re-unified-controls {{ display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; margin: 1rem 0 1.5rem; }}
    .re-area-cards-container {{ display: flex; flex-direction: column; gap: 1.75rem; }}
    .re-area-group-section {{ }}
    .re-area-group-title {{ font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text-muted); margin-bottom: 0.75rem; padding-bottom: 0.25rem; border-bottom: 1px solid var(--border); }}
    .re-area-cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.75rem; }}
    .re-area-card {{
      background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px;
      padding: 0.9rem 1rem; position: relative; transition: border-color 0.15s;
    }}
    .re-area-card:hover {{ border-color: var(--accent); }}
    .re-area-card-name {{ font-size: 0.85rem; font-weight: 700; padding-right: 1.5rem; margin-bottom: 0.5rem; line-height: 1.2; }}
    .re-area-card-rank {{ position: absolute; top: 0.7rem; right: 0.7rem; font-size: 0.65rem; font-weight: 700; color: var(--text-muted); }}
    .re-area-card-price {{ font-size: 1.05rem; font-weight: 700; color: var(--accent); margin-bottom: 0.35rem; }}
    .re-area-card-metric {{ display: flex; justify-content: space-between; font-size: 0.8rem; }}
    .re-area-card-metric-label {{ color: var(--text-muted); }}
    /* All-types: sub-rows */
    .re-area-card-subtypes {{ margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.3rem; }}
    .re-area-card-subrow {{ display: grid; grid-template-columns: 1fr auto auto; gap: 0.4rem; align-items: center; font-size: 0.78rem; }}
    .re-area-card-subrow-type {{ color: var(--text-muted); }}
    .re-area-card-subrow-price {{ font-weight: 600; text-align: right; }}
    .re-area-card-subrow-pct {{ font-weight: 600; text-align: right; min-width: 3.5rem; }}
    .re-area-card-sar {{ margin-top: 0.45rem; padding-top: 0.4rem; border-top: 1px solid var(--border); font-size: 0.75rem; }}
    @media (max-width: 640px) {{
      .re-cards {{ grid-template-columns: 1fr; }}
      .re-area-type-cards {{ grid-template-columns: 1fr; }}
      .re-area-cards-grid {{ grid-template-columns: 1fr 1fr; }}
      .tab-nav {{ gap: 0.25rem; }}
      .tab-btn {{ font-size: 0.85rem; padding: 0.4rem 0.6rem; }}
    }}
    /* ── Global footer actions ── */
    .global-footer-actions {{ display: flex; align-items: stretch; gap: 1.5rem; flex-wrap: wrap; margin-top: 2.5rem; }}
    .global-footer-actions .subscribe, .global-footer-actions .coffee {{ flex: 1; min-width: 280px; margin-top: 0; }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="lang-bar">
      <span class="lang-label" data-i18n="lang_label">Language</span>
      <select id="lang-select" aria-label="Language">
        <option value="en">🇺🇸 English</option>
        <option value="zh">🇨🇳 中文</option>
        <option value="fr">🇫🇷 Français</option>
      </select>
    </div>
    <h1 data-i18n="site_title">🇨🇦 New Immigrant Info Hub</h1>
    <ul class="tab-nav" role="tablist">
      <li><button class="tab-btn active" data-tab="rates" role="tab" aria-selected="true" data-i18n="tab_rates">💰 Rates</button></li>
      {re_tab}
    </ul>
  </header>

  <div id="tab-rates" class="tab-panel active" role="tabpanel">
    <h2 data-i18n="h1">🇨🇦 Top 3 High-Interest Savings (Canada)</h2>
    <p class="meta"><span data-i18n="meta_source">Data from RateHub, HighInterestSavings.ca. Updated:</span> {updated_at} · <span data-i18n="meta_freq_rates">Updated weekly (every Monday)</span></p>
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
        var noData='<tr><td colspan="7" style="padding:1rem;text-align:center;color:var(--text-muted);">—</td></tr>';
        var sRows=savingsR[v]||savingsR['all'];
        document.getElementById('savings-tbody').innerHTML=sRows||noData;
        if(gicR&&gicTbody){{
          var gRows=gicR[v]||gicR['all'];
          gicTbody.innerHTML=gRows||noData;
        }}
        if(window.applyLang) window.applyLang(document.documentElement.lang||'en');
      }}
      document.getElementById('tier-filter').onchange=function(){{ applyFilter(this.value); }};
      applyFilter(document.getElementById('tier-filter').value||'six');
    }})();
    </script>
  </div>

  <div id="tab-realestate" class="tab-panel" role="tabpanel">
    {property_html}
  </div>

  <div class="global-footer-actions">
    {subscribe_html}
    {coffee_html}
  </div>
  <footer class="page-footer" role="contentinfo">
    <p data-i18n="footer_copyright">© 2025 New Immigrant Info Hub. All rights reserved.</p>
    <p data-i18n="footer_disclaimer">Rates and data are for reference only. Not investment or legal advice.</p>
  </footer>
  <script>
  var conditionPartTranslations = {condition_part_translations_js};
  var i18n={{
    en:{{ site_title:"🇨🇦 New Immigrant Info Hub", tab_rates:"💰 Rates", tab_realestate:"🏠 Real Estate", h1:"🇨🇦 Top 3 High-Interest Savings (Canada)", meta_source:"Data from RateHub, HighInterestSavings.ca. Updated:", meta_type:"Types: <strong>Big Six</strong>=RBC/TD/BMO/Scotiabank/CIBC/National Bank; <strong>Known</strong>=direct/online banks.", filter_label:"Filter (savings & GIC):", opt_all:"All Top 3", opt_six:"Big Six Top 3", opt_known:"Known banks Top 3", th_bank:"Bank / Product", th_type:"Type", th_rate:"Rate", th_condition:"Condition", th_link:"Link", th_term:"Term", th_min_inv:"Min. investment", tier_six:"Big Six", tier_known:"Known banks", tier_credit:"Credit unions", tier_other:"Other", term_1y:"1 year", term_2y:"2 years", term_3y:"3 years", term_4y:"4 years", term_5y:"5 years", gic_title:"📌 GIC rates (non-registered, top 3 per term)", gic_meta:"Data from RateHub GIC.", gic_no_data_before:"No GIC table this run. See ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 Weekly email", subscribe_desc:"Get Top 3 in your inbox every Monday.", email_label:"Your email", message_label:"Message (optional)", submit_btn:"Subscribe", coffee_title:"☕ Buy me a coffee", coffee_desc:"Like this site? Tip me via Stripe.", coffee_btn:"Tip", lang_label:"Language", link_go:"Go to site", link_compare:"Compare", footer_copyright:"© 2025 New Immigrant Info Hub. All rights reserved.", footer_disclaimer:"Rates and data are for reference only. Not investment or legal advice.", re_title:"🏠 Vancouver Real Estate Market", re_area_title:"📍 By Area", re_detached:"Detached", re_attached:"Attached", re_apartment:"Apartment", re_detached_short:"Detached", re_attached_short:"Attached", re_apartment_short:"Apartment", re_sold:"sold", re_days:"days", re_market_buyers:"Buyer's", re_market_sellers:"Seller's", re_market_balanced:"Balanced", re_sold_th:"Sold", re_listed:"Listed", re_area:"Area", re_type:"Type", re_sar:"Sales Ratio", re_updated:"Data from", re_total_active:"Total active:", re_new_listings:"New listings:", re_all_types:"All types", re_no_area_data:"Area data unavailable.", re_snapshot_title:"📊 Market Snapshot", re_insight_sales:"Sales", re_insight_vs10yr:"vs 10yr avg", re_insight_composite:"Composite benchmark", re_insight_yoy:"YoY", re_insight_sar:"Sales ratio", re_lb_title:"🏆 Leaderboard", re_lb_desc:"HPI benchmark by area & type · Filter by type:", re_lb_price:"Benchmark", re_lb_ppsf:"$/ft²", re_lb_yoy:"YoY", re_lb_mom:"MoM", re_lb_3yr:"3yr", re_lb_yoy_btn:"Annual", re_lb_mom_btn:"Monthly", re_lb_3yr_btn:"3-Year", re_uc_desc_yoy:"Annual price change", re_uc_desc_mom:"Monthly price change", re_uc_desc_3yr:"3-year price change", re_uc_desc_all:"all types", re_uc_desc_sep:"·", re_sort_rank_note:"ranked by avg across Detached, Attached &amp; Apartment", re_sar_metro_note:"Metro-wide market (SAR):", re_sar_metro_scope:"(Greater Vancouver overall)", re_lb_gainers:"Top Gainers", re_lb_losers:"Top Losers", re_lb_gainers_yoy:"Annual Top Gainers", re_lb_losers_yoy:"Annual Top Losers", re_lb_gainers_mom:"Monthly Top Gainers", re_lb_losers_mom:"Monthly Top Losers", re_area_desc:"Click an area to see benchmark prices and changes by type.", re_group_gvr:"Greater Vancouver", re_group_north:"North Shore & East", re_group_fv:"Fraser Valley", re_group_coast:"Coast & Recreation", meta_freq_rates:"Updated weekly (every Monday)", meta_freq_property:"Updated monthly", re_group_other:"Other", re_opp_title:"💡 Market Intelligence", re_opp_buyers_label:"Buyer's Advantage", re_opp_buyers_desc:"SAR below 12% — more negotiating power for buyers", re_opp_vs_metro:"vs metro avg", re_opp_momentum_desc:"recent uptick despite", re_opp_correction_but:"but", re_opp_correction_5yr:"over 5 yrs — discounted with strong track record", re_opp_value_label:"Resilient Area", re_opp_momentum_label:"Recovery Signal", re_opp_correction_label:"Value Play" }},
    zh:{{ site_title:"🇨🇦 新移民资讯中心", tab_rates:"💰 利率", tab_realestate:"🏠 房产", h1:"🇨🇦 活期/短期高息储蓄 Top 3", meta_source:"数据来自 RateHub、HighInterestSavings.ca，仅供参考。更新时间：", meta_type:"类型说明：<strong>六大行</strong>=加拿大六大商业银行（RBC/TD/BMO/Scotiabank/CIBC/National Bank），<strong>知名银行/直销</strong>=常见直销或网络银行，<strong>其他</strong>=未分类。", filter_label:"筛选（储蓄与 GIC 同步）：", opt_all:"全部 Top 3", opt_six:"六大行 Top 3", opt_known:"知名银行/直销 Top 3", th_bank:"银行/产品", th_type:"类型", th_rate:"利率", th_condition:"条件", th_link:"官网", th_term:"期限", th_min_inv:"最低投资", tier_six:"六大行", tier_known:"知名银行/直销", tier_credit:"信贷/中小机构", tier_other:"其他", term_1y:"1年", term_2y:"2年", term_3y:"3年", term_4y:"4年", term_5y:"5年", gic_title:"📌 GIC 定存利率（非注册，各期限 Top 3）", gic_meta:"数据来自 RateHub GIC，仅供参考。", gic_no_data_before:"本次未解析到 GIC 表格。请查看 ", gic_no_data_link:"RateHub GIC 比价页", subscribe_title:"📧 每周邮件订阅", subscribe_desc:"输入邮箱，每周一收到本期 Top 3 推送。", email_label:"您的邮箱", message_label:"留言（选填）", submit_btn:"订阅", coffee_title:"☕ 请我喝杯咖啡", coffee_desc:"喜欢这个网站？可以通过 Stripe 打赏我。", coffee_btn:"打赏", lang_label:"语言", link_go:"去官网", link_compare:"比价页", footer_copyright:"© 2025 新移民资讯中心。保留所有权利。", footer_disclaimer:"利率与数据仅供参考，不构成投资或法律建议。", re_title:"🏠 温哥华房产市场", re_area_title:"📍 各区域数据", re_detached:"独立屋", re_attached:"联排", re_apartment:"公寓", re_detached_short:"独立屋", re_attached_short:"联排", re_apartment_short:"公寓", re_sold:"套成交", re_days:"天", re_market_buyers:"买方市场", re_market_sellers:"卖方市场", re_market_balanced:"均衡", re_sold_th:"成交", re_listed:"上市", re_area:"区域", re_type:"类型", re_sar:"销售比", re_updated:"数据来源", re_total_active:"在售总量：", re_new_listings:"新上市：", re_all_types:"全部类型", re_no_area_data:"区域数据暂不可用。", re_snapshot_title:"📊 市场概况", re_insight_sales:"成交量", re_insight_vs10yr:"vs 10年均值", re_insight_composite:"综合基准价", re_insight_yoy:"同比", re_insight_sar:"销售比", re_lb_title:"🏆 涨跌排行榜", re_lb_desc:"各区域 × 房型 HPI 基准价变化 · 筛选房型：", re_lb_price:"基准价", re_lb_ppsf:"均尺价", re_lb_yoy:"年涨跌", re_lb_mom:"月环比", re_lb_3yr:"3年", re_lb_yoy_btn:"年排行", re_lb_mom_btn:"月排行", re_lb_3yr_btn:"3年排行", re_uc_desc_yoy:"过去一年涨跌排行", re_uc_desc_mom:"近一月涨跌排行", re_uc_desc_3yr:"过去三年涨跌排行", re_uc_desc_all:"全部类型", re_uc_desc_sep:"·", re_sort_rank_note:"排名按独立屋、联排、公寓均值计算", re_sar_metro_note:"大温整体市场（销售比率）：", re_sar_metro_scope:"（大温哥华整体数据）", re_lb_gainers:"涨幅 Top 10", re_lb_losers:"跌幅 Top 10", re_lb_gainers_yoy:"年涨幅 Top 10", re_lb_losers_yoy:"年跌幅 Top 10", re_lb_gainers_mom:"月涨幅 Top 10", re_lb_losers_mom:"月跌幅 Top 10", re_area_desc:"点击区域查看各房型基准价和涨跌幅", re_group_gvr:"大温哥华", re_group_north:"北岸 & 东部", re_group_fv:"菲莎河谷", re_group_coast:"海岸 & 度假", meta_freq_rates:"每周更新（每周一）", meta_freq_property:"每月更新", re_group_other:"其他", re_opp_title:"💡 市场机遇", re_opp_buyers_label:"买方优势", re_opp_buyers_desc:"销售比低于 12% — 买方议价空间较大", re_opp_vs_metro:"vs 大温均值", re_opp_momentum_desc:"近期环比上涨，尽管年跌幅仍为", re_opp_correction_but:"但", re_opp_correction_5yr:"五年累计涨幅 — 折价入场，基本面稳健", re_opp_value_label:"抗跌区域", re_opp_momentum_label:"触底反弹", re_opp_correction_label:"价格修正" }},
    fr:{{ site_title:"🇨🇦 Centre d'info nouveaux arrivants", tab_rates:"💰 Taux", tab_realestate:"🏠 Immobilier", h1:"🇨🇦 Top 3 Épargne à intérêt élevé (Canada)", meta_source:"Données de RateHub, HighInterestSavings.ca. Mis à jour :", meta_type:"Types : <strong>Six grandes</strong>=RBC/TD/BMO/Scotiabank/CIBC/BNC ; <strong>Connues</strong>=banques en ligne.", filter_label:"Filtrer (épargne et GIC) :", opt_all:"Tous Top 3", opt_six:"Six grandes Top 3", opt_known:"Banques connues Top 3", th_bank:"Banque / Produit", th_type:"Type", th_rate:"Taux", th_condition:"Condition", th_link:"Lien", th_term:"Terme", th_min_inv:"Min. invest.", tier_six:"Six grandes", tier_known:"Banques connues", tier_credit:"Caisses", tier_other:"Autre", term_1y:"1 an", term_2y:"2 ans", term_3y:"3 ans", term_4y:"4 ans", term_5y:"5 ans", gic_title:"📌 Taux GIC (non enregistré, top 3 par terme)", gic_meta:"Données de RateHub GIC.", gic_no_data_before:"Pas de tableau GIC. Voir ", gic_no_data_link:"RateHub GIC", subscribe_title:"📧 Infolettre", subscribe_desc:"Recevez le Top 3 chaque lundi.", email_label:"Votre courriel", message_label:"Message (optionnel)", submit_btn:"S'abonner", coffee_title:"☕ Offrez-moi un café", coffee_desc:"Vous aimez ? Vous pouvez me remercier via Stripe.", coffee_btn:"Don", lang_label:"Langue", link_go:"Site", link_compare:"Comparer", footer_copyright:"© 2025 Centre d'info nouveaux arrivants. Tous droits réservés.", footer_disclaimer:"Taux et données à titre indicatif uniquement. Pas un conseil en investissement ou juridique.", re_title:"🏠 Marché immobilier de Vancouver", re_area_title:"📍 Par secteur", re_detached:"Détaché", re_attached:"Jumelé", re_apartment:"Appartement", re_detached_short:"Détaché", re_attached_short:"Jumelé", re_apartment_short:"Appart.", re_sold:"vendu(s)", re_days:"jours", re_market_buyers:"Marché acheteur", re_market_sellers:"Marché vendeur", re_market_balanced:"Équilibré", re_sold_th:"Vendus", re_listed:"Inscrits", re_area:"Secteur", re_type:"Type", re_sar:"Ratio ventes", re_updated:"Données de", re_total_active:"Inscriptions actives :", re_new_listings:"Nouveaux :", re_all_types:"Tous types", re_no_area_data:"Données par secteur non disponibles.", re_snapshot_title:"📊 Aperçu du marché", re_insight_sales:"Ventes", re_insight_vs10yr:"vs moy. 10 ans", re_insight_composite:"Prix de référence composite", re_insight_yoy:"Var. annuelle", re_insight_sar:"Ratio ventes", re_lb_title:"🏆 Classement", re_lb_desc:"Prix de référence HPI par secteur & type · Filtrer :", re_lb_price:"Référence", re_lb_ppsf:"$/pi²", re_lb_yoy:"Var. an.", re_lb_mom:"Var. mois", re_lb_3yr:"3 ans", re_lb_yoy_btn:"Annuel", re_lb_mom_btn:"Mensuel", re_lb_3yr_btn:"3 ans", re_uc_desc_yoy:"Variation annuelle", re_uc_desc_mom:"Variation mensuelle", re_uc_desc_3yr:"Variation sur 3 ans", re_uc_desc_all:"tous types", re_uc_desc_sep:"·", re_sort_rank_note:"classé par moyenne Détaché, Jumelé &amp; Appart.", re_sar_metro_note:"Marché métro (ratio ventes) :", re_sar_metro_scope:"(Grand Vancouver global)", re_lb_gainers:"Top hausses", re_lb_losers:"Top baisses", re_lb_gainers_yoy:"Top hausses annuelles", re_lb_losers_yoy:"Top baisses annuelles", re_lb_gainers_mom:"Top hausses mensuelles", re_lb_losers_mom:"Top baisses mensuelles", re_area_desc:"Cliquez sur un secteur pour voir les prix et variations.", re_group_gvr:"Grand Vancouver", re_group_north:"Rive nord & Est", re_group_fv:"Vallée du Fraser", re_group_coast:"Côte & villégiature", meta_freq_rates:"Mis à jour chaque lundi", meta_freq_property:"Mis à jour mensuellement", re_group_other:"Autre", re_opp_title:"💡 Intelligence du marché", re_opp_buyers_label:"Avantage acheteur", re_opp_buyers_desc:"Ratio ventes < 12% — plus de marge de négociation", re_opp_vs_metro:"vs moy. métro", re_opp_momentum_desc:"hausse récente malgré", re_opp_correction_but:"mais", re_opp_correction_5yr:"sur 5 ans — décoté avec de solides fondamentaux", re_opp_value_label:"Zone résiliente", re_opp_momentum_label:"Signal de reprise", re_opp_correction_label:"Opportunité valeur" }},
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
  window.i18n=i18n;
  var saved=localStorage.getItem('ca-savings-lang');
  applyLang(saved&&i18n[saved]?saved:'en');
  var langSel=document.getElementById('lang-select'); if(langSel) langSel.addEventListener('change',function(){{ applyLang(this.value); var subLang=document.getElementById('sub-lang'); if(subLang) subLang.value=this.value; }});
  var subForm=document.getElementById('subscribe-form'); if(subForm) subForm.addEventListener('submit',function(){{ var subLang=document.getElementById('sub-lang'); var sel=document.getElementById('lang-select'); if(subLang&&sel) subLang.value=sel.value; }});
  // Tab switching
  (function(){{
    function switchTab(tabId){{
      document.querySelectorAll('.tab-panel').forEach(function(p){{ p.classList.remove('active'); }});
      document.querySelectorAll('.tab-btn').forEach(function(b){{ b.classList.remove('active'); b.setAttribute('aria-selected','false'); }});
      var panel=document.getElementById('tab-'+tabId);
      if(panel) panel.classList.add('active');
      var btn=document.querySelector('[data-tab="'+tabId+'"]');
      if(btn){{ btn.classList.add('active'); btn.setAttribute('aria-selected','true'); }}
      try{{ localStorage.setItem('ca-hub-tab',tabId); }}catch(e){{}}
    }}
    document.querySelectorAll('.tab-btn').forEach(function(btn){{
      btn.addEventListener('click',function(){{ switchTab(this.dataset.tab); }});
    }});
    var savedTab=localStorage.getItem('ca-hub-tab');
    if(savedTab&&document.getElementById('tab-'+savedTab)) switchTab(savedTab);
  }})();
  </script>
</body>
</html>"""


def build_newsletter_html(lang: str, top3_six: list[dict], updated_at: str, site_url: str,
                          property_metro: dict = None, hpi_by_area: list[dict] = None) -> str:
    """生成邮件正文 HTML：仅六大行 Top 3，无 GIC 表；含 GIC 说明与「访问网站」按钮。
    若提供 property_metro / hpi_by_area 则附加房产市场摘要段落。
    """
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

    # ── 房产摘要段落 ──
    def _pct_str(v):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        color = "#16a34a" if v >= 0 else "#ea580c"
        return f'<span style="color:{color};font-weight:600;">{sign}{v:.1f}%</span>'

    re_html = ""
    if property_metro:
        re_title = t.get("re_section_title", "Vancouver Real Estate Snapshot")
        re_note  = t.get("re_data_note", "Source: GVR & FVREB monthly stats. MLS® HPI.")
        lbl_comp = t.get("re_composite", "Composite Benchmark")
        lbl_det  = t.get("re_detached", "Detached")
        lbl_att  = t.get("re_attached", "Attached")
        lbl_apt  = t.get("re_apartment", "Apartment")
        lbl_yoy  = t.get("re_yoy", "YoY")
        lbl_sales= t.get("re_sales", "Sales")
        lbl_avg  = t.get("re_vs_avg", "vs 10yr avg")
        lbl_gain = t.get("re_top_gainer", "Top Gainer")
        lbl_lose = t.get("re_top_loser", "Top Loser")

        comp_price = property_metro.get("composite_benchmark")
        comp_yoy   = property_metro.get("composite_benchmark_yoy_pct")
        total_sales= property_metro.get("total_sales")
        vs_10yr    = property_metro.get("total_sales_vs_10yr_pct")

        def _price(v):
            return f"${v:,.0f}" if v else "—"

        def _row(label, d):
            b = d.get("benchmark"); y = d.get("benchmark_yoy_pct")
            return f"""<tr>
              <td style="padding:6px 10px;font-size:14px;color:#555;">{_escape(label)}</td>
              <td style="padding:6px 10px;font-size:14px;font-weight:600;">{_price(b)}</td>
              <td style="padding:6px 10px;font-size:14px;">{_pct_str(y)}</td>
            </tr>"""

        price_rows = ""
        if comp_price:
            price_rows += f"""<tr style="background:#f6f6f6;">
              <td style="padding:6px 10px;font-size:14px;font-weight:700;">{_escape(lbl_comp)}</td>
              <td style="padding:6px 10px;font-size:14px;font-weight:700;">{_price(comp_price)}</td>
              <td style="padding:6px 10px;font-size:14px;">{_pct_str(comp_yoy)}</td>
            </tr>"""
        for lbl, key in [(lbl_det, "detached"), (lbl_att, "attached"), (lbl_apt, "apartment")]:
            d = property_metro.get(key) or {}
            if d.get("benchmark"):
                price_rows += _row(lbl, d)

        sales_line = ""
        if total_sales:
            vs = f" ({_pct_str(vs_10yr)} {_escape(lbl_avg)})" if vs_10yr is not None else ""
            sales_line = f'<p style="margin:8px 0 4px 0;font-size:13px;color:#555;">{_escape(lbl_sales)}: <strong>{total_sales:,}</strong>{vs}</p>'

        # Top gainer / loser from hpi_by_area
        gainer_line = loser_line = ""
        if hpi_by_area:
            valid = [r for r in hpi_by_area if r.get("yoy") is not None]
            if valid:
                top_g = max(valid, key=lambda r: r["yoy"])
                top_l = min(valid, key=lambda r: r["yoy"])
                type_zh = {"Detached": lbl_det, "Townhouse": lbl_att, "Apartment": lbl_apt}
                g_type = type_zh.get(top_g["type"], top_g["type"])
                l_type = type_zh.get(top_l["type"], top_l["type"])
                gainer_line = (f'<p style="margin:4px 0;font-size:13px;color:#555;">'
                               f'📈 {_escape(lbl_gain)}: <strong>{_escape(top_g["area"])}</strong> '
                               f'{_escape(g_type)} {_pct_str(top_g["yoy"])}</p>')
                loser_line  = (f'<p style="margin:4px 0;font-size:13px;color:#555;">'
                               f'📉 {_escape(lbl_lose)}: <strong>{_escape(top_l["area"])}</strong> '
                               f'{_escape(l_type)} {_pct_str(top_l["yoy"])}</p>')

        re_html = f"""
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <h2 style="margin:0 0 4px 0;font-size:17px;">🏠 {_escape(re_title)}</h2>
    <p style="margin:0 0 12px 0;font-size:12px;color:#aaa;">{_escape(re_note)}</p>
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
      <tbody>{price_rows}</tbody>
    </table>
    {sales_line}{gainer_line}{loser_line}"""
    else:
        no_data = t.get("re_no_data", "Real estate data not available this week.")
        re_html = f'<p style="margin:16px 0 0 0;font-size:13px;color:#aaa;">{_escape(no_data)}</p>'

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
    {re_html}
    <p style="margin:24px 0 16px 0;"><a href="{site_url_esc}" style="display:inline-block; padding:10px 20px; background:#0066cc; color:#fff; text-decoration:none; border-radius:6px; font-size:15px;">{visit_btn}</a></p>
    <p style="margin:0; font-size:12px; color:#999;">{footer}</p>
  </div>
</body>
</html>"""


# ── 房产数据爬取 ──────────────────────────────────────────────────────────────

def _current_month_year() -> tuple[str, str]:
    """返回 (month_slug, year)，例如 ('march', '2025')。"""
    now = datetime.utcnow()
    return now.strftime("%B").lower(), now.strftime("%Y")


def scrape_property_metro() -> dict:
    """用 Firecrawl 抓取 GVR 月报，优先当月，若抓取为空则退到上月。"""
    from datetime import timedelta
    now = datetime.utcnow()
    # 尝试当月和上月（月报通常月中发布，月初可能还没有）
    candidates = []
    for delta in (0, -1, -2):
        d = now.replace(day=1) + timedelta(days=delta * 31)
        # timedelta 可能跨年，用 replace 安全取月份
        d = (now.replace(day=1) - timedelta(days=max(delta * 28, 1) if delta < 0 else 0))
        month = d.strftime("%B").lower()
        year = d.strftime("%Y")
        candidates.append((month, year))
    # 去重保持顺序
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)

    for month, year in unique_candidates:
        url = PROPERTY_METRO_URL_TEMPLATE.format(month=month, year=year)
        print(f"正在抓取房产月报: {url}")
        try:
            md = scrape_url(url)
        except Exception as e:
            print(f"  抓取失败: {e}")
            continue
        if not md or len(md) < 200:
            print(f"  内容为空，尝试上月…")
            continue
        result = parse_property_metro(md, url)
        # 检查是否解析到有效数据
        if any(result.get(k) for k in ("detached", "attached", "apartment")):
            return result
        print(f"  未解析到有效数据，尝试上月…")
    print("  所有候选月份均无数据")
    return {}


def parse_property_metro(md: str, source_url: str) -> dict:
    """从 GVR 月报 markdown 中提取 Metro 级数据（三种房型 + 汇总）。"""
    result = {
        "source_url": source_url,
        "updated_at": "",
        "detached": {},
        "attached": {},
        "apartment": {},
        "total_active": None,
        "new_listings": None,
    }

    # 更新时间：从 URL 中推断
    m = re.search(r"/([a-z]+)-(\d{4})\.html", source_url)
    if m:
        result["updated_at"] = f"{m.group(1).capitalize()} {m.group(2)}"

    # 提取销量：如 "527 sales" / "527 detached sales"
    sales_matches = re.findall(r"(\d[\d,]*)\s+(?:detached\s+)?sales", md, re.I)
    # 提取 benchmark price
    benchmark_matches = re.findall(r"\$([0-9,]+)(?:\s+benchmark|\s+(?:composite\s+)?benchmark\s+price)?", md, re.I)
    # 提取 days on market
    dom_matches = re.findall(r"(\d+)\s+days?\s+(?:on\s+(?:the\s+)?market|average)", md, re.I)
    # 提取 sales-to-active ratio
    sar_matches = re.findall(r"(\d+\.?\d*)\s*%\s*(?:sales.to.active|sales.active)", md, re.I)

    # 更精确的分类型解析：找 detached/attached/apartment 区块
    type_map = {
        "detached": "detached",
        "attached": "attached",
        "townhouse": "attached",
        "apartment": "apartment",
        "condo": "apartment",
    }

    # 按行扫描，找各类型数据
    lines = md.splitlines()
    for i, line in enumerate(lines):
        line_lower = line.lower()
        for kw, prop_key in type_map.items():
            if kw in line_lower:
                # 在此行及后5行内找数字
                context = " ".join(lines[max(0, i-1):i+6])
                sales_m = re.search(r"(\d[\d,]*)\s+sales", context, re.I)
                bench_m = re.search(r"\$([0-9,]+)", context, re.I)
                dom_m = re.search(r"(\d+)\s+days", context, re.I)
                sar_m = re.search(r"(\d+\.?\d*)\s*%", context, re.I)
                if sales_m and prop_key not in result or not result[prop_key]:
                    entry = {}
                    if sales_m:
                        entry["sales"] = int(sales_m.group(1).replace(",", ""))
                    if bench_m:
                        entry["benchmark"] = int(bench_m.group(1).replace(",", ""))
                    if dom_m:
                        entry["dom"] = int(dom_m.group(1))
                    if sar_m:
                        entry["sar"] = sar_m.group(1) + "%"
                    if entry and not result[prop_key]:
                        result[prop_key] = entry

    # 提取 total active listings 和 new listings
    active_m = re.search(r"(\d[\d,]+)\s+(?:total\s+)?active\s+listings?", md, re.I)
    new_m = re.search(r"(\d[\d,]+)\s+new\s+listings?", md, re.I)
    if active_m:
        result["total_active"] = int(active_m.group(1).replace(",", ""))
    if new_m:
        result["new_listings"] = int(new_m.group(1).replace(",", ""))

    print(f"  房产月报解析完成: {result.get('updated_at')}, "
          f"detached={result['detached'].get('sales')}, "
          f"attached={result['attached'].get('sales')}, "
          f"apartment={result['apartment'].get('sales')}")
    return result


def scrape_property_areas() -> list[dict]:
    """用 Playwright 抓取 GVR 各区域 × 房型的上市/成交数据。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright 未安装，跳过区域数据 (pip install playwright && playwright install chromium)")
        return []

    results = []
    print(f"正在用 Playwright 抓取各区域房产数据 ({len(PROPERTY_AREAS)} 区 × {len(PROPERTY_TYPES)} 类型)…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(PROPERTY_AREAS_URL, wait_until="networkidle", timeout=30000)

        # 找到表单内的提交按钮（排除 navbar toggle）
        # GVR 页面用 input[type=submit] 或含 "View" 文字的按钮
        submit_selector = "input[type=submit], button[type=submit], button:has-text('View')"

        for area in PROPERTY_AREAS:
            for prop_type in PROPERTY_TYPES:
                try:
                    # 选择区域（第一个 select）
                    area_sel = page.locator("form select, #area, select[name*='area'], select").first
                    area_sel.select_option(label=area)
                    page.wait_for_timeout(500)

                    # 选择房型（最后一个 select，通常是第3个）
                    selects = page.locator("form select, select")
                    count = selects.count()
                    type_sel = selects.nth(count - 1) if count >= 3 else selects.last
                    type_sel.select_option(label=prop_type)
                    page.wait_for_timeout(500)

                    # 点击提交按钮（排除 navbar）
                    btn = page.locator(submit_selector).first
                    btn.click(timeout=15000)
                    page.wait_for_load_state("networkidle", timeout=15000)

                    # 提取表格第一行（最新月份）
                    rows = page.locator("table tbody tr")
                    if rows.count() > 0:
                        cells = rows.first.locator("td")
                        cell_texts = [cells.nth(j).inner_text().strip() for j in range(cells.count())]
                        # 预期列：月份, 上市, 成交, 销售比
                        listed = sold = ratio = None
                        if len(cell_texts) >= 4:
                            try:
                                listed = int(cell_texts[1].replace(",", ""))
                                sold = int(cell_texts[2].replace(",", ""))
                                ratio = cell_texts[3]
                            except (ValueError, IndexError):
                                pass
                        results.append({
                            "area": area,
                            "type": prop_type,
                            "listed": listed,
                            "sold": sold,
                            "ratio": ratio,
                        })
                        print(f"  {area} / {prop_type}: listed={listed}, sold={sold}, ratio={ratio}")
                except Exception as e:
                    print(f"  {area} / {prop_type} 失败: {e}")
                    results.append({"area": area, "type": prop_type, "listed": None, "sold": None, "ratio": None})

        browser.close()

    print(f"区域数据抓取完成，共 {len(results)} 条")
    return results


def _fmt_yoy(pct):
    """格式化 YoY 变化：正数绿色↑，负数橙红↓。"""
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    color = "#4ade80" if pct >= 0 else "#f97316"
    arrow = "↑" if pct >= 0 else "↓"
    return f'<span style="color:{color};font-size:0.85rem;font-weight:600;">{arrow} {sign}{pct:.1f}% YoY</span>'


def _sar_label(sar_str):
    """根据 sales-to-active ratio 判断市场状态。
    < 12%: 买方市场；12-20%: 均衡；> 20%: 卖方市场。"""
    if not sar_str:
        return ""
    try:
        v = float(sar_str.replace("%", ""))
    except ValueError:
        return ""
    if v < 12:
        return '<span class="re-market-tag re-buyer" data-i18n="re_market_buyers">Buyer\'s</span>'
    elif v > 20:
        return '<span class="re-market-tag re-seller" data-i18n="re_market_sellers">Seller\'s</span>'
    else:
        return '<span class="re-market-tag re-balanced" data-i18n="re_market_balanced">Balanced</span>'


def scrape_property_hpi_pdf() -> list[dict]:
    """下载 GVR Stats Package PDF，用 pdfminer 提取文字，解析各区域×房型 HPI 数据。
    返回 list[dict]，每项含 area, type, benchmark, mom, 3m, 6m, yoy, 3yr, 5yr。
    """
    from datetime import timedelta
    now = datetime.utcnow()

    # 尝试当月和上两个月
    candidates = []
    for delta in [0, -1, -2]:
        if delta == 0:
            d = now
        else:
            d = (now.replace(day=1) + timedelta(days=delta * 30)).replace(day=1)
        candidates.append((d.strftime("%B").lower(), d.strftime("%Y")))
    seen = set()
    unique_candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    pdf_bytes = None
    for month, year in unique_candidates:
        pdf_url = f"https://members.gvrealtors.ca/news/GVR-Stats-Package-{month.capitalize()}-{year}.pdf"
        print(f"正在下载 HPI PDF: {pdf_url}")
        try:
            import urllib.request
            req = urllib.request.Request(pdf_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            if len(pdf_bytes) < 50000:
                print(f"  PDF 太小({len(pdf_bytes)} bytes)，跳过")
                pdf_bytes = None
                continue
            print(f"  下载成功: {len(pdf_bytes)} bytes")
            break
        except Exception as e:
            print(f"  下载失败: {e}")
            continue

    if not pdf_bytes:
        print("  所有候选月份 PDF 均无法获取")
        return []

    # 提取文字
    try:
        import io
        from pdfminer.high_level import extract_text
        text = extract_text(io.BytesIO(pdf_bytes))
    except ImportError:
        print("  pdfminer.six 未安装，跳过 HPI PDF 解析")
        return []
    except Exception as e:
        print(f"  PDF 解析失败: {e}")
        return []

    return _parse_hpi_pdf_text(text)


def _parse_hpi_pdf_text(text: str) -> list[dict]:
    """从 PDF 提取的文字中解析 HPI 表格。
    GVR Stats Package 格式：区域名列表先出现，然后是对应的数字列（benchmark, index, 7列%）。
    每个 section 以 'Single Family Detached', 'Townhouse', 'Apartment' 开头。
    """
    KNOWN_AREAS = [
        "Lower Mainland", "Greater Vancouver", "Bowen Island",
        "Burnaby East", "Burnaby North", "Burnaby South",
        "Coquitlam", "Ladner", "Maple Ridge", "New Westminster",
        "North Vancouver", "Pitt Meadows", "Port Coquitlam", "Port Moody",
        "Richmond", "Squamish", "Sunshine Coast", "Tsawwassen",
        "Vancouver East", "Vancouver West", "West Vancouver", "Whistler",
    ]
    # GVR PDF 区域出现顺序（不含 Lower Mainland/Greater Vancouver）
    TARGET_AREAS = [a for a in KNOWN_AREAS if a not in ("Lower Mainland", "Greater Vancouver")]

    TYPE_MAP = {
        "Single Family Detached": "Detached",
        "Townhouse": "Townhouse",
        "Apartment": "Apartment",
    }

    results = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    i = 0
    current_type = None
    while i < len(lines):
        line = lines[i]
        # Detect section header
        for header, prop_type in TYPE_MAP.items():
            if header in line and ("Lower Mainland" in line or "Greater Vancouver" in line or i + 1 < len(lines) and "Lower Mainland" in lines[i+1]):
                current_type = prop_type
                break
        # Detect area name
        if current_type and line in KNOWN_AREAS and line not in ("Lower Mainland", "Greater Vancouver"):
            area = line
            # Look ahead for benchmark price ($X,XXX,XXX) within next 15 lines
            benchmark = None
            pcts = []
            j = i + 1
            while j < min(i + 20, len(lines)):
                l2 = lines[j]
                # Benchmark price
                m = re.match(r'^\$([0-9,]+)$', l2)
                if m and benchmark is None:
                    benchmark = int(m.group(1).replace(",", ""))
                # Percentage
                pm = re.match(r'^([+-]?\d+\.?\d*)\s*%$', l2)
                if pm:
                    pcts.append(float(pm.group(1)))
                # Stop at next area name or next section header
                if l2 in KNOWN_AREAS or any(h in l2 for h in TYPE_MAP):
                    break
                j += 1
            # pcts order: mom(1m), 3m, 6m, yoy(1yr), 3yr, 5yr, 10yr
            if benchmark and len(pcts) >= 4:
                results.append({
                    "area": area,
                    "type": current_type,
                    "benchmark": benchmark,
                    "mom": pcts[0] if len(pcts) > 0 else None,
                    "3m": pcts[1] if len(pcts) > 1 else None,
                    "6m": pcts[2] if len(pcts) > 2 else None,
                    "yoy": pcts[3] if len(pcts) > 3 else None,
                    "3yr": pcts[4] if len(pcts) > 4 else None,
                    "5yr": pcts[5] if len(pcts) > 5 else None,
                })
        i += 1

    print(f"  HPI PDF 解析完成，共 {len(results)} 条区域数据")
    return results


def build_property_html(metro: dict, areas: list[dict], hpi_by_area: list[dict] = None) -> str:
    """生成房产 Tab 的 HTML 内容（插入 tab panel 中）。"""
    def _fmt_price(val):
        if val is None:
            return "N/A"
        return f"${val:,.0f}"

    def _fmt_num(val):
        return f"{val:,}" if isinstance(val, int) else (str(val) if val is not None else "N/A")

    det = metro.get("detached") or {}
    att = metro.get("attached") or {}
    apt = metro.get("apartment") or {}
    updated = metro.get("updated_at", "")
    source_url = metro.get("source_url", PROPERTY_METRO_URL_TEMPLATE)

    total_sales = metro.get("total_sales")
    total_sales_yoy = metro.get("total_sales_yoy_pct")
    total_sales_10yr = metro.get("total_sales_10yr_avg")
    total_vs_10yr = metro.get("total_sales_vs_10yr_pct")
    composite_price = metro.get("composite_benchmark")
    composite_yoy = metro.get("composite_benchmark_yoy_pct")
    total_active = metro.get("total_active")
    total_active_yoy = metro.get("total_active_yoy_pct")
    new_listings = metro.get("new_listings")
    new_listings_yoy = metro.get("new_listings_yoy_pct")
    total_sar = metro.get("total_sar", "")

    # ── Market Intelligence: opportunity signals ──
    def _build_opp_html():
        cards = []

        # Signal 1: Buyer's market (any property type with SAR < 12%)
        buyer_types = []
        for key, d in [("detached", det), ("attached", att), ("apartment", apt)]:
            try:
                v = float((d.get("sar") or "").replace("%", ""))
                if v < 12:
                    label = {"detached": "Detached", "attached": "Attached", "apartment": "Apartment"}[key]
                    buyer_types.append(f'{label} ({d["sar"]})')
            except ValueError:
                pass
        if buyer_types:
            cards.append(
                f'<div class="re-opp-card re-opp-buyers">'
                f'<div class="re-opp-icon">🔵</div>'
                f'<div class="re-opp-label" data-i18n="re_opp_buyers_label">Buyer\'s Advantage</div>'
                f'<div class="re-opp-finding">{_escape(", ".join(buyer_types))}</div>'
                f'<div class="re-opp-desc"><span data-i18n="re_opp_buyers_desc">SAR below 12% — more negotiating power for buyers</span></div>'
                f'</div>'
            )

        # Signal 2: Most resilient area (highest YoY vs metro avg)
        if hpi_by_area:
            best = max((r for r in hpi_by_area if r.get("yoy") is not None), key=lambda r: r["yoy"], default=None)
            if best:
                metro_avg = composite_yoy if composite_yoy is not None else -6.8
                vs = best["yoy"] - metro_avg
                yoy_sign = "+" if best["yoy"] >= 0 else ""
                vs_sign = "+" if vs >= 0 else ""
                cards.append(
                    f'<div class="re-opp-card re-opp-value">'
                    f'<div class="re-opp-icon">🟢</div>'
                    f'<div class="re-opp-label" data-i18n="re_opp_value_label">Resilient Area</div>'
                    f'<div class="re-opp-finding">{_escape(best["area"])} · {_escape(best["type"])}</div>'
                    f'<div class="re-opp-desc">'
                    f'{yoy_sign}{best["yoy"]:.1f}% YoY &nbsp;({vs_sign}{vs:.1f}% <span data-i18n="re_opp_vs_metro">vs metro avg</span>)'
                    f'</div>'
                    f'</div>'
                )

        # Signal 3: Momentum reversal (MoM > 0 while YoY still negative)
        if hpi_by_area:
            reversals = [r for r in hpi_by_area if (r.get("mom") or 0) > 0 and (r.get("yoy") or 0) < -2]
            if reversals:
                top = max(reversals, key=lambda r: r["mom"])
                cards.append(
                    f'<div class="re-opp-card re-opp-momentum">'
                    f'<div class="re-opp-icon">📈</div>'
                    f'<div class="re-opp-label" data-i18n="re_opp_momentum_label">Recovery Signal</div>'
                    f'<div class="re-opp-finding">{_escape(top["area"])} · {_escape(top["type"])}</div>'
                    f'<div class="re-opp-desc">'
                    f'+{top["mom"]:.1f}% MoM — <span data-i18n="re_opp_momentum_desc">recent uptick despite</span> {top["yoy"]:.1f}% YoY'
                    f'</div>'
                    f'</div>'
                )

        # Signal 4: Value play (deep YoY dip but strong 5yr fundamentals)
        if hpi_by_area:
            value_plays = [r for r in hpi_by_area if r.get("yoy") is not None and (r.get("5yr") or 0) > 10]
            if value_plays:
                top = min(value_plays, key=lambda r: r["yoy"])
                cards.append(
                    f'<div class="re-opp-card re-opp-correction">'
                    f'<div class="re-opp-icon">📉</div>'
                    f'<div class="re-opp-label" data-i18n="re_opp_correction_label">Value Play</div>'
                    f'<div class="re-opp-finding">{_escape(top["area"])} · {_escape(top["type"])}</div>'
                    f'<div class="re-opp-desc">'
                    f'{top["yoy"]:.1f}% YoY, <span data-i18n="re_opp_correction_but">but</span> +{top["5yr"]:.1f}% <span data-i18n="re_opp_correction_5yr">over 5 yrs — discounted with strong track record</span>'
                    f'</div>'
                    f'</div>'
                )

        if not cards:
            return ""
        return (
            f'<h3 style="font-size:1rem;font-weight:600;margin:1.5rem 0 0.5rem;" data-i18n="re_opp_title">💡 Market Intelligence</h3>'
            f'<div class="re-opp-grid">{"".join(cards)}</div>'
        )

    opp_html = _build_opp_html()

    # ── 4-card snapshot grid (overview + 3 property types) ──
    def _pct_inline(val, size="0.82rem"):
        if val is None:
            return ""
        sign = "+" if val >= 0 else ""
        color = "#4ade80" if val >= 0 else "#f97316"
        return f'<span style="color:{color};font-weight:600;font-size:{size};">{sign}{val:.1f}%</span>'

    def _stat_row(label_i18n, label_en, value_html):
        return (
            f'<div class="re-snap-row">'
            f'<span class="re-snap-label" data-i18n="{label_i18n}">{label_en}</span>'
            f'<span class="re-snap-val">{value_html}</span>'
            f'</div>'
        )

    # Card 1: Greater Vancouver overall
    overview_rows = []
    if total_sales and total_sales_10yr:
        diff_pct = total_vs_10yr or round((total_sales / total_sales_10yr - 1) * 100, 1)
        overview_rows.append(_stat_row(
            "re_insight_sales", "Sales",
            f'<strong>{_fmt_num(total_sales)}</strong> {_pct_inline(diff_pct)}'
        ))
    if composite_yoy is not None:
        overview_rows.append(_stat_row(
            "re_insight_composite", "Composite",
            f'<strong>{_fmt_price(composite_price)}</strong> {_pct_inline(composite_yoy)}'
        ))
    if total_sar:
        overview_rows.append(_stat_row(
            "re_insight_sar", "Sales ratio",
            f'<strong>{total_sar}</strong> {_sar_label(total_sar)}'
        ))
    if total_active is not None:
        overview_rows.append(_stat_row(
            "re_total_active", "Active:",
            f'<strong>{_fmt_num(total_active)}</strong> {_pct_inline(total_active_yoy)}'
        ))
    if new_listings is not None:
        overview_rows.append(_stat_row(
            "re_new_listings", "New listings:",
            f'<strong>{_fmt_num(new_listings)}</strong> {_pct_inline(new_listings_yoy)}'
        ))
    overview_card = (
        f'<div class="re-snap-card re-snap-overview">'
        f'<div class="re-snap-title" data-i18n="re_snapshot_title">📊 Market Snapshot</div>'
        f'{"".join(overview_rows)}'
        f'</div>'
    )

    # Cards 2–4: Detached / Attached / Apartment
    def _type_card(icon, i18n_key, label_en, type_data):
        sales    = type_data.get("sales")
        benchmark= type_data.get("benchmark")
        yoy      = type_data.get("benchmark_yoy_pct")
        dom      = type_data.get("dom")
        sar      = type_data.get("sar", "")
        return (
            f'<div class="re-snap-card">'
            f'<div class="re-snap-icon">{icon}</div>'
            f'<div class="re-snap-type" data-i18n="{i18n_key}">{label_en}</div>'
            f'<div class="re-snap-price">{_fmt_price(benchmark)}</div>'
            f'<div class="re-snap-yoy">{_fmt_yoy(yoy)}</div>'
            f'<div class="re-snap-meta">'
            f'<strong>{_fmt_num(sales)}</strong> <span data-i18n="re_sold">sold</span>'
            f' · {_fmt_num(dom) if dom else "N/A"} <span data-i18n="re_days">days</span>'
            f'</div>'
            f'<div class="re-snap-sar">{sar or "N/A"} {_sar_label(sar)}</div>'
            f'</div>'
        )

    snapshot_html = (
        f'<div class="re-snap-grid">'
        f'{overview_card}'
        f'{_type_card("🏡", "re_detached", "Detached", det)}'
        f'{_type_card("🏘", "re_attached", "Attached", att)}'
        f'{_type_card("🏢", "re_apartment", "Apartment", apt)}'
        f'</div>'
    )

    insight_html = ""
    cards_html = ""
    inventory_html = ""

    # ── Unified area cards (replaces separate leaderboard + by-area sections) ──
    from collections import defaultdict
    hpi_area_map = defaultdict(dict)
    for row in (hpi_by_area or []):
        hpi_area_map[row["area"]][row["type"]] = row


    unified_html = ""
    if hpi_by_area:
        # Geographic groupings (i18n key → ordered area list)
        AREA_GROUPS = {
            "re_group_gvr":   ["Vancouver West", "Vancouver East", "Burnaby East", "Burnaby North", "Burnaby South",
                               "Richmond", "New Westminster", "Coquitlam", "Port Coquitlam", "Port Moody"],
            "re_group_north": ["North Vancouver", "West Vancouver", "Maple Ridge", "Pitt Meadows",
                               "Ladner", "Tsawwassen"],
            "re_group_fv":    ["Surrey", "North Surrey", "South Surrey / White Rock", "Cloverdale",
                               "Langley", "North Delta", "Abbotsford", "Mission"],
            "re_group_coast": ["Squamish", "Sunshine Coast", "Whistler"],
        }
        area_to_group = {n: grp for grp, names in AREA_GROUPS.items() for n in names}

        type_icons_d  = {"Detached": "🏡", "Townhouse": "🏘", "Apartment": "🏢"}
        type_i18n_d   = {"Detached": "re_detached_short", "Townhouse": "re_attached_short", "Apartment": "re_apartment_short"}
        type_en_d     = {"Detached": "Detached", "Townhouse": "Attached", "Apartment": "Apartment"}
        type_filter_d = {"detached": "Detached", "townhouse": "Townhouse", "apartment": "Apartment"}

        # Metro-level SAR tag per type (shown on every card when a single type is selected)
        def _metro_sar_tag(sar_str):
            if not sar_str:
                return ""
            try:
                v = float(str(sar_str).replace("%", ""))
            except ValueError:
                return ""
            if v < 12:
                return f'<span class="re-market-tag re-buyer" data-i18n="re_market_buyers">Buyer\'s</span> <span style="color:var(--text-muted);font-size:0.75em;">({sar_str})</span>'
            elif v > 20:
                return f'<span class="re-market-tag re-seller" data-i18n="re_market_sellers">Seller\'s</span> <span style="color:var(--text-muted);font-size:0.75em;">({sar_str})</span>'
            else:
                return f'<span class="re-market-tag re-balanced" data-i18n="re_market_balanced">Balanced</span> <span style="color:var(--text-muted);font-size:0.75em;">({sar_str})</span>'

        metro_type_sar_tag = {
            "detached":  _metro_sar_tag(det.get("sar", "")),
            "townhouse": _metro_sar_tag(att.get("sar", "")),
            "apartment": _metro_sar_tag(apt.get("sar", "")),
        }

        def _pct_span(val):
            if val is None:
                return '<span style="color:var(--text-muted)">—</span>'
            sign = "+" if val >= 0 else ""
            color = "#4ade80" if val >= 0 else "#f97316"
            return f'<span style="color:{color};font-weight:600;">{sign}{val:.1f}%</span>'

        def _area_card(area, sort_key, type_filter):
            """Build one area card for given sort_key and type_filter (all/detached/townhouse/apartment)."""
            area_types = hpi_area_map.get(area, {})
            if not area_types:
                return ""

            if type_filter == "all":
                # Show all 3 types as sub-rows, sorted by sort_key
                sub_rows = []
                for pt in ["Detached", "Townhouse", "Apartment"]:
                    hpi = area_types.get(pt)
                    if not hpi:
                        continue
                    icon = type_icons_d[pt]
                    i18n_key = type_i18n_d[pt]
                    label = type_en_d[pt]
                    val = hpi.get(sort_key)
                    sub_rows.append(f"""<div class="re-area-card-subrow">
              <span class="re-area-card-subrow-type">{icon} <span data-i18n="{i18n_key}">{label}</span></span>
              <span class="re-area-card-subrow-price">{_fmt_price(hpi.get("benchmark"))}</span>
              <span class="re-area-card-subrow-pct">{_pct_span(val)}</span>
            </div>""")
                if not sub_rows:
                    return ""
                # Rank by average across all available types (more representative than max)
                vals = [area_types.get(pt, {}).get(sort_key) for pt in ["Detached", "Townhouse", "Apartment"]
                        if area_types.get(pt, {}).get(sort_key) is not None]
                best_val = sum(vals) / len(vals) if vals else -999
                subtypes_html = f'<div class="re-area-card-subtypes">{"".join(sub_rows)}</div>'
                return (best_val, f"""<div class="re-area-card">
          <div class="re-area-card-name">{_escape(area)}</div>
          {subtypes_html}
        </div>""")
            else:
                pt = type_filter_d.get(type_filter)
                hpi = area_types.get(pt) if pt else None
                if not hpi:
                    return None
                val = hpi.get(sort_key)
                metric_key_map = {"yoy": "re_lb_yoy", "mom": "re_lb_mom", "3yr": "re_lb_3yr"}
                metric_label_key = metric_key_map.get(sort_key, sort_key)
                metric_en = {"yoy": "YoY", "mom": "MoM", "3yr": "3yr"}.get(sort_key, sort_key)
                return (val if val is not None else -999, f"""<div class="re-area-card">
          <div class="re-area-card-name">{_escape(area)}</div>
          <div class="re-area-card-price">{_fmt_price(hpi.get("benchmark"))}</div>
          <div class="re-area-card-metric">
            <span class="re-area-card-metric-label" data-i18n="{metric_label_key}">{metric_en}</span>
            {_pct_span(val)}
          </div>
        </div>""")

        def _build_groups_html(sort_key, type_filter, reverse=True):
            """Build the full grouped cards HTML for one (sort_key, type_filter, reverse) combo."""
            all_areas_in_data = set(hpi_area_map.keys())
            sentinel = -999 if reverse else 999
            groups_html = ""
            for grp, names in AREA_GROUPS.items():
                grp_areas = [a for a in names if a in all_areas_in_data]
                if not grp_areas:
                    continue
                cards = []
                for area in grp_areas:
                    result = _area_card(area, sort_key, type_filter)
                    if result:
                        cards.append(result)
                cards.sort(key=lambda x: x[0] if x[0] is not None else sentinel, reverse=reverse)
                if not cards:
                    continue
                cards_html_inner = "".join(
                    c[1].replace('<div class="re-area-card">', f'<div class="re-area-card"><span class="re-area-card-rank">#{i+1}</span>', 1)
                    for i, c in enumerate(cards)
                )
                groups_html += f"""<div class="re-area-group-section">
      <div class="re-area-group-title" data-i18n="{grp}">—</div>
      <div class="re-area-cards-grid">{cards_html_inner}</div>
    </div>"""
            # Ungrouped
            ungrouped = [a for a in sorted(all_areas_in_data) if a not in area_to_group]
            if ungrouped:
                cards = []
                for area in ungrouped:
                    result = _area_card(area, sort_key, type_filter)
                    if result:
                        cards.append(result)
                cards.sort(key=lambda x: x[0] if x[0] is not None else sentinel, reverse=reverse)
                if cards:
                    cards_html_inner = "".join(
                        c[1].replace('<div class="re-area-card">', f'<div class="re-area-card"><span class="re-area-card-rank">#{i+1}</span>', 1)
                        for i, c in enumerate(cards)
                    )
                    groups_html += f"""<div class="re-area-group-section">
      <div class="re-area-group-title" data-i18n="re_group_other">Other</div>
      <div class="re-area-cards-grid">{cards_html_inner}</div>
    </div>"""
            return groups_html

        # Pre-build 3 × 4 × 2 = 24 combinations (period × type × order)
        hpi_data = {}
        for sk in ["yoy", "mom", "3yr"]:
            hpi_data[sk] = {}
            for tf in ["all", "detached", "townhouse", "apartment"]:
                hpi_data[sk][tf] = {
                    "desc": _build_groups_html(sk, tf, reverse=True),
                    "asc":  _build_groups_html(sk, tf, reverse=False),
                }

        hpi_data_js = json.dumps(hpi_data)

        # Per-type SAR from metro data → JS map for the market condition banner
        def _sar_condition_key(sar_str):
            if not sar_str:
                return None
            try:
                v = float(str(sar_str).replace("%", ""))
            except ValueError:
                return None
            if v < 12:
                return "buyers"
            elif v > 20:
                return "sellers"
            else:
                return "balanced"

        type_sar_map = {
            "detached":  _sar_condition_key(det.get("sar", "")),
            "townhouse": _sar_condition_key(att.get("sar", "")),
            "apartment": _sar_condition_key(apt.get("sar", "")),
        }
        # Build JS object: { detached: {condition:"buyers",sar:"11%",tagKey:"re_market_buyers"}, ... }
        sar_tag_key = {"buyers": "re_market_buyers", "sellers": "re_market_sellers", "balanced": "re_market_balanced"}
        sar_js_entries = {}
        for tf, cond in type_sar_map.items():
            sar_val = {"detached": det.get("sar"), "townhouse": att.get("sar"), "apartment": apt.get("sar")}[tf]
            if cond:
                sar_js_entries[tf] = {"condition": cond, "sar": str(sar_val or ""), "tagKey": sar_tag_key[cond]}
        sar_js = json.dumps(sar_js_entries)

        unified_html = f"""
  <div class="re-unified-controls">
    <div class="re-lb-period-nav">
      <button class="re-lb-period re-uc-period active" data-period="yoy" data-i18n="re_lb_yoy_btn">Annual</button>
      <button class="re-lb-period re-uc-period" data-period="mom" data-i18n="re_lb_mom_btn">Monthly</button>
      <button class="re-lb-period re-uc-period" data-period="3yr" data-i18n="re_lb_3yr_btn">3-Year</button>
    </div>
    <div class="re-lb-filter">
      <button class="re-lb-btn re-uc-type active" data-uctype="all" data-i18n="re_all_types">All types</button>
      <button class="re-lb-btn re-uc-type" data-uctype="detached" data-i18n="re_detached_short">Detached</button>
      <button class="re-lb-btn re-uc-type" data-uctype="townhouse" data-i18n="re_attached_short">Attached</button>
      <button class="re-lb-btn re-uc-type" data-uctype="apartment" data-i18n="re_apartment_short">Apartment</button>
    </div>
  </div>
  <p class="meta" id="re-uc-desc" style="margin-bottom:0.5rem;">
    <span data-i18n="re_uc_desc_yoy">Annual price change</span>
    <span data-i18n="re_uc_desc_sep">·</span>
    <span data-i18n="re_uc_desc_all">all types</span>
  </p>
  <div class="re-area-cards-container" id="re-area-cards-container">
    {hpi_data["yoy"]["all"]["desc"]}
  </div>
  <script>
  (function(){{
    var hpiData={hpi_data_js};
    var curPeriod='yoy', curType='all';
    function _t(key){{var t=window.i18n&&window.i18n[document.documentElement.lang||'en'];return(t&&t[key])||key;}}
    function updateDesc(){{
      var periodKey={{'yoy':'re_uc_desc_yoy','mom':'re_uc_desc_mom','3yr':'re_uc_desc_3yr'}}[curPeriod]||'re_uc_desc_yoy';
      var typeKey={{'all':'re_uc_desc_all','detached':'re_detached_short','townhouse':'re_attached_short','apartment':'re_apartment_short'}}[curType]||'re_uc_desc_all';
      var sep=_t('re_uc_desc_sep');
      var desc=document.getElementById('re-uc-desc');
      if(desc) desc.innerHTML=
        '<span data-i18n="'+periodKey+'">'+_t(periodKey)+'</span>'
        +' <span data-i18n="re_uc_desc_sep">'+sep+'</span>'
        +' <span data-i18n="'+typeKey+'">'+_t(typeKey)+'</span>'
        +(curType==='all'?' <span style="color:var(--text-muted);font-size:0.85em;">· '+_t('re_sort_rank_note')+'</span>':'');
    }}
    function refresh(){{
      var html=(hpiData[curPeriod]&&hpiData[curPeriod][curType]&&hpiData[curPeriod][curType]['desc'])||'';
      document.getElementById('re-area-cards-container').innerHTML=html;
      updateDesc();
      if(window.applyLang) window.applyLang(document.documentElement.lang||'en');
    }}
    document.querySelectorAll('.re-uc-period').forEach(function(btn){{
      btn.addEventListener('click',function(){{
        document.querySelectorAll('.re-uc-period').forEach(function(b){{b.classList.remove('active');}});
        this.classList.add('active'); curPeriod=this.dataset.period; refresh();
      }});
    }});
    document.querySelectorAll('.re-uc-type').forEach(function(btn){{
      btn.addEventListener('click',function(){{
        document.querySelectorAll('.re-uc-type').forEach(function(b){{b.classList.remove('active');}});
        this.classList.add('active'); curType=this.dataset.uctype; refresh();
      }});
    }});
  }})();
  </script>"""

    src_link = f'<a href="{_escape(source_url)}" target="_blank" rel="noopener" style="color:var(--accent);">Greater Vancouver REALTORS®</a>'
    return f"""
  <h2 data-i18n="re_title">🏠 Vancouver Real Estate Market</h2>
  <p class="meta"><span data-i18n="re_updated">Data from</span> {src_link} · {_escape(updated)} · MLS® HPI · <span data-i18n="meta_freq_property">Updated monthly</span></p>
  {opp_html}
  {snapshot_html}
  <h2 style="margin-top:2rem;" data-i18n="re_area_title">📍 By Area</h2>
  <p class="meta" data-i18n="re_area_desc">Click an area to see benchmark prices and changes by type.</p>
  {unified_html}"""


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
    valid_langs = {"en", "zh", "fr"}
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


def send_newsletter_emails(top3_six: list[dict], updated_at: str, site_url: str,
                           property_metro: dict = None, hpi_by_area: list[dict] = None) -> None:
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
            html_cache[lang] = build_newsletter_html(
                lang, top3_six, updated_at, site_url,
                property_metro=property_metro, hpi_by_area=hpi_by_area,
            )
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
    parser.add_argument("--rebuild-property", action="store_true", help="Rebuild index.html using saved property_data.json + top3.json, no scraping")
    args = parser.parse_args()

    if args.rebuild_property:
        # Load cached data and rebuild HTML only
        prop_path = os.path.join(os.path.dirname(__file__), "property_data.json")
        top3_path = os.path.join(os.path.dirname(__file__), "top3.json")
        with open(prop_path, encoding="utf-8") as f:
            prop_data = json.load(f)
        with open(top3_path, encoding="utf-8") as f:
            top3_data = json.load(f)
        property_metro = prop_data.get("metro", {})
        property_areas = prop_data.get("areas", [])
        property_hpi = prop_data.get("hpi_by_area", [])
        prop_html = build_property_html(property_metro, property_areas, property_hpi) if property_metro else ""
        top3 = top3_data.get("top3", [])
        gic_top = top3_data.get("gic_top", [])
        updated_at = top3_data.get("updated_at", "")
        top3_six = [r for r in top3 if _get_bank_tier(r["bank_product"]) == "六大行"][:3]
        top3_known = [r for r in top3 if _get_bank_tier(r["bank_product"]) == "知名银行/直销"][:3]
        gic_top_six = [r for r in gic_top if _get_bank_tier(r.get("bank_product", "")) == "六大行"]
        gic_top_known = [r for r in gic_top if _get_bank_tier(r.get("bank_product", "")) == "知名银行/直销"]
        html = build_html(top3, top3_six, top3_known, gic_top, gic_top_six, gic_top_known, updated_at, property_html=prop_html)
        out_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"已重建 {out_path}（从缓存数据）")
        return

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

    # 房产数据：判断缓存是否已是本月，若是则跳过重新 scrape
    prop_path = os.path.join(os.path.dirname(__file__), "property_data.json")
    now_ym = datetime.utcnow().strftime("%Y-%m")
    cached_prop = {}
    if os.path.isfile(prop_path):
        try:
            with open(prop_path, encoding="utf-8") as f:
                cached_prop = json.load(f)
        except Exception:
            cached_prop = {}
    cached_updated = (cached_prop.get("metro") or {}).get("updated_at", "")
    force_refresh = os.environ.get("FORCE_PROPERTY_REFRESH", "false").lower() == "true"
    prop_is_current = cached_updated.startswith(now_ym) and not force_refresh

    if prop_is_current:
        print(f"房产数据已是本月（{cached_updated[:7]}），跳过重新 scrape，使用缓存")
        property_metro = cached_prop.get("metro", {})
        property_areas = cached_prop.get("areas", [])
        property_hpi   = cached_prop.get("hpi_by_area", [])
    else:
        print("房产数据需要更新，开始 scrape…")
        property_metro = scrape_property_metro()
        property_areas = scrape_property_areas()
        property_hpi   = scrape_property_hpi_pdf()
        if property_metro:
            # 保护机制：如果新抓的 hpi_by_area 为空，保留旧缓存中的数据
            if not property_hpi and cached_prop.get("hpi_by_area"):
                print(f"  警告：新抓取的 hpi_by_area 为空，保留旧缓存数据（{len(cached_prop['hpi_by_area'])} 条）")
                property_hpi = cached_prop["hpi_by_area"]
            with open(prop_path, "w", encoding="utf-8") as f:
                json.dump({"metro": property_metro, "areas": property_areas, "hpi_by_area": property_hpi},
                          f, ensure_ascii=False, indent=2)
            print(f"已写入 {prop_path}")

    prop_html = build_property_html(property_metro, property_areas, property_hpi) if property_metro else ""

    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(top3, top3_six, top3_known, gic_top, gic_top_six, gic_top_known, updated_at, property_html=prop_html)

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
            preview_html = build_newsletter_html(
                lang, top3_six, updated_at, site_url,
                property_metro=property_metro, hpi_by_area=property_hpi,
            )
            p = os.path.join(os.path.dirname(__file__), f"newsletter_preview_{lang}.html")
            with open(p, "w", encoding="utf-8") as f:
                f.write(preview_html)
            print(f"已写入 {p}")
    else:
        send_newsletter_emails(top3_six, updated_at, site_url,
                               property_metro=property_metro, hpi_by_area=property_hpi)


if __name__ == "__main__":
    main()
