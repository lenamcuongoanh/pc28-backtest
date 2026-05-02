"""给所有策略评分 (10 分制),输出排名"""
import json
import os
import glob

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def compute_max_dd(daily):
    """从 daily 数据计算最大回撤"""
    peak = 10000
    max_dd = 0
    for d in daily:
        if d["high"] > peak: peak = d["high"]
        dd = (peak - d["low"]) / peak if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    return max_dd * 100


def score(s, max_dd):
    """10 分制评分"""
    sc = 0
    p = s["pnl_pct"]
    if p > 200: sc += 4
    elif p > 50: sc += 3
    elif p > 0: sc += 2
    elif p > -25: sc += 1
    elif p > -50: sc += 0.5
    busts = s["busts"]
    if busts == 0: sc += 2
    elif busts <= 3: sc += 1.5
    elif busts <= 10: sc += 0.5
    if max_dd < 20: sc += 2
    elif max_dd < 40: sc += 1.5
    elif max_dd < 60: sc += 1
    elif max_dd < 80: sc += 0.5
    bets = s["total_bets"]
    if 500 <= bets <= 30000: sc += 2
    elif 100 <= bets <= 50000: sc += 1
    elif bets > 0: sc += 0.5
    return min(10, max(0, sc))


def main():
    # 7 个新策略评分 (从 test_7new.py 结果)
    new_7 = [
        {"id": "labouchere_1y", "name": "[1年 Labouchere取消法]", "pnl_pct": 330.2, "busts": 10, "max_dd": 80.7, "bets": 9067},
        {"id": "fibonacci_1y", "name": "[1年 Fibonacci 爬楼梯]", "pnl_pct": 3.9, "busts": 3, "max_dd": 64.6, "bets": 9067},
        {"id": "trend_1y", "name": "[1年 顺势押]", "pnl_pct": -97.0, "busts": 19, "max_dd": 98.7, "bets": 8933},
        {"id": "volatility_1y", "name": "[1年 Sum 波动率反向]", "pnl_pct": -35.0, "busts": 4, "max_dd": 62.6, "bets": 80435},
        {"id": "compound_dadan_1y", "name": "[1年 大单 4.322x 复合赌注]", "pnl_pct": -65.8, "busts": 7, "max_dd": 82.8, "bets": 461},
        {"id": "sum1314_1y", "name": "[1年 Sum=13/14 反向]", "pnl_pct": -58.5, "busts": 6, "max_dd": 78.4, "bets": 75674},
        {"id": "antimart_4win_1y", "name": "[1年 Anti-马丁+4连胜止盈]", "pnl_pct": 23.9, "busts": 0, "max_dd": 19.8, "bets": 8933},
    ]

    # 已有策略 - 从 JSON 读
    existing = []
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "*.json"))):
        if "strategies.json" in f or "draws_" in f: continue
        try:
            d = json.load(open(f))
            s = d["summary"]
            max_dd = compute_max_dd(d.get("daily", []))
            existing.append({
                "id": s["strategy_id"],
                "name": d.get("summary", {}).get("strategy_id", os.path.basename(f).replace(".json", "")),
                "pnl_pct": s["pnl_pct"],
                "busts": s["busts"],
                "max_dd": max_dd,
                "bets": s["total_bets"],
            })
        except Exception as e:
            print(f"  err: {f}: {e}")

    all_strats = existing + [{**n, "is_new": True} for n in new_7]

    # 评分
    for st in all_strats:
        # 构造伪 summary 用于 score 函数
        s = {"pnl_pct": st["pnl_pct"], "busts": st["busts"], "total_bets": st["bets"]}
        st["score"] = score(s, st["max_dd"])

    # 排序
    all_strats.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n=== 全部策略评分 (按 10 分制排序) ===\n")
    print(f"{'排名':>4} {'策略 ID':<32} {'PnL%':>10} {'爆仓':>5} {'回撤%':>7} {'下注':>8} {'分':>5}")
    print("-" * 90)
    for i, st in enumerate(all_strats, 1):
        marker = " ✨NEW" if st.get("is_new") else ""
        print(f"  {i:>2}. {st['id']:<32} {st['pnl_pct']:>+9.1f}% {st['busts']:>5} {st['max_dd']:>6.1f}% {st['bets']:>8,} {st['score']:>4.1f}/10{marker}")

    # 输出 TOP 5
    print(f"\n=== TOP 5 (网页保留) ===")
    for i, st in enumerate(all_strats[:5], 1):
        print(f"  🏆 {i}. {st['id']}: {st['score']:.1f}/10 (PnL {st['pnl_pct']:+.1f}%, 爆仓 {st['busts']}, 回撤 {st['max_dd']:.1f}%)")


if __name__ == "__main__":
    main()
