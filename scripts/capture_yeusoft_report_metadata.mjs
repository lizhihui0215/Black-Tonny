import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";

const SITE_URL = process.env.YEU_SITE_URL || "https://jypos.yeusoft.net/";
const USERNAME = process.env.YEU_USERNAME || "";
const PASSWORD = process.env.YEU_PASSWORD || "";
const REPORT_NAME = process.env.YEU_REPORT_NAME || "店铺零售清单";
const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/yeusoft_report_capture");
const START_DATE = process.env.YEU_START_DATE || "2025-03-01";
const END_DATE = process.env.YEU_END_DATE || new Date().toISOString().slice(0, 10);
const REPORT_GROUP_MAP = {
  零售明细统计: "零售报表",
  导购员报表: "零售报表",
  店铺零售清单: "零售报表",
  销售清单: "零售报表",
  库存明细统计: "库存报表",
  库存零售统计: "库存报表",
  库存综合分析: "库存报表",
  库存多维分析: "库存报表",
  进销存统计: "进出报表",
  出入库单据: "进出报表",
  日进销存: "进出报表",
  退货明细: "进出报表",
  会员综合分析: "会员报表",
  会员消费排行: "会员报表",
  储值按店汇总: "会员报表",
  储值卡汇总: "会员报表",
  储值卡明细: "会员报表",
  商品销售情况: "综合分析",
  商品品类分析: "综合分析",
  门店销售月报: "综合分析",
  每日流水单: "对账报表",
};
const REPORT_INTERNAL_NAME_MAP = {
  销售明细统计: "report01",
  零售缴款单: "report02",
  导购员统计: "report03",
  门店销售日报: "report09",
  库存明细统计: "report04",
  库存零售统计: "report05",
  库存综合分析: "report10",
  进销存统计: "report06",
  出入库单据: "report07",
  会员综合分析: "report08",
};

const INTERESTING_ENDPOINTS = [
  "GetMenuList",
  "GetConfiguration",
  "GetFilterContentData",
  "GetControlData",
  "GetViewGridList",
  "GetDIYReportData",
  "SelStockAnalysisList",
  "SelOutInStockReport",
  "SelectRetailDocPaymentSlip",
];

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function wait(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
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
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await page.goto(SITE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForTimeout(2000);
      await page.getByPlaceholder("用户名").fill(USERNAME);
      await page.getByPlaceholder("密码").fill(PASSWORD);
      await page
        .locator("input[type='button'][value*='登'], button:has-text('登录')")
        .first()
        .click();
      await page.waitForTimeout(7000);
      return;
    } catch (error) {
      lastError = error;
      if (attempt === 3) {
        throw error;
      }
      await wait(2000 * attempt);
    }
  }
  throw lastError;
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

async function waitForOperationalApp(frame, page) {
  for (let i = 0; i < 20; i += 1) {
    const state = await frame.evaluate(() => {
      const app = document.querySelector("#app")?.__vue__?.$children?.[0];
      return {
        hasApp: !!app,
        hasJumpPage: typeof app?.jumpPage === "function",
        hasAddTab: typeof app?.addTab === "function",
        hasReportArrList: !!app?.reportArrList,
      };
    }).catch(() => ({ hasApp: false, hasJumpPage: false, hasAddTab: false, hasReportArrList: false }));

    if (state.hasApp && (state.hasJumpPage || state.hasAddTab || state.hasReportArrList)) {
      return state;
    }
    await page.waitForTimeout(1000);
  }
  return { hasApp: false, hasJumpPage: false, hasAddTab: false, hasReportArrList: false };
}

async function extractAuth(page) {
  return page.evaluate(() => ({
    apiUrl: localStorage.getItem("yisapiurl") || localStorage.getItem("YIS_API_ERP_TEMP") || "",
    token: localStorage.getItem("yis_pc_token") || "",
  }));
}

function flattenMenu(items, bucket = []) {
  for (const item of items || []) {
    bucket.push(item);
    if (item.SubList && item.SubList.length) {
      flattenMenu(item.SubList, bucket);
    }
  }
  return bucket;
}

