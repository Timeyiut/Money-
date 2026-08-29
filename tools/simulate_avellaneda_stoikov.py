#!/usr/bin/env python3
"""Monte Carlo simulation of the Avellaneda-Stoikov (2008) market-making
model vs. a symmetric "control" strategy, calibrated with a real Taiwan
stock's historical volatility.

This is NOT a backtest on real trading data. It's the same kind of study
the Stanford MSE448 paper (Sasson, Ho, Samson — "High Frequency Trading
Strategies") itself ran: simulate a price path and a stream of order
arrivals under a set of modeling assumptions, then compare how the AS
quoting rule and a naive symmetric quoting rule perform over many
simulated sessions. Their own Figure 11 is a P&L *histogram* over many
runs, which is the signature of a Monte Carlo study, not a single
real-market replay.

What's real: the volatility (sigma) is calibrated from the target
stock's actual historical daily closes (data/price_history.json).

What's assumed, because no public data source gives it to us: the order
arrival intensity function lambda(delta) = A*exp(-k*delta) (A, k) and
the risk-aversion parameter gamma. Real order-book fill-rate parameters
for a specific Taiwan-listed stock aren't published anywhere we can pull
from for free — TWSE sells tick-level order book history commercially,
and this pipeline has no subscription to it. A, k, gamma here are the
same illustrative values used in the original Avellaneda-Stoikov (2008)
paper's own worked example, so the exercise stays comparable to the
published literature rather than inventing numbers with no citation at
all. Swap them if you have real fill-rate estimates for a specific
market.

Mechanics (standard AS 2008 closed-form, discretized):
  reservation price   r(t) = s(t) - q * gamma * sigma^2 * (T - t)
  optimal total spread  spread(t) = gamma*sigma^2*(T-t) + (2/gamma)*ln(1+gamma/k)
  AS quotes:  bid = r - spread/2,  ask = r + spread/2
  Control quotes: bid = s - spread0/2, ask = s + spread0/2
    (spread0 = the AS spread's value at t=0, q=0 -- fixed, no inventory
    skew, which is exactly what makes it "control" rather than "AS")
  fill probability per step: P(fill on a side) ~= A*exp(-k*delta)*dt
    (thinned Poisson, valid for small dt)
  mid-price: arithmetic Brownian motion, dS = sigma*sqrt(dt)*Z

At T, remaining inventory is marked to market at the final mid-price:
  final_wealth = cash + inventory * S_T
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
from dataclasses import dataclass

PRICE_HISTORY_PATH = "data/price_history.json"


def historical_daily_vol(code: str) -> tuple[float, float, int]:
    """Returns (daily_log_return_stdev, last_close, n_days) for a symbol
    already tracked in data/price_history.json."""
    data = json.load(open(PRICE_HISTORY_PATH, encoding="utf-8"))
    sym = data["symbols"][code]
    closes = [r["close"] for r in sym["series"]]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    return statistics.pstdev(rets), closes[-1], len(closes)


@dataclass
class SimParams:
    sigma: float       # absolute price volatility per unit T (dS = sigma*sqrt(dt)*Z)
    gamma: float = 0.1  # risk aversion
    k: float = 1.5      # order arrival decay
    A: float = 140.0    # order arrival base intensity
    T: float = 1.0       # session length (normalised)
    dt: float = 0.005    # time step (paper's own value -> 200 steps/session)
    s0: float = 100.0    # starting mid-price


def run_session(p: SimParams, strategy: str, rng: random.Random) -> tuple[float, int]:
    n_steps = int(p.T / p.dt)
    s = p.s0
    q = 0          # inventory
    cash = 0.0

    # Control's fixed spread = the AS formula's own value at t=0, q=0 --
    # same quoting width AS would use if it ignored inventory entirely.
    spread0 = p.gamma * p.sigma ** 2 * p.T + (2 / p.gamma) * math.log(1 + p.gamma / p.k)

    for i in range(n_steps):
        t = i * p.dt
        remaining = p.T - t

        if strategy == "AS":
            r = s - q * p.gamma * p.sigma ** 2 * remaining
            spread = p.gamma * p.sigma ** 2 * remaining + (2 / p.gamma) * math.log(1 + p.gamma / p.k)
            bid = r - spread / 2
            ask = r + spread / 2
        else:  # control: symmetric around the raw mid-price, fixed width
            bid = s - spread0 / 2
            ask = s + spread0 / 2

        delta_b = s - bid
        delta_a = ask - s
        p_fill_b = min(1.0, p.A * math.exp(-p.k * delta_b) * p.dt)
        p_fill_a = min(1.0, p.A * math.exp(-p.k * delta_a) * p.dt)

        if rng.random() < p_fill_b:
            q += 1
            cash -= bid
        if rng.random() < p_fill_a:
            q -= 1
            cash += ask

        s += p.sigma * math.sqrt(p.dt) * rng.gauss(0, 1)

    final_wealth = cash + q * s
    return final_wealth, q


def monte_carlo(p: SimParams, n_runs: int, seed: int) -> dict:
    rng = random.Random(seed)
    out = {}
    for strat in ("AS", "control"):
        profits, invs = [], []
        for _ in range(n_runs):
            wealth, q = run_session(p, strat, rng)
            profits.append(wealth)
            invs.append(q)
        out[strat] = {
            "avg_profit": round(statistics.mean(profits), 3),
            "std_profit": round(statistics.pstdev(profits), 3),
            "avg_inventory": round(statistics.mean(invs), 3),
            "std_inventory": round(statistics.pstdev(invs), 3),
        }
    return out


def main() -> int:
    n_runs = 1000
    seed = 42

    print("=== Reference case: paper's own illustrative parameters (sigma=2, S0=100) ===")
    ref = monte_carlo(SimParams(sigma=2.0), n_runs, seed)
    for strat, r in ref.items():
        print(f"  {strat:8s} avg_profit={r['avg_profit']:8.3f}  std_profit={r['std_profit']:7.3f}  "
              f"avg_inv={r['avg_inventory']:7.3f}  std_inv={r['std_inventory']:6.3f}")

    print("\n=== Calibrated with real Taiwan-stock daily volatility (same gamma/k/A/T/dt, S0 rescaled to 100) ===")
    for code in ["3105", "00919", "00631L", "8021"]:
        daily_vol, last_close, n_days = historical_daily_vol(code)
        sigma_scaled = daily_vol * 100  # express relative daily vol on the S0=100 scale
        params = SimParams(sigma=sigma_scaled)
        result = monte_carlo(params, n_runs, seed)
        print(f"\n{code} (real daily vol {daily_vol*100:.2f}%, {n_days} trading days of history, last close {last_close}):")
        print(f"  sigma used in sim (scaled to S0=100): {sigma_scaled:.3f}")
        for strat, r in result.items():
            sharpe_like = r["avg_profit"] / r["std_profit"] if r["std_profit"] else float("nan")
            print(f"  {strat:8s} avg_profit={r['avg_profit']:8.3f}  std_profit={r['std_profit']:7.3f}  "
                  f"profit/std={sharpe_like:5.2f}  avg_inv={r['avg_inventory']:7.3f}  std_inv={r['std_inventory']:6.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
