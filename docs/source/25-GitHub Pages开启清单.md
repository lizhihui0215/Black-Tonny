# GitHub Pages 开启清单

版本：v1.0  
更新时间：2026-03-14  
适用对象：仓库管理员 / 老板 / 协作人员

## 这份清单解决什么问题

这份清单用来把当前仓库里的在线经营仪表盘发布到 GitHub Pages。

目标是：

1. 让最新看板有一个固定网址
2. 老板后面只打开这一个网址
3. 仓库继续保留历史版本，不影响日常生成

当前仓库已经准备好的固定发布目录是：

- `site/dashboard/`

固定入口文件是：

- `site/dashboard/index.html`

## 当前发布结构

- `site/dashboard/`
  用于 GitHub Pages 发布
- `reports/dashboard-history/`
  用于保留每天的历史版本

当前脚本每次运行会同时刷新两份：

1. 历史版本到 `reports/dashboard-history/`
2. 最新版本到 `site/dashboard/`

## GitHub Pages 最推荐配置

推荐方式：

1. 在 GitHub 打开这个仓库
2. 进入 `Settings`
3. 进入 `Pages`
4. 在 `Build and deployment` 里选择：
   - `Source`：`Deploy from a branch`
   - `Branch`：默认分支，例如 `main`
   - `Folder`：`/site`
5. 保存

这样 Pages 会从 `site/` 发布整个站点。

当前在线仪表盘入口就是：

- `/dashboard/`

也就是：

- `https://<你的GitHub用户名>.github.io/<仓库名>/dashboard/`

如果这是用户主页仓库或组织主页仓库，路径会更短，但当前默认先按项目仓库理解。

## 建议同时做的 2 件事

### 1. 在 `site/` 目录保留 `.nojekyll`

原因：

- 当前看板是纯 HTML/CSS/JS 输出
- 不需要 Jekyll 构建
- 加 `.nojekyll` 可以避免 GitHub Pages 把某些目录或文件当成 Jekyll 站点处理

## 2. 每次更新后只让老板打开固定路径

不要把每天带日期的 HTML 发给老板。

固定只发：

- `/dashboard/`

原因：

- 地址不会变
- 后面你脚本重跑后，老板不用重新换链接

## 上线前自查

上线前看这 6 项：

1. `site/dashboard/index.html` 是否存在
2. `site/dashboard/summary.md` 是否存在
3. `site/dashboard/report.md` 是否存在
4. 仓库默认分支是否已推送最新内容
5. GitHub Pages 是否选择了 `main + /site`
6. 页面打开后顶部是否先看到：
   - 今日经营重点
   - 核心经营指标
   - 赚钱机会

如果想在开启前先做一次自动检查，先看：

- [26-GitHub Pages上线前最后检查](26-GitHub%20Pages上线前最后检查.md)
- 或直接运行：

```bash
cd /Users/lizhihui/Workspace/Black\ Tony
python3 -m scripts.tools.check_pages_ready
```

## 上线后怎么验证

Pages 开启后，打开：

- `https://<你的GitHub用户名>.github.io/<仓库名>/dashboard/`

验证这几件事：

1. 手机打开是否第一屏能看到 `今日经营重点`
2. 页面顶部是否有 6 个模块
3. 页面顶部是否有 `当前阶段` 和 `日销趋势`
4. 标签悬浮是否还能看到操作提示
5. 详细数据区是否还能正常展开

## 如果页面没更新

先按这个顺序排查：

1. 本地有没有重新运行脚本
2. `site/dashboard/index.html` 是否真的被刷新
3. 是否已经提交并 push 到远程仓库
4. GitHub Pages 设置是否还是 `main + /site`
5. 浏览器是否缓存旧页面

## 官方参考

GitHub 官方关于 Pages 的说明：

- [What is GitHub Pages?](https://docs.github.com/pages/getting-started-with-github-pages/what-is-github-pages)
- [Creating a GitHub Pages site with Jekyll](https://docs.github.com/pages/setting-up-a-github-pages-site-with-jekyll/creating-a-github-pages-site-with-jekyll)
- [GitHub Pages documentation](https://docs.github.com/en/pages)

说明：

- 当前仓库不是按 Jekyll 内容站来用，而是借 Pages 托管纯静态 HTML
- 官方文档明确支持从分支和目录发布
- 如果不需要 Jekyll 处理，放 `.nojekyll` 会更稳
