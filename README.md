# 加拿大高息储蓄 Top 3

https://zyy198520038.github.io/ca-savings-rates/

每周自动从 [RateHub](https://www.ratehub.ca/savings-accounts/accounts/high-interest) 和 [HighInterestSavings.ca](https://www.highinterestsavings.ca/chart/) 抓取储蓄利率，汇总后展示**当前最高的 3 条**，并标注条件（如：首 N 个月促销、需新资金、需新开户等）。

- **网站**：用 GitHub Pages 托管，你打开链接即可查看。
- **更新**：GitHub Action 每周一（UTC 15:00，温哥华约早上 8 点）自动跑一次；也可在仓库的 Actions 里手动运行。
- **邮件订阅**：访客在页面填写邮箱后，你把他们加入 `subscribers.json`，每周一他们会收到当周 Top 3 的邮件推送。

---

## 邮件订阅（可选）

1. **收集邮箱**：在 [Formspree](https://formspree.io) 注册并新建一个表单，得到表单 ID（如 `xyzabc`）。在 `config.py` 里填 `FORMSPREE_FORM_ID = "xyzabc"`，重新生成并推送 `index.html` 后，页面上的订阅表单会把提交的邮箱发到你的 Formspree 邮箱。
2. **保存订阅者**（二选一）：
   - **自动同步（推荐）**：把本仓库部署到 [Vercel](https://vercel.com)，用项目里的 Webhook 端点自动把新订阅写入 `subscribers.json`，无需再手动添加。详见下方「订阅自动同步」。
   - **手动**：收到新订阅邮件后，把该邮箱加入仓库里的 `subscribers.json`（JSON 数组，如 `["a@example.com", "b@example.com"]`），提交并推送。
3. **发信**：在 [Resend](https://resend.com) 注册并获取 API Key，在 Resend 里添加并验证发信域名（或使用其测试发件地址）。在仓库 **Settings → Secrets and variables → Actions** 里新增：
   - `RESEND_API_KEY`：Resend 的 API Key
   - `RESEND_FROM_EMAIL`：发件人邮箱（须在 Resend 中验证过的域名或测试地址）
4. 每周 Action 跑完后会按 `subscribers.json` 给每个邮箱发一封当周 Top 3 的 HTML 邮件。未配置上述 Secret 时不会发信，仅更新网页。

### 订阅自动同步（新订阅自动写入 subscribers.json）

若希望访客提交邮箱后**自动**加入 `subscribers.json`、无需你手动添加，可部署项目自带的 Webhook 端点（例如到 Vercel），并让表单服务在有人提交时请求该端点。

1. **部署 Webhook 到 Vercel**
   - 用 GitHub 账号登录 [Vercel](https://vercel.com)，选择 **Import** 本仓库（或先 fork 再 import）。
   - 在项目的 **Settings → Environment Variables** 里添加：
     - `GITHUB_TOKEN`：GitHub Personal Access Token，需勾选 `repo` 权限（[创建 Token](https://github.com/settings/tokens)）。
     - `GITHUB_REPO`：仓库名，如 `你的用户名/ca-savings-rates`。
   - 部署完成后，会得到类似 `https://xxx.vercel.app` 的地址，Webhook 地址为：**`https://xxx.vercel.app/api/subscribe`**。

2. **让表单把提交转发到 Webhook**
   - **Formspree**：在表单的 **Settings / Integrations** 中若有「Webhook」或「Webhook URL」，填上 `https://xxx.vercel.app/api/subscribe`。若免费版没有该选项，可改用支持 Webhook 的表单服务（如 [Formspark](https://formspark.io)、[Getform](https://getform.io) 等），或继续用手动方式把邮箱加入 `subscribers.json`。
   - 其他支持 Webhook 的表单服务：在「提交时 POST 到 URL」里填上述 `.../api/subscribe` 即可。请求体需包含 `email` 字段（JSON 如 `{"email":"a@example.com"}` 或 form 字段名 `email`）。

3. 之后每次有人提交订阅，该端点会把邮箱追加到仓库的 `subscribers.json` 并自动 commit，周一发信时就会包含新订阅者。

**在 localhost 测试 Webhook（可选）**  
不用先部署到 Vercel，也可以在本地跑接口、用 curl 试：会真的去改 GitHub 上仓库里的 `subscribers.json`。在项目根目录执行：

```bash
export GITHUB_TOKEN="你的 GitHub PAT（需 repo 权限）"
export GITHUB_REPO="你的用户名/ca-savings-rates"
npm run dev:api
```

然后另开终端：

```bash
curl -X POST http://localhost:3000/api/subscribe -H "Content-Type: application/json" -d '{"email":"test@example.com"}'
```

返回 `{"ok":true,"updated":true}` 且仓库里的 `subscribers.json` 多了一条，就说明逻辑正常。  
**注意**：Formspree 等外部服务只能访问公网 URL，所以「访客提交表单 → 自动写入订阅」必须用部署后的地址（如 Vercel）；localhost 只适合你自己验证接口行为。

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
