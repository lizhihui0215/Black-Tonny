import fs from "fs/promises";
import path from "path";
import {
  captureReportInSession,
  closeYeusoftSession,
  createYeusoftSession,
} from "./capture_yeusoft_report_metadata.mjs";

const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/yeusoft_report_capture");
const DEFAULT_REPORTS = [
  "店铺零售清单",
  "销售清单",
  "库存综合分析",
  "出入库单据",
  "商品销售情况",
  "零售明细统计",
  "库存明细统计",
  "库存零售统计",
  "进销存统计",
  "会员综合分析",
  "会员消费排行",
  "每日流水单",
];
const REPORTS = process.env.YEU_REPORT_LIST
  ? process.env.YEU_REPORT_LIST.split(",").map((item) => item.trim()).filter(Boolean)
  : DEFAULT_REPORTS;

function withTimeout(promise, reportName, ms = 90000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${reportName} 超时（>${ms / 1000}s）`)), ms);
    }),
  ]);
}

function extractEndpoint(payload, keyword) {
  return payload.responses.find((item) => item.url.includes(keyword));
}

function extractRequest(payload, keyword) {
  return payload.requests.find((item) => item.url.includes(keyword));
}

function extractReportSummary(result) {
  const configuration = extractEndpoint(result.payload, "GetConfiguration");
  const grid = extractEndpoint(result.payload, "GetViewGridList");
  const queryRequest = extractRequest(result.payload, "GetDIYReportData");
  const queryResponse = extractEndpoint(result.payload, "GetDIYReportData");

  const configurationBody = configuration?.body || {};
  const queryBody = queryResponse?.body || {};
  const retData = queryBody?.retdata || {};
  const dataRows = Array.isArray(retData?.Data) ? retData.Data.length : 0;
  const firstRowKeys = dataRows && retData.Data[0] ? Object.keys(retData.Data[0]).slice(0, 30) : [];

  return {
    reportName: result.payload.reportName,
    capturedAt: result.payload.capturedAt,
    tabValue: result.payload.tabState.titleTabsValue,
    funcUrls: result.payload.tabState.editableTabs.map((item) => item.FuncUrl).filter(Boolean),
    filterLabels: result.payload.filterLabels,
    configurationUrl: configuration?.url || "",
    configurationProc: configurationBody?.retdata?.Sql || configurationBody?.retdata?.sql || "",
    gridUrl: grid?.url || "",
    gridColumns:
      Array.isArray(grid?.body?.retdata?.Columns) ? grid.body.retdata.Columns.map((item) => item.caption || item.field || item.prop).filter(Boolean) : [],
    queryUrl: queryRequest?.url || "",
    queryPayload: queryRequest?.postData || {},
    queryRows: dataRows,
    queryKeys: firstRowKeys,
    jsonPath: result.jsonPath,
    screenshotPath: result.screenshotPath,
  };
}

async function main() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });

  const summaries = [];
  const outputPath = path.join(OUTPUT_DIR, "index.json");
  const session = await createYeusoftSession({ outputDir: OUTPUT_DIR });
  try {
    for (const reportName of REPORTS) {
      try {
        const result = await withTimeout(captureReportInSession(session, reportName, { outputDir: OUTPUT_DIR }), reportName);
        summaries.push({ status: "ok", ...extractReportSummary(result) });
        console.log(`[OK] ${reportName}`);
      } catch (error) {
        summaries.push({
          status: "error",
          reportName,
          error: String(error),
        });
        console.error(`[ERROR] ${reportName}: ${error}`);
      }

      await fs.writeFile(
        outputPath,
        JSON.stringify(
          {
            capturedAt: new Date().toISOString(),
            reports: summaries,
          },
          null,
          2,
        ),
        "utf8",
      );
    }
  } finally {
    await closeYeusoftSession(session);
  }

  const payload = {
    capturedAt: new Date().toISOString(),
    reports: summaries,
  };

  await fs.writeFile(outputPath, JSON.stringify(payload, null, 2), "utf8");
  console.log(`Saved summary index: ${outputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
