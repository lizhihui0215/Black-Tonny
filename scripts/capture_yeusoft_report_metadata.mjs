import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";

const SITE_URL = process.env.YEU_SITE_URL || "https://jypos.yeusoft.net/";
const USERNAME = process.env.YEU_USERNAME || "";
const PASSWORD = process.env.YEU_PASSWORD || "";
const REPORT_NAME = process.env.YEU_REPORT_NAME || "店铺零售清单";
const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/yeusoft_report_capture");

const INTERESTING_ENDPOINTS = [
  "GetConfiguration",
  "GetFilterContentData",
  "GetControlData",
  "GetViewGridList",
  "GetDIYReportData",
];

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function sanitizeName(value) {
  return String(value || "")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 80);
}

function summarizeText(value, limit = 500) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, limit);
}

async function login(page) {
  await page.goto(SITE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2000);
  await page.getByPlaceholder("用户名").fill(USERNAME);
  await page.getByPlaceholder("密码").fill(PASSWORD);
  await page
    .locator("input[type='button'][value*='登'], button:has-text('登录')")
    .first()
    .click();
  await page.waitForTimeout(7000);
}

async function waitForPosFrame(page) {
  for (let i = 0; i < 30; i += 1) {
    const frame = page.frames().find((item) => item.url().includes("/pos_internal/"));
    if (frame) {
      return frame;
    }
    await page.waitForTimeout(1000);
  }
  throw new Error("pos_internal frame not found");
}

async function revealReportMenu(frame, page) {
  await frame.evaluate(() => {
    const app = document.querySelector("#app")?.__vue__?.$children?.[0];
    if (app) {
      app.showSilder = true;
    }
  });
  await page.waitForTimeout(1500);
  await frame.getByText("报表管理", { exact: true }).click();
  await page.waitForTimeout(1200);
}

export async function captureReport(reportName, options = {}) {
  if (!USERNAME || !PASSWORD) {
    throw new Error("Missing YEU_USERNAME or YEU_PASSWORD");
  }

  const outputDir = options.outputDir ? path.resolve(options.outputDir) : OUTPUT_DIR;
  await ensureDir(outputDir);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();

  const requestLog = [];
  const responseLog = [];

  page.on("request", async (request) => {
    const url = request.url();
    if (!INTERESTING_ENDPOINTS.some((name) => url.includes(name))) {
      return;
    }
    requestLog.push({
      method: request.method(),
      url,
      postData: safeJsonParse(request.postData() || ""),
    });
  });

  page.on("response", async (response) => {
    const url = response.url();
    if (!INTERESTING_ENDPOINTS.some((name) => url.includes(name))) {
      return;
    }
    let body;
    try {
      body = await response.json();
    } catch {
      try {
        body = summarizeText(await response.text(), 3000);
      } catch {
        body = "<unreadable>";
      }
    }
    responseLog.push({
      status: response.status(),
      url,
      body,
    });
  });

  await login(page);
  const frame = await waitForPosFrame(page);
  await revealReportMenu(frame, page);

  const reportLink = frame.getByText(reportName, { exact: true });
  await reportLink.click();
  await page.waitForTimeout(2500);

  const tabState = await frame.evaluate(() => {
    const app = document.querySelector("#app")?.__vue__?.$children?.[0];
    const tabs = app?.editableTabs || [];
    const bodyPreview = String(document.body?.innerText || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 2500);
    return {
      titleTabsValue: app?.titleTabsValue || "",
      editableTabs: tabs.map((tab) => ({
        title: tab.title || "",
        name: tab.name || "",
        FuncUrl: tab.FuncUrl || "",
      })),
      bodyPreview,
    };
  });

  const filterLabels = await frame.evaluate(() => {
    return Array.from(document.querySelectorAll("label, .el-form-item__label, .queryFormItemLabel"))
      .map((el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 100);
  });

  const queryButton = frame.locator(".el-button.useButton.el-button--primary.el-button--small").first();
  if (await queryButton.count()) {
    await queryButton.click();
    await page.waitForTimeout(3500);
  }

  const screenshotPath = path.join(outputDir, `${sanitizeName(reportName)}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const payload = {
    capturedAt: new Date().toISOString(),
    siteUrl: SITE_URL,
    reportName,
    tabState,
    filterLabels,
    requests: requestLog,
    responses: responseLog,
    screenshotPath,
  };

  const jsonPath = path.join(outputDir, `${sanitizeName(reportName)}.json`);
  await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");

  await browser.close();

  return { jsonPath, screenshotPath, payload };
}

const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isDirectRun) {
  captureReport(REPORT_NAME)
    .then(({ jsonPath, screenshotPath, payload }) => {
      console.log(`Saved JSON: ${jsonPath}`);
      console.log(`Saved screenshot: ${screenshotPath}`);
      console.log(`Report: ${payload.reportName}`);
      console.log(`Tab value: ${payload.tabState.titleTabsValue}`);
      console.log(`Requests captured: ${payload.requests.length}`);
      console.log(`Responses captured: ${payload.responses.length}`);
    })
    .catch((error) => {
      console.error(error);
      process.exit(1);
    });
}
