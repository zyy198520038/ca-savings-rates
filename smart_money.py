#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
黄金 & 比特币「聪明钱 / 风险状态」仪表盘
========================================
本地专用脚本，生成包含智能仪表盘 Tab 的 index_local.html，
同时写入 smart_money_data.json（均不推送 GitHub）。

用法：
    python3 smart_money.py            # 抓取数据 + 生成页面
    python3 smart_money.py --no-fetch # 只用缓存数据重建页面（快速测试）
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "smart_money_data.json"
INDEX_SRC  = BASE_DIR / "index.html"
INDEX_OUT  = BASE_DIR / "index_local.html"

# ── 状态机阈值（保守默认，可调整）──────────────────────────────────────
THRESHOLDS = {
    "cot_extreme_high": 85,   # COT 净多头分位 > 85 → 拥挤否决
    "funding_extreme": 80,    # Funding 分位 > 80 → 杠杆拥挤
    "oi_surge": 75,           # OI 分位 > 75 且价格同向 → 风险上升
    "regime_good_tips": 40,   # TIPS 分位 < 40 → 实际利率偏低（顺风）
    "regime_good_dxy": 40,    # DXY 分位 < 40 → 美元偏弱（顺风）
    "regime_vix_ok": 60,      # VIX 分位 < 60 → 恐慌不极端（顺风）
}

# ── 颜色映射 ─────────────────────────────────────────────────────────
STATE_COLORS = {
    "ACCUMULATE": "#1aae39",   # Notion Green
    "NEUTRAL":    "#dd5b00",   # Notion Orange
    "DE_RISK":    "#e03e3e",   # Notion Red
}
STATE_LABELS_ZH = {
    "ACCUMULATE": "🟢 累积友好",
    "NEUTRAL":    "🟡 中性观望",
    "DE_RISK":    "🔴 降低风险",
}
STATE_DESC_ZH = {
    "ACCUMULATE": "环境偏顺风，仓位不拥挤，可按计划定投或小批加仓。",
    "NEUTRAL":    "信号冲突或强度不足，建议观望，不大幅改变仓位。",
    "DE_RISK":    "拥挤/杠杆/趋势破坏触发，建议降低杠杆或暂停加仓。",
}


# ══════════════════════════════════════════════════════════════════════
# 1. 数据获取
# ══════════════════════════════════════════════════════════════════════

def fetch_yf(ticker: str, period: str = "3y", interval: str = "1wk"):
    """用 yfinance 抓取价格序列，返回 pandas Series（Close）。"""
    import yfinance as yf
    df = yf.download(ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"yfinance 无数据：{ticker}")
    close = df["Close"]
    # yfinance 新版可能返回多列 DataFrame（MultiIndex），取第一列
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    return close.dropna()


def fetch_fred_tips() -> "pd.Series":
    """
    获取 10Y 实际利率代理：
    优先从 FRED DFII10 抓取，失败则用 Yahoo Finance TIP ETF 收益率代理
    （TIP = iShares TIPS Bond ETF，价格与实际利率反向）。
    返回 pandas Series（周频）。
    """
    import pandas as pd
    import urllib.request
    print("  抓取 FRED TIPS 10Y...")

    # 方法1：FRED CSV（可能因公司代理超时）
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode()
        lines = [l for l in data.strip().splitlines() if not l.startswith("DATE") and "." in l]
        rows = []
        for line in lines:
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    rows.append((parts[0].strip(), float(parts[1].strip())))
                except ValueError:
                    pass
        if rows:
            idx = pd.to_datetime([r[0] for r in rows])
            vals = [r[1] for r in rows]
            s = pd.Series(vals, index=idx, name="TIPS10Y").sort_index()
            print(f"  FRED TIPS 获取成功，最新值 {s.iloc[-1]:.2f}%")
            return s.resample("W").last().ffill()
    except Exception as e:
        print(f"  FRED 超时，改用 Yahoo Finance 代理: {e}")

    # 方法2：^TNX（10Y 名义利率）- 用 yfinance
    # 真实利率 ≈ 10Y 名义 - 通胀预期，这里用名义利率作近似代理
    try:
        tnx = fetch_yf("^TNX", period="10y", interval="1wk")
        print(f"  使用 ^TNX (10Y 国债收益率) 作为实际利率代理，最新值 {float(tnx.iloc[-1]):.2f}%")
        return tnx
    except Exception as e:
        raise ValueError(f"TIPS 数据获取全部失败: {e}")


def fetch_cot_gold() -> float:
    """
    从 CFTC 抓取黄金期货 COT 报告（Disaggregated Futures Only）。
    返回最新一期「Managed Money 净多头」值。
    若抓取失败返回 None。
    """
    import csv, io, urllib.request, zipfile
    # CFTC Disaggregated COT（期货，CSV zip）
    # 优先取上一年完整文件，再试当年文件
    year = datetime.utcnow().year
    urls = [
        f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year-1}.zip",
        f"https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip",
    ]
    print("  抓取 CFTC COT 黄金数据...")
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                zdata = resp.read()
            with zipfile.ZipFile(io.BytesIO(zdata)) as z:
                fname = [n for n in z.namelist() if n.endswith(".txt") or n.endswith(".csv")]
                if not fname:
                    continue
                with z.open(fname[0]) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
                    # COMEX 黄金的正式名称含 "COMMODITY EXCHANGE"
                    rows = [r for r in reader if "GOLD" in r.get("Market_and_Exchange_Names", "").upper()
                            and "COMMODITY EXCHANGE" in r.get("Market_and_Exchange_Names", "").upper()]
            if rows:
                # 取最新一期（按 Report_Date_as_YYYY-MM-DD 排序）
                rows.sort(key=lambda r: r.get("Report_Date_as_YYYY-MM-DD", ""), reverse=True)
                r = rows[0]
                mm_long  = float(r.get("M_Money_Positions_Long_All", 0) or 0)
                mm_short = float(r.get("M_Money_Positions_Short_All", 0) or 0)
                net = mm_long - mm_short
                report_date = r.get("Report_Date_as_YYYY-MM-DD", "unknown")
                print(f"  COT 黄金 Managed Money 净多头: {net:,.0f}（报告期 {report_date}）")
                return net
        except Exception as e:
            print(f"  COT 抓取失败（{u}）: {e}")
    return None


