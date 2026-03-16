# GitHub Pages 上线前最后检查

版本：v1.0  
更新时间：2026-03-14  
适用对象：仓库管理员 / 协作人员

## 这份清单解决什么问题

这份清单不是教你怎么开启 GitHub Pages，而是帮你在开启前先确认：

1. 发布目录是不是已经准备好
2. 首页和仪表盘入口是不是已经接好
3. 老板打开后会不会先看到正确的内容

如果这一步先做完，后面开 Pages 基本就是照着设置点一次。

## 当前最重要的发布入口

- Pages 首页：`site/index.html`
- 仪表盘固定入口：`site/dashboard/index.html`
- 文字摘要：`site/dashboard/summary.md`
- 分析报告：`site/dashboard/report.md`

老板后面固定打开的建议路径还是：

- `/dashboard/`

## 最推荐的检查方式

优先跑仓库里的检查脚本：

```bash
cd /Users/lizhihui/Workspace/Black\ Tony
python3 -m scripts.tools.check_pages_ready
```

这条命令会自动检查：

1. `site/.nojekyll` 是否存在
2. `site/index.html` 是否存在
3. `site/dashboard/` 里的最新文件是否齐全
4. README 是否已经接好入口
5. 仪表盘 HTML 是否包含老板最需要先看到的核心模块

## 脚本通过后，再人工看这 6 件事

1. 首页能不能点进仪表盘
2. 仪表盘顶部是不是先看到 `今日经营重点`
3. 六个老板模块顺序是否正确
4. 手机打开第一屏是否先看到结论和任务
5. 悬浮提示是否还能解释红黄绿标签和动作词
6. 页面里是否还能看到最新数据日期

## 如果脚本报错，先怎么处理

### 场景 1：缺文件

先确认有没有重新跑看板生成脚本：

```bash
cd /Users/lizhihui/Workspace/Black\ Tony
python3 -m scripts.dashboard.main \
  --input-dir /Users/lizhihui/Workspace/Black\ Tony/data/imports/inventory_zip_extract
```

如果你平时是喂 zip，就继续用 zip 路径跑。

### 场景 2：README 或首页链接不对

这通常不是数据问题，而是入口没接好。  
优先检查：

1. README 里有没有 `site/index.html`
2. 首页里有没有 `./dashboard/`
3. `site/dashboard/index.html` 是否真的存在

### 场景 3：仪表盘少了核心模块

这通常说明：

1. 看板脚本改坏了结构
2. 输出目录没有刷新到最新版本

这时候先重跑看板，再重跑检查脚本。

## 上线前最后一句判断

只有同时满足下面 3 件事，才建议去 GitHub 开 Pages：

1. 检查脚本全部通过
2. 手机本地打开第一页阅读顺序正常
3. 老板能在 10 秒内看懂今天先做什么

## 建议的最终操作顺序

1. 先跑 `python3 -m scripts.tools.check_pages_ready`
2. 再本地打开 `site/index.html`
3. 再本地打开 `site/dashboard/index.html`
4. 确认没问题后去 GitHub 开 `main + /site`
5. 开完后用手机打开最终网址再验一次
