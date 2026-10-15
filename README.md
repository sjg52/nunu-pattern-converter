# 努努排版小工具

努努图纸部件识别与自动排版工具。上传努努图纸（支持多图、非白底色），自动识别部件并基于 MaxRects 算法进行无重合排版，可设置部件间距、来源尺寸等参数，适合手工/缝纫制版场景下的图样排料。

## 功能特性

- 多图上传，自动识别图纸中的部件
- 形状感知的 MaxRects 无重合排版（碰撞检测优化）
- 支持非白色底色图纸
- 可配置部件间距、来源尺寸等参数
- 浅蓝主题界面，单文件运行，无需后端

## 在线访问

- **WorkBuddy 分享链接（最新发布）**：https://nunu-layout-tool.app.workbuddy.host/
- GitHub Pages：见本仓库 GitHub Pages 设置页

## 本地运行

纯静态单文件页面，直接用浏览器打开 `index.html` 即可；或在该目录执行：

```bash
python3 -m http.server 8000
```

然后访问 http://localhost:8000 。

## 目录结构

```
nunu-pattern-converter/
├── index.html   # 单文件应用（含样式与脚本）
└── README.md
```
