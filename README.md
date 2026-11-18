# StoneVast 石广

[![Telegram](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fhaolinsong32-lang%2Fstonevast%2Fmain%2Fapi%2Ftg-shield.json)](https://t.me/+ES7qp-bOLURjM2I1)
[![Website](https://img.shields.io/badge/Website-stonevast.com-f0a35e)](https://stonevast.com)
[![License](https://img.shields.io/badge/License-MIT-2ecc8f)](./LICENSE)
[![Ledger](https://img.shields.io/badge/Ledger-Public-5b9dff)](https://stonevast.com/withdrawals.html)

> Honest tools for PoW miners. No promised returns. Public ledger. Unlimited referral tree and commission eligibility, with deeper-tier rates halving progressively.
>
> 为 PoW 矿工打造的诚实工具。不承诺收益。账本公开。邀请关系与分成资格不限层级，深层费率逐级减半。

---

## What is StoneVast?

StoneVast is built by a miner, for miners. After running a 4070 laptop for 7 days straight and **losing ¥0.11 to electricity**, we built the calculator that tells 70% of people **NOT** to start mining.

石广是矿工为矿工打造的工具集。在 4070 笔记本连续挖矿 7 天、倒贴电费之后，我们做了一个会告诉你「别挖」的计算器。

**Historical ledger snapshot · 历史账本快照** (recorded values, not a live feed):

| Metric | Value |
|---|---|
| Current hashrate | 20.34 MH/s |
| Power draw | 49 W |
| Cumulative paid | 12.0929 IRON ([txids](https://stonevast.com/withdrawals.html)) |
| Net (after ¥0.55/kWh) | **¥0.39 / day** |

These are historical recorded values, not a current yield claim. See the [open ledger](https://stonevast.com/dashboard.html) for the latest available snapshot and verify pool access independently.

Thin margin. Honest math. That's the whole pitch.

---

## Quick Start · 3 分钟开始

**1. Verify the math first · 先验证再决定**

Open the [Break-even Calculator](https://stonevast.com/calculator.html). Input your GPU and electricity rate. If it says **NO-GO** in red — trust it and walk away.

**2. Pick a path · 选一条路径**

| Path | Cost | Commission Rules | Best For |
|---|---|---|---|
| **Standard** | Free | L1 5% default; L2 2%; L3 1%; L4 0.5%; L5 0.25%; then halve per tier | Verify first, scale later |
| **Genesis** | 199 IRON one-time | L1 30%; other tiers follow the same halving schedule | Early believers, limited #001-#100 |
| **Pro** | $4.9 USDT first month; $9.9/month; $99/year | No commission boost | Data & tooling |

The referral tree and commission eligibility have no depth limit. Each tier uses integer atomic-unit rounding; rounding remainders stay with the producing node, and a rounded share can be zero. The current commission core handles eligible real net output only — never recruitment or entry fees. Accrued commission rights are not actual payments, and production settlement remains gated on a trusted on-chain-event-to-producer-UID mapping.

**3. Join the community · 加入社群**

- Telegram (live): <https://t.me/+ES7qp-bOLURjM2I1>
- Discord: *coming soon*

**4. Run your own numbers · 跑自己的数据**

Don't trust our dashboard. First confirm local rules, pool reachability and a positive electricity-cost estimate; otherwise keep the rig off. If those checks pass, run your own measured test, log hashrate and power, and compare. We publish our methodology so you can replicate it.

---

## Tools · 三个工具

| Tool | What it does | Link |
|---|---|---|
| **Break-even Calculator** | Input GPU + ¥/kWh → GO / NO-GO verdict | [calculator.html](https://stonevast.com/calculator.html) |
| **Real-time Dashboard** | Hashrate, power, daily net, cumulative | [dashboard.html](https://stonevast.com/dashboard.html) |
| **APR vs APY Explainer** | Because most people in crypto confuse these | [calculator.html § APR vs APY](https://stonevast.com/calculator.html) |

---

## FAQ · 常见疑问

**Q: Can I really make money mining on a laptop?**
A: There is no universal answer. Use the calculator with your own hashrate, power draw, electricity price and current pool conditions. Historical snapshots are not forecasts; if pool access is unavailable or the estimate is negative, keep the rig off. If someone promises you 10x ROI, they're lying.

**Q: Why would I pay $9.9/month for Pro then?**
A: Pro isn't about mining more — it's about *deciding faster*. The calculator saves you from bad decisions. The dashboard saves you from checking pool stats manually. The first month is $4.9 USDT, then $9.9/month; annual billing is $99. Payment and TXID activation are paused during API migration; do not pay until the Pro page explicitly restores them.

**Q: Does the referral program pay for recruiting people?**
A: No. Standard registration is free; Genesis Pass is optional and separately priced. There is no headcount reward. The invitation tree and commission eligibility are unlimited: L1 is 5% by default (30% for a Genesis direct invite), L2 is 2%, L3 is 1%, L4 is 0.5%, L5 is 0.25%, and later tiers halve progressively. The current core calculates integer rights only from eligible real net output; rights are not actual payments, and production settlement is not enabled until a trusted event-to-node mapping exists. This design alone does not guarantee legal compliance; operators and users must check their local laws before participating.

**Q: What if I want a refund?**
A: Pro follows the 7-day refund terms shown on [pro.html](https://stonevast.com/pro.html). Genesis Pass is a one-time limited credential, no refunds (that's why it's limited to 100).

**Q: Where does the revenue go?**
A: Public ledger. Every IRON we receive from users is visible on-chain. See [withdrawals.html](https://stonevast.com/withdrawals.html).

**Q: Why IRON and not BTC/ETH?**
A: IRON (Iron Fish) is one of the few PoW coins still mineable on consumer GPUs with a meaningful hashrate-to-power ratio. We may add KARL/XTR comparisons later — the calculator already supports multi-coin.

---

## The Commission Boundary · 返佣边界

> Unlimited invitation relationships and commission eligibility. L1 uses the inviter's configured rate (5% standard, 30% Genesis), L2 is 2%, L3 is 1%, L4 is 0.5%, L5 is 0.25%, and later tiers halve progressively. The theoretical aggregate rate is capped at 9% for a standard chain, or 34% when L1 is Genesis; integer rounding can make an individual share zero.
>
> 邀请关系与分成资格均不限层级：一级使用邀请人的配置费率（标准 5%、创世直推 30%），二级 2%、三级 1%、四级 0.5%、五级 0.25%，后续逐级减半。普通链理论总费率上限 9%，创世一级参与时理论上限 34%；按最小单位整数取整后，单笔分成可能为 0。
>
> Standard registration is free; Genesis Pass is optional and separately priced. No headcount reward, no promised return. The current core uses eligible real net output only. Commission rights are not actual payments; production settlement requires a trusted on-chain-event-to-producer-UID mapping, and historical events are not silently retroactive by default.
> 标准节点免费注册，Genesis Pass 可选且单独付费；不按人头计酬、不承诺收益，当前核心只基于符合条件的真实净产出。分账权益不等于实际付款；生产结算须先建立可信的「链上事件 → 产币节点 UID」映射，历史事件默认不按新规则静默回溯。

---

## Roadmap · 路线图

- [x] Break-even calculator (GO / NO-GO in red)
- [x] Real-time dashboard with public ledger
- [x] Telegram community with auto-broadcast
- [x] Live member count badge
- [ ] Discord server (in progress)
- [ ] KARL / XTR dual-mining profitability comparison
- [ ] Genesis Pass #001-#100 distribution
- [ ] Mobile-friendly dashboard v2

---

## Links · 链接

- Website: <https://stonevast.com>
- Break-even Calculator (free, no signup): <https://stonevast.com/calculator.html>
- Open Ledger Dashboard: <https://stonevast.com/dashboard.html>
- BNB explainer (why BNB can't be mined): <https://stonevast.com/blog-bnb-mechanics.html>
- Monster vote (community event): <https://stonevast.com/monsters.html>
- Pro: <https://stonevast.com/pro.html>
- Paths: <https://stonevast.com/paths.html>
- Withdrawal Proof: <https://stonevast.com/withdrawals.html>
- Telegram: <https://t.me/+ES7qp-bOLURjM2I1>

---

## License

MIT — but the brand "StoneVast 石广" and the Genesis Pass artwork are not open-source. Fork the code, don't fork the brand.
