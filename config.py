import os

# 邮件订阅：Formspree 表单 ID（在 https://formspree.io 建表单后得到，如 xyzabc）
# 填好后访客提交的邮箱会发到你邮箱，你手动加入 subscribers.json 并 push
FORMSPREE_FORM_ID = "xnjgjpaa"

# 请我喝杯咖啡：填 Stripe Payment Link 或 Ko-fi / Buy Me a Coffee 等链接，留空则不显示
# 在 Stripe Dashboard 创建 One-time payment 即可得到 Payment Link
COFFEE_URL = "https://buy.stripe.com/eVq4gA98f3GH3yS3FdaEE00"

# 网站公开 URL，用于邮件中「访问网站」按钮。可覆盖为环境变量 SITE_URL
SITE_URL = os.environ.get("SITE_URL", "https://zyy198520038.github.io/ca-savings-rates/")

# 数据源：加拿大储蓄利率比价页（活期/短期高息储蓄）
SOURCES = [
    {
        "name": "RateHub",
        "url": "https://www.ratehub.ca/savings-accounts/accounts/high-interest",
        "parser": "ratehub",
    },
    {
        "name": "HighInterestSavings.ca",
        "url": "https://www.highinterestsavings.ca/chart/",
        "parser": "highinterestsavings",
    },
]

# GIC 定存利率数据源（同法抓取）
GIC_SOURCES = [
    {
        "name": "RateHub GIC",
        "url": "https://www.ratehub.ca/gics/best-gic-rates",
        "parser": "ratehub_gic",
    },
]

# 温哥华房产数据源
PROPERTY_METRO_URL_TEMPLATE = "https://www.gvrealtors.ca/market-watch/monthly-market-report/{month}-{year}.html"
PROPERTY_AREAS_URL = "https://www.gvrealtors.ca/market-watch/summary-of-homes-listed-and-sold.html"
PROPERTY_AREAS = [
    "Vancouver West", "Vancouver East", "Burnaby", "New Westminster",
    "Richmond", "Coquitlam", "Port Coquitlam", "Port Moody",
    "North Vancouver", "West Vancouver", "Maple Ridge", "South Delta",
]
PROPERTY_TYPES = ["Detached", "Attached", "Apartment"]

# 可选：只保留这些银行（None = 不过滤，显示所有）
BANK_WHITELIST = None  # 例如: ["TD", "RBC", "Scotiabank", "Tangerine", "EQ Bank", "Simplii", ...]

# 银行/产品名中的子串（小写）-> 类型/可信度，用于表格「类型」列。未匹配的显示「其他」。
# 六大行：加拿大六大商业银行（CDIC 成员，系统重要性高）
# 知名银行/直销：常见直销/网络银行或大型机构旗下
# 信贷/中小机构：信用合作社或规模较小的 CDIC 成员
BANK_TIER = {
    "rbc": "六大行",
    "royal bank": "六大行",
    "td bank": "六大行",
    "bmo": "六大行",
    "bank of montreal": "六大行",
    "scotiabank": "六大行",
    "cibc": "六大行",
    "national bank": "六大行",
    "tangerine": "知名银行/直销",
    "simplii": "知名银行/直销",
    "eq bank": "知名银行/直销",
    "oaken financial": "知名银行/直销",
    "wealthsimple": "知名银行/直销",
    "manulife bank": "知名银行/直销",
    "canadian tire bank": "知名银行/直销",
    "pc financial": "知名银行/直销",
    "neo financial": "知名银行/直销",
    "meridian credit": "知名银行/直销",
    "alterna bank": "信贷/中小机构",
    "peoples trust": "信贷/中小机构",
    "home trust": "信贷/中小机构",
    "achieva": "信贷/中小机构",
    "hubert financial": "信贷/中小机构",
    "saven financial": "知名银行/直销",
    "wealth one": "信贷/中小机构",
    "laurentian bank": "知名银行/直销",
    "bridgewater bank": "信贷/中小机构",
    "outlook financial": "信贷/中小机构",
    "lbc digital": "信贷/中小机构",
    "icici bank canada": "知名银行/直销",
    "mcan wealth": "信贷/中小机构",
    "koho": "知名银行/直销",
    "ci direct": "知名银行/直销",
}

