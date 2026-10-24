#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦凑单 · 团餐凑单最优化与 AA 分账引擎

设计原则：
1. 金额一律用「分」为单位的整数运算，避免浮点误差（这是大模型最容易算错的地方）；
2. 券/满减的叠加与互斥用「分组互斥」建模：同组只生效一条，跨组可叠加；
3. 搜索空间按「凑门槛 / 换品 / 拆单」三条确定性路径展开，结果可解释、可复现。

CLI:
    python3 optimizer.py demo                 # 跑内置示例
    python3 optimizer.py solve < payload.json # 读 JSON，输出方案 JSON
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Sequence

__all__ = [
    "Sku", "Rule", "Line", "Person", "Deal", "Plan",
    "evaluate", "solve", "split_bill", "allocate_cents",
]

CENT = 100


def yuan(cents: int) -> str:
    """分 -> 元字符串，保留两位。"""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // CENT}.{cents % CENT:02d}"


# ---------------------------------------------------------------- 数据模型

@dataclass(frozen=True)
class Sku:
    code: str
    name: str
    price: int                      # 分
    category: str = ""              # burger / side / drink / dessert / combo
    tags: tuple[str, ...] = ()      # 辣 / 含牛肉 / 含咖啡因 ...

    @classmethod
    def from_dict(cls, d: dict) -> "Sku":
        return cls(
            code=d["code"],
            name=d["name"],
            price=int(round(float(d["price"]) * CENT)),
            category=d.get("category", ""),
            tags=tuple(d.get("tags", ())),
        )


@dataclass(frozen=True)
class Rule:
    """一条优惠规则。

    threshold  满多少分可用
    off        减多少分
    scope      限定的商品 code 集合；空集合表示全场
    group      同组互斥（如「满减阶梯」「优惠券」），跨组可叠加
    """
    rule_id: str
    name: str
    threshold: int
    off: int
    scope: frozenset = frozenset()
    group: str = "default"

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(
            rule_id=d["id"],
            name=d["name"],
            threshold=int(round(float(d["threshold"]) * CENT)),
            off=int(round(float(d["off"]) * CENT)),
            scope=frozenset(d.get("scope", ())),
            group=d.get("group", "default"),
        )

    def eligible_amount(self, lines: Sequence["Line"], catalog: dict) -> int:
        """本条规则计算门槛时的有效金额。"""
        if not self.scope:
            return sum(l.sku_ref(catalog).price * l.qty for l in lines)
        return sum(
            l.sku_ref(catalog).price * l.qty
            for l in lines
            if l.sku in self.scope
        )


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int = 1
    owner: str = "shared"           # 归属人；shared 表示公摊（如凑单补差件）

    def sku_ref(self, catalog: dict) -> Sku:
        return catalog[self.sku]

    def amount(self, catalog: dict) -> int:
        return self.sku_ref(catalog).price * self.qty


@dataclass(frozen=True)
class Person:
    name: str
    wants: tuple = ()
    budget: int | None = None       # 分

    @classmethod
    def from_dict(cls, d: dict) -> "Person":
        b = d.get("budget")
        return cls(
            name=d["name"],
            wants=tuple(d.get("wants", ())),
            budget=None if b is None else int(round(float(b) * CENT)),
        )


@dataclass
class Deal:
    """对某个购物篮的一次完整结算结果。"""
    lines: list
    subtotal: int
    applied: list = field(default_factory=list)   # [(Rule, 抵扣分)]
    off: int = 0

    @property
    def payable(self) -> int:
        return self.subtotal - self.off

    @property
    def rate(self) -> float:
        return (self.off / self.subtotal) if self.subtotal else 0.0


# ---------------------------------------------------------------- 结算核心

def evaluate(lines: Sequence[Line], rules: Sequence[Rule], catalog: dict) -> Deal:
    """给定购物篮，求最优优惠组合：每个分组取优惠最大的一条。"""
    subtotal = sum(l.amount(catalog) for l in lines)

    best_by_group: dict = {}
    for r in rules:
        if r.eligible_amount(lines, catalog) < r.threshold:
            continue
        cur = best_by_group.get(r.group)
        if cur is None or r.off > cur.off:
            best_by_group[r.group] = r

    applied = [(r, r.off) for r in best_by_group.values()]
    off = min(sum(x[1] for x in applied), subtotal)
    return Deal(lines=list(lines), subtotal=subtotal, applied=applied, off=off)


# ---------------------------------------------------------------- 分账

