# 小黑托昵门店增长、经营与小团队管理文档仓

这个仓库按 `纯文档` 方式维护，目标不是只做抖音号，而是把 `儿童贴身棉品门店` 的 `内容增长 + 店铺经营 + 1个老板2个员工的小团队管理` 放在一个总文档仓里持续推进。

## 本地运行准备

建议本地统一使用：

- `Python 3.11+`
- `Node.js 20+`

首次在新机器上拉起环境时，先执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
npx playwright install chromium
```

如果要启用店里电脑的一键同步，再准备本地配置文件：

```bash
cp data/examples/yeusoft_local_config.example.json data/local/yeusoft_local_config.json
cp data/examples/store_cost_snapshot.example.json data/local/store_cost_snapshot.json
```

最常用的本地命令：

```bash
python3 -m scripts.docs_site.build
python3 -m scripts.dashboard.main
python3 -m scripts.tools.publish_static_site --skip-sync
python3 -m scripts.tools.check_pages_ready
python3 -m scripts.tools.local_dashboard_service
```

## 数据与发布边界

这个仓库同时包含 `可公开的文档资产` 和 `仅适合本地保存的经营数据`，建议长期按下面的边界维护：

- `仅本地保存，不要提交`：`data/local/yeusoft_local_config.json`
- `原始导出 / 抓取产物，默认按本地敏感数据处理`：`data/imports/inventory_zip_extract/`、`reports/capture-cache/`、`reports/debug/explore/`、`reports/debug/inspect/`
- `发布前先复核是否适合公开`：`data/local/store_cost_snapshot.json`、`data/local/store_cost_history.json`、`reports/dashboard-history/`、`site/dashboard/`
- `通常适合继续版本化`：`docs/source/*.md`、`mindmaps/`、`scripts/`、`*.example.json`

如果后面要把仓库改成公开仓，建议先单独复查一次当前已经跟踪的 `data/`、`reports/`、`site/dashboard/` 内容，再决定哪些继续保留在 Git 里。

## 先看这里

- 总导航：看 [00-文档阅读导航](docs/source/00-文档阅读导航.md)
- 想直接打开最新在线经营仪表盘入口文件：看 [site/dashboard/index.html](site/dashboard/index.html)
- 想先看 GitHub Pages 首页入口：看 [site/index.html](site/index.html)
- 想直接网页阅读全部手册：看 [site/manuals/index.html](site/manuals/index.html)
- 想在店里电脑维护月度成本快照：看 [site/costs/index.html](site/costs/index.html)
- 想直接看怎么开启 GitHub Pages：看 [GitHub Pages开启清单](docs/source/25-GitHub%20Pages开启清单.md)
- 想先做 GitHub Pages 上线前自检：看 [GitHub Pages上线前最后检查](docs/source/26-GitHub%20Pages上线前最后检查.md)
- 想先搭整体经营盘：看 [店铺经营基础框架](docs/source/06-店铺经营基础框架.md)
- 想先拉营业额：看 [门店营业额增长框架](docs/source/15-门店营业额增长框架.md)
- 想先管库存和进货：看 [门店库存与营收核心计算方法](docs/source/18-门店库存与营收核心计算方法.md)
- 想先看库存销售图形化工具：看 [库存销售看板工具使用说明](docs/source/22-库存销售看板工具使用说明.md)
- 想先补全历史数据：看 [全量历史数据导出与看板升级清单](docs/source/23-全量历史数据导出与看板升级清单.md)
- 想先看下一步优化建议：看 [内容经营与数据看板下一步优化建议](docs/source/24-内容经营与数据看板下一步优化建议.md)
- 想先判断 POS 哪些报表值得接入老板看板：看 [POS报表收益评估与接入建议](docs/source/27-POS报表收益评估与接入建议.md)
- 想先看 POS 报表当前实际导出结果和引入决策：看 [POS报表导出结果与引入决策](docs/source/29-POS报表导出结果与引入决策.md)
- 想看整个经营系统后面怎么拆任务、按什么顺序实现：看 [经营系统总目标拆解与实施任务清单](docs/source/30-经营系统总目标拆解与实施任务清单.md)
- 想维护月度成本、利润和保本口径：看 [月度成本快照维护说明](docs/source/28-月度成本快照维护说明.md)
- 想先做复购和会员：看 [老客复购经营清单](docs/source/19-老客复购经营清单.md)
- 想先看扩品：看 [低冲突扩品与产品线丰富策略](docs/source/21-低冲突扩品与产品线丰富策略.md)
- 想先让员工跑顺：看 [小团队门店分工与排班手册](docs/source/08-小团队门店分工与排班手册.md)
- 想先看全部脑图：去 `mindmaps/`

## 按目标阅读

| 目标 | 建议先看 |
| --- | --- |
| 门店整体经营 | [06-店铺经营基础框架](docs/source/06-店铺经营基础框架.md) |
| 营业额增长 | [15-门店营业额增长框架](docs/source/15-门店营业额增长框架.md) |
| 库存和进货 | [18-门店库存与营收核心计算方法](docs/source/18-门店库存与营收核心计算方法.md) |
| 库存销售看板工具 | [22-库存销售看板工具使用说明](docs/source/22-库存销售看板工具使用说明.md) |
| GitHub Pages 在线仪表盘入口 | [site/dashboard/index.html](site/dashboard/index.html) |
| GitHub Pages 首页入口 | [site/index.html](site/index.html) |
| GitHub Pages 文档中心 | [site/manuals/index.html](site/manuals/index.html) |
| 月度成本维护台（店里电脑） | [site/costs/index.html](site/costs/index.html) |
| GitHub Pages 开启步骤 | [25-GitHub Pages开启清单](docs/source/25-GitHub%20Pages开启清单.md) |
| GitHub Pages 上线前最后检查 | [26-GitHub Pages上线前最后检查](docs/source/26-GitHub%20Pages上线前最后检查.md) |
| 历史数据补齐 | [23-全量历史数据导出与看板升级清单](docs/source/23-全量历史数据导出与看板升级清单.md) |
| 下一步优化建议 | [24-内容经营与数据看板下一步优化建议](docs/source/24-内容经营与数据看板下一步优化建议.md) |
| POS报表接入优先级 | [27-POS报表收益评估与接入建议](docs/source/27-POS报表收益评估与接入建议.md) |
| POS报表当前导出结果与引入决策 | [29-POS报表导出结果与引入决策](docs/source/29-POS报表导出结果与引入决策.md) |
| 经营系统总任务路线 | [30-经营系统总目标拆解与实施任务清单](docs/source/30-经营系统总目标拆解与实施任务清单.md) |
| 复购和会员 | [19-老客复购经营清单](docs/source/19-老客复购经营清单.md) |
| 扩品策略 | [21-低冲突扩品与产品线丰富策略](docs/source/21-低冲突扩品与产品线丰富策略.md) |
| 商场引流 | [14-商场引流与营业额增长方法](docs/source/14-商场引流与营业额增长方法.md) |
| 员工执行 | [08-小团队门店分工与排班手册](docs/source/08-小团队门店分工与排班手册.md) |
| 接待成交 | [12-门店接待话术SOP](docs/source/12-门店接待话术SOP.md) |
| 抖音内容 | [01-抖音起号执行手册](docs/source/01-抖音起号执行手册.md) |
| 老号优化 | [02-抖音老号低流量优化手册](docs/source/02-抖音老号低流量优化手册.md) |
| AI协同 | [03-AI工具学习与协同手册](docs/source/03-AI工具学习与协同手册.md) |

## 文档目录

## 在线仪表盘

- GitHub Pages 固定入口文件：[`site/dashboard/index.html`](site/dashboard/index.html)
- GitHub Pages 首页入口：[`site/index.html`](site/index.html)
- GitHub Pages 文档中心入口：[`site/manuals/index.html`](site/manuals/index.html)
- 店里电脑本地成本维护入口：[`site/costs/index.html`](site/costs/index.html)
- Pages 开启后，建议固定访问路径：`/dashboard/`
- GitHub Pages 开启说明：[`docs/source/25-GitHub Pages开启清单.md`](docs/source/25-GitHub%20Pages开启清单.md)
- GitHub Pages 上线前最后检查：[`docs/source/26-GitHub Pages上线前最后检查.md`](docs/source/26-GitHub%20Pages上线前最后检查.md)
- 历史版本继续保留在 [`reports/dashboard-history/`](reports/dashboard-history/)
- 仓库内 `site/dashboard/` 放最新可发布版本，`reports/` 放每天留档版本

## 内容增长线

- [抖音起号执行手册](docs/source/01-抖音起号执行手册.md)
  内容定位、人设、主页配置、基础内容系统，主线聚焦 `儿童贴身棉品`
- [抖音老号低流量优化手册](docs/source/02-抖音老号低流量优化手册.md)
  适合已经发了很多视频但播放和咨询不理想的账号
- [AI工具学习与协同手册](docs/source/03-AI工具学习与协同手册.md)
  `Kimi + 即梦AI + 剪映` 的学习路径、付费顺序和协同方式
- [项目推进路线图](docs/source/04-项目推进路线图.md)
  未来 90 天怎么分阶段推进
- [PhaseA前14天执行清单](docs/source/05-PhaseA前14天执行清单.md)
  前 14 天每天做什么、做到什么算完成

## 店铺经营线

- [店铺经营基础框架](docs/source/06-店铺经营基础框架.md)
  从接待、产品结构、成交承接、复购、会员和日常经营去搭门店基本盘
- [店铺日常经营复盘表](docs/source/07-店铺日常经营复盘表.md)
  让每天、每周、每月的经营复盘有固定记录方式
- [门店接待话术SOP](docs/source/12-门店接待话术SOP.md)
  把顾客进店后的开口、判断、推荐和收口统一成现场可执行的话术
- [抖音到店承接SOP](docs/source/13-抖音到店承接SOP.md)
  把评论、私信、直播里的问题一路接到门店现场，不让顾客到店重新解释一遍
- [商场引流与营业额增长方法](docs/source/14-商场引流与营业额增长方法.md)
  重点解决商场店怎么把现成客流变成停留、进店和成交
- [门店营业额增长框架](docs/source/15-门店营业额增长框架.md)
  把营业额拆成公式、分工和周看板，知道门店该先拉哪个指标
- [库存预警与补货计算手册](docs/source/16-库存预警与补货计算手册.md)
  重点解决什么时候该补货、补多少、哪些货已经进入风险区
- [进货平衡库存与收益模型](docs/source/17-进货平衡库存与收益模型.md)
  重点解决怎么进货不压货，同时尽量不丢掉营业额机会
- [门店库存与营收核心计算方法](docs/source/18-门店库存与营收核心计算方法.md)
  用一套公式同时看营业额、库存覆盖、售罄率和毛利率
- [老客复购经营清单](docs/source/19-老客复购经营清单.md)
  重点解决哪些老客最值得经营、什么时候提醒、怎么提高回头营业额
- [会员与私域跟进清单](docs/source/20-会员与私域跟进清单.md)
  重点解决顾客怎么轻量沉淀、怎么跟进而不打扰
- [低冲突扩品与产品线丰富策略](docs/source/21-低冲突扩品与产品线丰富策略.md)
  重点解决商场店怎么低风险试扩品，并用公开业态信息做低冲突判断
- [库存销售看板工具使用说明](docs/source/22-库存销售看板工具使用说明.md)
  重点解决怎么把库存、销售、会员和补货建议做成老板和店员都能看的图形化工具
- [全量历史数据导出与看板升级清单](docs/source/23-全量历史数据导出与看板升级清单.md)
  重点解决为什么现在只看到最近几天，以及怎么补齐 `2025-03` 到现在的完整趋势数据
- [内容经营与数据看板下一步优化建议](docs/source/24-内容经营与数据看板下一步优化建议.md)
  重点解决当前仓库下一阶段最值得继续补什么、先补什么
- [POS报表收益评估与接入建议](docs/source/27-POS报表收益评估与接入建议.md)
  重点解决 Yeusoft 哪些报表最值得接入老板看板、哪些适合只放详细页或复盘
- [POS报表导出结果与引入决策](docs/source/29-POS报表导出结果与引入决策.md)
  重点解决当前已经实际导出到什么程度、哪些值得现在就引入、哪些先继续攻克
- [经营系统总目标拆解与实施任务清单](docs/source/30-经营系统总目标拆解与实施任务清单.md)
  重点解决整个项目后续怎么拆主线、按什么顺序实现、当前哪些先做哪些暂不做
- [月度成本快照维护说明](docs/source/28-月度成本快照维护说明.md)
  重点解决老板每月怎么维护销售、进货、固定费用和保本口径，而不需要手改 JSON

## 小团队管理线

- [小团队门店分工与排班手册](docs/source/08-小团队门店分工与排班手册.md)
  按 `1 个老板 + 2 位员工` 的实际分工，固定排班、交接班和日常纪律
- [员工培训与带教SOP](docs/source/09-员工培训与带教SOP.md)
  让老板把两位员工带上手，统一接待和抖音来客承接
- [老板周复盘与执行校准](docs/source/10-老板周复盘与执行校准.md)
  用小团队能执行的方式，每周看经营、执行和培训
- [员工日常检查清单](docs/source/11-员工日常检查清单.md)
  把员工每天要看的、要做的、要交接的动作固定下来

## 脑图资源

说明：

- `mindmaps/*.md` 是可编辑源文件
- `mindmaps/*.xmind` 是可直接在 XMind 里打开的版本

| 主题 | Markdown脑图 | XMind |
| --- | --- | --- |
| 文档阅读导航 | [00](mindmaps/00-文档阅读导航-mindmap.md) | [00](mindmaps/00-文档阅读导航-mindmap.xmind) |
| 抖音起号 | [01](mindmaps/01-抖音起号-mindmap.md) | [01](mindmaps/01-抖音起号-mindmap.xmind) |
| 老号优化 | [02](mindmaps/02-抖音老号低流量优化-mindmap.md) | [02](mindmaps/02-抖音老号低流量优化-mindmap.xmind) |
| AI工具学习 | 无 | [03](mindmaps/03-AI工具学习与协同手册.xmind) |
| 项目推进路线图 | [04](mindmaps/04-项目推进路线图-mindmap.md) | [04](mindmaps/04-项目推进路线图-mindmap.xmind) |
| PhaseA前14天执行清单 | [05](mindmaps/05-PhaseA前14天执行清单-mindmap.md) | [05](mindmaps/05-PhaseA前14天执行清单-mindmap.xmind) |
| 店铺经营基础框架 | [06](mindmaps/06-店铺经营基础框架-mindmap.md) | [06](mindmaps/06-店铺经营基础框架-mindmap.xmind) |
| 店铺日常经营复盘表 | [07](mindmaps/07-店铺日常经营复盘表-mindmap.md) | [07](mindmaps/07-店铺日常经营复盘表-mindmap.xmind) |
| 小团队门店分工与排班 | [08](mindmaps/08-小团队门店分工与排班手册-mindmap.md) | [08](mindmaps/08-小团队门店分工与排班手册-mindmap.xmind) |
| 员工培训与带教 | [09](mindmaps/09-员工培训与带教SOP-mindmap.md) | [09](mindmaps/09-员工培训与带教SOP-mindmap.xmind) |
| 老板周复盘与执行校准 | [10](mindmaps/10-老板周复盘与执行校准-mindmap.md) | [10](mindmaps/10-老板周复盘与执行校准-mindmap.xmind) |
| 员工日常检查清单 | [11](mindmaps/11-员工日常检查清单-mindmap.md) | [11](mindmaps/11-员工日常检查清单-mindmap.xmind) |
| 门店接待话术 | [12](mindmaps/12-门店接待话术SOP-mindmap.md) | [12](mindmaps/12-门店接待话术SOP-mindmap.xmind) |
| 抖音到店承接 | [13](mindmaps/13-抖音到店承接SOP-mindmap.md) | [13](mindmaps/13-抖音到店承接SOP-mindmap.xmind) |
| 商场引流与营业额增长 | [14](mindmaps/14-商场引流与营业额增长方法-mindmap.md) | [14](mindmaps/14-商场引流与营业额增长方法-mindmap.xmind) |
| 门店营业额增长框架 | [15](mindmaps/15-门店营业额增长框架-mindmap.md) | [15](mindmaps/15-门店营业额增长框架-mindmap.xmind) |
| 库存预警与补货计算 | [16](mindmaps/16-库存预警与补货计算手册-mindmap.md) | [16](mindmaps/16-库存预警与补货计算手册-mindmap.xmind) |
| 进货平衡库存与收益 | [17](mindmaps/17-进货平衡库存与收益模型-mindmap.md) | [17](mindmaps/17-进货平衡库存与收益模型-mindmap.xmind) |
| 门店库存与营收核心计算方法 | [18](mindmaps/18-门店库存与营收核心计算方法-mindmap.md) | [18](mindmaps/18-门店库存与营收核心计算方法-mindmap.xmind) |
| 老客复购经营清单 | [19](mindmaps/19-老客复购经营清单-mindmap.md) | [19](mindmaps/19-老客复购经营清单-mindmap.xmind) |
| 会员与私域跟进清单 | [20](mindmaps/20-会员与私域跟进清单-mindmap.md) | [20](mindmaps/20-会员与私域跟进清单-mindmap.xmind) |
| 低冲突扩品与产品线丰富策略 | [21](mindmaps/21-低冲突扩品与产品线丰富策略-mindmap.md) | [21](mindmaps/21-低冲突扩品与产品线丰富策略-mindmap.xmind) |

## 仓库定位

后续这个仓库统一按三条主线维护：

- `内容增长线`：负责获客、建立信任、把问题带进门店
- `店铺经营线`：负责接待、成交、复购、经营稳定
- `小团队管理线`：负责 `1个老板 + 2个员工` 的分工、排班、带教、复盘和执行稳定

三条线必须互相联动，而不是各做各的。

## 维护规则

- 改策略、SOP、脚本、学习路径、经营动作时，优先改 `docs/source/`
- 改了章节结构后，同步更新 `mindmaps/`
- 新增专题时，沿用两位序号命名，方便长期排序
- 如果 XMind 文件需要继续补，优先保持和同主题 Markdown 脑图一致
