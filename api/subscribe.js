/**
 * Webhook 端点：收到新订阅邮箱后，自动追加到仓库的 subscribers.json 并提交。
 * 部署到 Vercel 后，在表单服务（支持 Webhook 的如 Formspree/Formspark 等）里填此 URL 即可自动同步。
 *
 * 环境变量（在 Vercel 项目 Settings → Environment Variables 中配置）：
 *   GITHUB_TOKEN   - 有 repo 权限的 Personal Access Token
 *   GITHUB_REPO   - 仓库，如 "你的用户名/ca-savings-rates"
 */

const REPO = process.env.GITHUB_REPO || "";
const TOKEN = process.env.GITHUB_TOKEN || "";
const FILE_PATH = "subscribers.json";

const VALID_LANGS = new Set(["en", "zh", "fr", "es", "pa"]);

function getEmailFromBody(body) {
  if (!body) return null;
  const email = typeof body === "string" ? (() => { try { return JSON.parse(body).email; } catch { return null; } })() : (body.email || body.Email);
  if (typeof email !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return null;
  return email.trim().toLowerCase();
}

function getLangFromBody(body) {
  if (!body || typeof body !== "object") return "en";
  const lang = (body.lang || body.language || "en").toString().trim().toLowerCase();
  return VALID_LANGS.has(lang) ? lang : "en";
}

async function getFileSha(contentUrl) {
  const res = await fetch(contentUrl, {
    headers: { Authorization: `Bearer ${TOKEN}`, Accept: "application/vnd.github.v3+json" },
  });
  if (!res.ok) return { sha: null, content: "[]" };
  const data = await res.json();
  const content = data.content ? Buffer.from(data.content, "base64").toString("utf-8") : "[]";
  return { sha: data.sha, content };
}

async function updateSubscribers(newEmail, lang) {
  const [owner, repo] = REPO.split("/").filter(Boolean);
  if (!owner || !repo || !TOKEN) {
    throw new Error("Missing GITHUB_REPO or GITHUB_TOKEN");
  }
  const base = `https://api.github.com/repos/${owner}/${repo}/contents/${FILE_PATH}`;
  const { sha, content } = await getFileSha(base);
  let list = [];
  try {
    list = JSON.parse(content || "[]");
    if (!Array.isArray(list)) list = [];
  } catch {
    list = [];
  }
  const normalized = newEmail.trim().toLowerCase();
  const existingEmails = list.map((e) => (typeof e === "object" && e && e.email ? e.email : String(e)).trim().toLowerCase());
  if (existingEmails.includes(normalized)) {
    return { updated: false, message: "already subscribed" };
  }
  list.push({ email: normalized, lang: VALID_LANGS.has(lang) ? lang : "en" });
  const body = JSON.stringify(list, null, 2);
  const putRes = await fetch(base, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      Accept: "application/vnd.github.v3+json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      message: "chore: add subscriber via webhook",
      content: Buffer.from(body, "utf-8").toString("base64"),
      sha: sha || undefined,
    }),
  });
  if (!putRes.ok) {
    const err = await putRes.text();
    throw new Error(`GitHub API error: ${putRes.status} ${err}`);
  }
  return { updated: true };
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "Method not allowed" });
  }

  let body = req.body;
  // 兼容 JSON 字符串或 form-urlencoded
  if (typeof body === "string") {
    if (body.trim().startsWith("{")) {
      try {
        body = JSON.parse(body);
      } catch {
        body = {};
      }
    } else if (body.includes("=")) {
      const params = new URLSearchParams(body);
      body = { email: params.get("email") || params.get("Email"), lang: params.get("lang") };
    } else {
      body = {};
    }
  }
  if (!body || typeof body !== "object") body = {};

  const email = getEmailFromBody(body);
  if (!email) {
    return res.status(400).json({ ok: false, error: "Invalid or missing email" });
  }
  const lang = getLangFromBody(body);

  try {
    const result = await updateSubscribers(email, lang);
    return res.status(200).json({ ok: true, ...result });
  } catch (e) {
    console.error(e);
    return res.status(500).json({ ok: false, error: e.message || "Failed to update subscribers" });
  }
}
