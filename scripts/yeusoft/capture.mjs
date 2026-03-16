import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { chromium } from "playwright";

const SITE_URL = process.env.YEU_SITE_URL || "https://jypos.yeusoft.net/";
const ERP_API_URL = process.env.YEU_ERP_API_URL || "https://erpapistaging.yeusoft.net";
const JY_API_URL = process.env.YEU_JY_API_URL || "https://jyapistaging.yeusoft.net";
const USERNAME = process.env.YEU_USERNAME || "";
const PASSWORD = process.env.YEU_PASSWORD || "";
const REPORT_NAME = process.env.YEU_REPORT_NAME || "店铺零售清单";
const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/capture-cache");
const START_DATE = process.env.YEU_START_DATE || "2025-03-01";
const END_DATE = process.env.YEU_END_DATE || new Date().toISOString().slice(0, 10);
const REPORT_ROOT_NAME = "报表管理";
const REPORT_GROUPS = new Set(["零售报表", "库存报表", "进出报表", "会员报表", "综合分析", "对账报表"]);
const REPORT_ALIAS_MAP = {
  销售明细统计: "零售明细统计",
  导购员统计: "导购员报表",
};
const SNAPSHOT_REPORTS = new Set(["库存综合分析"]);
const REPORT_GROUP_MAP = {
  零售明细统计: "零售报表",
  销售明细统计: "零售报表",
  导购员报表: "零售报表",
  导购员统计: "零售报表",
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
  会员中心: "会员报表",
  商品销售情况: "综合分析",
  商品品类分析: "综合分析",
  门店销售月报: "综合分析",
  每日流水单: "对账报表",
};
const REPORT_INTERNAL_NAME_MAP = {
  零售明细统计: "report01",
  零售缴款单: "report02",
  导购员报表: "report03",
  门店销售月报: "salesMonthlyReport",
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
  "SelDeptSaleList",
  "SelPersonSale",
  "SelDeptStockWaitList",
  "SelDeptStockSaleList",
  "SelStockAnalysisList",
  "SelDeptStockAnalysis",
  "SelInSalesReport",
  "SelOutInStockReport",
  "SelInSalesReportByDay",
  "SelVipAnalysisReport",
  "SelVipSaleRank",
  "SelSaleReportData",
  "SelWareTypeAnalysisList",
  "DeptMonthSalesReport",
  "SelectRetailDocPaymentSlip",
];
const NON_DATA_ENDPOINTS = new Set([
  "GetMenuList",
  "GetConfiguration",
  "GetFilterContentData",
  "GetControlData",
  "GetViewGridList",
]);
const DATA_ENDPOINT_HINTS = [
  "GetDIYReportData",
  "SelDeptSaleList",
  "SelPersonSale",
  "SelDeptStockWaitList",
  "SelDeptStockSaleList",
  "SelStockAnalysisList",
  "SelDeptStockAnalysis",
  "SelInSalesReport",
  "SelOutInStockReport",
  "SelInSalesReportByDay",
  "SelVipAnalysisReport",
  "SelVipSaleRank",
  "SelSaleReportData",
  "SelWareTypeAnalysisList",
  "DeptMonthSalesReport",
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

export function normalizeReportName(reportName) {
  return REPORT_ALIAS_MAP[reportName] || reportName;
}

function compactDateValue(value) {
  return String(value || "").replace(/[^0-9]/g, "");
}

function extractRowCount(body) {
  if (!body || typeof body !== "object") {
    return null;
  }

  if (Array.isArray(body)) {
    return body.length;
  }

  const nestedPathCandidates = [
    ["Data", "PageData", "Items"],
    ["retdata", "PageData", "Items"],
    ["data", "PageData", "Items"],
    ["Data", "List"],
    ["retdata", "List"],
    ["data", "List"],
    ["Data", "Items"],
    ["retdata", "Items"],
    ["data", "Items"],
    ["PageData", "Items"],
  ];
  for (const pathKeys of nestedPathCandidates) {
    let current = body;
    let matched = true;
    for (const key of pathKeys) {
      if (!current || typeof current !== "object" || !(key in current)) {
        matched = false;
        break;
      }
      current = current[key];
    }
    if (matched && Array.isArray(current)) {
      return current.length;
    }
  }

  const directCandidates = ["retdata", "data", "Data", "list", "List", "rows", "Rows", "Items", "items"];
  for (const key of directCandidates) {
    if (Array.isArray(body[key])) {
      return body[key].length;
    }
  }

  const retdata = body.retdata;
  if (Array.isArray(retdata)) {
    return retdata.length;
  }
  if (retdata && typeof retdata === "object") {
    for (const key of directCandidates) {
      if (Array.isArray(retdata[key])) {
        return retdata[key].length;
      }
    }
  }

  const stack = [body];
  const visited = new Set();
  const recursiveCandidates = [];
  while (stack.length) {
    const current = stack.pop();
    if (!current || typeof current !== "object" || visited.has(current)) {
      continue;
    }
    visited.add(current);
    for (const [key, value] of Object.entries(current)) {
      if (Array.isArray(value) && ["Items", "items", "List", "list", "Rows", "rows", "Data", "data", "retdata", "TotalData"].includes(key)) {
        recursiveCandidates.push(value.length);
      } else if (value && typeof value === "object") {
        stack.push(value);
      }
    }
  }

  if (recursiveCandidates.length) {
    return Math.max(...recursiveCandidates);
  }

  return null;
}

function findDateRangeCandidate(payload) {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const startKeys = ["BeginDate", "beginDate", "StartDate", "startDate", "bdate", "BDate", "salebdate", "SaleBeginDate"];
  const endKeys = ["EndDate", "endDate", "FinishDate", "finishDate", "edate", "EDate", "saleedate", "SaleEndDate"];
  const stack = [payload];

  while (stack.length) {
    const current = stack.pop();
    if (!current || typeof current !== "object") {
      continue;
    }

    const startValue = startKeys.find((key) => current[key] !== undefined && current[key] !== null);
    const endValue = endKeys.find((key) => current[key] !== undefined && current[key] !== null);
    if (startValue || endValue) {
      return {
        start: startValue ? String(current[startValue]) : "",
        end: endValue ? String(current[endValue]) : "",
      };
    }

    for (const value of Object.values(current)) {
      if (value && typeof value === "object") {
        stack.push(value);
      }
    }
  }

  return null;
}

function isIgnoredEndpoint(url) {
  return Array.from(NON_DATA_ENDPOINTS).some((keyword) => url.includes(keyword));
}

function isLikelyDataEndpoint(url) {
  if (!url) {
    return false;
  }
  if (DATA_ENDPOINT_HINTS.some((keyword) => url.includes(keyword))) {
    return true;
  }
  if (isIgnoredEndpoint(url)) {
    return false;
  }
  return /report|analysis|slip|customreport|vip|member|sale|stock|inout/i.test(url);
}

function summarizeCapture(reportName, captureLog, requestedRange) {
  const responses = captureLog.responses.map((item) => ({
    ...item,
    rowCount: extractRowCount(item.body),
  }));
  const dataResponses = responses.filter((item) => isLikelyDataEndpoint(item.url) || (item.rowCount ?? 0) > 0);
  const preferredResponse =
    dataResponses.find((item) => (item.rowCount ?? 0) > 0) ||
    dataResponses.find((item) => DATA_ENDPOINT_HINTS.some((keyword) => item.url.includes(keyword))) ||
    dataResponses[0] ||
    null;

  const matchingRequest =
    [...captureLog.requests]
      .reverse()
      .find((item) => preferredResponse && item.url === preferredResponse.url) ||
    [...captureLog.requests]
      .reverse()
      .find((item) => isLikelyDataEndpoint(item.url)) ||
    null;

  const requestRange = matchingRequest ? findDateRangeCandidate(matchingRequest.postData) : null;
  const requestedStart = compactDateValue(requestedRange.start);
  const requestedEnd = compactDateValue(requestedRange.end);
  const requestStart = compactDateValue(requestRange?.start || "");
  const requestEnd = compactDateValue(requestRange?.end || "");
  const isSnapshotReport = SNAPSHOT_REPORTS.has(reportName);
  const rangeMatched = isSnapshotReport
    ? true
    : Boolean(requestStart && requestEnd && requestStart === requestedStart && requestEnd === requestedEnd);
  const rowCount = preferredResponse?.rowCount ?? 0;

  let captureQuality = "opened-only";
  if (preferredResponse && isSnapshotReport) {
    captureQuality = "snapshot-data";
  } else if (preferredResponse && rangeMatched && rowCount > 0) {
    captureQuality = "full-range-data";
  } else if (preferredResponse && rangeMatched && rowCount === 0) {
    captureQuality = "full-range-empty";
  } else if (preferredResponse && !rangeMatched) {
    captureQuality = "partial-range-data";
  } else if (matchingRequest) {
    captureQuality = "query-sent-no-data";
  }

  return {
    captureQuality,
    reportMode: isSnapshotReport ? "snapshot" : "date-range",
    requestedRange,
    requestRange: requestRange || { start: "", end: "" },
    rangeMatched,
    requestFound: Boolean(matchingRequest),
    responseFound: Boolean(preferredResponse),
    recordCount: rowCount,
    dataEndpoint: preferredResponse?.url || matchingRequest?.url || "",
    requestMethod: matchingRequest?.method || "",
  };
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
  const frameHints = ["/pos_internal/", "#/Cashier", "Cashier"];
  for (let i = 0; i < 90; i += 1) {
    const frame = page.frames().find((item) => frameHints.some((hint) => item.url().includes(hint)));
    if (frame) {
      return frame;
    }
    const mainFrame = page.mainFrame();
    const mainFrameReady = await mainFrame
      .evaluate(() => {
        const app = document.querySelector("#app")?.__vue__?.$children?.[0];
        return !!app && (typeof app?.jumpPage === "function" || typeof app?.addTab === "function" || !!app?.reportArrList);
      })
      .catch(() => false);
    if (mainFrameReady) {
      return mainFrame;
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

function decodeJwtPayload(token) {
  try {
    const [, payload] = String(token || "").split(".");
    if (!payload) {
      return {};
    }
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = Buffer.from(normalized, "base64").toString("utf8");
    return JSON.parse(decoded);
  } catch {
    return {};
  }
}

async function extractAuth(page) {
  const auth = await page.evaluate(() => ({
    apiUrl: localStorage.getItem("yisapiurl") || localStorage.getItem("YIS_API_ERP_TEMP") || "",
    token: localStorage.getItem("yis_pc_token") || "",
  }));
  const tokenPayload = decodeJwtPayload(auth.token);
  return {
    ...auth,
    deptCode: tokenPayload.DeptCode || "",
    companyCode: tokenPayload.ComCode || "",
  };
}

function compactDate(value) {
  return String(value || "").replace(/-/g, "");
}

function shiftDate(dateText, yearDelta = 0, monthDelta = 0) {
  const date = new Date(`${dateText}T00:00:00+08:00`);
  if (Number.isNaN(date.getTime())) {
    return dateText;
  }
  date.setFullYear(date.getFullYear() + yearDelta);
  date.setMonth(date.getMonth() + monthDelta);
  return date.toISOString().slice(0, 10);
}

function buildDirectReportRequest(reportName, startDate, endDate, auth = {}) {
  const resolvedReportName = normalizeReportName(reportName);
  const compactStart = compactDate(startDate);
  const compactEnd = compactDate(endDate);
  const quotedDeptCode = auth.deptCode ? `'${auth.deptCode}'` : "";

  if (resolvedReportName === "库存综合分析") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelStockAnalysisList`,
      body: {
        rtype: 1,
        spenum: "",
        warecause: "",
      },
    };
  }

  if (resolvedReportName === "零售明细统计") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelDeptSaleList`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        depts: "",
        spenum: "",
        warecause: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "导购员报表") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposPerson/SelPersonSale`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        name: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "店铺零售清单") {
    return {
      url: `${ERP_API_URL}/FxErpApi/FXDIYReport/GetDIYReportData`,
      body: {
        menuid: "E004001007",
        gridid: "E004001007_main",
        parameter: {
          WareClause: "",
          Depart: "  ",
          EndDate: endDate,
          BeginDate: startDate,
          Operater: "",
          Tiem: "",
        },
      },
    };
  }

  if (resolvedReportName === "销售清单") {
    return {
      url: `${ERP_API_URL}/FxErpApi/FXDIYReport/GetDIYReportData`,
      body: {
        menuid: "E004001008",
        gridid: "E004001008_2",
        parameter: {
          BeginDate: compactStart,
          Depart: quotedDeptCode,
          EndDate: compactEnd,
          Operater: "",
          Tiem: "1",
          WareClause: "",
        },
      },
    };
  }

  if (resolvedReportName === "库存明细统计") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelDeptStockWaitList`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        depts: "",
        spenum: "",
        warecause: "",
        stockflag: "0",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "库存零售统计") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelDeptStockSaleList`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        depts: "",
        spenum: "",
        warecause: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "库存多维分析") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelDeptStockAnalysis`,
      body: {
        bdate: compactStart,
        edate: compactEnd,
        warecause: "",
        spenum: "",
        depts: "",
        stockflag: "0",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "进销存统计") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelInSalesReport`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        sort: "",
        spenum: "",
        warecause: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "出入库单据") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelOutInStockReport`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        datetype: "1",
        type: "已出库,已入库,在途",
        spenum: "",
        doctype: "1,2,3,4,5,6,7",
        warecause: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "日进销存") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelInSalesReportByDay`,
      body: {
        bdate: compactStart,
        edate: compactEnd,
        warecause: "",
        spenum: "",
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "会员综合分析") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelVipAnalysisReport`,
      body: {
        salebdate: compactStart,
        saleedate: compactEnd,
        birthbdate: "",
        birthedate: "",
        page: 0,
        pagesize: 0,
        salemoney1: "0",
        salemoney2: "0",
        tag: "",
        type: "",
      },
    };
  }

  if (resolvedReportName === "会员消费排行") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelVipSaleRank`,
      body: {
        bdate: compactStart,
        edate: compactEnd,
        page: 0,
        pagesize: 0,
      },
    };
  }

  if (resolvedReportName === "储值按店汇总") {
    return {
      url: `${ERP_API_URL}/FxErpApi/FXDIYReport/GetDIYReportData`,
      body: {
        menuid: "E004004003",
        gridid: "E004004003_main",
        parameter: {
          EndDate: endDate,
          BeginDate: startDate,
        },
      },
    };
  }

  if (resolvedReportName === "储值卡汇总") {
    return {
      url: `${ERP_API_URL}/FxErpApi/FXDIYReport/GetDIYReportData`,
      body: {
        menuid: "E004004004",
        gridid: "E004004004_main",
        parameter: {
          EndDate: endDate,
          BeginDate: startDate,
          Search: "",
        },
      },
    };
  }

  if (resolvedReportName === "储值卡明细") {
    return {
      url: `${ERP_API_URL}/FxErpApi/FXDIYReport/GetDIYReportData`,
      body: {
        menuid: "E004004005",
        gridid: "E004004005_main",
        parameter: {
          EndDate: endDate,
          BeginDate: startDate,
          Search: "",
        },
      },
    };
  }

  if (resolvedReportName === "会员中心") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposVipManage/SelVipInfoList`,
      body: {
        condition: "",
        searchval: "",
        VolumeNumber: "",
      },
    };
  }

  if (resolvedReportName === "商品销售情况") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposReport/SelSaleReportData`,
      body: {
        edate: compactEnd,
        bdate: compactStart,
        warecause: "",
        spenum: "",
      },
    };
  }

  if (resolvedReportName === "商品品类分析") {
    return {
      url: `${ERP_API_URL}/eposapi/YisEposWareTypeAnalysis/SelWareTypeAnalysisList`,
      body: {
        menuid: "E004005002",
        gridid: "E004005002_1",
        warecause: "",
        type: 3,
        bdate: compactStart,
        edate: compactEnd,
      },
    };
  }

  if (resolvedReportName === "门店销售月报") {
    return {
      url: `${JY_API_URL}/JyApi/DeptMonthSalesReport/DeptMonthSalesReport`,
      body: {
        Type: "1",
        BeginDate: startDate,
        EndDate: endDate,
        YBeginDate: shiftDate(startDate, -1, 0),
        YEndDate: shiftDate(endDate, -1, 0),
        MBeginDate: shiftDate(startDate, 0, -1),
        MEndDate: shiftDate(endDate, 0, -1),
        PageIndex: 1,
        PageSize: 2000,
      },
    };
  }

  if (resolvedReportName === "每日流水单") {
    return {
      url: `${JY_API_URL}/JyApi/ReconciliationAnalysis/SelectRetailDocPaymentSlip`,
      body: {
        MenuID: "E004006001",
        SearchType: "1",
        Search: "",
        LastDate: "",
        BeginDate: startDate,
        EndDate: endDate,
      },
    };
  }

  return null;
}

async function enrichReportWithDirectApi(session, reportName, captureLog, options = {}) {
  const requestPlan = buildDirectReportRequest(
    reportName,
    options.startDate || session.startDate || START_DATE,
    options.endDate || session.endDate || END_DATE,
    session.auth || {},
  );
  if (!requestPlan) {
    return false;
  }

  const headers = {
    "content-type": "application/json;charset=UTF-8",
  };
  if (session.auth?.token) {
    headers.token = session.auth.token;
    headers.authorization = `Bearer ${session.auth.token}`;
  }

  const response = await session.context.request.post(requestPlan.url, {
    data: requestPlan.body,
    headers,
    failOnStatusCode: false,
  });

  let body;
  try {
    body = await response.json();
  } catch {
    body = summarizeText(await response.text(), 3000);
  }

  captureLog.requests.push({
    method: "POST",
    url: requestPlan.url,
    postData: requestPlan.body,
    source: "direct-api",
  });
  captureLog.responses.push({
    status: response.status(),
    url: requestPlan.url,
    body,
    source: "direct-api",
  });
  return response.ok();
}

function flattenMenu(items, bucket = [], parents = []) {
  for (const item of items || []) {
    const current = {
      ...item,
      _parents: parents,
      _reportGroup: parents[1] || "",
    };
    bucket.push(current);
    if (item.SubList && item.SubList.length) {
      flattenMenu(item.SubList, bucket, [...parents, item.FuncName]);
    }
  }
  return bucket;
}

export function listReportMenuItems(menuList) {
  return flattenMenu(menuList)
    .filter((item) => item.FuncLID?.startsWith("E004") && item.FuncUrl && item._parents?.[0] === REPORT_ROOT_NAME)
    .map((item) => ({
      ...item,
      canonicalName: normalizeReportName(item.FuncName),
      groupName: item._reportGroup || REPORT_GROUP_MAP[item.FuncName] || "",
    }));
}

function buildMenuLookup(menuList) {
  const lookup = {};
  for (const item of listReportMenuItems(menuList)) {
    lookup[item.FuncName] = item;
    lookup[item.canonicalName] = item;
  }
  for (const [alias, canonical] of Object.entries(REPORT_ALIAS_MAP)) {
    if (lookup[canonical] && !lookup[alias]) {
      lookup[alias] = lookup[canonical];
    }
  }
  return lookup;
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
  return payload.retdata || [];
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
  const groupName = REPORT_GROUPS.has(reportName) ? reportName : REPORT_GROUP_MAP[reportName];
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
      capturedAt: new Date().toISOString(),
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
      capturedAt: new Date().toISOString(),
    });
  });

  return {
    start(reportName, metadata = {}) {
      activeCapture = {
        reportName,
        startedAt: new Date().toISOString(),
        ...metadata,
        requests: [],
        responses: [],
      };
      return activeCapture;
    },
    stop() {
      const snapshot = activeCapture || {
        reportName: "",
        startedAt: "",
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
  let frame;
  let frameError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      frame = await waitForPosFrame(page);
      break;
    } catch (error) {
      frameError = error;
      if (attempt === 3) {
        throw error;
      }
      console.log(`[STEP] frame retry ${attempt} failed, refreshing page`);
      await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => null);
      await page.waitForTimeout(4000 * attempt);
    }
  }
  if (!frame) {
    throw frameError || new Error("pos_internal frame not found");
  }
  console.log("[STEP] frame ok");
  const appState = await waitForOperationalApp(frame, page);
  console.log(`[STEP] app ready jump:${appState.hasJumpPage} addTab:${appState.hasAddTab} reportArr:${appState.hasReportArrList}`);
  const menuList = await fetchMenuList(page).catch(() => []);
  console.log(`[STEP] menu list loaded ${listReportMenuItems(menuList).length} reports`);
  const auth = await extractAuth(page).catch(() => ({ apiUrl: "", token: "" }));
  const menuLookup = buildMenuLookup(menuList);
  const reportMenuItems = listReportMenuItems(menuList);

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
    auth,
    menuList,
    menuLookup,
    reportMenuItems,
  };
}

export async function closeYeusoftSession(session) {
  await session.browser.close();
}

export async function captureReportInSession(session, reportName, options = {}) {
  const outputDir = options.outputDir ? path.resolve(options.outputDir) : session.outputDir;
  await ensureDir(outputDir);
  const resolvedReportName = normalizeReportName(reportName);
  const requestedRange = {
    start: options.startDate || session.startDate || START_DATE,
    end: options.endDate || session.endDate || END_DATE,
  };
  const directRequestPlan = buildDirectReportRequest(
    resolvedReportName,
    requestedRange.start,
    requestedRange.end,
    session.auth || {},
  );
  console.log(`[STEP] start ${resolvedReportName}`);
  const captureLog = session.collector.start(resolvedReportName, {
    requestedRange,
  });

  let directApiCaptured = false;
  let dateRangeApplied = false;
  let queryTriggered = false;
  let menuItem = session.menuLookup?.[resolvedReportName] || session.menuLookup?.[reportName] || null;

  if (directRequestPlan) {
    directApiCaptured = await enrichReportWithDirectApi(session, resolvedReportName, captureLog, {
      startDate: requestedRange.start,
      endDate: requestedRange.end,
    }).catch((error) => {
      console.log(`[STEP] direct api skipped: ${String(error)}`);
      return false;
    });
  }

  if (!directApiCaptured) {
    const openResult = await tryOpenReportByMenuItem(session.frame, session.page, resolvedReportName, menuItem);
    if (openResult?.ok) {
      console.log(
        `[STEP] opened by menu item ${menuItem?.FuncUrl || REPORT_INTERNAL_NAME_MAP[resolvedReportName] || "unknown"} via ${openResult.method || "unknown"}`,
      );
    } else {
      if (openResult?.reason) {
        console.log(`[STEP] menu item open skipped: ${openResult.reason}`);
      }
      await revealReportMenu(session.frame, session.page);
      console.log("[STEP] report menu open");
      await ensureReportGroup(session.frame, session.page, menuItem?.groupName || resolvedReportName);
      await clickReportMenuItem(session.frame, resolvedReportName);
      console.log(`[STEP] clicked ${resolvedReportName}`);
    }
    await session.page.waitForTimeout(2500);

    dateRangeApplied = await trySetDateRange(
      session.frame,
      requestedRange.start,
      requestedRange.end,
    );
    if (dateRangeApplied) {
      console.log("[STEP] date range updated");
      await session.page.waitForTimeout(800);
    }
    queryTriggered = await clickQueryButton(session.frame, session.page);
  }
  await session.page.waitForTimeout(2000);

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

  const screenshotPath = path.join(outputDir, `${sanitizeName(resolvedReportName)}.png`);
  console.log("[STEP] screenshot");
  await session.page.screenshot({ path: screenshotPath, fullPage: true });

  const finalCaptureLog = session.collector.stop();
  const captureSummary = summarizeCapture(resolvedReportName, finalCaptureLog, requestedRange);
  const payload = {
    capturedAt: new Date().toISOString(),
    siteUrl: SITE_URL,
    reportName: resolvedReportName,
    requestedReportName: reportName,
    menuItem: menuItem || null,
    tabState,
    filterLabels,
    dateRangeApplied,
    requestedDateRange: requestedRange,
    appliedDateRange: requestedRange,
    queryTriggered,
    directApiCaptured,
    captureSummary,
    requests: finalCaptureLog.requests,
    responses: finalCaptureLog.responses,
    screenshotPath,
  };

  const jsonPath = path.join(outputDir, `${sanitizeName(resolvedReportName)}.json`);
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
