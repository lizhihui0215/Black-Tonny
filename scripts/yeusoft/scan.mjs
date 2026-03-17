import fs from "fs/promises";
import path from "path";
import {
  captureReportInSession,
  closeYeusoftSession,
  createYeusoftSession,
  listReportMenuItems,
  normalizeReportName,
} from "./capture.mjs";

const OUTPUT_DIR = process.env.YEU_OUTPUT_DIR || path.resolve("reports/capture-cache");
const LAST_SUCCESS_DIR = path.join(OUTPUT_DIR, "_last_success");
const DEFAULT_START_DATE = process.env.YEU_START_DATE || "2025-03-01";
const DEFAULT_END_DATE = process.env.YEU_END_DATE || new Date().toISOString().slice(0, 10);
const DEFAULT_MODE = process.env.YEU_SYNC_MODE || "full";
const QUICK_REPORTS = [
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
const FULL_REPORTS = [
  "零售明细统计",
  "导购员报表",
  "店铺零售清单",
  "销售清单",
  "库存明细统计",
  "库存零售统计",
  "库存综合分析",
  "库存多维分析",
  "进销存统计",
  "出入库单据",
  "日进销存",
  "退货明细",
  "会员综合分析",
  "会员消费排行",
  "储值按店汇总",
  "储值卡汇总",
  "储值卡明细",
  "商品销售情况",
  "商品品类分析",
  "门店销售月报",
  "每日流水单",
  "会员中心",
];
const KNOWN_IGNORED_REPORTS = {
  退货明细: "接口当前已确认不稳定，暂时忽略并沿用现状，后续单独处理。",
};

function withTimeout(promise, reportName, ms = 90000) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(`${reportName} 超时（>${ms / 1000}s）`)), ms);
    }),
  ]);
}

function normalizeReportList(values) {
  return [...new Set(values.map((item) => normalizeReportName(item)).filter(Boolean))];
}

function sanitizeName(value) {
  return String(value || "")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .slice(0, 80);
}

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

function pickReportNames(session, mode) {
  const menuReports = normalizeReportList(listReportMenuItems(session.menuList).map((item) => item.FuncName));
  if (process.env.YEU_REPORT_LIST) {
    return normalizeReportList(process.env.YEU_REPORT_LIST.split(",").map((item) => item.trim()));
  }
  if (mode === "quick") {
    return QUICK_REPORTS.filter((name) => menuReports.includes(name));
  }
  return normalizeReportList([...FULL_REPORTS, ...menuReports]);
}

function classifyResult(summary) {
  if (!summary) {
    return "opened-only";
  }
  if (["full-range-data", "snapshot-data", "full-range-empty"].includes(summary.captureQuality)) {
    return "ok";
  }
  if (["partial-range-data", "query-sent-no-data"].includes(summary.captureQuality)) {
    return "partial";
  }
  return "opened-only";
}

function summarizeCounts(reports) {
  return reports.reduce(
    (acc, item) => {
      acc.total += 1;
      acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    },
    { total: 0, ok: 0, partial: 0, warning: 0, ignored: 0, "opened-only": 0, error: 0 },
  );
}

function ignoredReasonFor(reportName) {
  return KNOWN_IGNORED_REPORTS[normalizeReportName(reportName)] || "";
}

function applyKnownIssuePolicy(summary) {
  if (!summary) {
    return summary;
  }
  const ignoredReason = ignoredReasonFor(summary.reportName || summary.requestedReportName || "");
  if (!ignoredReason || summary.status === "ok") {
    return summary;
  }
  return {
    ...summary,
    status: "ignored",
    ignored: true,
    ignoredReason,
  };
}

function buildReportSummary(result, requestedRange) {
  const captureSummary = result.payload.captureSummary || {};
  return {
    status: classifyResult(captureSummary),
    reportName: result.payload.reportName,
    requestedReportName: result.payload.requestedReportName || result.payload.reportName,
    capturedAt: result.payload.capturedAt,
    requestedDateRange: requestedRange,
    appliedDateRange: result.payload.appliedDateRange || requestedRange,
    dateRangeApplied: Boolean(result.payload.dateRangeApplied),
    queryTriggered: Boolean(result.payload.queryTriggered),
    captureQuality: captureSummary.captureQuality || "opened-only",
    reportMode: captureSummary.reportMode || "unknown",
    rangeMatched: Boolean(captureSummary.rangeMatched),
    requestFound: Boolean(captureSummary.requestFound),
    responseFound: Boolean(captureSummary.responseFound),
    recordCount: Number(captureSummary.recordCount || 0),
    dataEndpoint: captureSummary.dataEndpoint || "",
    requestMethod: captureSummary.requestMethod || "",
    tabValue: result.payload.tabState?.titleTabsValue || "",
    funcUrls: (result.payload.tabState?.editableTabs || []).map((item) => item.FuncUrl).filter(Boolean),
    jsonPath: result.jsonPath,
    screenshotPath: result.screenshotPath,
  };
}

function shouldPersistLastSuccess(summary) {
  if (!summary) {
    return false;
  }
  if (summary.status === "opened-only" || summary.status === "error") {
    return false;
  }
  return Number(summary.recordCount || 0) > 0 || summary.captureQuality === "snapshot-data";
}

function artifactPaths(outputDir, reportName) {
  const baseName = sanitizeName(reportName);
  return {
    currentJsonPath: path.join(outputDir, `${baseName}.json`),
    currentScreenshotPath: path.join(outputDir, `${baseName}.png`),
    backupJsonPath: path.join(LAST_SUCCESS_DIR, `${baseName}.json`),
    backupScreenshotPath: path.join(LAST_SUCCESS_DIR, `${baseName}.png`),
  };
}

