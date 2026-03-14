import fs from "fs/promises";
import path from "path";
import { chromium } from "playwright";

const SITE_URL = process.env.YEU_SITE_URL || "https://jypos.yeusoft.net/";
const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/yeusoft_inspect");

function summarizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, 160);
}

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function main() {
  await ensureDir(OUTPUT_DIR);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1200 },
  });

  await page.goto(SITE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(5000);

  const pageInfo = await page.evaluate(() => {
    const inputs = Array.from(document.querySelectorAll("input, textarea, select")).map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute("type") || "",
      name: el.getAttribute("name") || "",
      id: el.getAttribute("id") || "",
      placeholder: el.getAttribute("placeholder") || "",
      valuePreview: String(el.value || "").slice(0, 24),
      autocomplete: el.getAttribute("autocomplete") || "",
    }));

    const buttons = Array.from(document.querySelectorAll("button, a, [role='button'], .el-button, .btn"))
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        text: (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
        id: el.getAttribute("id") || "",
        className: (el.getAttribute("class") || "").slice(0, 120),
      }))
      .filter((item) => item.text || item.id || item.className);

    const iframes = Array.from(document.querySelectorAll("iframe")).map((el) => ({
      id: el.getAttribute("id") || "",
      name: el.getAttribute("name") || "",
      src: el.getAttribute("src") || "",
    }));

    return {
      title: document.title,
      url: location.href,
      bodyTextPreview: (document.body?.innerText || "").replace(/\s+/g, " ").trim().slice(0, 1200),
      inputs,
      buttons,
      iframes,
    };
  });

  const frameInfo = [];
  for (const frame of page.frames()) {
    try {
      frameInfo.push({
        url: frame.url(),
        name: frame.name(),
        inputCount: await frame.locator("input, textarea, select").count(),
        buttonCount: await frame.locator("button, a, [role='button'], .el-button, .btn").count(),
      });
    } catch (error) {
      frameInfo.push({
        url: frame.url(),
        name: frame.name(),
        error: String(error),
      });
    }
  }

  await page.screenshot({ path: path.join(OUTPUT_DIR, "landing.png"), fullPage: true });

  const payload = {
    capturedAt: new Date().toISOString(),
    siteUrl: SITE_URL,
    pageInfo: {
      ...pageInfo,
      bodyTextPreview: summarizeText(pageInfo.bodyTextPreview),
      buttons: pageInfo.buttons.slice(0, 80),
    },
    frameInfo,
  };

  await fs.writeFile(
    path.join(OUTPUT_DIR, "landing.json"),
    JSON.stringify(payload, null, 2),
    "utf8",
  );

  console.log(`Saved screenshot: ${path.join(OUTPUT_DIR, "landing.png")}`);
  console.log(`Saved summary: ${path.join(OUTPUT_DIR, "landing.json")}`);
  console.log(`Title: ${pageInfo.title}`);
  console.log(`URL: ${pageInfo.url}`);
  console.log(`Inputs: ${pageInfo.inputs.length}`);
  console.log(`Buttons: ${pageInfo.buttons.length}`);
  console.log(`Iframes: ${pageInfo.iframes.length}`);

  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