# GIC 产品名中的子串（小写）-> 该银行 GIC 官方页面，用于 GIC 表格「链接」列
# 未匹配的仍显示比价页链接
GIC_LINKS = {
    "rbc": "https://www.rbcroyalbank.com/investments/gic-rates.html",
    "td bank": "https://www.td.com/ca/en/personal-banking/personal-investing/products/gic/gic-rates-canada",
    "bmo": "https://www.bmo.com/main/personal/investments/gics/",
    "scotiabank": "https://www.scotiabank.com/ca/en/personal/rates-prices/gic-rates.html",
    "cibc": "https://www.cibc.com/en/personal-banking/investments/gics.html",
    "national bank": "https://www.nbc.ca/personal/rates/gic-rates.html",
    "eq bank": "https://www.eqbank.ca/personal-banking/investments/gics",
    "oaken financial": "https://www.oaken.com/gics/",
    "tangerine": "https://www.tangerine.ca/en/rates/",
    "simplii financial": "https://www.simplii.com/en/investments/gics.html",
    "alterna bank": "https://www.alternabank.ca/savings-investments/gics",
    "peoples trust": "https://www.peoplestrust.com/en/peoples-trust/investments/gics/",
    "meridian credit": "https://www.meridiancu.ca/Invest/GICs.aspx",
    "achieva": "https://www.achieva.mb.ca/gics",
    "hubert financial": "https://happysavings.ca/gics/",
    "saven financial": "https://savenfinancial.ca/en/gics",
    "mcan wealth": "https://www.mcanwealth.com/gic-rates/",
    "icici bank canada": "https://www.icicibank.ca/ca-en/savings-invest/gic.html",
    "lbc digital": "https://www.lbcdigital.ca/en/rates/",
}

# 银行/产品名 -> 官方营销页（用于「链接」列，优先于比价站链接）
# 键为产品名中出现的子串（小写匹配），会按键长度从长到短匹配，先匹配到的生效
BANK_LINKS = {
    "scotiabank momentum": "https://www.scotiabank.com/ca/en/personal/bank-accounts/savings-accounts/momentum-plus-savings-account.html",
    "simplii financial": "https://www.simplii.com/en/bank-accounts/high-interest-savings.html",
    "tangerine savings": "https://www.tangerine.ca/en/personal/save/savings-account",
    "tangerine": "https://www.tangerine.ca/en/rates",
    "rbc high-interest": "https://www.rbcroyalbank.com/bank-accounts/savings-accounts/high-interest-savings-account.html",
    "rbc": "https://www.rbcroyalbank.com/accounts/e-savings.html",
    "cibc eadvantage": "https://www.cibc.com/en/personal-banking/bank-accounts/savings-accounts/eadvantage-high-interest-savings-account.html",
    "cibc": "https://www.cibc.com/en/personal-banking/bank-accounts/savings-accounts.html",
    "eq bank": "https://www.eqbank.ca/personal-banking/personal-account",
    "eq bank notice": "https://www.eqbank.ca/personal-banking/notice-savings-account",
    "neo financial": "https://www.neofinancial.com/savings",
    "neo savings": "https://www.neofinancial.com/savings",
    "oaken financial": "https://www.oaken.com/oaken-savings-account/",
    "wealthsimple": "https://www.wealthsimple.com/en-ca/product/cash",
    "canadian tire bank": "https://www.ctfs.com/content/ctfs/en/retailbanking/hisa_info.html",
    "koho": "https://www.koho.ca/",
    "saven financial": "https://savenfinancial.ca/en/on-high-interest-savings-account",
    "wealth one": "https://www.wealthonebankofcanada.com/Bank/High+interest+savings+account",
    "laurentian bank": "https://www.laurentianbank.ca/en/personal/bank-accounts/savings-accounts/high-interest-savings-account",
    "manulife bank": "https://www.manulifebank.ca/personal-banking/bank-accounts/high-interest-chequing-savings-account.html",
    "peoples trust": "https://www.peoplestrust.com/en/peoples-trust/high-interest-accounts/savings/e-savings/",
    "alterna bank": "https://www.alternabank.ca/everyday-banking/high-interest-esavings",
    "home trust": "https://www.hometrust.ca/deposits/",
    "achieva": "https://www.achieva.mb.ca/daily-interest-savings-account",
    "coast capital": "https://www.coastcapitalsavings.com/",
    "hubert financial": "https://happysavings.ca/high-interest-accounts/",
    "pc financial": "https://www.pcfinancial.ca/en/pc-money-account/",
    "bridgewater bank": "https://bridgewaterbank.ca/savings/savings-accounts/rates-features/",
    "outlook financial": "https://www.outlookfinancial.com/products/savings-account",
    "maxa financial": "https://maxafinancial.com/products/",
    "steinbach credit": "https://scu.mb.ca/personal/personal-savings-accounts/",
    "ci direct": "https://www.ci.com/",
}
