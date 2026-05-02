"""新评分标准 v2: PnL 占 6 分,其他 4 分"""
import json
import os
import glob
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '.openclaw', 'workspace', 'PC28'))


def compute_max_dd(daily):
    peak = 10000
    max_dd = 0
    for d in daily:
        if d["high"] > peak: peak = d["high"]
        dd = (peak - d["low"]) / peak if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    return max_dd * 100


def score_v2(s, max_dd):
    """新评分 v3: PnL 占 7 分 (主导),其他 3 分"""
    sc = 0
    p = s["pnl_pct"]
    # PnL (7分,粒度更细)
    if p > 10000: sc += 7.0
    elif p > 5000: sc += 6.5
    elif p > 2000: sc += 6.0
    elif p > 1000: sc += 5.5
    elif p > 500: sc += 5.0
    elif p > 200: sc += 4.5
    elif p > 100: sc += 4.0
    elif p > 50: sc += 3.0
    elif p > 25: sc += 2.5
    elif p > 0: sc += 2.0
    elif p > -25: sc += 1.0
    elif p > -50: sc += 0.5
    # 爆仓 (1.5分)
    busts = s["busts"]
    if busts == 0: sc += 1.5
    elif busts <= 3: sc += 1.0
    elif busts <= 10: sc += 0.5
    # 回撤 (1分)
    if max_dd < 20: sc += 1.0
    elif max_dd < 40: sc += 0.7
    elif max_dd < 60: sc += 0.3
    # 下注 (0.5分)
    bets = s["total_bets"]
    if 500 <= bets <= 30000: sc += 0.5
    elif 100 <= bets <= 50000: sc += 0.3
    elif bets > 0: sc += 0.1
    return min(10, max(0, sc))


def main():
    # 已知 9+ 分策略 (从 search_9plus.py)
    candidates = [
        {"id": "k7da_xiao80_1y_old", "pnl_pct": 6530.9, "busts": 13, "max_dd": 82.8, "bets": 1032},
        {"id": "k4dan_shuang_1000_10y_old", "pnl_pct": 3093.7, "busts": 10, "max_dd": 68.4, "bets": 89478},
        {"id": "k12da_xiao_5000_10y", "pnl_pct": 2489.7, "busts": 3, "max_dd": 33.3, "bets": 279},
        {"id": "k12da_xiao_1500_10y", "pnl_pct": 743.4, "busts": 0, "max_dd": 24.6, "bets": 279},
        {"id": "k11da_xiao_1000_10y", "pnl_pct": 569.6, "busts": 0, "max_dd": 35.1, "bets": 616},
        {"id": "k10da_xiao_700_10y", "pnl_pct": 487.6, "busts": 0, "max_dd": 36.9, "bets": 1304},
        {"id": "k11da_xiao_800_10y", "pnl_pct": 455.7, "busts": 0, "max_dd": 32.6, "bets": 616},
        {"id": "k10da_xiao_600_10y", "pnl_pct": 416.8, "busts": 0, "max_dd": 35.0, "bets": 1304},
        {"id": "k12da_xiao_800_10y", "pnl_pct": 404.5, "busts": 0, "max_dd": 19.2, "bets": 279},
        {"id": "k11da_xiao_700_10y", "pnl_pct": 398.7, "busts": 0, "max_dd": 30.9, "bets": 616},
        {"id": "k10da_xiao_500_10y", "pnl_pct": 353.9, "busts": 1, "max_dd": 30.2, "bets": 1304},
        {"id": "k11da_xiao_500_10y", "pnl_pct": 284.5, "busts": 1, "max_dd": 26.9, "bets": 616},
        {"id": "k13da_xiao_1000_10y", "pnl_pct": 278.4, "busts": 0, "max_dd": 18.3, "bets": 114},
        {"id": "k11da_xiao_450_10y", "pnl_pct": 256.3, "busts": 0, "max_dd": 25.4, "bets": 616},
        {"id": "k12da_xiao_500_10y", "pnl_pct": 252.8, "busts": 0, "max_dd": 15.5, "bets": 279},
        {"id": "k10da_xiao_350_10y", "pnl_pct": 244.3, "busts": 0, "max_dd": 27.3, "bets": 1304},
        {"id": "k11da_xiao_400_10y", "pnl_pct": 227.8, "busts": 0, "max_dd": 23.9, "bets": 616},
        {"id": "k13da_xiao_800_10y", "pnl_pct": 222.7, "busts": 0, "max_dd": 16.4, "bets": 114},
        {"id": "k9da_xiao_300_10y", "pnl_pct": 220.9, "busts": 0, "max_dd": 48.2, "bets": 2686},
        {"id": "k4dan_dalembert_1y", "pnl_pct": 219.6, "busts": 3, "max_dd": 47.5, "bets": 9067},
        {"id": "k10da_xiao_300_10y", "pnl_pct": 209.4, "busts": 0, "max_dd": 25.1, "bets": 1304},
        {"id": "k12da_xiao_400_10y", "pnl_pct": 202.2, "busts": 0, "max_dd": 13.8, "bets": 279},
        {"id": "labouchere_1y", "pnl_pct": 330.2, "busts": 10, "max_dd": 80.7, "bets": 9067},
        {"id": "k11da_xiao_200_10y", "pnl_pct": 113.9, "busts": 0, "max_dd": 15.6, "bets": 616},
        {"id": "k12da_xiao_300_10y", "pnl_pct": 151.0, "busts": 0, "max_dd": 12.0, "bets": 279},  # 估算
        {"id": "antimart_4win_1y", "pnl_pct": 23.9, "busts": 0, "max_dd": 19.8, "bets": 8933},
        {"id": "dalembert_K10_xiao_10y", "pnl_pct": 65.6, "busts": 0, "max_dd": 9.3, "bets": 1304},
        {"id": "dalembert_K6_xiao_1y", "pnl_pct": 82.7, "busts": 0, "max_dd": 13.8, "bets": 2132},
        {"id": "k11da_xiao_100_10y", "pnl_pct": 57.0, "busts": 0, "max_dd": 9.2, "bets": 616},
        {"id": "k4dan_shuang_50_1y", "pnl_pct": 79.7, "busts": 0, "max_dd": 18.7, "bets": 9067},
        {"id": "antimart_K4xiao_chain6_1y", "pnl_pct": 77.0, "busts": 0, "max_dd": 19.8, "bets": 8933},
    ]

    for c in candidates:
        s = {"pnl_pct": c["pnl_pct"], "busts": c["busts"], "total_bets": c["bets"]}
        c["score"] = score_v2(s, c["max_dd"])

    candidates.sort(key=lambda x: (-x["score"], -x["pnl_pct"]))

    print(f"\n=== 新评分 v2 (PnL 占 6 分) - TOP 30 ===\n")
    print(f"{'排名':>4} {'分':>5} {'策略':<32} {'PnL%':>10} {'爆仓':>4} {'回撤%':>6} {'下注':>6}")
    print("-" * 80)
    for i, c in enumerate(candidates[:30], 1):
        print(f"  {i:>2}. {c['score']:>4.1f}/10  {c['id']:<32} {c['pnl_pct']:>+9.1f}% {c['busts']:>4} {c['max_dd']:>5.1f}% {c['bets']:>6,}")


if __name__ == "__main__":
    main()
