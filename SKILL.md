---
name: mcd-group-deal
display_name_zh: 麦凑单
display_name_en: MCD Group Deal
description: "办公室/同事/朋友一起点麦当劳时的团餐凑单与 AA 分账助手。基于麦当劳中国 MCP，自动拉取门店菜单和实时满减规则，算出「怎么点最省」的组合（含加一份反而更便宜、拆单、换品三种思路），并生成每个人的应付金额分账卡。触发词：麦凑单、团餐、一起点麦当劳、办公室点餐、凑单、拼单、AA 分账、满减怎么凑、几个人点麦当劳、帮我算谁该付多少。"
description_en: "Group-order copilot for McDonald's China. Pulls live store menu and tiered promotions via McDonald's MCP, computes the cheapest compliant basket (add-on / split-order / swap), and produces a per-person split bill. Triggers: group order, team lunch, split bill, McDonald's ordering for the office."
version: 1.0.0
---

# 麦凑单 · 团餐凑单与分账

帮一群人点麦当劳时，**把满减吃满、把账分清楚**。

这个 Skill 存在的原因是：吃饭凑单的算术题，人算不清，大模型也算不清。
「再加 6 块钱的甜筒反而少付 9 块」这种事，需要真枚举，不能靠嘴估。

## 什么时候用

- 一次要帮 2 人及以上点单（办公室午餐、团建、加班餐）
- 用户问「怎么点最便宜」「满减怎么凑」「谁该付多少」
- 用户有明确预算、忌口或必点项，需要有人替他做决定

单人点餐、单纯查优惠券、查订单状态 → 不要用本 Skill，直接调对应 MCP 工具即可。

## 铁律（先读这段）

1. **绝不代替用户付款。** 麦当劳 MCP 没有支付能力，`create-order` 只创建待支付订单。
   永远把付款这一步明确交还给用户，并说清楚「订单已创建，请在麦乐送/到店扫码完成支付」。
2. **下单前必须让用户确认最终清单和金额。** 未得到明确同意，不调 `create-order`。
3. **价格、券、活动一律以 MCP 实时返回为准。** 不要用记忆或示例数据里的价格回答用户。
4. 不重复下单、不批量下单、不无人值守下单。每次只处理一单，用户不确认就停。
5. 涉及真实手机号、地址时，只用于当次下单，不写入任何文件或日志。

## 工作流

### 第 1 步 · 收集名单

需要问清楚的（能推断的就别问）：

| 信息 | 必填 | 说明 |
|---|---|---|
| 参与人数与人名 | ✅ | 用于分账，可用「甲/乙/丙」代替真名 |
| 每人想吃什么 | ✅ | 允许模糊（「想吃鸡」「随便」），由你代选 |
| 每份预算 | 可选 | 用于校验分账结果是否超支 |
| 忌口 / 硬性要求 | 可选 | 辣、含牛肉、含咖啡因、无糖等 |
| 到店自取 还是 外送 | ✅ | 决定 orderType 和门店查询方式 |
| 送达/取餐时间 | 可选 | 有则用 `reservationDate` 预约，价格与库存更准 |

### 第 2 步 · 定位门店

- **外送 / 团餐**：`delivery-query-addresses` 拿地址 ID → `delivery-query-stores` 拿 `storeCode` + `beCode`
  - 没有地址先 `delivery-create-address`
  - 团餐场景一律 `beType=6`、`orderType=2`
- **到店自取**：`query-nearby-stores`（`beType=1`，不传 `beCode`）；得来速用 `beType=5`

> 拿到 `storeCode` 和 `beCode` 后，后面每个工具都要成对传。

### 第 3 步 · 拉菜单和优惠（可以并行）

```
query-meals        → 菜单：productCode / 名称 / 价格 / 分类
query-promotions   → 团餐满减满折规则（仅 beType=6 可用）
query-store-coupons→ 本店本场景可用的券
auto-bind-coupons  → 顺手把「麦麦省」能领的券全领了（可选，会改变可用券集合）
```

优惠有两类，**都要收**：门店满减阶梯（`query-promotions`）和用户自己的券（`query-store-coupons`）。

### 第 4 步 · 交给引擎算，不要自己心算

把菜单、优惠、人员整理成一个 JSON，喂给脚本：

```bash
python3 scripts/optimizer.py solve payload.json
```

`payload.json` 结构：

```json
{
  "store": { "name": "陆家嘴店" },
  "skus":  [{ "code": "bigmac", "name": "巨无霸", "price": 25.5, "category": "burger", "tags": ["含牛肉"] }],
  "rules": [
    { "id": "ladder_100", "name": "满100减25", "threshold": 100.0, "off": 25.0, "group": "discount" },
    { "id": "c_bigmac2", "name": "巨无霸第二份半价", "threshold": 51.0, "off": 12.75,
      "group": "discount", "scope": ["bigmac"] }
  ],
  "people": [{ "name": "张伟", "wants": ["bigmac", "coke_m"], "budget": 40 }],
  "mode": "proportional"
}
```

字段约定：

- `price / threshold / off` 单位为**元**（引擎内部转成分做整数运算）
- `rules[].group`：**同组互斥、跨组叠加**。满减阶梯和券都放 `"discount"`；
  另有可叠加的活动（如会员日额外减免）放到别的 group
- `rules[].scope`：限定适用商品 code，留空表示全场
- `people[].wants`：该人必点的商品 code
- `mode`：`proportional`（按金额比例分摊，默认）/ `equal`（优惠均分）

引擎会返回四种方案（`base / addon / swap / split`）和分账明细，并已按实付从低到高排好。

### 第 5 步 · 出分账卡

```bash
python3 scripts/optimizer.py solve payload.json | python3 scripts/render.py
```

得到一张可以直接贴进群里的 Markdown 卡片：方案对比、为什么这么点、每个人各付多少。

**把卡片给用户看，并口头讲清最关键的一句话**——通常是「多买一份 X，反而少付 Y」。

### 第 6 步 · 用户确认后才下单

```
query-meal-assistance  → 团餐必查助餐服务（仅 beType=6）
calculate-price        → 得到最终价、可用券、takeWayCode
create-order           → 下单
```

`create-order` 的关键参数：

| 参数 | 取值来源 |
|---|---|
| `storeCode` | 第 2 步 |
| `orderType` / `beType` | 到店 1 / 外送 2；团餐 6、麦乐送 2 |
| `beCode` | 外送/团餐/得来速必传 |
| `items` | `[{productCode, quantity, couponId}]`，商品 code 来自 `query-meals` |
| `takeWayCode` | `orderType=1` 时必传，来自 `calculate-price` 的 `data.takeWayList[].code` |
| `addressId` | `orderType=2` 时必传 |
| `reservationDate` | 预约场景传 `yyyy-MM-dd HH:mm`，非预约不传 |

下单成功后**只做两件事**：把订单号和应付金额告诉用户，提醒他去支付。

## 输出要求

- 先说结论（实付多少、省了多少），再说过程
- 分账表必须列出每个人的明细，不能只给总数
- 引用价格时标注「以门店实时返回为准」
- 用户人数多（≥5）时，主动提一句「公摊凑单件的人均摊金额」已在每人小计里

## 参考

- [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)：用了哪些工具、调用链、为什么这么设计
- [examples/sample-order.json](./examples/sample-order.json)：离线可跑的完整样例
- [README.md](./README.md)：安装与效果示例