def allocate_cents(total: int, weights: Sequence[int]) -> list:
    """按权重分摊金额（最大余数法），保证各项之和恰好等于 total。"""
    if not weights:
        return []
    w_sum = sum(weights)
    if w_sum <= 0:
        base = [0] * len(weights)
        base[-1] = total
        return base

    raw = [total * w / w_sum for w in weights]
    floors = [int(x) for x in raw]
    remainder = total - sum(floors)
    order = sorted(
        range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), -weights[i], i)
    )
    for i in order[:remainder]:
        floors[i] += 1
    if remainder < 0:                       # total 为负（返券场景）时兜底
        for i in order[: abs(remainder)]:
            floors[i] -= 1
    return floors


def split_bill(deal: Deal, catalog: dict, mode: str = "proportional") -> list:
    """把优惠分摊到每个人，返回每人的应付明细。

    mode:
      proportional —— 按各自点单金额占比分摊优惠（默认，最常用）
      equal        —— 优惠均分（人多且金额接近时更省事）
      shared_first —— 公摊件先归「团长」，其余优惠按比例分
    """
    owners, subtotal_by_owner = [], {}
    for l in deal.lines:
        if l.owner not in subtotal_by_owner:
            owners.append(l.owner)
            subtotal_by_owner[l.owner] = 0
        subtotal_by_owner[l.owner] += l.amount(catalog)

    # 公摊件（凑单补差的那份）按人头均摊进每个人的小计，不单独占一行
    shared_items = [
        {"name": l.sku_ref(catalog).name, "qty": l.qty, "amount": l.amount(catalog)}
        for l in deal.lines if l.owner == "shared"
    ]
    shared_total = subtotal_by_owner.pop("shared", 0)
    owners = [o for o in owners if o != "shared"]
    shared_shares = [0] * len(owners)
    if shared_total and owners:
        shared_shares = allocate_cents(shared_total, [1] * len(owners))
        for o, s in zip(owners, shared_shares):
            subtotal_by_owner[o] += s

    if mode == "equal":
        weights = [1] * len(owners)
    else:
        weights = [subtotal_by_owner[o] for o in owners]

    shares = allocate_cents(deal.off, weights)

    rows = []
    for o, off, sh in zip(owners, shares, shared_shares):
        sub = subtotal_by_owner[o]
        items = [
            {"name": l.sku_ref(catalog).name, "qty": l.qty,
             "amount": l.amount(catalog)}
            for l in deal.lines if l.owner == o
        ]
        if sh:
            if len(shared_items) == 1:
                items.append({"name": shared_items[0]["name"] + "（公摊）",
                              "qty": 1, "amount": sh})
            else:
                items.append({"name": f"公摊凑单件×{len(shared_items)}",
                              "qty": 1, "amount": sh})
        rows.append({
            "name": o,
            "subtotal": sub,
            "shared": sh,
            "off": off,
            "due": sub - off,
            "items": items,
        })
    return rows


# ---------------------------------------------------------------- 方案搜索

@dataclass
class Plan:
    kind: str                       # base / addon / swap / split
    deal: Deal
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def payable(self) -> int:
        return self.deal.payable


def _cheapest_addon(
    lines: Sequence[Line],
    rule: Rule,
    catalog: dict,
    banned_codes: Iterable[str] = (),
) -> Sku | None:
    """为凑满 rule.threshold 找到「加价最小」的商品。"""
    eligible = rule.eligible_amount(lines, catalog)
    gap = rule.threshold - eligible
    if gap <= 0:
        return None

    pool = [
        s for s in catalog.values()
        if s.code not in set(banned_codes)
        and (not rule.scope or s.code in rule.scope)
    ]
    # 优先能正好补上差额的最便宜单品；找不到就用最贵的顶上去
    enough = [s for s in pool if s.price >= gap]
    if enough:
        return min(enough, key=lambda s: (s.price, s.code))
    if not pool:
        return None
    return max(pool, key=lambda s: (s.price, s.code))


