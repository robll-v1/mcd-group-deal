#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""麦凑单 · 结果渲染器

把 optimizer 输出渲染成一张可以直接截图发群里的「分账卡」。
纯文本 Markdown，不依赖第三方库，任何聊天窗口贴上去都整齐。
"""
from __future__ import annotations

from optimizer import yuan

KIND_LABEL = {
    "base": "各点各的",
    "addon": "凑一单",
    "swap": "替换同款",
    "split": "拆单",
}


def _bar(rate: float, width: int = 20) -> str:
    filled = int(round(rate * width))
    return "█" * filled + "░" * (width - filled)


def _collapse(plans: list, best: dict) -> list:
    """同一类方案只保留最优的一条，保持 基础 → 凑单 → 换品 → 拆单 的阅读顺序。"""
    order = {"base": 0, "addon": 1, "swap": 2, "split": 3}
    top: dict = {}
    for p in plans:
        k = p["kind"]
        if k not in top or p["payable"] < top[k]["payable"]:
            top[k] = p
    out = [top[k] for k in sorted(top, key=lambda x: order.get(x, 9))]
    return out


def render_card(result: dict, title: str = "麦凑单 · 团餐分账卡") -> str:
    best = result["best"]
    base = next((p for p in result["plans"] if p["kind"] == "base"), best)
    saving = result["saving_vs_base"]

    out = []
    out.append(f"## 🍔 {title}")
    out.append("")

    # ---- 一行结论（截图最需要这一行）
    if saving > 0:
        out.append(
            f"> **实付 ¥{yuan(best['payable'])}** ，比各点各的少花 "
            f"**¥{yuan(saving)}**（省 {result['saving_rate'] * 100:.1f}%）"
        )
    else:
        out.append(f"> **实付 ¥{yuan(best['payable'])}** ，当前点法已是最优")
    out.append("")
    out.append(f"`原价 ¥{yuan(base['subtotal'])} → 优惠 ¥{yuan(best['off'])} "
               f"→ 实付 ¥{yuan(best['payable'])}`")
    out.append("")

    # ---- 方案对比（每一类只展示最优的一条，避免同质行刷屏）
    out.append("### 方案对比")
    out.append("")
    out.append("| 方案 | 原价 | 优惠 | 实付 | 省 |")
    out.append("|---|---:|---:|---:|---:|")
    for p in _collapse(result["plans"], best):
        label = KIND_LABEL.get(p["kind"], p["kind"])
        diff = base["payable"] - p["payable"]
        mark = " ⭐" if p is best or p == best else ""
        out.append(
            f"| {label}{mark} | ¥{yuan(p['subtotal'])} | ¥{yuan(p['off'])} "
            f"| **¥{yuan(p['payable'])}** | "
            f"{'—' if diff == 0 else '¥' + yuan(diff)} |"
        )
    out.append("")

    # ---- 推荐方案说明
    if best["note"]:
        out.append(f"**为什么这么点：** {best['note']}")
        out.append("")

    if best["rules"]:
        used = "、".join(f"{r['name']}（-¥{yuan(r['off'])}）" for r in best["rules"])
        out.append(f"**用到的优惠：** {used}")
        out.append("")

    # ---- 分账表
    out.append("### 谁该付多少")
    out.append("")
    out.append("| 人 | 点单 | 小计 | 分摊优惠 | 应付 |")
    out.append("|---|---|---:|---:|---:|")
    for row in result["bill"]:
        items = "、".join(
            f"{i['name']}" + (f"×{i['qty']}" if i["qty"] > 1 else "")
            for i in row["items"]
        )
        name = row["name"]
        if name == "shared":
            name = "公摊"
        out.append(
            f"| {name} | {items} | ¥{yuan(row['subtotal'])} "
            f"| -¥{yuan(row['off'])} | **¥{yuan(row['due'])}** |"
        )
    total_due = sum(r["due"] for r in result["bill"])
    out.append(f"| **合计** | | ¥{yuan(best['subtotal'])} | -¥{yuan(best['off'])} "
               f"| **¥{yuan(total_due)}** |")
    out.append("")

    # ---- 凑单提示（传播点）
    addon = next((p for p in result["plans"] if p["kind"] == "addon"), None)
    if addon and addon["kind"] != best["kind"] and saving <= 0:
        out.append(f"💡 {addon['note']}")
        out.append("")

    out.append("---")
    out.append("_示例数据，价格与优惠为演示用，实际以下单时麦当劳官方返回为准。_")
    return "\n".join(out)


if __name__ == "__main__":
    import json
    import sys

    payload = json.loads(sys.stdin.read())
    print(render_card(payload))