async function fetchMenuList(page) {
  const auth = await extractAuth(page);
  if (!auth.apiUrl || !auth.token) {
    return [];
  }
  const response = await fetch(`${auth.apiUrl}/eposapi/YisEposSaleManage/GetMenuList`, {
    method: "POST",
    headers: {
      "content-type": "application/json;charset=UTF-8",
      token: auth.token,
    },
    body: JSON.stringify({ isaution: "E" }),
  });
  const payload = await response.json();
  return flattenMenu(payload.retdata || []);
}

async function revealReportMenu(frame, page) {
  await frame.evaluate(() => {
    const app = document.querySelector("#app")?.__vue__?.$children?.[0];
    if (app) {
      app.showSilder = true;
    }
  });
  await page.waitForTimeout(1500);
  const candidates = frame.locator("li, p, span, div").filter({ hasText: "报表管理" });
  const count = await candidates.count();
  for (let index = 0; index < count; index += 1) {
    const item = candidates.nth(index);
    if (await item.isVisible()) {
      try {
        await item.click();
        await page.waitForTimeout(1200);
        return;
      } catch {
        // try the next visible candidate
      }
    }
  }
  await frame.evaluate(() => {
    const labels = Array.from(document.querySelectorAll("li, p, span, div"));
    const target = labels.find((item) => (item.textContent || "").trim() === "报表管理");
    target?.click();
  });
  await page.waitForTimeout(1200);
}

async function clickExactTextNode(frame, text) {
  return frame.evaluate((expectedText) => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const candidates = Array.from(document.querySelectorAll("li, p, span, div"))
      .filter((item) => {
        const rect = item.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && normalize(item.textContent) === expectedText;
      })
      .sort((left, right) => normalize(left.textContent).length - normalize(right.textContent).length);
    const target = candidates[0];
    if (!target) {
      return false;
    }
    target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
    return true;
  }, text);
}

async function tryOpenReportByMenuItem(frame, page, reportName, menuItem) {
  if (!menuItem) {
    return { ok: false, reason: "no-menu-item" };
  }
  return frame.evaluate(
    async ({ expectedTitle, menuItemValue }) => {
      const app = document.querySelector("#app")?.__vue__?.$children?.[0];
      if (!app) {
        return { ok: false, reason: "app-missing" };
      }

      const startTitle = app.titleTabsValue || "";
      if (typeof app.addTab === "function") {
        try {
          await app.addTab(menuItemValue);
          const tabs = app.editableTabs || [];
          const activeTab = tabs.find((tab) => tab.FuncUrl === app.titleTabsValue);
          const matchedTab = tabs.find(
            (tab) => tab.FuncUrl === menuItemValue.FuncUrl || tab.FuncName === menuItemValue.FuncName,
          );
          const success = app.titleTabsValue === menuItemValue.FuncUrl || !!activeTab || !!matchedTab;
          return {
            ok: success,
            method: "addTab",
            startTitle,
            endTitle: app.titleTabsValue || "",
            matchedTab: matchedTab || null,
            reason: success ? "" : "tab-not-activated",
          };
        } catch (error) {
          return { ok: false, reason: `addTab:${String(error)}` };
        }
      }

      return { ok: false, reason: "no-method" };
    },
    { expectedTitle: reportName, menuItemValue: menuItem },
  ).then(async (result) => {
    if (result?.ok) {
      await page.waitForTimeout(2500);
      return result;
    }
    return result || { ok: false, reason: "empty-result" };
  }).catch((error) => ({ ok: false, reason: `exception:${String(error)}` }));
}