async function fileExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function persistLastSuccess(summary, reportName, outputDir) {
  if (!shouldPersistLastSuccess(summary)) {
    return;
  }
  const paths = artifactPaths(outputDir, reportName);
  await ensureDir(LAST_SUCCESS_DIR);
  if (await fileExists(paths.currentJsonPath)) {
    await fs.copyFile(paths.currentJsonPath, paths.backupJsonPath);
  }
  if (await fileExists(paths.currentScreenshotPath)) {
    await fs.copyFile(paths.currentScreenshotPath, paths.backupScreenshotPath);
  }
}

async function buildFallbackSummary(reportName, requestedRange, outputDir, error) {
  const paths = artifactPaths(outputDir, reportName);
  const candidates = [
    {
      jsonPath: paths.backupJsonPath,
      screenshotPath: paths.backupScreenshotPath,
      label: "上次成功数据缓存",
    },
    {
      jsonPath: paths.currentJsonPath,
      screenshotPath: paths.currentScreenshotPath,
      label: "当前目录已有数据",
    },
  ];

  for (const candidate of candidates) {
    if (!(await fileExists(candidate.jsonPath))) {
      continue;
    }
    try {
      const payload = JSON.parse(await fs.readFile(candidate.jsonPath, "utf8"));
      if (candidate.jsonPath !== paths.currentJsonPath) {
        await fs.copyFile(candidate.jsonPath, paths.currentJsonPath);
        if (await fileExists(candidate.screenshotPath)) {
          await fs.copyFile(candidate.screenshotPath, paths.currentScreenshotPath);
        }
      }
      const summary = buildReportSummary(
        {
          jsonPath: paths.currentJsonPath,
          screenshotPath: await fileExists(paths.currentScreenshotPath) ? paths.currentScreenshotPath : candidate.screenshotPath,
          payload,
        },
        requestedRange,
      );
      return applyKnownIssuePolicy({
        ...summary,
        status: "warning",
        fallbackUsed: true,
        fallbackSource: candidate.label,
        fallbackCapturedAt: payload.capturedAt || "",
        staleReason: String(error),
      });
    } catch {
      // Continue trying the next fallback source.
    }
  }

  return null;
}

async function writeIndex(outputPath, payload) {
  await fs.writeFile(outputPath, JSON.stringify(payload, null, 2), "utf8");
}

async function main() {
  await fs.mkdir(OUTPUT_DIR, { recursive: true });
  await fs.mkdir(LAST_SUCCESS_DIR, { recursive: true });

  const requestedRange = {
    start: DEFAULT_START_DATE,
    end: DEFAULT_END_DATE,
  };
  const session = await createYeusoftSession({
    outputDir: OUTPUT_DIR,
    startDate: requestedRange.start,
    endDate: requestedRange.end,
  });
  const mode = DEFAULT_MODE;
  const reports = pickReportNames(session, mode);
  const summaries = [];
  const outputPath = path.join(OUTPUT_DIR, "index.json");
  const reportTimeoutMs = mode === "full" ? 120000 : 90000;

  try {
    for (const reportName of reports) {
      try {
        const result = await withTimeout(
          captureReportInSession(session, reportName, {
            outputDir: OUTPUT_DIR,
            startDate: requestedRange.start,
            endDate: requestedRange.end,
          }),
          reportName,
          reportTimeoutMs,
        );
        const summary = applyKnownIssuePolicy(buildReportSummary(result, requestedRange));
        summaries.push(summary);
        await persistLastSuccess(summary, result.payload.reportName, OUTPUT_DIR);
        console.log(summary.status === "ignored" ? `[IGNORED] ${reportName}` : `[OK] ${reportName}`);
      } catch (error) {
        const fallbackSummary = await buildFallbackSummary(reportName, requestedRange, OUTPUT_DIR, error);
        if (fallbackSummary) {
          summaries.push(fallbackSummary);
          if (fallbackSummary.status === "ignored") {
            console.warn(`[IGNORED] ${reportName}: ${error}；已沿用${fallbackSummary.fallbackSource}`);
          } else {
            console.warn(`[WARN] ${reportName}: ${error}；已沿用${fallbackSummary.fallbackSource}`);
          }
        } else {
          const errorSummary = applyKnownIssuePolicy({
            status: "error",
            reportName,
            requestedDateRange: requestedRange,
            captureQuality: "error",
            error: String(error),
          });
          summaries.push(errorSummary);
          if (errorSummary.status === "ignored") {
            console.warn(`[IGNORED] ${reportName}: ${error}`);
          } else {
            console.error(`[ERROR] ${reportName}: ${error}`);
          }
        }
      }

      const partialPayload = {
        capturedAt: new Date().toISOString(),
        mode,
        requestedDateRange: requestedRange,
        counts: summarizeCounts(summaries),
        totalReports: reports.length,
        reports: summaries,
      };
      await writeIndex(outputPath, partialPayload);
    }
  } finally {
    await closeYeusoftSession(session);
  }

  const payload = {
    capturedAt: new Date().toISOString(),
    mode,
    requestedDateRange: requestedRange,
    counts: summarizeCounts(summaries),
    totalReports: reports.length,
    reports: summaries,
  };

  await writeIndex(outputPath, payload);
  console.log(`Saved summary index: ${outputPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
