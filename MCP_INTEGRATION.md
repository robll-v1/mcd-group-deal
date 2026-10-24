# MCP 集成说明

本文说明「麦凑单」实际调用了哪些麦当劳 MCP 能力、按什么顺序调用、每一层解决了什么问题。

- **MCP Server**：麦当劳中国官方 `mcd-mcp`（`https://mcp.mcd.cn`，Streamable HTTP）
- **协议版本**：`2025-06-18`
- **本项目实测可用工具总数**：35 个（`tools/list` 返回值），本项目使用其中 10 个

---

## 一、用到的 Tool 清单

| # | Tool | 在本项目中的作用 | 是否必需 |
|---|---|---|---|
| 1 | `delivery-query-addresses` | 取用户已保存的配送地址，拿到 `addressId` | 外送/团餐必需 |
| 2 | `delivery-create-address` | 首次使用、无地址时先建档 | 条件必需 |
| 3 | `delivery-query-stores` | 按地址查可配送门店，取 `storeCode` + `beCode` | 外送/团餐必需 |
| 4 | `query-nearby-stores` | 到店自取（`beType=1`）/ 得来速（`beType=5`）查门店 | 到店场景替换 3 |
| 5 | `query-meals` | 拉当前门店实时菜单：`productCode`、名称、价格、分类 | 必需 |
| 6 | `query-promotions` | 拉团餐场景的满减/满折规则（仅 `beType=6`） | 必需 |
| 7 | `query-store-coupons` | 拉本店本场景可用的用户券 | 必需 |
| 8 | `auto-bind-coupons` | 一键领取「麦麦省」全部可领券，扩大候选券池 | 可选 |
| 9 | `query-meal-assistance` | 团餐下单前查询助餐服务，`calculate-price` 前置 | 团餐必需 |
| 10 | `calculate-price` | 校验最终价、可用券，取 `takeWayList[].code` 作为 `takeWayCode` | 必需 |
| 11 | `create-order` | 创建订单（支持 `reservationDate` 预约） | 用户确认后调用 |

> 其余 24 个工具（积分账户、积分商城、抽奖、派对预约、营养查询、订单查询/取消、满意度问卷等）本项目未使用，属于刻意收敛范围。

---

## 二、调用链

```
                     ┌─ delivery-query-addresses ─┐
用户报人数与诉求 ────┤                            ├─→ storeCode + beCode
                     └─ delivery-query-stores ────┘
                                  │
              ┌───────────────────┼────────────────────┐
              ▼                   ▼                    ▼
        query-meals      query-promotions     query-store-coupons
        （菜单/价格）      （满减阶梯）          （可用券）
              │                   │                    │
              └───────────────────┴────────────────────┘
                                  ▼
                    ┌──────────────────────────┐
                    │  本地最优解引擎（Python）  │
                    │  凑门槛 / 换品 / 拆单      │
                    │  券组合 + AA 分账          │
                    └──────────────────────────┘
                                  ▼
                        分账卡 → 用户确认
                                  ▼
                    query-meal-assistance（团餐）
                                  ▼
                          calculate-price
                    （终价 + takeWayCode）
                                  ▼
                           create-order
                    （返回待支付订单，用户自行支付）
```

关键设计：**所有金额计算都在本地完成，不在模型侧完成。**

MCP 负责「事实」——门店、菜单、价格、券、下单；
本地引擎负责「算术」——组合枚举、门槛求解、分摊进位。
这两件事分开，是因为让模型算「119.5 加 6 块后满 120 减 40 是否比满 100 减 25 更划算」,
它大概率会算错，而错一次就是真金白银。

---

## 三、三个易错点（实战踩过的）

### 1. `beType` / `orderType` / `beCode` 必须成对传

不同场景的参数组合是硬约定，传错直接报错：

| 场景 | `beType` | `orderType` | `beCode` |
|---|---:|---:|---|
| 到店自取 | 1 | 1 | 不传 |
| 得来速 | 5 | 1 | 必传（来自 `query-nearby-stores`）|
| 麦乐送 | 2 | 2 | 必传（来自 `delivery-query-stores`）|
| 企业团餐 | 6 | 2 | 必传（来自 `delivery-query-stores`）|

`query-promotions` 和 `query-meal-assistance` **只在 `beType=6` 下有效**，这是本项目选择团餐场景的
重要原因——满减规则只在团餐接口暴露。

### 2. `takeWayCode` 只能从 `calculate-price` 拿

到店场景下 `create-order` 必须传 `takeWayCode`，它来自
`calculate-price` 返回的 `data.takeWayList[].code`，**不能自己拼**。
这也是为什么调用链里 `calculate-price` 一定要在 `create-order` 之前。

### 3. 商品 code 必须来自 `query-meals`

`calculate-price` / `create-order` 的 `items[].productCode` 只接受当前门店在售商品的 code。
跨门店复制 code 会失败——每个门店的菜单和 code 不一定一致。

---

## 四、业务价值

团餐的痛点不是「不知道吃什么」，而是**三个人以上就开始算不清账**：

- 满减阶梯有 4 档，券有 5 张，人和商品还要配对 → 人脑的搜索空间是几十种组合
- 优惠怎么分？按人头平分对点得多的人不公平，按金额比例又要算半天
- 最反直觉的情况：**差 5 毛钱到下一档，加一份便宜的东西反而少付**

「麦凑单」把这三件事做成确定性计算：

1. **凑门槛**：枚举未达标的每一档，算出「补多少、换多少减免、净收益是否为正」
2. **拆单对比**：一单用大额满减 vs 拆两单各用一张券，取实付更低者
3. **精确分账**：优惠按各自点单金额比例分摊，用最大余数法保证**分摊总和与实付一分不差**

第 3 点尤其重要：AA 分账最常见的翻车是「每人算完加起来差一毛钱」，这会让发起人尴尬。
整数分 + 最大余数法可以彻底消除这个问题（见 `scripts/test_optimizer.py` 的 `test_allocate_exact`）。

---

## 五、复现方式

```bash
# 1. 配置 MCP（token 从 https://open.mcd.cn/mcp 申请）
cp mcp-config.example.json ~/.workbuddy/mcp.json
# 编辑该文件，把 ${MCD_MCP_TOKEN} 换成真实 token

# 2. 离线验证引擎逻辑（不需要 token）
python3 scripts/demo.py

# 3. 跑自测
python3 scripts/test_optimizer.py

# 4. 在 WorkBuddy 里直接说：
#    「我们办公室 4 个人一起点麦当劳，怎么凑最便宜」
```

`examples/sample-order.json` 中的菜单与价格均为演示数据，**不是麦当劳官方定价**。
真实运行时，`skus` 与 `rules` 全部由 `query-meals` / `query-promotions` / `query-store-coupons` 实时返回填充。