async function ensureReportGroup(frame, page, reportName) {
  const groupName = REPORT_GROUP_MAP[reportName];
  if (!groupName) {
    return;
  }
  if (await clickExactTextNode(frame, groupName)) {
    await page.waitForTimeout(600);
    return;
  }
  const groupCandidates = frame.locator("li, p, span, div").filter({ hasText: groupName });
  const count = await groupCandidates.count();
  for (let index = 0; index < count; index += 1) {
    const item = groupCandidates.nth(index);
    if (await item.isVisible()) {
      try {
        await item.click({ force: true });
        await page.waitForTimeout(600);
        return;
      } catch {
        // keep trying visible candidates
      }
    }
  }
}

async function clickReportMenuItem(frame, reportName) {
  await frame.locator(".el-loading-mask").waitFor({ state: "hidden", timeout: 5000 }).catch(() => {});

  if (await clickExactTextNode(frame, reportName)) {
    return;
  }

  const candidates = frame.locator("li, p, span, div").filter({ hasText: reportName });
  const count = await candidates.count();
  if (!count) {
    throw new Error(`未找到报表菜单项：${reportName}`);
  }

  for (let index = 0; index < count; index += 1) {
    const item = candidates.nth(index);
    if (await item.isVisible()) {
      await item.click();
      return;
    }
  }

  await candidates.first().click({ force: true });
}

function createNetworkCollector(page) {
  let activeCapture = null;

  page.on("request", async (request) => {
    const url = request.url();
    if (!activeCapture || !INTERESTING_ENDPOINTS.some((name) => url.includes(name))) {
      return;
    }
    activeCapture.requests.push({
      method: request.method(),
      url,
      postData: safeJsonParse(request.postData() || ""),
    });
  });

  page.on("response", async (response) => {
    const url = response.url();
    if (!activeCapture || !INTERESTING_ENDPOINTS.some((name) => url.includes(name))) {
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
    activeCapture.responses.push({
      status: response.status(),
      url,
      body,
    });
  });

  return {
    start(reportName) {
      activeCapture = {
        reportName,
        requests: [],
        responses: [],
      };
      return activeCapture;
    },
    stop() {
      const snapshot = activeCapture || {
        reportName: "",
        requests: [],
        responses: [],
      };
      activeCapture = null;
      return snapshot;
    },
  };
}

async function trySetDateRange(frame, startDate, endDate) {
  const inputLocator = frame.locator(
    ".el-date-editor input, .el-range-editor input, input[placeholder*='开始'], input[placeholder*='结束'], input[placeholder*='时间']",
  );
  const visibleInputs = [];
  const count = await inputLocator.count();
  for (let index = 0; index < count; index += 1) {
    const input = inputLocator.nth(index);
    try {
      if (await input.isVisible()) {
        visibleInputs.push(input);
      }
    } catch {
      // ignore detached input
    }
  }

  if (visibleInputs.length < 2) {
    return false;
  }

  try {
    await visibleInputs[0].fill(startDate);
    await visibleInputs[1].fill(endDate);
    await visibleInputs[1].press("Enter").catch(() => {});
    return true;
  } catch {
    return false;
  }
}

async function clickQueryButton(frame, page) {
  const queryButtonCandidates = [
    frame.locator(".el-button.useButton.el-button--primary.el-button--small").first(),
    frame.getByRole("button", { name: "查询" }).first(),
    frame.locator("button:has-text('查询')").first(),
    frame.locator(".el-button--primary:has-text('查询')").first(),
    frame.getByText("查询", { exact: true }).first(),
  ];

  for (const queryButton of queryButtonCandidates) {
    if (await queryButton.count()) {
      try {
        console.log("[STEP] click query");
        await queryButton.click();
        await page.waitForTimeout(3500);
        console.log("[STEP] query done");
        return true;
      } catch {
        // try next candidate
      }
    }
  }

  return false;
}

export async function createYeusoftSession(options = {}) {
  const outputDir = options.outputDir ? path.resolve(options.outputDir) : OUTPUT_DIR;
  await ensureDir(outputDir);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1200 },
  });
  const page = await context.newPage();
  const collector = createNetworkCollector(page);

  console.log("[STEP] login");
  await login(page);
  console.log("[STEP] login ok");
  const frame = await waitForPosFrame(page);
  console.log("[STEP] frame ok");
  const appState = await waitForOperationalApp(frame, page);
  console.log(`[STEP] app ready jump:${appState.hasJumpPage} addTab:${appState.hasAddTab} reportArr:${appState.hasReportArrList}`);
  const menuList = await fetchMenuList(page).catch(() => []);
  console.log(`[STEP] menu list loaded ${menuList.length}`);
  const menuLookup = Object.fromEntries(
    menuList
      .filter((item) => item && item.FuncName)
      .map((item) => [item.FuncName, item]),
  );

  return {
    browser,
    context,
    page,
    frame,
    outputDir,
    collector,
    startDate: options.startDate || START_DATE,
    endDate: options.endDate || END_DATE,
    appState,
    menuList,
    menuLookup,
  };
}

