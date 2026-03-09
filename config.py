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
