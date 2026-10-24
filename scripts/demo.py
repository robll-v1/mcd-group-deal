#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦凑单 · 离线演示

不需要 MCP Token，用 examples/sample-order.json 里的示例菜单数据，
完整跑一遍「凑单 → 最优方案 → AA 分账 → 出卡」的链路。

    python3 scripts/demo.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from optimizer import Person, Rule, Sku, solve, yuan  # noqa: E402
from render import render_card  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "examples", "sample-order.json")


def load_sample(path: str = SAMPLE):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    catalog = {s["code"]: Sku.from_dict(s) for s in payload["skus"]}
    rules = [Rule.from_dict(r) for r in payload["rules"]]
    people = [Person.from_dict(p) for p in payload["people"]]
    return catalog, rules, people, payload


def run_demo() -> None:
    catalog, rules, people, payload = load_sample()
    result = solve(people, rules, catalog, payload.get("mode", "proportional"))

    base = next(p for p in result["plans"] if p["kind"] == "base")
    best = result["best"]

    print("=" * 58)
    print("麦凑单 · 离线演示（示例数据，非官方菜单）")
    print("=" * 58)
    print(f"参与人数：{len(people)} 人   门店：{payload['store']['name']}")
    print()
    print(f"【第一次算】各点各的：原价 ¥{yuan(base['subtotal'])}，"
          f"优惠 ¥{yuan(base['off'])}，实付 ¥{yuan(base['payable'])}")
    for r in base["rules"]:
        print(f"            └ {r['name']}  -¥{yuan(r['off'])}")
    print()
    print(f"【最优解】{best['note'] or '当前点法已最优'}")
    print(f"           实付 ¥{yuan(best['payable'])}，"
          f"比各点各的少花 ¥{yuan(result['saving_vs_base'])}")
    print()

    # 把「加单反而更便宜」这件事单独讲清楚
    addon = next((p for p in result["plans"] if p["kind"] == "addon"), None)
    if addon:
        added = addon["extra"].get("addon")
        add_price = catalog[added].price if added in catalog else 0
        print(f"⚠️ 反直觉的那一步：多买一份「{catalog[added].name}」"
              f"（¥{yuan(add_price)}）")
        print(f"   订单从 ¥{yuan(base['subtotal'])} 推到 ¥{yuan(addon['subtotal'])}，"
              f"优惠从 ¥{yuan(base['off'])} 涨到 ¥{yuan(addon['off'])}")
        print(f"   净效果：多花 ¥{yuan(add_price)}，少付 "
              f"¥{yuan(base['payable'] - addon['payable'])}")
        print()

    print("-" * 58)
    print(render_card(result))
    print("-" * 58)


if __name__ == "__main__":
    run_demo()
