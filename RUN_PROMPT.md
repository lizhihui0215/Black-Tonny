# 🧠 Black-Tony Codex 执行指令（PROMPT）

## 🎯 目标
基于当前 SQLite 分析数据，完成门店经营分析，并更新所有 dashboard 与静态页面。

---

## ⚠️ 强制遵守 AGENTS.md
- 不允许修改数据库结构
- 不允许重建 ETL
- 必须复用 latest_* 视图
- 所有结论必须区分：
  - 实际数据（observed）
  - 估算（estimated）
  - 预测（forecast）

---

## 🚀 执行流程（必须严格按顺序）

### Phase 1：理解系统
1. 阅读以下文件（必须）：
   - scripts/tools/build_analysis_db.py
   - scripts/tools/calibrate_sales.py
   - scripts/dashboard/yeusoft.py
   - scripts/dashboard/main.py
   - docs/CODEBASE_MAP.md
   - docs/DATAFLOW_MAP.md
   - docs/SQLITE_ANALYSIS_MAP.md
   - docs/DASHBOARD_PAYLOAD_MAP.md

2. 输出：
   - 当前数据流
   - 可复用模块
   - 存在缺口

---

### Phase 2：构建经营分析

基于 SQLite 数据构建：

#### 📊 核心指标
- 销售额 / 销量 / 客单价
- 日销趋势
- 会员占比
- 累计销售 vs 当前库存

#### 📦 库存分析
- 库存健康度
- 库存周转（days of supply）
- 滞销商品
- 高库存风险

#### 🔥 销售表现
- 畅销款（best sellers）
- 慢销款（slow movers）
- 断货风险（stockout risk）

#### 📈 经营指标
- sell-through
- product mix
- inventory value
- profit estimate（如果有成本）

#### 🔮 预测
- 短期销售趋势
- 补货建议
- 去库存策略

---

## 🧾 输出要求（非常重要）

所有分析必须是：

### 中文 + 老板视角

每条必须包含：

- 结论（结论）
- 依据（数据）
- 建议（行动）
- 数据来源（source）
- 置信度（confidence）

---

## 📦 最终动作（必须执行）

1. 生成 dashboard payload（JSON）
2. 更新 HTML 页面
3. 确保：
   - JSON 正常
   - CSV 正常
   - HTML 正常
   - 页面不报错
   - 缺数据时 graceful degrade

---

## 🚫 禁止事项

- 不要修改 SQLite schema
- 不要破坏现有 pipeline
- 不要虚构数据
- 数据不足必须明确说明

---

## ✅ 成功标准

- dashboard 可正常打开
- 数据结构未破坏
- 输出为中文老板可读内容
- 所有模块兼容旧系统