def solve(
    persons: Sequence[Person],
    rules: Sequence[Rule],
    catalog: dict,
    mode: str = "proportional",
) -> dict:
    """主入口：给出基础方案、凑单方案、拆单方案，并选最优。"""
    base_lines: list = []
    for p in persons:
        for code in p.wants:
            base_lines.append(Line(sku=code, qty=1, owner=p.name))

    base_deal = evaluate(base_lines, rules, catalog)
    plans = [Plan("base", base_deal, "各点各的，不做任何凑单")]

    # --- 路径一：检测未达标的门槛，算「加一个」是否划算
    for r in rules:
        if r.eligible_amount(base_lines, catalog) >= r.threshold:
            continue
        addon = _cheapest_addon(base_lines, r, catalog)
        if addon is None:
            continue
        cand = list(base_lines) + [Line(sku=addon.code, qty=1, owner="shared")]
        deal = evaluate(cand, rules, catalog)
        delta = deal.payable - base_deal.payable
        if delta < 0:
            plans.append(Plan(
                "addon", deal,
                f"再加一份「{addon.name}」({yuan(addon.price)}元) 把订单推到满 "
                f"{yuan(r.threshold)} 减 {yuan(r.off)}，实付反而少 "
                f"{yuan(-delta)} 元",
                {"addon": addon.code, "rule": r.rule_id},
            ))

    # --- 路径二：同品类换更便宜的替代品（保住门槛的前提下）
    by_cat: dict = {}
    for s in catalog.values():
        by_cat.setdefault(s.category, []).append(s)
    for i, l in enumerate(base_lines):
        cur = catalog[l.sku]
        best_swap = None
        for alt in by_cat.get(cur.category, []):
            if alt.price >= cur.price:
                continue
            cand = list(base_lines)
            cand[i] = Line(sku=alt.code, qty=l.qty, owner=l.owner)
            deal = evaluate(cand, rules, catalog)
            if deal.payable < base_deal.payable:
                if best_swap is None or deal.payable < best_swap[0].payable:
                    best_swap = (deal, cur, alt)
        if best_swap:
            deal, cur, alt = best_swap
            plans.append(Plan(
                "swap", deal,
                f"把「{cur.name}」换成同类的「{alt.name}」，省 "
                f"{yuan(deal.payable - base_deal.payable)} 元",
                {"from": cur.code, "to": alt.code},
            ))

    # --- 路径三：拆成两单（各自独立享优惠）
    if len(base_lines) >= 2:
        best_split = None
        for k in range(1, len(base_lines)):
            for head in combinations(range(len(base_lines)), k):
                if 0 not in head:            # 避免重复枚举
                    continue
                g1 = [base_lines[i] for i in head]
                g2 = [base_lines[i] for i in range(len(base_lines)) if i not in head]
                d1 = evaluate(g1, rules, catalog)
                d2 = evaluate(g2, rules, catalog)
                total = d1.payable + d2.payable
                if best_split is None or total < best_split[0]:
                    best_split = (total, d1, d2)
        if best_split and best_split[0] < base_deal.payable:
            total, d1, d2 = best_split
            plans.append(Plan(
                "split", d1,
                f"拆成两单分别用券，合计实付 {yuan(total)} 元，比一单省 "
                f"{yuan(base_deal.payable - total)} 元",
                {"second": {
                    "subtotal": d2.subtotal, "off": d2.off,
                    "payable": d2.payable,
                    "rules": [r.name for r, _ in d2.applied],
                }, "total": total},
            ))

    plans.sort(key=lambda p: p.payable)
    best = plans[0]

    bill = split_bill(best.deal, catalog, mode)
    plan_dicts = [_plan_dict(p, catalog) for p in plans]
    return {
        "best": plan_dicts[0],          # 与 plans[0] 是同一个对象，便于渲染层比对
        "plans": plan_dicts,
        "bill": bill,
        "saving_vs_base": base_deal.payable - best.payable,
        "saving_rate": (base_deal.payable - best.payable) / base_deal.payable
        if base_deal.payable else 0.0,
    }


def _plan_dict(plan: Plan, catalog: dict) -> dict:
    d = plan.deal
    return {
        "kind": plan.kind,
        "note": plan.note,
        "subtotal": d.subtotal,
        "off": d.off,
        "payable": d.payable,
        "rules": [{"id": r.rule_id, "name": r.name, "off": v}
                  for r, v in d.applied],
        "lines": [{"code": l.sku, "name": l.sku_ref(catalog).name,
                   "qty": l.qty, "owner": l.owner,
                   "amount": l.amount(catalog)} for l in d.lines],
        "extra": plan.extra,
    }


# ---------------------------------------------------------------- 入口

def _load_payload(payload: dict) -> tuple:
    catalog = {s["code"]: Sku.from_dict(s) for s in payload["skus"]}
    rules = [Rule.from_dict(r) for r in payload.get("rules", [])]
    persons = [Person.from_dict(p) for p in payload["people"]]
    return catalog, rules, persons


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    if argv[1] == "demo":
        from demo import run_demo
        run_demo()
        return 0

    if argv[1] == "solve":
        raw = open(argv[2], encoding="utf-8").read() if len(argv) > 2 else sys.stdin.read()
        payload = json.loads(raw)
        catalog, rules, persons = _load_payload(payload)
        result = solve(persons, rules, catalog, payload.get("mode", "proportional"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"未知命令：{argv[1]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
