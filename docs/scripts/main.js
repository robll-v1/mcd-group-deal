/* ============================================================
   麦凑单 · 首页交互
   把 Python 引擎的核心逻辑移植到浏览器：整数分运算 + 凑门槛 + 分账。
   这里只保留演示所需的最小闭环，完整算法见 scripts/optimizer.py。
   ============================================================ */

(function () {
  "use strict";

  /* ---------------------------- 数据 ---------------------------- */

  const MENU = {
    bigmac: { name: "巨无霸", price: 25.5 },
    mcspicy: { name: "麦辣鸡腿堡", price: 23.0 },
    grilled: { name: "板烧鸡腿堡", price: 24.0 },
    filetofish: { name: "麦香鱼", price: 16.5 },
    dblcheese: { name: "双层吉士汉堡", price: 18.5 },
    cone: { name: "甜筒", price: 6.0 },
    sundae: { name: "巧克力新地", price: 8.5 },
    fries_m: { name: "中薯条", price: 11.5 },
    nuggets: { name: "麦乐鸡（5块）", price: 12.5 },
  };

  // 满减阶梯：门槛 / 减免（元）
  const LADDER = [
    { t: 90, off: 18 },
    { t: 100, off: 25 },
    { t: 120, off: 40 },
    { t: 150, off: 60 },
  ];

  // 可选凑单件，按价格升序
  const ADDONS = ["cone", "sundae", "fries_m", "nuggets"];

  const PEOPLE = [
    { name: "张伟", group: "p1", side: { name: "可乐（中）", price: 9.5 } },
    { name: "李娜", group: "p2", side: { name: "中薯条", price: 11.5 } },
    { name: "王强", group: "p3", side: { name: "零度可乐（中）", price: 9.5 } },
    { name: "赵敏", group: "p4", side: null },
  ];

  /* --------------------------- 工具函数 --------------------------- */

  const toCents = (yuan) => Math.round(yuan * 100);
  const fmt = (cents) => "¥" + (cents / 100).toFixed(2);
  const fmtSigned = (cents) => (cents < 0 ? "-¥" : "¥") + (Math.abs(cents) / 100).toFixed(2);

  /** 找到当前金额能吃到的最高一档 */
  function bestTier(cents) {
    let hit = null;
    for (const tier of LADDER) {
      if (cents >= tier.t * 100) hit = tier;
    }
    return hit;
  }

  /** 最大余数法分摊，保证各项之和恰好等于 total */
  function allocate(total, weights) {
    const sum = weights.reduce((a, b) => a + b, 0);
    if (sum <= 0) {
      const out = new Array(weights.length).fill(0);
      out[out.length - 1] = total;
      return out;
    }
    const raw = weights.map((w) => (total * w) / sum);
    const floors = raw.map(Math.floor);
    let rest = total - floors.reduce((a, b) => a + b, 0);
    const order = raw
      .map((v, i) => ({ i, frac: v - Math.floor(v), w: weights[i] }))
      .sort((a, b) => b.frac - a.frac || b.w - a.w || a.i - b.i);
    for (let k = 0; k < rest; k++) floors[order[k % order.length].i] += 1;
    return floors;
  }

  /* --------------------------- 结算核心 --------------------------- */

  function compute(autoAddon) {
    // 1. 基础篮：每人主食 + 自带配餐饮料
    const people = PEOPLE.map((p) => {
      const picked = document.querySelector(`input[name="${p.group}"]:checked`);
      const mainCode = picked ? picked.value : "bigmac";
      const main = MENU[mainCode];
      const items = [{ name: main.name, cents: toCents(main.price) }];
      if (p.side) items.push({ name: p.side.name, cents: toCents(p.side.price) });
      return {
        name: p.name,
        items,
        subtotal: items.reduce((a, it) => a + it.cents, 0),
      };
    });

    const baseSubtotal = people.reduce((a, p) => a + p.subtotal, 0);
    const baseTier = bestTier(baseSubtotal);
    const baseOff = baseTier ? baseTier.off * 100 : 0;
    const basePayable = baseSubtotal - baseOff;

    // 2. 凑门槛：找下一档，算净收益
    let addon = null;
    if (autoAddon) {
      const next = LADDER.find((t) => t.t * 100 > baseSubtotal);
      if (next) {
        const gap = next.t * 100 - baseSubtotal;
        const pool = ADDONS.map((c) => ({ code: c, ...MENU[c], cents: toCents(MENU[c].price) }));
        const enough = pool.filter((x) => x.cents >= gap).sort((a, b) => a.cents - b.cents);
        const candidate = enough[0] || null;
        if (candidate) {
          const newSubtotal = baseSubtotal + candidate.cents;
          const newTier = bestTier(newSubtotal);
          const newOff = newTier ? newTier.off * 100 : 0;
          if (newOff - baseOff - candidate.cents > 0) {
            addon = { ...candidate, newSubtotal, newOff, newTier };
          }
        }
      }
    }

    const subtotal = addon ? addon.newSubtotal : baseSubtotal;
    const off = addon ? addon.newOff : baseOff;
    const tier = addon ? addon.newTier : baseTier;
    const payable = subtotal - off;
    const saving = basePayable - payable;

    // 3. 分账：凑单件按人头均摊，优惠按金额比例分摊
    const peopleSubtotal = people.map((p) => p.subtotal);
    let shared = 0;
    if (addon) {
      const shares = allocate(addon.cents, people.map(() => 1));
      shares.forEach((s, i) => (peopleSubtotal[i] += s));
      shared = addon.cents;
    }
    const offShares = allocate(off, peopleSubtotal);

    const bill = people.map((p, i) => ({
      name: p.name,
      subtotal: peopleSubtotal[i],
      off: offShares[i],
      due: peopleSubtotal[i] - offShares[i],
      items: p.items.map((it) => it.name).join("·") + (addon ? "·甜筒(公摊)" : ""),
    }));

    return { people, subtotal, off, payable, tier, addon, saving, bill, baseSubtotal, baseOff, basePayable, shared };
  }

  /* --------------------------- 数字滚动 --------------------------- */

  const displayed = new WeakMap();

  function countTo(el, target, dur) {
    if (!el) return;
    const from = displayed.has(el) ? displayed.get(el) : target;
    displayed.set(el, target);
    if (from === target) {
      el.textContent = fmt(target);
      return;
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = fmt(target);
      return;
    }
    const t0 = performance.now();
    function step(now) {
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(Math.round(from + (target - from) * eased));
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  /* --------------------------- 渲染 --------------------------- */

  const el = {
    subtotal: document.getElementById("r-subtotal"),
    ruleName: document.getElementById("r-rule-name"),
    discount: document.getElementById("r-discount"),
    addon: document.getElementById("r-addon"),
    total: document.getElementById("r-total"),
    stamp: document.getElementById("stamp"),
    bill: document.getElementById("r-bill"),
    tip: document.getElementById("r-tip"),
  };

  function render() {
    const autoAddon = document.getElementById("auto-addon").checked;
    const r = compute(autoAddon);

    // 原价：基础篮 + 凑单件分别显示，让"多买一份"这件事看得见
    el.subtotal.textContent = fmt(r.baseSubtotal);
    el.ruleName.textContent = r.tier ? `满 ${r.tier.t} 减 ${r.tier.off}` : "未达任何满减门槛";
    el.discount.textContent = r.off ? "-" + fmt(r.off) : "—";
    el.addon.textContent = r.addon ? `+${fmt(r.addon.cents)} ${r.addon.name}` : "—";

    countTo(el.total, r.payable, 520);

    // 印章：只在真的省到钱时出现
    if (r.saving > 0) {
      el.stamp.textContent = "省 " + fmt(r.saving);
      el.stamp.dataset.on = "true";
    } else {
      el.stamp.dataset.on = "false";
    }

    // 分账表
    el.bill.innerHTML = r.bill
      .map(
        (row) => `
        <div class="bill__row">
          <div class="bill__who">
            <span class="bill__name">${row.name}</span>
            <span class="bill__items">${row.items}</span>
          </div>
          <span class="bill__due">${fmt(row.due)}</span>
        </div>`
      )
      .join("");

    // 一句话结论
    if (r.addon) {
      const diff = r.basePayable - r.payable;
      el.tip.textContent = `加一份${r.addon.name}（${fmt(
        r.addon.cents
      )}）凑到满 ${r.addon.newTier.t} 减 ${r.addon.newTier.off}，整单反而少付 ${fmt(diff)}。`;
    } else if (r.saving > 0) {
      el.tip.textContent = "当前点法已是最优，没有更划算的凑法。";
    } else {
      el.tip.textContent = "当前点法已在这一档里最省；想再省就需要跨到下一档。";
    }
  }

  /* --------------------------- 入场观察 --------------------------- */

  function initReveal() {
    const nodes = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 }
    );
    nodes.forEach((n) => io.observe(n));
  }

  /* --------------------------- 启动 --------------------------- */

  document.querySelectorAll('.chips input[type="radio"]').forEach((input) => {
    input.addEventListener("change", render);
  });
  document.getElementById("auto-addon").addEventListener("change", render);

  initReveal();
  render();
})();
