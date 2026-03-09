# 数据源：加拿大储蓄利率比价页
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

# 可选：只保留这些银行（None = 不过滤，显示所有）
BANK_WHITELIST = None  # 例如: ["TD", "RBC", "Scotiabank", "Tangerine", "EQ Bank", "Simplii", ...]

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
