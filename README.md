# 🍁 新移民资讯中心 — 加拿大利率 & 房产数据

**网站地址：[zyy198520038.github.io/ca-savings-rates](https://zyy198520038.github.io/ca-savings-rates/)**

面向加拿大新移民的数据仪表盘，汇总高息储蓄利率、GIC 定存利率与大温哥华房产市场数据，支持中英法三语切换。

---

## 功能

### 💰 利率 Tab
- **高息储蓄 Top 3**：自动抓取 RateHub 和 HighInterestSavings.ca，按六大行 / 知名银行 / 全部筛选
- **GIC 定存利率**：各期限（1–5 年）Top 3，同步筛选
- **每周自动更新**（每周一早上 8 点温哥华时间）
- 支持邮件订阅，每周一收到当期 Top 3 推送

### 🏠 房产 Tab（大温哥华）
- **市场概况**：各房型（独立屋 / 联排 / 公寓）基准价、成交量、库存、销售比
- **各区域数据**：35 个区域的 HPI 基准价及各周期涨跌幅
- **💡 市场机遇**：算法识别买方优势、抗跌区域、触底反弹、价格修正等投资信号
- **每月自动更新**（每月 5 号，数据来自 Greater Vancouver REALTORS®）

---

## 自动更新机制

| 触发时间 | 内容 |
|---------|------|
| 每周一 15:00 UTC | 更新高息储蓄 & GIC 利率 |
| 每月 5 号 16:00 UTC | 强制重新抓取房产数据 |
| 手动触发 | Actions 页面可手动运行，支持强制刷新房产数据 |

---

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt
playwright install chromium --with-deps

# 设置环境变量
export FIRECRAWL_API_KEY="你的 key"   # 从 firecrawl.dev 获取

# 完整抓取（利率 + 房产）并生成 index.html
python scrape_and_build.py

# 仅用缓存数据重建页面（不重新抓取）
python scrape_and_build.py --rebuild-property
```

---

## 邮件订阅配置（可选）

在仓库 **Settings → Secrets and variables → Actions** 中配置：

| Secret | 说明 |
|--------|------|
| `FIRECRAWL_API_KEY` | [Firecrawl](https://firecrawl.dev) API Key，用于抓取网页 |
| `RESEND_API_KEY` | [Resend](https://resend.com) API Key，用于发送订阅邮件 |
| `RESEND_FROM_EMAIL` | 发件人邮箱（需在 Resend 中验证） |

订阅者列表存储在 `subscribers.json` 中，每周一 Action 运行时自动发信。未配置 Resend 相关 Secret 时仅更新网页，不发信。

---

## 数据来源

- 储蓄利率：[RateHub](https://www.ratehub.ca/savings-accounts/accounts/high-interest)、[HighInterestSavings.ca](https://www.highinterestsavings.ca/chart/)
- GIC 利率：[RateHub GIC](https://www.ratehub.ca/gics/best-gic-rates)
- 房产数据：[Greater Vancouver REALTORS®](https://www.gvrealtors.ca/market-watch/monthly-market-report/) MLS® HPI

> 数据仅供参考，实际以各银行及 GVR 官网为准。
