# 加拿大高息储蓄 Top 3

每周自动从 [RateHub](https://www.ratehub.ca/savings-accounts/accounts/high-interest) 和 [HighInterestSavings.ca](https://www.highinterestsavings.ca/chart/) 抓取储蓄利率，汇总后展示**当前最高的 3 条**，并标注条件（如：首 N 个月促销、需新资金、需新开户等）。

- **网站**：用 GitHub Pages 托管，你打开链接即可查看。
- **更新**：GitHub Action 每周一（UTC 15:00，温哥华约早上 8 点）自动跑一次；也可在仓库的 Actions 里手动运行。

---

## 本地运行（可选）

1. 安装依赖：`pip install -r requirements.txt`
2. 到 [Firecrawl](https://firecrawl.dev) 注册并获取 API Key。
3. 设置环境变量并执行：
   ```bash
   export FIRECRAWL_API_KEY="你的 key"
   python scrape_and_build.py
   ```
4. 当前目录会生成 `index.html` 和 `top3.json`。

---

## 部署到 GitHub Pages（推荐）

1. **新建仓库**  
   在 GitHub 上新建一个仓库（例如 `ca-savings-rates`），把本地的 `config.py`、`scrape_and_build.py`、`requirements.txt`、`README.md` 以及 `.github/workflows/update-rates.yml` 推上去。

2. **配置 Firecrawl API Key**  
   - 仓库页 → **Settings** → **Secrets and variables** → **Actions**  
   - 点 **New repository secret**，名称填 `FIRECRAWL_API_KEY`，值填你在 Firecrawl 拿到的 API Key。

3. **开启 GitHub Pages**  
   - 仓库 **Settings** → **Pages**  
   - **Source** 选 **Deploy from a branch**  
   - **Branch** 选 `main`（或你的默认分支），**Folder** 选 **/ (root)**  
   - 保存后，等几分钟即可通过 `https://<你的用户名>.github.io/<仓库名>/` 访问。

4. **第一次生成页面**  
   - 若仓库里还没有 `index.html`，可到 **Actions** 里运行一次 **Update savings rates** workflow；或本地运行 `scrape_and_build.py` 后把生成的 `index.html`（和可选 `top3.json`）提交并推送。  
   - 之后每周会自动更新，你只需打开上述链接查看。

---

## 数据说明

- 数据来源于第三方比价网站，仅供参考，实际以各银行官网为准。
- 条件一列会尽量标注「首 N 个月促销」「需新资金」「需新开户」等；若无法自动识别则显示「见官网」。
