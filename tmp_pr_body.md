MarketView 界面文案全部改为英文（含后端生成的展示文本），页面已无中文字符。

- 面板：模块空态、市场标签提示、折叠/展开、口径说明、表格空态与底部说明、筛选弹层（标题/已选/按钮/空值标签）、实时 chip 文案
- 后端展示文本：risk_notes（无基线 / 无 bar / 基线滞后 / ADV20 缺失 / 前收缺失 / 量比 / 波动偏高 / 涨跌）、阈值文案、高亮 note、风险提示分隔符由「；」改为「; 」
- 池配置 description 改英文
- 抽屉：副标题、会话行（去掉含中文注释的 session_note）、三图说明、gap 文案、SVG aria-label 与 tooltip
- 测试同步：MarketView 后端 92 passed、前端面板/抽屉测试 13 passed；前端全量 273 passed、typecheck / lint 无错误
- Playwright 实测：主页面、抽屉、筛选弹层三处 innerText 的中文字符计数均为 0