export async function closeYeusoftSession(session) {
  await session.browser.close();
}

export async function captureReportInSession(session, reportName, options = {}) {
  const outputDir = options.outputDir ? path.resolve(options.outputDir) : session.outputDir;
  await ensureDir(outputDir);
  console.log(`[STEP] start ${reportName}`);

  session.collector.start(reportName);
  const menuItem = session.menuLookup?.[reportName] || null;
  const openResult = await tryOpenReportByMenuItem(session.frame, session.page, reportName, menuItem);
  if (openResult?.ok) {
    console.log(
      `[STEP] opened by menu item ${menuItem?.FuncUrl || REPORT_INTERNAL_NAME_MAP[reportName] || "unknown"} via ${openResult.method || "unknown"}`,
    );
  } else {
    if (openResult?.reason) {
      console.log(`[STEP] menu item open skipped: ${openResult.reason}`);
    }
    await revealReportMenu(session.frame, session.page);
    console.log("[STEP] report menu open");
    await ensureReportGroup(session.frame, session.page, reportName);
    await clickReportMenuItem(session.frame, reportName);
    console.log(`[STEP] clicked ${reportName}`);
  }
  await session.page.waitForTimeout(2500);

  const dateRangeApplied = await trySetDateRange(
    session.frame,
    options.startDate || session.startDate || START_DATE,
    options.endDate || session.endDate || END_DATE,
  );
  if (dateRangeApplied) {
    console.log("[STEP] date range updated");
    await session.page.waitForTimeout(800);
  }

  const tabState = await session.frame.evaluate(() => {
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

  const filterLabels = await session.frame.evaluate(() => {
    return Array.from(document.querySelectorAll("label, .el-form-item__label, .queryFormItemLabel"))
      .map((el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .slice(0, 100);
  });

  await clickQueryButton(session.frame, session.page);

  const screenshotPath = path.join(outputDir, `${sanitizeName(reportName)}.png`);
  console.log("[STEP] screenshot");
  await session.page.screenshot({ path: screenshotPath, fullPage: true });

  const captureLog = session.collector.stop();
  const payload = {
    capturedAt: new Date().toISOString(),
    siteUrl: SITE_URL,
    reportName,
    menuItem: menuItem || null,
    tabState,
    filterLabels,
    dateRangeApplied,
    appliedDateRange: {
      start: options.startDate || session.startDate || START_DATE,
      end: options.endDate || session.endDate || END_DATE,
    },
    requests: captureLog.requests,
    responses: captureLog.responses,
    screenshotPath,
  };

  const jsonPath = path.join(outputDir, `${sanitizeName(reportName)}.json`);
  await fs.writeFile(jsonPath, JSON.stringify(payload, null, 2), "utf8");
  console.log("[STEP] write done");

  return { jsonPath, screenshotPath, payload };
}

export async function captureReport(reportName, options = {}) {
  if (!USERNAME || !PASSWORD) {
    throw new Error("Missing YEU_USERNAME or YEU_PASSWORD");
  }
  const session = await createYeusoftSession(options);
  try {
    return await captureReportInSession(session, reportName, options);
  } finally {
    await closeYeusoftSession(session);
  }
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
