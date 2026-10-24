#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦凑单 · 引擎自测（不依赖第三方测试框架）

    python3 scripts/test_optimizer.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optimizer import (  # noqa: E402
    Line, Person, Rule, Sku, allocate_cents, evaluate, solve, split_bill,
)

CATALOG = {
    "a": Sku("a", "汉堡A", 2000, "burger"),
    "b": Sku("b", "汉堡B", 1500, "burger"),
    "c": Sku("c", "可乐", 800, "drink"),
    "d": Sku("d", "甜筒", 600, "dessert"),
}

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def test_allocate_exact():
    """分摊后求和必须与实际优惠一分不差。"""
    for total in (0, 1, 7, 40_00, 12345):
        for weights in ([1, 1, 1], [35_00, 34_50, 33_50, 16_50], [5, 0, 3]):
            parts = allocate_cents(total, weights)
            assert sum(parts) == total, f"{total} / {weights} -> {parts}"


@case
def test_group_mutex():
    """同一分组只生效一条，跨分组可叠加。"""
    rules = [
        Rule("r1", "满20减5", 2000, 500, group="discount"),
        Rule("r2", "满20减8", 2000, 800, group="discount"),
        Rule("r3", "会员再减2", 0, 200, group="member"),
    ]
    lines = [Line("a", 1, "甲"), Line("c", 1, "甲")]
    deal = evaluate(lines, rules, CATALOG)
    assert deal.subtotal == 2800, deal.subtotal
    assert deal.off == 1000, deal.off          # 800 + 200，不是 500+800+200
    assert deal.payable == 1800, deal.payable


@case
def test_threshold_not_met():
    """未达门槛时不应触发优惠。"""
    rules = [Rule("r1", "满100减30", 10_000, 3000, group="discount")]
    deal = evaluate([Line("a", 1, "甲")], rules, CATALOG)
    assert deal.off == 0, deal.off


@case
def test_addon_beats_base():
    """凑单后实付必须真的更低，且「多买反而少付」成立。"""
    catalog = {
        "x": Sku("x", "主食", 9500, "burger"),
        "y": Sku("y", "小食", 600, "side"),
    }
    rules = [
        Rule("t1", "满100减20", 10_000, 2000, group="discount"),
        Rule("t2", "满120减50", 12_000, 5000, group="discount"),
    ]
    people = [Person("甲", ("x",))]
    res = solve(people, rules, catalog)
    kinds = {p["kind"] for p in res["plans"]}
    assert "addon" in kinds, kinds
    assert res["best"]["payable"] < 9500 - 0, res["best"]
    addon_plan = next(p for p in res["plans"] if p["kind"] == "addon")
    base_plan = next(p for p in res["plans"] if p["kind"] == "base")
    assert addon_plan["payable"] < base_plan["payable"], addon_plan["payable"]


@case
def test_bill_sums_to_payable():
    """分账合计必须等于实付，且每人应付非负。"""
    catalog, rules, people, _ = _load_sample()
    res = solve(people, rules, catalog)
    total = sum(r["due"] for r in res["bill"])
    assert total == res["best"]["payable"], (total, res["best"]["payable"])
    assert all(r["due"] >= 0 for r in res["bill"])
    assert all(r["subtotal"] - r["off"] == r["due"] for r in res["bill"])


@case
def test_split_bill_modes():
    """均分模式与比例模式的优惠总额一致，只是分配不同。"""
    catalog, rules, people, _ = _load_sample()
    res = solve(people, rules, catalog)
    deal = evaluate(
        [Line(l["code"], l["qty"], l["owner"]) for l in res["best"]["lines"]],
        rules, catalog,
    )
    for mode in ("proportional", "equal"):
        rows = split_bill(deal, catalog, mode)
        assert sum(r["off"] for r in rows) == deal.off, mode


def _load_sample():
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "examples", "sample-order.json"), encoding="utf-8") as f:
        payload = json.load(f)
    catalog = {s["code"]: Sku.from_dict(s) for s in payload["skus"]}
    rules = [Rule.from_dict(r) for r in payload["rules"]]
    people = [Person.from_dict(p) for p in payload["people"]]
    return catalog, rules, people, payload


def main() -> int:
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f"  ✓ {fn.__name__}  {fn.__doc__.strip()}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {fn.__name__}  {e}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
