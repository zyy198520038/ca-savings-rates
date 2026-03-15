/**
 * 本地运行 /api/subscribe，用于在 localhost 测试 Webhook 逻辑。
 * 会真正调用 GitHub API 更新仓库里的 subscribers.json。
 *
 * 用法：
 *   1. 设置环境变量（或建 .env 后 node --env-file=.env scripts/serve-api.mjs）：
 *      export GITHUB_TOKEN="你的 GitHub PAT"
 *      export GITHUB_REPO="你的用户名/ca-savings-rates"
 *   2. 运行：npm run dev:api  或  node scripts/serve-api.mjs
 *   3. 测试：curl -X POST http://localhost:3000/api/subscribe -H "Content-Type: application/json" -d '{"email":"test@example.com"}'
 */
import http from "http";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

// 动态加载 Vercel 风格的 handler（ESM default export）
const mod = await import(join(__dirname, "..", "api", "subscribe.js"));
const handler = mod.default;

const PORT = Number(process.env.PORT) || 3000;

function parseBody(raw) {
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://localhost:${PORT}`);
  if (url.pathname !== "/api/subscribe") {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found. POST to /api/subscribe to test.");
    return;
  }

  let body = "";
  for await (const chunk of req) body += chunk;
  const reqObj = {
    method: req.method,
    body: parseBody(body),
  };
  const resObj = {
    setHeader(k, v) {
      res.setHeader(k, v);
    },
    status(code) {
      res.statusCode = code;
      return {
        json(obj) {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify(obj));
        },
        end() {
          res.end();
        },
      };
    },
  };

  try {
    await handler(reqObj, resObj);
  } catch (e) {
    console.error(e);
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify({ ok: false, error: String(e.message || e) }));
  }
});

server.listen(PORT, () => {
  console.log(`API 本地地址: http://localhost:${PORT}/api/subscribe`);
  console.log("测试: curl -X POST http://localhost:3000/api/subscribe -H \"Content-Type: application/json\" -d '{\"email\":\"test@example.com\"}'");
  if (!process.env.GITHUB_TOKEN || !process.env.GITHUB_REPO) {
    console.warn("提示: 请设置 GITHUB_TOKEN 和 GITHUB_REPO，否则请求会报错。");
  }
});
