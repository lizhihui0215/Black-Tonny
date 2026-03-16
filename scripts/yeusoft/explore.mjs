import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";

const SITE_URL = process.env.YEU_SITE_URL || "https://jypos.yeusoft.net/";
const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/debug/explore");
const USERNAME = process.env.YEU_USERNAME || "";
const PASSWORD = process.env.YEU_PASSWORD || "";

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function shorten(value, size = 180) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, size);
}

async function main() {
  if (!USERNAME || !PASSWORD) {
    throw new Error("Missing YEU_USERNAME or YEU_PASSWORD.");
  }

  await ensureDir(OUTPUT_DIR);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();

  const requests = [];
  page.on("request", (request) => {
    const url = request.url();
    if (/yeusoft\.net/.test(url)) {
      requests.push({
        method: request.method(),
        url,
        resourceType: request.resourceType(),
      });
    }
  });

  await page.goto(SITE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);

  await page.getByPlaceholder("用户名").fill(USERNAME);
  await page.getByPlaceholder("密码").fill(PASSWORD);

  const loginButton = page.locator("input[type='button'][value*='登'], button:has-text('登录')").first();
  await loginButton.click();

  await page.waitForTimeout(8000);

  const storage = await page.evaluate(() => ({
    localStorage: { ...localStorage },
    sessionStorage: { ...sessionStorage },
    title: document.title,
    url: location.href,
    bodyTextPreview: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 3000),
    menuTexts: Array.from(document.querySelectorAll("a, button, .menu-item, .el-menu-item, .el-submenu__title, .ivu-menu-item"))
      .map((el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 300),
  }));

  await page.screenshot({ path: path.join(OUTPUT_DIR, "after-login.png"), fullPage: true });

  const uniqueRequests = [];
  const seen = new Set();
  for (const item of requests) {
    const key = `${item.method} ${item.url}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniqueRequests.push(item);
    }
  }

  const payload = {
    capturedAt: new Date().toISOString(),
    siteUrl: SITE_URL,
    successHeuristic: Boolean(storage.localStorage.yis_pc_token || storage.localStorage.yis_v2_refreshToken),
    storage,
    requests: uniqueRequests.slice(0, 500),
  };

  await fs.writeFile(path.join(OUTPUT_DIR, "after-login.json"), JSON.stringify(payload, null, 2), "utf8");

  console.log(`Saved screenshot: ${path.join(OUTPUT_DIR, "after-login.png")}`);
  console.log(`Saved summary: ${path.join(OUTPUT_DIR, "after-login.json")}`);
  console.log(`URL: ${storage.url}`);
  console.log(`Title: ${storage.title}`);
  console.log(`Token present: ${Boolean(storage.localStorage.yis_pc_token)}`);
  console.log(`Menu texts captured: ${storage.menuTexts.length}`);

  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
