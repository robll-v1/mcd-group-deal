# WorkBuddy 开发上下文

本文件记录本项目使用腾讯 WorkBuddy 的实际开发过程，用于核验参与 WorkBuddy 专项奖励的条件。

- 工具：WorkBuddy（Agent 模式）
- 日期：2026-10-24
- 开发者 GitHub 账号：robll-v1

---

## 会话 1 · 接入麦当劳 MCP

**目标**：把麦当劳中国 MCP 接进 WorkBuddy，确认可用。

过程要点：

1. 写入 `~/.workbuddy/mcp.json`，`type` 从 `streamablehttp` 修正为 `streamable-http`
2. 实测发现 `Authorization` 裸 token 被服务端 403 拒绝（返回「校验鉴权authToken必填」），
   补上 `Bearer ` 前缀后 `initialize` 返回 200
3. `tools/list` 拿到 35 个工具，逐个检查了 `create-order` / `calculate-price` /
   `query-meals` / `query-promotions` / `query-meal-assistance` 的入参定义

> 这一步决定了后面整个技术方案：确认了团餐场景 `beType=6` 是唯一能拿到满减规则的口子，
> 同时确认了 MCP **没有支付工具**，`create-order` 只产待支付订单。

## 会话 2 · 赛事规则核对与选题

**目标**：确认比赛规则边界，确定做什么。

过程要点：

1. 读取活动仓库 `M-China/mcd-developer-innovation-challenge` 的
   `README.md` / `activityGuidelines.md` / `RANKING.md`
2. 发现官方两处文档的必交文件清单不一致（README 表格缺 `mcp-config.example.json`），
   决定按「全交」处理
3. 抓取实时排行榜（当时第 1 名 1185 star，第 98 名约 44 star），据此确定现实目标
4. 排除了「自动订购」方向：无支付工具导致无法闭环、demo 不可截图、有合规风险
5. 选定「团餐凑单 + AA 分账」：传播性最好，且正好用上只在团餐接口暴露的满减规则

## 会话 3 · 实现引擎

**目标**：把凑单算法和分账逻辑写成可离线复现的代码。

交付：

- `scripts/optimizer.py`：金额用整数分运算；优惠按「同组互斥、跨组叠加」建模；
  三条搜索路径（凑门槛 / 拆单 / 换品）；最大余数法分摊
- `scripts/render.py`：Markdown 分账卡渲染
- `scripts/demo.py`：离线演示
- `scripts/test_optimizer.py`：6 个自测用例

调试过程中修掉的问题：

1. 方案列表里「替换同款」重复出现 9 行 → 改为每类只保留最优一条
2. 公摊凑单件单独占一行导致团长吃亏 → 改为按人头均摊进每人小计
3. `result["best"]` 与 `plans` 里不是同一对象，渲染层无法比对 → 改为共用同一字典
4. 自测用例自身的数据构造错误（门槛算错），逐个修正至 6/6 通过

## 会话 4 · 文档与合规

- `CONTEST_DECLARATION.md` 从官方仓库逐字节复制，未做任何改动
- `mcp-config.example.json` 只保留 `${MCD_MCP_TOKEN}` 占位符，无真实 Token
- 示例菜单数据明确标注为虚构，避免与官方定价混淆
- 在 SKILL.md 与 README 中明确写入「不代替用户付款」「下单前必须确认」两条铁律

---

## 说明

以上为该项目的实际开发轨迹。项目代码、文档结构、测试用例均在上述会话中由 WorkBuddy 协作完成，
开发者的判断体现在方向选择、取舍与验收标准上。