def fetch_btc_funding() -> float:
    """
    从 Binance 公开 API 抓取 BTC 永续合约资金费率（8h，年化 %）。
    返回当前费率值，失败返回 None。
    """
    import urllib.request
    # Binance Futures 公开 API，无需 key
    url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
    print("  抓取 Binance BTC Funding Rate...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        rate = float(data.get("lastFundingRate", 0) or 0)
        # 转为年化 %（8h * 3 * 365）
        annual = rate * 3 * 365 * 100
        print(f"  BTC Funding Rate (Binance, 年化): {annual:.1f}%")
        return annual
    except Exception as e:
        print(f"  Binance Funding 抓取失败: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
# 2. 指标计算工具
# ══════════════════════════════════════════════════════════════════════

def percentile_rank(series, window: int = 90) -> float:
    """返回 series 最新值在过去 window 个观测中的分位数（0-100）。"""
    vals = series.dropna().iloc[-window:]
    if len(vals) < 5:
        return 50.0
    latest = vals.iloc[-1]
    rank = (vals < latest).sum() / len(vals) * 100
    return round(float(rank), 1)


def hist_vol(price_series, window: int = 20) -> float:
    """计算价格序列过去 window 期的历史波动率（年化 %）。"""
    import numpy as np
    ret = price_series.pct_change().dropna()
    if len(ret) < window:
        return float("nan")
    hv = ret.iloc[-window:].std() * (52 ** 0.5) * 100  # 周频，年化
    return round(float(hv), 1)


def above_ma(price_series, ma_window: int = 200) -> bool:
    """判断最新收盘价是否在 ma_window 周简单均线之上。"""
    if len(price_series) < ma_window:
        return None
    ma = float(price_series.iloc[-ma_window:].mean())
    return bool(float(price_series.iloc[-1]) > ma)


def direction_label(pct: float, flip: bool = False) -> str:
    """
    将分位数转换为方向文字。
    flip=True 表示「高分位 = 顺风」（如 VIX 高 = 逆风，flip=False）。
    """
    if flip:
        if pct >= 70:
            return "顺风"
        elif pct <= 30:
            return "逆风"
        return "中性"
    else:
        if pct <= 30:
            return "顺风"
        elif pct >= 70:
            return "逆风"
        return "中性"


def indicator_hint(key: str, pct: float, value) -> str:
    """
    生成指标说明：解释「这个指标是什么、为什么高/低影响买卖、当前是什么意思」。
    格式：[逻辑]  →  [当前含义]
    """
    hints = {
        "tips": {
            "顺风": "📌 黄金不付息，实际利率越低，持有黄金的机会成本越小，资金更愿意买黄金。\n→ 当前实际利率偏低，对金价 ✅ 偏有利",
            "逆风": "📌 黄金不付息，实际利率越高，存款/债券收益越好，资金会流出黄金。\n→ 当前实际利率偏高，对金价 ⚠️ 有一定压力",
            "中性": "📌 黄金不付息，实际利率越低越利好金价。\n→ 当前实际利率处于历史中性区间，影响有限",
        },
        "dxy": {
            "顺风": "📌 黄金以美元计价，美元越弱金价越容易上涨。更关键的是「趋势」：当美元在过去8周持续贬值（>2%），往往是金价上涨的强力催化剂。\n→ 当前美元偏弱，对金价 ✅ 偏有利（若8周跌幅>2%则触发ACCUMULATE信号）",
            "逆风": "📌 黄金以美元计价，美元越强外国买家的成本越高，需求受压。尤其当美元持续走强时，金价上行阻力大。\n→ 当前美元偏强，对金价 ⚠️ 有压力",
            "中性": "📌 黄金以美元计价，美元强弱直接影响全球买家成本。本系统重点看8周美元变化趋势。\n→ 当前美元处于历史中性区间，影响有限",
        },
        "vix": {
            "顺风": "📌 VIX 是股市恐慌指数。市场平稳时，投资者风险偏好正常，黄金无极端溢价。\n→ 当前市场情绪平稳，适合正常配置",
            "逆风": "📌 VIX 极高说明市场恐慌，历史上「卖一切」行情中黄金也可能短期被抛售。\n→ 当前恐慌情绪偏高，短期波动风险上升",
            "中性": "📌 VIX 是股市恐慌指数，极高时连黄金也可能被抛售套现。\n→ 当前情绪中性，波动不极端",
        },
        "gold_hv": {
            "顺风": "📌 波动率低说明金价近期平稳，单笔买入的时机风险较小。\n→ 当前波动率偏低，✅ 适合正常定投",
            "逆风": "📌 波动率高说明金价近期大幅震荡，一次性买入风险较大。\n→ 当前波动率处于历史高位，⚠️ 建议分批小额操作",
            "中性": "📌 波动率衡量价格震荡幅度，偏高时建议分批而非一次性大额。\n→ 当前波动率适中",
        },
        "gold_trend": {
            "顺风": "📌 200 周均线是长期趋势的「地基」，价格在上方说明大趋势向上，历史上大多数买入机会都在均线上方。\n→ 当前金价在 200 周均线上方，✅ 中期趋势健康",
            "逆风": "📌 价格跌破 200 周均线是严重的趋势破坏信号，历史上往往伴随较长的下跌周期。\n→ 当前金价已跌破 200 周均线，⚠️ 建议降低风险",
            "中性": "📌 200 周均线是长期趋势判断的核心参考线。\n→ 趋势信号不明确",
        },
        "cot": {
            "顺风": "📌 COT 是美国期货监管机构（CFTC）每周公布的机构持仓报告。Managed Money 净多头处于低位，说明「聪明钱」还没大量涌入，上涨空间更大。\n→ 当前机构仓位不拥挤，✅ 没有明显的追高风险",
            "逆风": "📌 COT 净多头极高意味着「大家都买了」，没有新买盘推动，历史上此时往往是回调前夕。\n→ 当前机构仓位处于历史高位，⚠️ 拥挤风险上升，不宜追涨",
            "中性": "📌 COT 净多头反映机构对黄金的整体多空态度，极高 = 拥挤，极低 = 悲观但有反弹空间。\n→ 当前仓位处于历史中性区间",
        },
        "funding": {
            "顺风": "📌 资金费率是永续合约多头付给空头的费用。费率为负说明空头更多，多数人在做空或不看好——这通常是底部特征，价格更容易向上修复。\n→ 当前费率偏低/为负，✅ 市场不拥挤，适合考虑买入",
            "逆风": "📌 资金费率持续偏高说明大量资金用杠杆做多，「多头太多」的状态历史上常在大跌前出现（杠杆爆仓会放大跌幅）。\n→ 当前费率偏高，⚠️ 多头拥挤，注意杠杆清算风险",
            "中性": "📌 资金费率是杠杆多空情绪的晴雨表。持续极正 = 多头拥挤危险，持续极负 = 空头绝望可能见底。\n→ 当前费率处于正常区间",
        },
        "oi": {
            "顺风": "📌 均线偏离度衡量 BTC 当前价格比 200 周长期均线高多少。偏离越低说明价格越接近「历史地板」，历史上这种情况往往是中长期买入的好时机。\n→ 当前偏离度处于历史低位，✅ 价格接近长期均线，超跌风险较小",
            "逆风": "📌 均线偏离度极高（如 >100%）意味着价格已大幅偏离长期均值，历史上 BTC 每次偏离过高后都经历了大幅回调来「均值回归」。\n→ 当前偏离度处于历史高位，⚠️ 泡沫风险较高，不宜大额追涨",
            "中性": "📌 BTC 价格与 200 周均线的偏离度反映了「泡沫程度」：偏离越高越危险，越低越接近历史底部区域。\n→ 当前偏离度处于历史中性区间",
        },
        "btc_hv": {
            "顺风": "📌 波动率低说明 BTC 近期价格稳定，一次性买入的时机风险较小。\n→ 当前波动率偏低，✅ 适合正常仓位操作",
            "逆风": "📌 BTC 波动率极高时，单日价格可能涨跌超过 10%，一次性大额买入的风险很大。\n→ 当前波动率偏高，⚠️ 建议缩小单笔规模",
            "中性": "📌 波动率衡量价格震荡幅度，偏高时分批操作可以降低单次买错的损失。\n→ 当前波动率适中",
        },
        "btc_trend": {
            "顺风": "📌 200 周均线是 BTC 历史上最可靠的牛熊分界线，历史上每次跌破后都经历了较长熊市。在均线上方说明大趋势没有破坏。\n→ 当前 BTC 在 200 周均线上方，✅ 中期趋势向上",
            "逆风": "📌 BTC 历史上跌破 200 周均线后，通常还有大幅下跌空间（2018、2022 年均如此）。这是最重要的风险信号之一。\n→ 当前 BTC 已跌破 200 周均线，⚠️ 建议大幅降低风险",
            "中性": "📌 200 周均线是 BTC 牛熊周期的核心参考线，历史上跌破时风险极高。\n→ 趋势信号不明确",
        },
    }
    d = direction_label(pct) if key not in ("gold_trend", "btc_trend") else (
        "顺风" if value else ("逆风" if value is not None else "中性")
    )
    return hints.get(key, {}).get(d, "")


# ══════════════════════════════════════════════════════════════════════
# 3. 状态机
# ══════════════════════════════════════════════════════════════════════

def state_machine_gold(indicators: list) -> tuple:
    """
    黄金「时机评分」实时版。
    使用与回测完全相同的 _gold_timing_stars() 函数，保证实时=回测口径一致。
    返回 (signal, stars)。
    """
    by_key = {i["key"]: i for i in indicators}

    trend_val = by_key.get("gold_trend", {}).get("value", None)
    dxy_chg8  = by_key.get("dxy", {}).get("chg8", 0.0) or 0.0
    gold_chg8 = by_key.get("gold_trend", {}).get("gold_chg8", 0.0) or 0.0
    cot_pct   = by_key.get("cot", {}).get("pct", 50)
    hv_pct    = by_key.get("gold_hv", {}).get("pct", 50)
    vix_pct   = by_key.get("vix", {}).get("pct", 50)
    dev_pct   = by_key.get("gold_trend", {}).get("dev_pct", None)

    stars = _gold_timing_stars(trend_val, dxy_chg8, gold_chg8, cot_pct, hv_pct, vix_pct,
                               dev_pct=dev_pct)
    signal = _stars_to_signal(stars, "gold")
    return signal, stars


def state_machine_btc(indicators: list) -> tuple:
    """
    BTC 5星安全边际状态机（与回测口径统一）。
    返回 (signal, stars)。
    """
    by_key = {i["key"]: i for i in indicators}

    trend_val   = by_key.get("btc_trend", {}).get("value", None)
    funding_pct = by_key.get("funding", {}).get("pct", 50)

    # 真实均线偏离度（百分比值，非分位数）
    oi_val = by_key.get("oi", {}).get("value", None)
    try:
        dev_val = float(str(oi_val).replace("+", "")) if oi_val is not None else 50.0
    except Exception:
        dev_val = 50.0
    if trend_val is False:
        dev_val = -1.0  # 跌破均线，强制进5★区间

    stars  = _btc_stars(None, None, trend_val, dev_val, funding_pct)
    signal = _stars_to_signal(stars, "btc")
    return signal, stars


def compute_score(indicators: list) -> int:
    """将指标列表合成 0-100 风险分（越高越偏 DE_RISK）。"""
    scores = []
    for ind in indicators:
        pct = ind.get("pct", 50)
        key = ind.get("key", "")
        # 趋势类指标特殊处理
        if key in ("gold_trend", "btc_trend"):
            val = ind.get("value")
            scores.append(20 if val else 80 if val is False else 50)
        elif key in ("tips", "dxy", "vix", "cot", "funding", "oi", "gold_hv", "btc_hv"):
            # 高分位 = 高风险（除了 vix 需要额外逻辑，这里统一保守处理）
            scores.append(pct)
    return int(sum(scores) / len(scores)) if scores else 50


# ══════════════════════════════════════════════════════════════════════
# 4. 主数据流
# ══════════════════════════════════════════════════════════════════════

def build_gold_indicators() -> list:
    """抓取并计算黄金各项指标，返回指标列表。"""
    import yfinance as yf
    import pandas as pd
    indicators = []

    # TIPS 10Y
    try:
        tips = fetch_fred_tips()
        # 重采样为周频（取最后一个可用值）
        tips_wk = tips.resample("W").last().ffill()
        tips_pct = percentile_rank(tips_wk, 90)
        latest_tips = float(tips_wk.iloc[-1])
        d = direction_label(tips_pct, flip=False)
        indicators.append({
            "key": "tips", "name": "实际利率（TIPS 10Y）",
            "value": round(latest_tips, 2), "unit": "%",
            "pct": tips_pct, "direction": d,
            "hint": indicator_hint("tips", tips_pct, latest_tips),
        })
    except Exception as e:
        print(f"  TIPS 失败: {e}")

    # DXY
    try:
        print("  抓取 DXY...")
        dxy = fetch_yf("DX-Y.NYB", period="3y", interval="1wk")
        dxy_pct = percentile_rank(dxy, 90)
        d = direction_label(dxy_pct, flip=False)
        # 8周DXY变化（状态机使用）
        dxy_chg8 = round((float(dxy.iloc[-1]) - float(dxy.iloc[-8])) / float(dxy.iloc[-8]) * 100, 2) if len(dxy) >= 8 else 0.0
        indicators.append({
            "key": "dxy", "name": "美元指数（DXY）",
            "value": round(float(dxy.iloc[-1]), 1), "unit": "",
            "pct": dxy_pct, "direction": d,
            "chg8": dxy_chg8,
            "hint": indicator_hint("dxy", dxy_pct, float(dxy.iloc[-1])),
        })
    except Exception as e:
        print(f"  DXY 失败: {e}")

    # VIX
    try:
        print("  抓取 VIX...")
        vix = fetch_yf("^VIX", period="3y", interval="1wk")
        vix_pct = percentile_rank(vix, 90)
        d = direction_label(vix_pct, flip=False)
        indicators.append({
            "key": "vix", "name": "VIX 恐慌指数",
            "value": round(float(vix.iloc[-1]), 1), "unit": "",
            "pct": vix_pct, "direction": d,
            "hint": indicator_hint("vix", vix_pct, float(vix.iloc[-1])),
        })
    except Exception as e:
        print(f"  VIX 失败: {e}")

    # 黄金价格（波动率 + 趋势）
    try:
        print("  抓取 黄金价格（GC=F）...")
        gold = fetch_yf("GC=F", period="5y", interval="1wk")
        hv = hist_vol(gold, 20)
        hv_pct = percentile_rank(
            gold.pct_change().dropna().rolling(20).std().dropna() * (52**0.5) * 100, 90
        )
        d_hv = direction_label(hv_pct, flip=False)
        indicators.append({
            "key": "gold_hv", "name": "黄金波动率（HV 20W）",
            "value": hv, "unit": "%",
            "pct": hv_pct, "direction": d_hv,
            "hint": indicator_hint("gold_hv", hv_pct, hv),
        })
        # 趋势（200 周均线）+ 偏离度
        trend = above_ma(gold, 200)
        trend_dir = "顺风" if trend else ("逆风" if trend is False else "中性")
        # 8周金价变化
        gold_chg8 = round((float(gold.iloc[-1]) - float(gold.iloc[-8])) / float(gold.iloc[-8]) * 100, 1) if len(gold) >= 8 else 0.0
        # 200周均线偏离度（核心估值锚）
        ma200_val = float(gold.rolling(200).mean().iloc[-1]) if len(gold) >= 200 else None
        price_now = float(gold.iloc[-1])
        dev_pct = round((price_now - ma200_val) / ma200_val * 100, 1) if ma200_val else None
        indicators.append({
            "key": "gold_trend", "name": "黄金中期趋势（200W 均线）",
            "value": trend,
            "value_display": "均线上方 ↑" if trend else ("均线下方 ↓" if trend is False else "数据不足"),
            "unit": "",
            "pct": 20 if trend else 80 if trend is False else 50,
            "direction": trend_dir,
            "gold_chg8": gold_chg8,
            "dev_pct": dev_pct,
            "ma200": round(ma200_val, 0) if ma200_val else None,
            "price_now": round(price_now, 0),
            "hint": indicator_hint("gold_trend", 0, trend),
        })
    except Exception as e:
        print(f"  黄金价格失败: {e}")

    # COT
    try:
        cot_net = fetch_cot_gold()
        if cot_net is not None:
            # 需要历史 COT 序列来计算分位，这里用简化方法：
            # 暂时用固定范围（约 -50k ~ 300k）做线性分位估算
            # 实际项目中应存储历史 COT 序列
            cot_pct = min(100, max(0, (cot_net + 50000) / 350000 * 100))
            cot_pct = round(cot_pct, 1)
            d = direction_label(cot_pct, flip=False)
            indicators.append({
                "key": "cot", "name": "COT 黄金净多头（Managed Money）",
                "value": int(cot_net), "unit": "手",
                "pct": cot_pct, "direction": d,
                "hint": indicator_hint("cot", cot_pct, cot_net),
            })
    except Exception as e:
        print(f"  COT 失败: {e}")

    return indicators


def build_btc_indicators() -> list:
    """抓取并计算 BTC 各项指标，返回指标列表。"""
    indicators = []

    # BTC 价格（波动率 + 趋势）
    try:
        print("  抓取 BTC 价格...")
        btc = fetch_yf("BTC-USD", period="5y", interval="1wk")
        hv = hist_vol(btc, 20)
        hv_pct = percentile_rank(
            btc.pct_change().dropna().rolling(20).std().dropna() * (52**0.5) * 100, 90
        )
        d_hv = direction_label(hv_pct, flip=False)
        indicators.append({
            "key": "btc_hv", "name": "BTC 波动率（HV 20W）",
            "value": hv, "unit": "%",
            "pct": hv_pct, "direction": d_hv,
            "hint": indicator_hint("btc_hv", hv_pct, hv),
        })
        trend = above_ma(btc, 200)
        trend_dir = "顺风" if trend else ("逆风" if trend is False else "中性")
        btc_price_now = round(float(btc.iloc[-1]), 0)
        indicators.append({
            "key": "btc_trend", "name": "BTC 中期趋势（200W 均线）",
            "value": trend,
            "value_display": "均线上方 ↑" if trend else ("均线下方 ↓" if trend is False else "数据不足"),
            "unit": "",
            "pct": 20 if trend else 80 if trend is False else 50,
            "direction": trend_dir,
            "hint": indicator_hint("btc_trend", 0, trend),
            "price_now": btc_price_now,
        })
    except Exception as e:
        print(f"  BTC 价格失败: {e}")

    # Funding Rate
    try:
        funding = fetch_btc_funding()
        if funding is not None:
            # 年化 funding rate：历史范围约 -20% ~ +150%
            funding_pct = min(100, max(0, (funding + 20) / 170 * 100))
            funding_pct = round(funding_pct, 1)
            d = direction_label(funding_pct, flip=False)
            indicators.append({
                "key": "funding", "name": "BTC 资金费率（年化）",
                "value": round(funding, 1), "unit": "%",
                "pct": funding_pct, "direction": d,
                "hint": indicator_hint("funding", funding_pct, funding),
            })
    except Exception as e:
        print(f"  Funding 失败: {e}")

    # 均线偏离度（Price vs 200W MA）：衡量"泡沫程度"
    # BTC 历史上偏离 >100% 往往是高位，<30% 往往是低位
    try:
        print("  计算均线偏离度指标...")
        btc2 = fetch_yf("BTC-USD", period="6y", interval="1wk")
        ma200 = btc2.rolling(200).mean()
        dev_series = ((btc2 - ma200) / ma200 * 100).dropna()
        latest_dev = round(float(dev_series.iloc[-1]), 1)
        # 分位：偏离越高越危险（高分位 = 逆风）
        dev_pct = percentile_rank(dev_series, len(dev_series))  # 全历史分位
        d = direction_label(dev_pct, flip=False)  # 高 = 逆风
        indicators.append({
            "key": "oi", "name": "BTC 均线偏离度（距200W均线）",
            "value": f"+{latest_dev}" if latest_dev >= 0 else str(latest_dev), "unit": "%",
            "pct": dev_pct, "direction": d,
            "hint": indicator_hint("oi", dev_pct, latest_dev),
            "price_now": round(float(btc2.iloc[-1]), 0),
            "ma200": round(float(ma200.iloc[-1]), 0),
        })
        print(f"  BTC 均线偏离度: {latest_dev:+.1f}% (分位 {dev_pct:.0f}%)")
    except Exception as e:
        print(f"  均线偏离度失败: {e}")

    return indicators


# ══════════════════════════════════════════════════════════════════════
# 5. 回测
# ══════════════════════════════════════════════════════════════════════

def _gold_timing_stars(trend, dxy_chg8, gold_chg8, cot_pct,
                       hv_pct=50, vix_pct=50,
                       dev_pct=None) -> int:
    """
    黄金星级：回答两个不同问题
    ─────────────────────────────────────────────────────
    黄金是长期慢牛（通胀对冲），价格长期上涨是常态，
    因此"历史便宜程度"不是正确的问题。

    正确的两层问题：
      第一层（持仓者）：趋势是否健康，要不要降风险？
        → 默认 3★ NEUTRAL（持有）
        → 出现趋势破坏/极端拥挤/急涨反转 → 降为 2★/1★ DE_RISK

      第二层（加仓者）：现在是否比平时更好的入场时机？
        → 近期回调 + 美元走弱 + 不拥挤 → 升为 4★/5★ ACCUMULATE
        → 无明显信号 → 维持 3★ NEUTRAL

    评分逻辑（从默认 3★ 开始调整）：
      DE_RISK 条件（-1 或 -2）：
        - 趋势破坏（跌破200周均线）     → -2
        - COT 极端拥挤（>85%分位）      → -1
        - 近8周急涨 >15%               → -1
        - HV 极端（>95%分位）           → -1
      ACCUMULATE 条件（+1 或 +2）：
        - 美元8周贬值 >2%              → +1
        - 近8周回调 5-15%              → +1
        - 上述两者同时满足且COT不拥挤  → 额外 +1（共振）
    """
    score = 0  # 从 0 开始，映射到 3★

    # ── DE_RISK 信号（下行风险）──
    if trend is False:
        score -= 1   # 跌破200周均线：趋势破坏（-1，需叠加其他信号才到1★）
    if cot_pct > 85:
        score -= 1   # 机构仓位极度拥挤
    if gold_chg8 > 15:
        score -= 1   # 8周急涨 >15%，超买

    # 注：HV 极端不触发 DE_RISK——高波动往往是恐慌底部，
    # 历史上 HV 极端后金价反而大涨。HV 高只说明要分批入场。

    # ── ACCUMULATE 信号（入场时机）──
    if dxy_chg8 < -2:
        score += 1   # 美元走弱，黄金顺风
    if -15 <= gold_chg8 <= -5:
        score += 1   # 近期健康回调，好时机
    if dxy_chg8 < -2 and -15 <= gold_chg8 <= -5 and cot_pct <= 70:
        score += 1   # 三者共振：最佳入场窗口

    # score → stars：中心是 3★（score=0）
    if score >= 2:    return 5
    elif score == 1:  return 4
    elif score == 0:  return 3   # 默认：持有，无特别信号
    elif score == -1: return 2
    else:             return 1   # 多重 DE_RISK 叠加


def _btc_stars(price, ma200, trend, dev_val, funding_pct=50) -> int:
    """
    BTC 星级评分（1-5星），对标螺丝钉逻辑：
      星级 ↔ 价格区间有稳定的 ~30-50% 间距

    核心锚：200周均线真实偏离度（dev_val = (price - MA200) / MA200 * 100）
      跌破均线(dev_val<0) → 基础 5★（历史底部，最大机会）
      0-20%              → 基础 5★（贴近均线，历史低位）
      20-60%             → 基础 4★
      60-100%            → 基础 3★
      100-150%           → 基础 2★
      >150%              → 基础 1★（历史泡沫区）

    辅助调整（最多 ±1）：
      +1 若 Funding 极低或负值（多头不拥挤，定投友好）
      -1 若 Funding 极端高（>80%分位，多头严重拥挤）
    """
    # 基础星级（价格锚）
    if dev_val <= 0:     base = 5   # 跌破或贴近均线：历史底部
    elif dev_val <= 40:  base = 4
    elif dev_val <= 80:  base = 3
    elif dev_val <= 140: base = 2
    else:                base = 1

    # 辅助调整
    bonus   = 1 if funding_pct < 20 else 0   # 资金费率极低/负 → 定投友好
    penalty = 1 if funding_pct > 80 else 0   # 资金费率极高 → 多头拥挤
    adj = bonus - penalty
    return max(1, min(5, base + adj))


def _stars_to_signal(stars: int, asset: str) -> str:
    """星级映射到三态信号"""
    if asset == "gold":
        # 黄金：4/5星=买入，3星=观望，1/2星=降风险
        if stars >= 4:  return "ACCUMULATE"
        elif stars == 3: return "NEUTRAL"
        else:           return "DE_RISK"
    else:
        # BTC：4/5星=买入，3星=观望，1/2星=降风险
        if stars >= 4:  return "ACCUMULATE"
        elif stars == 3: return "NEUTRAL"
        else:           return "DE_RISK"


def backtest_gold(lookback_weeks: int = 208) -> tuple:
    """
    黄金回测，使用「时机评分」体系（与实时 state_machine_gold 口径完全一致）。
    5星 = 时机好（均线上+美元贬值+适度回调）
    1星 = 时机差（趋势破坏 or 大涨追高 or 美元强）
    """
    import yfinance as yf
    import pandas as pd
    print("  黄金回测中...")

    try:
        gold  = fetch_yf("GC=F",     period="10y", interval="1wk")
        dxy   = fetch_yf("DX-Y.NYB", period="10y", interval="1wk")
    except Exception as e:
        print(f"  回测数据获取失败: {e}")
        return [], {}

    df = pd.DataFrame({
        "gold": gold,
        "dxy":  dxy.reindex(gold.index, method="ffill"),
    }).dropna()

    records = []
    start_idx = max(200, len(df) - lookback_weeks)
    for i in range(start_idx, len(df)):
        hist = df.iloc[:i]
        date_str = str(df.index[i].date())

        gold_hist = hist["gold"]
        dxy_hist  = hist["dxy"].dropna()

        if len(gold_hist) < 200:
            continue

        ma200_g = float(gold_hist.rolling(200).mean().iloc[-1])
        price_g = float(gold_hist.iloc[-1])
        trend   = price_g > ma200_g
        dev_pct_bt = (price_g - ma200_g) / ma200_g * 100

        dxy_chg8  = (float(dxy_hist.iloc[-1]) - float(dxy_hist.iloc[-8])) / float(dxy_hist.iloc[-8]) * 100 if len(dxy_hist) >= 8 else 0.0
        gold_chg8 = (price_g - float(gold_hist.iloc[-8])) / float(gold_hist.iloc[-8]) * 100 if len(gold_hist) >= 8 else 0.0

        # HV 20W 历史分位
        hv_series = gold_hist.pct_change().dropna().rolling(20).std().dropna() * (52**0.5) * 100
        hv_pct_bt = float(percentile_rank(hv_series, min(90, len(hv_series)))) if len(hv_series) >= 20 else 50.0

        # COT/VIX 在回测中无历史序列，用中性值
        stars  = _gold_timing_stars(trend, dxy_chg8, gold_chg8, cot_pct=50,
                                    hv_pct=hv_pct_bt, vix_pct=50,
                                    dev_pct=dev_pct_bt)
        signal = _stars_to_signal(stars, "gold")

        records.append({
            "date":  date_str,
            "price": round(price_g, 0),
            "signal": signal,
            "stars": stars,
            "score": stars * 20,  # 1-5星 → 20-100分
        })

    accuracy = _calc_accuracy(records)
    # 额外计算各星级胜率
    stars_acc = _calc_stars_accuracy(records)
    accuracy["stars"] = stars_acc
    print(f"  黄金回测完成，{len(records)} 条记录")
    return records, accuracy


def backtest_btc(lookback_weeks: int = 208) -> tuple:
    """
    BTC 回测，使用5星安全边际体系。
    5星 = 跌破200W均线或历史低分位（长线定投黄金坑）
    1星 = 历史泡沫高位（降风险）
    """
    import yfinance as yf
    import pandas as pd
    print("  BTC 回测中...")

    try:
        btc = fetch_yf("BTC-USD", period="10y", interval="1wk")
    except Exception as e:
        print(f"  BTC 回测数据获取失败: {e}")
        return [], {}

    records = []
    start_idx = max(200, len(btc) - lookback_weeks)
    for i in range(start_idx, len(btc)):
        hist = btc.iloc[:i]
        row  = btc.iloc[i]
        date_str = str(btc.index[i].date())

        if len(hist) < 200:
            continue

        ma200_val = float(hist.rolling(200).mean().iloc[-1])
        price_now = float(hist.iloc[-1])
        trend     = price_now > ma200_val
        dev_val   = (price_now - ma200_val) / ma200_val * 100  # 真实偏离度值

        # 回测中 funding 无历史序列，用中性值
        stars  = _btc_stars(price_now, ma200_val, trend, dev_val, funding_pct=50)
        signal = _stars_to_signal(stars, "btc")

        records.append({
            "date":  date_str,
            "price": round(price_now, 0),
            "signal": signal,
            "stars": stars,
            "score": stars * 20,
        })

    accuracy = _calc_accuracy(records)
    stars_acc = _calc_stars_accuracy(records)
    accuracy["stars"] = stars_acc
    print(f"  BTC 回测完成，{len(records)} 条记录")
    return records, accuracy


def _calc_stars_accuracy(records: list) -> dict:
    """计算各星级后 4 周和 26 周价格上涨概率 + 平均涨幅。"""
    result = {}
    for s in range(1, 6):
        idx = [i for i, r in enumerate(records) if r.get("stars") == s]
        # 4周
        pairs4  = [(i, i+4)  for i in idx if i+4  < len(records)]
        pairs26 = [(i, i+26) for i in idx if i+26 < len(records)]
        w4  = sum(1 for i, j in pairs4  if records[j]["price"] > records[i]["price"])
        w26 = sum(1 for i, j in pairs26 if records[j]["price"] > records[i]["price"])
        # 平均涨幅（含跌）
        ret4  = [(records[j]["price"] - records[i]["price"]) / records[i]["price"] * 100 for i, j in pairs4]
        ret26 = [(records[j]["price"] - records[i]["price"]) / records[i]["price"] * 100 for i, j in pairs26]
        avg4  = round(sum(ret4)  / len(ret4),  1) if ret4  else None
        avg26 = round(sum(ret26) / len(ret26), 1) if ret26 else None
        result[str(s)] = {
            "win4":  round(w4/len(pairs4),  2) if pairs4  else None,
            "win26": round(w26/len(pairs26), 2) if pairs26 else None,
            "avg4":  avg4,
            "avg26": avg26,
            "n4": len(pairs4), "n26": len(pairs26),
        }
    return result


def _calc_accuracy(records: list) -> dict:
    """计算信号后 4 周价格变动准确率。"""
    n_acc, acc_win = 0, 0
    n_der, der_win = 0, 0
    for i, r in enumerate(records):
        if i + 4 >= len(records):
            break
        future_price = records[i + 4]["price"]
        if r["signal"] == "ACCUMULATE":
            n_acc += 1
            if future_price > r["price"]:
                acc_win += 1
        elif r["signal"] == "DE_RISK":
            n_der += 1
            if future_price < r["price"]:
                der_win += 1
    return {
        "accumulate_win_rate": round(acc_win / n_acc, 2) if n_acc > 0 else None,
        "derisk_win_rate":     round(der_win / n_der, 2) if n_der > 0 else None,
        "n_accumulate": n_acc,
        "n_derisk":     n_der,
        "note": "信号后 4 周价格方向准确率（仅供参考，过往不代表未来）",
    }


# ══════════════════════════════════════════════════════════════════════
# 6. HTML 生成
# ══════════════════════════════════════════════════════════════════════

def _pct_bar(pct: float, direction: str) -> str:
    """生成分位数进度条 HTML。"""
    color_map = {"顺风": "#1aae39", "逆风": "#e03e3e", "中性": "#f97316"}
    dir_key_map = {"顺风": "tailwind", "逆风": "headwind", "中性": "neutral"}
    color = color_map.get(direction, "#f97316")
    dir_key = dir_key_map.get(direction, "neutral")
    return (
        f'<div class="sm-pct-bar-wrap">'
        f'<div class="sm-pct-bar" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
        f'<span class="sm-pct-label" style="color:{color};">'
        f'<span data-i18n="sm_percentile">分位</span> {pct:.0f}% · '
        f'<span data-i18n="sm_dir_{dir_key}">{direction}</span>'
        f'</span>'
    )


def _indicator_card(ind: dict) -> str:
    val_display = ind.get("value_display") or f'{ind["value"]}{ind.get("unit","")}'
    note = f'<div class="sm-ind-note">{ind["note"]}</div>' if ind.get("note") else ""
    # For DXY: show 8-week change as secondary value
    chg8 = ind.get("chg8")
    chg8_html = ""
    if chg8 is not None:
        chg8_color = "#1aae39" if chg8 < -2.0 else ("#e03e3e" if chg8 > 2.0 else "#9b9691")
        chg8_sign = "+" if chg8 >= 0 else ""
        chg8_html = (f'<span style="font-size:0.78rem;color:{chg8_color};margin-left:0.5rem;"'
                     f' data-i18n-tpl="sm_tpl_8w_chg" data-i18n-vals=\'["{chg8_sign}{chg8:.1f}"]\'>'
                     f'8周变化 {chg8_sign}{chg8:.1f}%</span>')
    return (
        f'<div class="sm-ind-card">'
        f'<div class="sm-ind-name">{ind["name"]}</div>'
        f'<div class="sm-ind-val">{val_display}{chg8_html}</div>'
        f'{_pct_bar(ind["pct"], ind["direction"])}'
        f'<div class="sm-ind-hint">{ind.get("hint","")}</div>'
        f'{note}'
        f'</div>'
    )


def _accuracy_text(acc: dict, asset: str) -> str:
    if not acc:
        return ""

    stars_acc = acc.get("stars", {})
    star_rows = ""
    MIN_SAMPLE = 10
    for s in range(5, 0, -1):
        sa = stars_acc.get(str(s), {})
        w4   = sa.get("win4"); w26  = sa.get("win26")
        avg4 = sa.get("avg4"); avg26 = sa.get("avg26")
        n4   = sa.get("n4", 0)
        star_str = "⭐" * s
        low_sample = n4 < MIN_SAMPLE
        row_opacity = 'opacity:0.45;' if low_sample else ''
        color4  = "#1aae39" if (w4  or 0) >= 0.65 else ("#e03e3e" if (w4  or 0) < 0.45 else "#f97316")
        color26 = "#1aae39" if (w26 or 0) >= 0.70 else ("#e03e3e" if (w26 or 0) < 0.50 else "#f97316")
        cavg4  = "#1aae39" if (avg4  or 0) > 2  else ("#e03e3e" if (avg4  or 0) < -2 else "#9b9691")
        cavg26 = "#1aae39" if (avg26 or 0) > 5  else ("#e03e3e" if (avg26 or 0) < -5 else "#9b9691")
        w4_str   = f'{int(w4*100)}%'  if w4   is not None else "—"
        w26_str  = f'{int(w26*100)}%' if w26  is not None else "—"
        avg4_str  = (f'+{avg4:.1f}%'  if (avg4  or 0) >= 0 else f'{avg4:.1f}%')  if avg4  is not None else "—"
        avg26_str = (f'+{avg26:.1f}%' if (avg26 or 0) >= 0 else f'{avg26:.1f}%') if avg26 is not None else "—"
        unreliable = (f' <span data-i18n="sm_low_sample" style="font-size:0.68rem;color:#615d59;">⚠️ 样本少</span>'
                      if low_sample else '')
        n4_cell = (f'<span data-i18n-tpl="sm_tpl_samples" data-i18n-vals=\'["{n4}"]\'>{n4}次</span>')
        star_rows += (
            f'<tr style="{row_opacity}">'
            f'<td style="padding:3px 8px;">{star_str}{unreliable}</td>'
            f'<td style="padding:3px 8px;color:{color4};">{w4_str}</td>'
            f'<td style="padding:3px 8px;color:{cavg4};">{avg4_str}</td>'
            f'<td style="padding:3px 8px;color:{color26};">{w26_str}</td>'
            f'<td style="padding:3px 8px;color:{cavg26};">{avg26_str}</td>'
            f'<td style="padding:3px 8px;color:#615d59;">{n4_cell}</td></tr>'
        )

    if asset == "黄金":
        title_key  = "sm_acc_title_gold";  title_zh  = "时机评分回测（黄金）"
        logic_key  = "sm_acc_logic_gold";  logic_zh  = "时机评分：默认持有=3★，加仓信号（回调+美元弱）→4/5★，风险信号（趋势破坏/拥挤/急涨）→2/1★"
        caveat_key = "sm_acc_caveat_gold"; caveat_zh = ('⚠️ 黄金是长期慢牛（通胀对冲），价格长期上涨是常态。'
                  '1★/2★ 样本极少，且多发生在恐慌底部（高波动期），统计意义有限。'
                  '本系统核心价值在于：识别「好的加仓时机（4★）」和「趋势真正破坏时的离场信号（1★）」，而非预测短期涨跌。')
    else:
        title_key  = "sm_acc_title_btc";  title_zh  = "安全边际回测（BTC）"
        logic_key  = "sm_acc_logic_btc";  logic_zh  = "BTC 距200W均线偏离度（历史分位）"
        caveat_key = "sm_acc_caveat_btc"; caveat_zh = '⚠️ BTC 波动极大，短期（4周）随机性强。26周平均涨幅更能体现安全边际的价值。'

    return (
        f'<div class="sm-accuracy">'
        f'<div style="font-weight:600;margin-bottom:0.4rem;">📊 <span data-i18n="{title_key}">{title_zh}</span></div>'
        f'<div style="font-size:0.75rem;color:#9b9691;margin-bottom:0.5rem;">'
        f'<span data-i18n="sm_acc_logic_label">评分逻辑：</span>'
        f'<span data-i18n="{logic_key}">{logic_zh}</span></div>'
        f'<table style="font-size:0.8rem;border-collapse:collapse;width:100%;">'
        f'<tr style="color:#615d59;font-size:0.73rem;">'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_stars">星级</th>'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_win4w">4周上涨率</th>'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_avg4w">4周平均涨幅</th>'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_win26w">26周上涨率</th>'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_avg26w">26周平均涨幅</th>'
        f'<th style="padding:3px 8px;text-align:left;" data-i18n="sm_th_samples">样本数</th></tr>'
        f'{star_rows}'
        f'</table>'
        f'<span class="sm-acc-caveat" data-i18n="{caveat_key}">{caveat_zh}</span>'
        f'<span class="sm-acc-note" data-i18n="sm_acc_note">历史回测仅供参考，不代表未来表现，不构成投资建议</span>'
        f'</div>'
    )


def _draw_svg_chart(records: list, price_label: str, price_color: str, width: int = 900, height: int = 280) -> str:
    """
    生成内联 SVG 回测图表：左轴 = 1★–5★，右轴 = 价格。
    和螺丝钉 App 风格一致：彩色星级折线 + 价格折线 + 当前时刻竖线。
    """
    if not records:
        return '<div style="color:#615d59;padding:2rem;text-align:center;">暂无回测数据</div>'

    STAR_COLORS = {
        5: '#1aae39',  # Notion Green
        4: '#2a9d99',  # Notion Teal
        3: '#a39e98',  # Notion Warm Gray
        2: '#dd5b00',  # Notion Orange
        1: '#e03e3e',  # Notion Red
    }

    # Layout margins
    lm, rm, tm, bm = 52, 70, 18, 42
    cw = width - lm - rm   # chart area width
    ch = height - tm - bm  # chart area height

    n = len(records)
    prices = [r['price'] for r in records]
    stars_list = [r.get('stars', 3) for r in records]
    dates = [r['date'] for r in records]

    p_min, p_max = min(prices), max(prices)
    p_range = p_max - p_min or 1

    # Star axis: fixed 0.5 to 5.5
    s_min, s_max = 0.5, 5.5

    def x_px(i):
        return lm + (i / (n - 1)) * cw if n > 1 else lm + cw / 2

    def y_star(s):
        return tm + ch - (s - s_min) / (s_max - s_min) * ch

    def y_price(p):
        return tm + ch - (p - p_min) / p_range * ch

    lines = []

    # Background grid lines for star axis (1–5)
    for s in range(1, 6):
        yy = y_star(s)
        lines.append(f'<line x1="{lm}" y1="{yy:.1f}" x2="{lm+cw}" y2="{yy:.1f}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>')

    # Price polyline (right axis, semi-transparent)
    price_pts = " ".join(f"{x_px(i):.1f},{y_price(prices[i]):.1f}" for i in range(n))
    lines.append(f'<polyline points="{price_pts}" fill="none" stroke="{price_color}" stroke-width="1.5" stroke-opacity="0.55"/>')

    # Star colored polyline: draw segment by segment
    for i in range(n - 1):
        x1, y1 = x_px(i), y_star(stars_list[i])
        x2, y2 = x_px(i + 1), y_star(stars_list[i + 1])
        c = STAR_COLORS.get(stars_list[i], '#9b9691')
        lines.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{c}" stroke-width="2.5"/>')

    # Star dots (every ~4 points to reduce clutter)
    dot_step = max(1, n // 52)
    for i in range(0, n, dot_step):
        cx, cy = x_px(i), y_star(stars_list[i])
        c = STAR_COLORS.get(stars_list[i], '#9b9691')
        lines.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="{c}" stroke="none"/>')

    # Current time vertical dashed line
    last_x = x_px(n - 1)
    last_star = stars_list[-1]
    curr_color = STAR_COLORS.get(last_star, '#9b9691')
    lines.append(f'<line x1="{last_x:.1f}" y1="{tm}" x2="{last_x:.1f}" y2="{tm+ch}" stroke="{curr_color}" stroke-width="1.5" stroke-dasharray="5,3"/>')
    label_x = last_x - 4 if last_x > lm + cw * 0.8 else last_x + 4
    label_anchor = "end" if last_x > lm + cw * 0.8 else "start"
    lines.append(f'<text x="{label_x:.1f}" y="{tm+14}" fill="{curr_color}" font-size="10" font-weight="bold" text-anchor="{label_anchor}">▶ 当前 {last_star}★</text>')

    # Left Y axis labels (stars)
    for s in range(1, 6):
        yy = y_star(s)
        c = STAR_COLORS.get(s, '#9b9691')
        lines.append(f'<text x="{lm-6}" y="{yy+4:.1f}" fill="{c}" font-size="11" font-weight="600" text-anchor="end">{s}★</text>')
    lines.append(f'<text x="{lm-28}" y="{tm+ch//2}" fill="#615d59" font-size="10" text-anchor="middle" transform="rotate(-90,{lm-28},{tm+ch//2})">安全边际</text>')

    # Right Y axis labels (price)
    for frac in [0, 0.25, 0.5, 0.75, 1.0]:
        pv = p_min + frac * p_range
        yy = y_price(pv)
        # format large numbers
        if pv >= 1000:
            label = f'{pv/1000:.0f}k' if pv < 1e6 else f'{pv/1e6:.2f}M'
        else:
            label = f'{pv:.0f}'
        lines.append(f'<text x="{lm+cw+6}" y="{yy+4:.1f}" fill="{price_color}" font-size="10" text-anchor="start" opacity="0.8">{label}</text>')

    # X axis date labels (8 evenly spaced)
    tick_count = 8
    tick_step = max(1, n // tick_count)
    tick_indices = list(range(0, n, tick_step))
    if tick_indices[-1] != n - 1:
        tick_indices.append(n - 1)
    for i in tick_indices:
        xp = x_px(i)
        label = dates[i][2:7]  # "YY-MM"
        lines.append(f'<line x1="{xp:.1f}" y1="{tm+ch}" x2="{xp:.1f}" y2="{tm+ch+4}" stroke="#615d59" stroke-width="1"/>')
        lines.append(f'<text x="{xp:.1f}" y="{tm+ch+15}" fill="#615d59" font-size="10" text-anchor="middle">{label}</text>')

    # Axis lines
    lines.append(f'<line x1="{lm}" y1="{tm}" x2="{lm}" y2="{tm+ch}" stroke="#37352f" stroke-width="1"/>')
    lines.append(f'<line x1="{lm}" y1="{tm+ch}" x2="{lm+cw}" y2="{tm+ch}" stroke="#37352f" stroke-width="1"/>')
    lines.append(f'<line x1="{lm+cw}" y1="{tm}" x2="{lm+cw}" y2="{tm+ch}" stroke="#37352f" stroke-width="1"/>')

    svg_body = '\n'.join(lines)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;background:transparent;">'
        f'{svg_body}'
        f'</svg>'
    )


def _gold_factor_cards(indicators: list) -> str:
    """
    生成黄金「时机评分因子」卡片组（6个因子，与算法完全对应）。
    """
    by_key    = {i["key"]: i for i in indicators}
    dxy_chg8  = float(by_key.get("dxy", {}).get("chg8", 0.0) or 0.0)
    cot_pct   = float(by_key.get("cot", {}).get("pct", 50) or 50)
    hv_pct    = float(by_key.get("gold_hv", {}).get("pct", 50) or 50)
    hv_val    = by_key.get("gold_hv", {}).get("value", "—")
    vix_pct   = float(by_key.get("vix", {}).get("pct", 50) or 50)
    vix_val   = by_key.get("vix", {}).get("value", "—")
    dxy_val   = by_key.get("dxy", {}).get("value", "—")
    dev_pct   = by_key.get("gold_trend", {}).get("dev_pct", None)
    ma200_val = by_key.get("gold_trend", {}).get("ma200", None)
    price_now = by_key.get("gold_trend", {}).get("price_now", None)

    # 与 _gold_timing_stars 完全同步
    trend_val = by_key.get("gold_trend", {}).get("value", None)
    gold_chg8 = float(by_key.get("gold_trend", {}).get("gold_chg8", 0.0) or 0.0)

    score = 0
    if trend_val is False: score -= 2
    if cot_pct > 85:       score -= 1
    if gold_chg8 > 15:     score -= 1
    if hv_pct > 95:        score -= 1
    if dxy_chg8 < -2:      score += 1
    if -15 <= gold_chg8 <= -5: score += 1
    if dxy_chg8 < -2 and -15 <= gold_chg8 <= -5 and cot_pct <= 70: score += 1

    stars_final = 5 if score >= 2 else (4 if score == 1 else (3 if score == 0 else (2 if score == -1 else 1)))

    def _badge(f):
        if f > 0:  return f'<span style="color:#22c55e;font-weight:700;">+{f}</span>'
        elif f < 0: return f'<span style="color:#ef4444;font-weight:700;">{f}</span>'
        return '<span style="color:#615d59;">0</span>'

    # 各因子贡献
    factors = []

    # 趋势
    f_trend = -1 if trend_val is False else 0
    trend_display = ('<span data-i18n="sm_trend_up">均线上方 ↑</span>' if trend_val is True
                     else ('<span data-i18n="sm_trend_down">均线下方 ↓ ⚠️</span>' if trend_val is False
                           else '数据不足'))
    trend_hint = ('<span data-i18n="sm_trend_healthy">大趋势健康，无 DE_RISK 信号</span>' if trend_val is True
                  else '<span data-i18n="sm_trend_broken">跌破200周均线，趋势破坏 → -1</span>')
    trend_bg = "#ef444422" if f_trend < 0 else "#22c55e22" if trend_val is True else "var(--bg-elevated)"
    factors.append(('<span data-i18n="sm_factor_gold_trend">📐 趋势（200周均线）</span>',
                    trend_display, f_trend, trend_hint, trend_bg))

    # 8周金价变化
    if gold_chg8 > 15:
        f_chg = -1
        chg_hint = (f'<span data-i18n-tpl="sm_tpl_chg_surge" data-i18n-vals=\'["{gold_chg8:+.1f}"]\'>'
                    f'8周急涨 {gold_chg8:+.1f}%（>15%），超买风险 → -1</span>')
    elif -15 <= gold_chg8 <= -5:
        f_chg = 1
        chg_hint = (f'<span data-i18n-tpl="sm_tpl_chg_dip" data-i18n-vals=\'["{gold_chg8:+.1f}"]\'>'
                    f'健康回调 {gold_chg8:+.1f}%，加仓好时机 → +1</span>')
    else:
        f_chg = 0
        chg_hint = (f'<span data-i18n-tpl="sm_tpl_chg_neutral" data-i18n-vals=\'["{gold_chg8:+.1f}"]\'>'
                    f'近期涨跌 {gold_chg8:+.1f}%，无特别信号</span>')
    factors.append(('<span data-i18n="sm_factor_gold_chg">📈 近期金价变化（8周）</span>',
                    f"{gold_chg8:+.1f}%", f_chg, chg_hint, "var(--bg-elevated)"))

    # DXY
    dxy_sign = "+" if dxy_chg8 >= 0 else ""
    if dxy_chg8 < -2:
        f_dxy = 1
        dxy_hint = (f'<span data-i18n-tpl="sm_tpl_dxy_weak" data-i18n-vals=\'["{dxy_chg8:.1f}"]\'>'
                    f'美元8周贬值 {dxy_chg8:.1f}%，黄金顺风 → +1</span>')
        if -15 <= gold_chg8 <= -5 and cot_pct <= 70:
            dxy_hint += '<span data-i18n="sm_tpl_dxy_resonance">（+回调+COT不拥挤 = 三重共振额外 +1）</span>'
    else:
        f_dxy = 0
        dxy_hint = (f'<span data-i18n-tpl="sm_tpl_dxy_neutral" data-i18n-vals=\'["{dxy_sign}{dxy_chg8:.1f}"]\'>'
                    f'美元变化 {dxy_sign}{dxy_chg8:.1f}%，无顺风信号</span>')
    factors.append(('<span data-i18n="sm_factor_dxy">💵 美元（DXY 8周变化）</span>',
                    f"{dxy_sign}{dxy_chg8:.1f}%（{dxy_val}）", f_dxy, dxy_hint, "var(--bg-elevated)"))

    # COT
    f_cot = -1 if cot_pct > 85 else 0
    if f_cot < 0:
        cot_hint = (f'<span data-i18n-tpl="sm_tpl_cot_crowded" data-i18n-vals=\'["{cot_pct:.0f}"]\'>'
                    f'机构仓位极度拥挤（{cot_pct:.0f}%分位）→ -1</span>')
    else:
        cot_hint = (f'<span data-i18n-tpl="sm_tpl_cot_neutral" data-i18n-vals=\'["{cot_pct:.0f}"]\'>'
                    f'机构仓位 {cot_pct:.0f}% 分位，无风险信号</span>')
    factors.append(('<span data-i18n="sm_factor_cot">📋 COT 机构仓位</span>',
                    f"{cot_pct:.0f}% 分位", f_cot, cot_hint,
                    "#ef444422" if f_cot < 0 else "var(--bg-elevated)"))

    # HV
    if hv_pct > 90:
        hv_note = (f'<span data-i18n-tpl="sm_tpl_hv_extreme" data-i18n-vals=\'["{hv_pct:.0f}"]\'>'
                   f'波动率极端（{hv_pct:.0f}%分位）— 建议分批入场，不影响星级</span>')
    elif hv_pct > 70:
        hv_note = (f'<span data-i18n-tpl="sm_tpl_hv_high" data-i18n-vals=\'["{hv_pct:.0f}"]\'>'
                   f'波动率偏高（{hv_pct:.0f}%分位）— 正常牛市波动</span>')
    else:
        hv_note = (f'<span data-i18n-tpl="sm_tpl_hv_normal" data-i18n-vals=\'["{hv_pct:.0f}"]\'>'
                   f'波动率正常（{hv_pct:.0f}%分位）</span>')
    factors.append(('<span data-i18n="sm_factor_hv">📊 波动率（HV 20W）参考</span>',
                    f"{hv_val}%（{hv_pct:.0f}%分位）", 0, hv_note, "var(--bg-elevated)"))

    # 总分说明
    score_color = "#1aae39" if stars_final >= 4 else "#f97316" if stars_final == 3 else "#e03e3e"
    total_line = (
        f'<div style="font-size:0.82rem;color:#9b9691;margin:0.5rem 0 0.75rem;padding:0.5rem 0.75rem;'
        f'background:var(--bg-elevated);border-radius:8px;border:1px solid var(--border);">'
        f'<span data-i18n="sm_score_total">得分合计：</span>'
        f'<strong style="color:{score_color};">{score:+d}</strong> → '
        f'<strong style="color:{score_color};">{stars_final}★</strong>'
        f'&nbsp;&nbsp;<span style="color:#615d59;" data-i18n="sm_score_default">（默认持有=3★，加仓信号→4/5★，风险信号→2/1★）</span>'
        f'</div>'
    )

    html_cards = total_line
    for name, val, f, hint, bg in factors:
        if f == 0: continue
        html_cards += f"""<div class="sm-ind-card" style="background:{bg};">
  <div class="sm-ind-name">{name}</div>
  <div class="sm-ind-val">{val} &nbsp; {_badge(f)}</div>
  <div class="sm-ind-hint">{hint}</div>
</div>"""

    if score == 0:
        html_cards += f"""<div class="sm-ind-card">
  <div class="sm-ind-name" data-i18n="sm_status_title">📊 当前状态</div>
  <div class="sm-ind-val" data-i18n="sm_no_signal">无特别信号</div>
  <div class="sm-ind-hint" data-i18n="sm_no_signal_hint">趋势健康，无加仓/降险触发条件 → 持有即可，3★ NEUTRAL</div>
</div>"""
    return html_cards


def _btc_factor_cards(indicators: list) -> str:
    """BTC 因子卡片：200周均线偏离度（核心锚）+ 资金费率（调整）"""
    by_key = {i["key"]: i for i in indicators}
    trend_val   = by_key.get("btc_trend", {}).get("value", None)
    funding_pct = float(by_key.get("funding", {}).get("pct", 50) or 50)
    funding_val = by_key.get("funding", {}).get("value", "—")

    oi_raw = by_key.get("oi", {}).get("value", None)
    try:
        dev_val = float(str(oi_raw).replace("+", "")) if oi_raw is not None else 50.0
    except Exception:
        dev_val = 50.0
    if trend_val is False:
        dev_val = -1.0

    # 与 _btc_stars 同步
    if dev_val <= 20:    base = 5
    elif dev_val <= 60:  base = 4
    elif dev_val <= 100: base = 3
    elif dev_val <= 150: base = 2
    else:                base = 1

    bonus   = 1 if funding_pct < 20 else 0
    penalty = 1 if funding_pct > 80 else 0
    adj     = bonus - penalty
    final   = max(1, min(5, base + adj))

    # 偏离度区间说明
    if dev_val <= 0:
        dev_zone = '<span data-i18n="sm_btc_zone_5">跌破/贴近200周均线，历史极底区 → 基础 5★</span>'; dev_bg = "#22c55e22"
    elif dev_val <= 40:
        dev_zone = '<span data-i18n="sm_btc_zone_4">温和偏高，合理入场区 → 基础 4★</span>'; dev_bg = "#86efac22"
    elif dev_val <= 80:
        dev_zone = '<span data-i18n="sm_btc_zone_3">偏贵，历史中高位 → 基础 3★</span>'; dev_bg = "#fbbf2422"
    elif dev_val <= 140:
        dev_zone = '<span data-i18n="sm_btc_zone_2">明显高估，历史高位 → 基础 2★</span>'; dev_bg = "#f9731622"
    else:
        dev_zone = '<span data-i18n="sm_btc_zone_1">严重泡沫区 → 基础 1★</span>'; dev_bg = "#ef444422"

    dev_display = f"{dev_val:+.1f}%" if isinstance(dev_val, float) else str(dev_val)
    btc_ma_val = by_key.get("oi", {}).get("ma200", None)
    btc_price_now = by_key.get("oi", {}).get("price_now", None)

    # 资金费率调整说明
    if bonus == 1:
        fund_hint = (f'<span data-i18n-tpl="sm_tpl_btc_funding_low" data-i18n-vals=\'["{funding_pct:.0f}"]\'>'
                     f'资金费率极低/负值（{funding_pct:.0f}%分位），多头不拥挤 → +1</span>')
        fund_bg   = "#22c55e22"
        adj_label = f'<span style="color:#22c55e;font-weight:700;">+1</span>'
    elif penalty == 1:
        fund_hint = (f'<span data-i18n-tpl="sm_tpl_btc_funding_high" data-i18n-vals=\'["{funding_pct:.0f}"]\'>'
                     f'资金费率极高（{funding_pct:.0f}%分位），多头严重拥挤 → -1</span>')
        fund_bg   = "#ef444422"
        adj_label = f'<span style="color:#ef4444;font-weight:700;">-1</span>'
    else:
        fund_hint = (f'<span data-i18n-tpl="sm_tpl_btc_funding_neutral" data-i18n-vals=\'["{funding_pct:.0f}"]\'>'
                     f'资金费率正常（{funding_pct:.0f}%分位），无调整</span>')
        fund_bg   = "var(--bg-elevated)"
        adj_label = '<span style="color:#615d59;">0（中性）</span>'

    final_color = "#1aae39" if final >= 4 else "#f97316" if final == 3 else "#e03e3e"
    total_line = (
        f'<div style="font-size:0.82rem;color:#9b9691;margin:0.5rem 0 0.75rem;padding:0.5rem 0.75rem;'
        f'background:var(--bg-elevated);border-radius:8px;border:1px solid var(--border);">'
        f'<span data-i18n="sm_btc_base_stars">基础星级：</span>{base}★ &nbsp;|&nbsp; '
        f'<span data-i18n="sm_btc_adj_label">调整（Funding）：</span>{adj_label} &nbsp;|&nbsp; '
        f'<span data-i18n="sm_btc_final_stars">最终：</span>'
        f'<strong style="color:{final_color};">{final}★</strong>'
        f'<br><span data-i18n="sm_btc_range_note" style="color:#615d59;font-size:0.78rem;">'
        f'区间：≤0%偏离=5★，0-40%=4★，40-80%=3★，80-140%=2★，>140%=1★；调整最多±1</span>'
        f'</div>'
    )

    html_cards = total_line
    html_cards += f"""<div class="sm-ind-card" style="background:{dev_bg};">
  <div class="sm-ind-name" data-i18n="sm_factor_btc_dev">📊 200周均线偏离度（核心估值锚）</div>
  <div class="sm-ind-val" style="font-size:1.1rem;font-weight:700;">{dev_display}</div>
  <div class="sm-ind-hint">{dev_zone}</div>
</div>
<div class="sm-ind-card" style="background:{fund_bg};">
  <div class="sm-ind-name" data-i18n="sm_factor_btc_funding">⚡ 资金费率（杠杆拥挤度）</div>
  <div class="sm-ind-val"><span data-i18n-tpl="sm_tpl_funding_annualized" data-i18n-vals='["{funding_val}","{funding_pct:.0f}"]'>年化 {funding_val}%（{funding_pct:.0f}%分位）</span></div>
  <div class="sm-ind-hint">{fund_hint}</div>
</div>"""
    return html_cards


def build_smart_tab_html(data: dict) -> str:
    """
    生成「智能仪表盘」Tab 的完整 HTML，包含 CSS + JS + 内容。
    data: smart_money_data.json 的内容。
    """
    gold_state = data["gold"]["state"]
    btc_state  = data["btc"]["state"]
    gold_score = data["gold"]["score"]
    btc_score  = data["btc"]["score"]
    gold_stars = data["gold"].get("stars", 3)
    btc_stars  = data["btc"].get("stars", 3)
    gold_star_str = "⭐" * gold_stars
    btc_star_str  = "⭐" * btc_stars

    gold_inds = data["gold"]["indicators"]
    btc_inds  = data["btc"]["indicators"]

    # 只显示真正参与星级计算的因子卡片
    gold_cards = _gold_factor_cards(gold_inds)
    btc_cards  = _btc_factor_cards(btc_inds)

    gold_acc_text = _accuracy_text(data.get("accuracy", {}).get("gold", {}), "黄金")
    btc_acc_text  = _accuracy_text(data.get("accuracy", {}).get("btc",  {}), "BTC")

    bt_gold_records = list(data.get("backtest_gold", []))
    bt_btc_records  = list(data.get("backtest_btc",  []))

    # 确保图表最右端 = 当前实时星级（追加今日数据点，若最后一条不是今天）
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    if bt_gold_records:
        last = bt_gold_records[-1]
        if last["stars"] != gold_stars or last["signal"] != gold_state:
            bt_gold_records.append({
                "date": today_str,
                "price": last["price"],  # 用上周价格近似（避免需要单独抓取）
                "signal": gold_state,
                "stars": gold_stars,
                "score": gold_stars * 20,
            })
    if bt_btc_records:
        last = bt_btc_records[-1]
        if last["stars"] != btc_stars or last["signal"] != btc_state:
            bt_btc_records.append({
                "date": today_str,
                "price": last["price"],
                "signal": btc_state,
                "stars": btc_stars,
                "score": btc_stars * 20,
            })

    # Generate SVG charts server-side — no JS/CDN dependency
    gold_svg = _draw_svg_chart(bt_gold_records, "黄金价格 (USD/oz)", "#f59e0b")
    btc_svg  = _draw_svg_chart(bt_btc_records,  "BTC 价格 (USD)",    "#f97316")

    updated = data.get("updated_at", "")

    css = """
<style>
/* ── Smart Money Tab ────────────────────────────────── */
.sm-asset-tabs { display:flex; gap:0.5rem; margin-bottom:1.25rem; }
.sm-asset-btn { padding:0.4rem 1.1rem; border-radius:var(--radius-sm,6px); border:1px solid var(--border);
  background:var(--bg-elevated); color:var(--text-muted); cursor:pointer; font-size:0.85rem;
  transition:all .12s; font-family:inherit; }
.sm-asset-btn.active { background:var(--accent); color:#111110; border-color:var(--accent); }

.sm-state-badge { display:inline-flex; align-items:center; gap:0.6rem;
  padding:0.6rem 1.4rem; border-radius:var(--radius-lg,14px); font-size:1.25rem; font-weight:700;
  margin-bottom:1rem; }

.sm-state-desc { font-size:0.875rem; color:var(--text-muted); margin-bottom:1.25rem; }

.sm-ind-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:0.75rem; margin-bottom:1.5rem; }
.sm-ind-card { background:var(--bg-elevated); border:1px solid var(--border);
  border-radius:var(--radius-md,10px); padding:0.9rem 1rem;
  box-shadow:0 1px 2px rgba(0,0,0,0.3),0 2px 4px rgba(0,0,0,0.2); }
.sm-ind-name { font-size:0.72rem; color:var(--text-muted); margin-bottom:0.3rem; font-weight:500; }
.sm-ind-val  { font-size:1.1rem; font-weight:700; margin-bottom:0.4rem; letter-spacing:-0.01em; }
.sm-pct-bar-wrap { background:var(--border); border-radius:4px; height:4px;
  margin-bottom:0.3rem; overflow:hidden; }
.sm-pct-bar { height:100%; border-radius:4px; transition:width .4s; }
.sm-pct-label { font-size:0.72rem; font-weight:600; }
.sm-ind-hint { font-size:0.77rem; color:var(--text-muted); margin-top:0.4rem; line-height:1.5; white-space:pre-line; }
.sm-ind-note { font-size:0.72rem; color:var(--text-faint,#6b6560); margin-top:0.2rem; font-style:italic; }

.sm-chart-wrap { background:var(--bg-elevated); border:1px solid var(--border);
  border-radius:var(--radius-lg,14px); padding:1rem; margin-bottom:1rem;
  box-shadow:0 1px 2px rgba(0,0,0,0.4),0 2px 6px rgba(0,0,0,0.25),0 4px 12px rgba(0,0,0,0.15); }
.sm-chart-title { font-size:0.72rem; font-weight:700; color:var(--text-faint,#6b6560);
  text-transform:uppercase; letter-spacing:.06em; margin-bottom:0.75rem; }

.sm-accuracy { font-size:0.82rem; color:var(--text-muted); padding:0.7rem 1rem;
  background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-md,10px);
  margin-bottom:1rem; line-height:1.7; }
.sm-acc-note { display:block; font-size:0.74rem; color:var(--text-faint,#6b6560); margin-top:0.25rem; }
.sm-acc-caveat { display:block; font-size:0.75rem; color:#f97316; margin-top:0.3rem; }

.sm-updated { font-size:0.72rem; color:var(--text-faint,#6b6560); margin-bottom:0.5rem; }
.sm-disclaimer { font-size:0.72rem; color:var(--text-faint,#6b6560); border-top:1px solid var(--border);
  padding-top:0.6rem; margin-top:0.75rem; }

@media(max-width:640px){
  .sm-ind-grid { grid-template-columns:1fr 1fr; }
}
</style>"""

    js = """
<script>
// 子 Tab 切换
document.querySelectorAll('.sm-asset-btn').forEach(function(btn){
  btn.addEventListener('click', function(){
    document.querySelectorAll('.sm-asset-btn').forEach(function(b){b.classList.remove('active');});
    document.querySelectorAll('.sm-asset-panel').forEach(function(p){p.style.display='none';});
    btn.classList.add('active');
    var panel=document.getElementById('sm-panel-'+btn.dataset.asset);
    if(panel) panel.style.display='block';
  });
});
</script>"""

    gold_color = STATE_COLORS[gold_state]
    btc_color  = STATE_COLORS[btc_state]
    state_i18n = {"ACCUMULATE": "accumulate", "NEUTRAL": "neutral", "DE_RISK": "derisk"}

    # 提取当前价格
    gold_inds_map = {i["key"]: i for i in gold_inds}
    btc_inds_map  = {i["key"]: i for i in btc_inds}
    _bt_gold = data.get("backtest_gold", [])
    gold_price_now = (gold_inds_map.get("gold_trend", {}).get("price_now", None)
                      or (_bt_gold[-1]["price"] if _bt_gold else None))
    _bt_btc = data.get("backtest_btc", [])
    btc_price_now  = (btc_inds_map.get("oi", {}).get("price_now", None)
                      or btc_inds_map.get("btc_trend", {}).get("price_now", None)
                      or (_bt_btc[-1]["price"] if _bt_btc else None))
    gold_price_str = f"${gold_price_now:,.0f}" if gold_price_now else "—"
    btc_price_str  = f"${btc_price_now:,.0f}"  if btc_price_now  else "—"

    html = f"""
{css}
<style>
.sm-price-row {{display:flex;align-items:baseline;gap:0.5rem;margin-bottom:1rem;}}
.sm-price-val {{font-size:1.6rem;font-weight:700;letter-spacing:-0.03em;}}
.sm-price-label {{font-size:0.78rem;color:var(--text-muted);}}
.sm-price-today {{font-size:0.72rem;color:var(--text-faint);}}
</style>

<div class="sm-updated"><span data-i18n="sm_updated">数据更新时间：</span>{updated}</div>

<!-- 子 Tab 切换 -->
<div class="sm-asset-tabs">
  <button class="sm-asset-btn active" data-asset="gold" data-i18n="sm_gold">🥇 黄金</button>
  <button class="sm-asset-btn" data-asset="btc" data-i18n="sm_btc">₿ 比特币</button>
</div>

<!-- 黄金面板 -->
<div class="sm-asset-panel" id="sm-panel-gold">
  <div class="sm-price-row">
    <span class="sm-price-label" data-i18n="sm_price_gold_label">黄金 (XAU/USD)</span>
    <span class="sm-price-val">{gold_price_str}</span>
    <span class="sm-price-today" data-i18n="sm_as_of_today">今日价格</span>
  </div>
  <div class="sm-state-badge" style="background:{gold_color}22;color:{gold_color};border:1.5px solid {gold_color}66;">
    <span data-i18n="sm_state_{state_i18n[gold_state]}">{STATE_LABELS_ZH[gold_state]}</span>
    <span style="font-size:1.1rem;margin-left:0.3rem;">{gold_star_str}</span>
    <span style="font-size:0.82rem;font-weight:400;opacity:0.75;margin-left:0.2rem;"
          data-i18n-tpl="sm_tpl_stars_timing" data-i18n-vals='["{gold_stars}"]'>{gold_stars}星 / 5星时机评分</span>
  </div>
  <div class="sm-state-desc" data-i18n="sm_desc_{state_i18n[gold_state]}">{STATE_DESC_ZH[gold_state]}</div>

  <div class="sm-chart-wrap">
    <div class="sm-chart-title">
      <span data-i18n="sm_chart_gold_title">📈 黄金时机评分（左轴）vs 金价（右轴）</span>&nbsp;
      <span style="color:#22c55e;" data-i18n="sm_chart_5star_gold">●5★ 时机极好</span>&nbsp;
      <span style="color:#86efac;">●4★</span>&nbsp;
      <span style="color:#fbbf24;" data-i18n="sm_chart_3star">●3★ 中性</span>&nbsp;
      <span style="color:#f97316;">●2★</span>&nbsp;
      <span style="color:#ef4444;" data-i18n="sm_chart_1star_gold">●1★ 时机差</span>
    </div>
    {gold_svg}
  </div>

  <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);margin:0.75rem 0 0.5rem;text-transform:uppercase;letter-spacing:.05em;"
       data-i18n-tpl="sm_factor_label_tpl" data-i18n-vals='["{gold_stars}"]'>🔍 当前评分因子（共 {gold_stars}★）</div>
  <div class="sm-ind-grid">{gold_cards}</div>
  {gold_acc_text}
</div>

<!-- BTC 面板 -->
<div class="sm-asset-panel" id="sm-panel-btc" style="display:none;">
  <div class="sm-price-row">
    <span class="sm-price-label" data-i18n="sm_price_btc_label">比特币 (BTC/USD)</span>
    <span class="sm-price-val">{btc_price_str}</span>
    <span class="sm-price-today" data-i18n="sm_as_of_today">今日价格</span>
  </div>
  <div class="sm-state-badge" style="background:{btc_color}22;color:{btc_color};border:1.5px solid {btc_color}66;">
    <span data-i18n="sm_state_{state_i18n[btc_state]}">{STATE_LABELS_ZH[btc_state]}</span>
    <span style="font-size:1.1rem;margin-left:0.3rem;">{btc_star_str}</span>
    <span style="font-size:0.82rem;font-weight:400;opacity:0.75;margin-left:0.2rem;"
          data-i18n-tpl="sm_tpl_stars_margin" data-i18n-vals='["{btc_stars}"]'>{btc_stars}星 / 5星安全边际</span>
  </div>
  <div class="sm-state-desc" data-i18n="sm_desc_{state_i18n[btc_state]}">{STATE_DESC_ZH[btc_state]}</div>

  <div class="sm-chart-wrap">
    <div class="sm-chart-title">
      <span data-i18n="sm_chart_btc_title">📈 BTC 安全边际（左轴）vs BTC 价格（右轴）</span>&nbsp;
      <span style="color:#22c55e;" data-i18n="sm_chart_5star_btc">●5★ 底部/接近均线</span>&nbsp;
      <span style="color:#86efac;">●4★</span>&nbsp;
      <span style="color:#fbbf24;" data-i18n="sm_chart_3star">●3★ 中性</span>&nbsp;
      <span style="color:#f97316;">●2★</span>&nbsp;
      <span style="color:#ef4444;" data-i18n="sm_chart_1star_btc">●1★ 泡沫高位</span>
    </div>
    {btc_svg}
  </div>

  <div style="font-size:0.8rem;font-weight:600;color:var(--text-muted);margin:0.75rem 0 0.5rem;text-transform:uppercase;letter-spacing:.05em;"
       data-i18n-tpl="sm_factor_label_tpl" data-i18n-vals='["{btc_stars}"]'>🔍 当前评分因子（共 {btc_stars}★）</div>
  <div class="sm-ind-grid">{btc_cards}</div>
  {btc_acc_text}
</div>

<div class="sm-disclaimer" data-i18n="sm_disclaimer">
  ⚠️ 本工具基于公开历史数据与统计方法，仅供个人参考，不构成投资建议。过往表现不代表未来结果。
</div>

{js}"""
    return html


def inject_tab_into_html(src_html: str, tab_html: str) -> str:
    """
    将智能仪表盘 Tab 注入到现有 index.html 中。
    在 Tab 导航栏添加按钮，在 </body> 前添加 Tab 面板（带密码保护，4小时过期）。
    """
    # 1. 在 tab-nav </ul> 前插入新按钮
    nav_btn = '      <li><button class="tab-btn" data-tab="smart" data-i18n="tab_smart">📊 智能仪表盘</button></li>\n'
    src_html = src_html.replace(
        '    </ul>\n  </header>',
        nav_btn + '    </ul>\n  </header>',
        1
    )

    # 2. 带密码保护的 Tab 面板（SHA-256 校验，4 小时 localStorage 过期）
    PWD_HASH = "5fc4ebd05f7af1c722eb400bdcd51826a461423b88ee11163b13cdbe567834ae"
    panel = f"""
  <div id="tab-smart" class="tab-panel" role="tabpanel">
    <h2 data-i18n="tab_smart">📊 智能仪表盘</h2>

    <!-- 密码锁屏 -->
    <div id="sm-lock-overlay" style="display:flex;justify-content:center;padding:4rem 0;">
      <div style="background:var(--bg-elevated);border:1px solid var(--border-strong);border-radius:var(--radius-lg);padding:2rem;width:100%;max-width:320px;text-align:center;box-shadow:var(--shadow-card);">
        <div style="font-size:2rem;margin-bottom:0.75rem;">🔒</div>
        <div style="font-weight:600;font-size:1rem;margin-bottom:1.25rem;" data-i18n="sm_lock_title">请输入访问密码</div>
        <input type="password" id="sm-pwd-input" placeholder="密码"
          data-i18n-placeholder="sm_lock_placeholder"
          style="width:100%;padding:0.55rem 0.75rem;background:var(--bg);border:1px solid var(--border-strong);border-radius:var(--radius-sm);color:var(--text);font-family:inherit;font-size:0.9rem;margin-bottom:0.75rem;outline:none;" />
        <button id="sm-pwd-btn"
          style="width:100%;padding:0.55rem;background:var(--accent);border:none;border-radius:var(--radius-sm);color:#fff;font-family:inherit;font-size:0.9rem;font-weight:600;cursor:pointer;"
          data-i18n="sm_lock_btn">解锁
        </button>
        <div id="sm-pwd-err" style="display:none;color:#e03e3e;font-size:0.82rem;margin-top:0.75rem;"
             data-i18n="sm_lock_error">密码错误，请重试</div>
      </div>
    </div>

    <!-- 实际内容（解锁后显示） -->
    <div id="sm-content" style="display:none;">
{tab_html}
    </div>

    <script>
(function(){{
  var HASH = '{PWD_HASH}';
  var EXPIRE = 4 * 60 * 60 * 1000;
  var KEY = 'sm-unlock-until';

  function isUnlocked() {{
    var v = localStorage.getItem(KEY);
    return v && Date.now() < parseInt(v, 10);
  }}
  function showContent() {{
    document.getElementById('sm-lock-overlay').style.display = 'none';
    document.getElementById('sm-content').style.display = 'block';
  }}
  function showLock() {{
    document.getElementById('sm-lock-overlay').style.display = 'flex';
    document.getElementById('sm-content').style.display = 'none';
  }}

  if (isUnlocked()) showContent();

  async function tryUnlock() {{
    var pwd = document.getElementById('sm-pwd-input').value;
    var buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(pwd));
    var hex = Array.from(new Uint8Array(buf)).map(function(b){{ return b.toString(16).padStart(2,'0'); }}).join('');
    if (hex === HASH) {{
      localStorage.setItem(KEY, String(Date.now() + EXPIRE));
      showContent();
    }} else {{
      document.getElementById('sm-pwd-err').style.display = 'block';
      document.getElementById('sm-pwd-input').value = '';
      document.getElementById('sm-pwd-input').focus();
    }}
  }}

  document.getElementById('sm-pwd-btn').addEventListener('click', tryUnlock);
  document.getElementById('sm-pwd-input').addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') tryUnlock();
    else document.getElementById('sm-pwd-err').style.display = 'none';
  }});

  // 每次切换到此 Tab 时检查是否过期
  var panel = document.getElementById('tab-smart');
  new MutationObserver(function() {{
    if (panel.classList.contains('active') && !isUnlocked()) showLock();
  }}).observe(panel, {{ attributes: true, attributeFilter: ['class'] }});
}})();
    </script>
  </div>
"""
    marker = '\n  <div class="global-footer-actions">'
    if marker in src_html:
        src_html = src_html.replace(marker, panel + marker, 1)
    else:
        src_html = src_html.replace('</body>', panel + '</body>', 1)

    return src_html


# ══════════════════════════════════════════════════════════════════════
# 7. 主函数
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="生成黄金 & BTC 智能仪表盘（本地专用）")
    parser.add_argument("--no-fetch", action="store_true",
                        help="跳过数据抓取，使用缓存的 smart_money_data.json 重建页面")
    args = parser.parse_args()

    if args.no_fetch and DATA_FILE.exists():
        print("使用缓存数据...")
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
    else:
        print("=== 抓取黄金指标 ===")
        gold_inds = build_gold_indicators()
        gold_state, gold_stars = state_machine_gold(gold_inds)
        gold_score = gold_stars * 20  # 1-5星 → 20-100分

        print("=== 抓取 BTC 指标 ===")
        btc_inds  = build_btc_indicators()
        btc_state, btc_stars = state_machine_btc(btc_inds)
        btc_score = btc_stars * 20

        print("=== 运行回测 ===")
        bt_gold, acc_gold = backtest_gold(208)
        bt_btc,  acc_btc  = backtest_btc(208)

        # 追加"今日"实时数据点到回测末尾，确保图表最右端 = 顶部显示的星级
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        gold_price_now = next(
            (i["value"] for i in gold_inds if i["key"] == "gold_trend"), None
        )
        # gold_trend value is bool; get actual price from gold_hv or use last bt price
        gold_price_now = bt_gold[-1]["price"] if bt_gold else 0
        # Try to get actual price from indicators
        for ind in gold_inds:
            if ind["key"] in ("gold_hv",) and isinstance(ind.get("value"), (int, float)):
                pass  # HV is not price
        # Use last known backtest price as approximation (same week or +small delta)
        if bt_gold and bt_gold[-1]["date"] != today_str:
            bt_gold.append({
                "date": today_str,
                "price": bt_gold[-1]["price"],  # approximate with last known
                "signal": gold_state,
                "stars": gold_stars,
                "score": gold_score,
            })
        if bt_btc and bt_btc[-1]["date"] != today_str:
            bt_btc.append({
                "date": today_str,
                "price": bt_btc[-1]["price"],
                "signal": btc_state,
                "stars": btc_stars,
                "score": btc_score,
            })

        data = {
            "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "gold": {"state": gold_state, "score": gold_score, "stars": gold_stars, "indicators": gold_inds},
            "btc":  {"state": btc_state,  "score": btc_score,  "stars": btc_stars,  "indicators": btc_inds},
            "backtest_gold": bt_gold,
            "backtest_btc":  bt_btc,
            "accuracy": {"gold": acc_gold, "btc": acc_btc},
        }

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"已写入 {DATA_FILE}")

    print("=== 生成 HTML ===")
    tab_html = build_smart_tab_html(data)

    if not INDEX_SRC.exists():
        print(f"错误：找不到 {INDEX_SRC}")
        sys.exit(1)

    with open(INDEX_SRC, encoding="utf-8") as f:
        src = f.read()

    result = inject_tab_into_html(src, tab_html)

    with open(INDEX_OUT, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"已生成 {INDEX_OUT}")
    print()
    print("本地预览：")
    print("  cd /Users/yiyzhu/ca-savings-rates")
    print("  python3 -m http.server 8080")
    print("  然后打开 http://localhost:8080/index_local.html")


if __name__ == "__main__":
    main()
