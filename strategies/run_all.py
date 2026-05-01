"""跑 4 个策略的过去 1 年回测,生成 JSON 数据供前端读取。

输出:
- data/strategies.json  策略列表 + 简要描述
- data/{strategy_id}.json  每个策略的 daily / trades / summary / events
"""
import sqlite3
import json
import os
from collections import defaultdict
from dataclasses import dataclass

DB_1Y = "/Users/long/.openclaw/workspace/PC28/data/pc28_past_1year.db"
DB_FULL = "/Users/long/.openclaw/workspace/PC28/data/pc28_full.db"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
START_TOTAL = 10000
TARGET = 1_000_000


@dataclass
class State:
    total: int
    table: int
    table_init: int
    anchor: int
    consec_loss: int = 0
    busts: int = 0
    realloc: int = 0


def settle(side, amount, draw_sum):
    s = draw_sum
    win = False
    payout = 2.0
    if side == "大":
        win = s >= 14
        if win and s == 14: payout = 1.98
    elif side == "小":
        win = s <= 13
        if win and s == 13: payout = 1.98
    elif side == "单":
        win = s % 2 == 1
        if win and s == 13: payout = 1.98
    elif side == "双":
        win = s % 2 == 0
        if win and s == 14: payout = 1.98
    if win:
        return int(round(amount * (payout - 1)))
    return -amount


# ===== Strategy primitives =====

def streak_oe(K, side):
    def f(h):
        if len(h) < K: return False
        return all(r["oe"] == side for r in h[-K:])
    return f

def streak_bs(K, side):
    def f(h):
        if len(h) < K: return False
        return all(r["bs"] == side for r in h[-K:])
    return f

def or_cond(*conds):
    def f(h): return any(c(h) for c in conds)
    return f


# ===== Strategies =====

def strat_micro_martingale():
    """连3单→押双 微马丁 base=$10 L=2"""
    cond = streak_oe(3, "单")
    def f(state, history, draw_sum):
        if state.total >= TARGET: return None
        if not cond(history): return None
        base = 10
        if state.consec_loss >= 2:
            amt = base
        else:
            amt = base * (2 ** state.consec_loss)
        amt = max(1, min(amt, state.table, 12000))
        return ("双", amt, "连3单→押双 微马丁")
    return f


def strat_dalembert():
    """连3单→押双 爬楼梯。起步金额 = 当前口袋 // 200,最低 $1"""
    cond = streak_oe(3, "单")
    state_track = {"level": 1}
    def f(state, history, draw_sum):
        if state.total >= TARGET: return None
        if not cond(history): return None
        unit = max(1, state.table_init // 200)
        amt = unit * state_track["level"]
        amt = max(1, min(amt, state.table, 12000))
        return ("双", amt, "连3单→押双 爬楼梯")
    f.update = lambda won: state_track.update({"level": max(1, state_track["level"] - 1) if won else state_track["level"] + 1})
    f.reset = lambda: state_track.update({"level": 1})
    return f


def strat_dalembert_take_profit():
    """连3单→押双 爬楼梯 + 1% 止盈重置。
    起步 = 锚点 // 200。锚点 = 上次重置时的口袋金额。
    口袋 ≥ 锚点 × 1.01 → 重置 (锚点更新为当前口袋,起步按新锚点重算,level 回 1)。
    """
    cond = streak_oe(3, "单")
    state_track = {"level": 1, "anchor": None, "unit": None}

    def reset_round(current_pocket):
        state_track["anchor"] = current_pocket
        state_track["unit"] = max(1, current_pocket // 200)
        state_track["level"] = 1

    def f(state, history, draw_sum):
        if state.total >= TARGET: return None
        if not cond(history): return None
        # 首次 / bust / realloc 后初始化
        if state_track["anchor"] is None:
            reset_round(state.table)
        # 1% 止盈检查
        if state.table >= state_track["anchor"] * 1.01:
            reset_round(state.table)
        amt = state_track["unit"] * state_track["level"]
        amt = max(1, min(amt, state.table, 12000))
        return ("双", amt, "连3单→押双 爬楼梯+1%止盈")

    def update(won):
        state_track["level"] = max(1, state_track["level"] - 1) if won else state_track["level"] + 1

    def reset():
        state_track["anchor"] = None
        state_track["unit"] = None
        state_track["level"] = 1

    f.update = update
    f.reset = reset
    return f


def strat_moonshot():
    """连3同色 → 反向全押 + 达 $1M 停手"""
    cond = or_cond(streak_oe(3, "单"), streak_oe(3, "双"), streak_bs(3, "大"), streak_bs(3, "小"))
    def f(state, history, draw_sum):
        if state.total >= TARGET: return None
        if not cond(history): return None
        # 选反向
        last3_bs = [r["bs"] for r in history[-3:]]
        last3_oe = [r["oe"] for r in history[-3:]]
        side = None
        if all(x == "大" for x in last3_bs): side = "小"
        elif all(x == "小" for x in last3_bs): side = "大"
        elif all(x == "单" for x in last3_oe): side = "双"
        elif all(x == "双" for x in last3_oe): side = "单"
        if not side: return None
        amt = min(state.table, 12000)
        if amt < 1: return None
        return (side, amt, f"连3{last3_oe[0] if side in ['双','单'] else last3_bs[0]}→反向全押")
    return f


def strat_low_freq():
    """连11大 → 押小 $50"""
    cond = streak_bs(11, "大")
    def f(state, history, draw_sum):
        if state.total >= TARGET: return None
        if not cond(history): return None
        amt = min(50, state.table, 12000)
        if amt < 1: return None
        return ("小", amt, "连11大→押小")
    return f


STRATEGIES = [
    {
        "id": "dalembert_1y",
        "name": "连3单押双 爬楼梯 (过去 1 年)",
        "desc": "信号:连续 3 期开单 → 押双。爬楼梯下注:起步 = 当前口袋 // 200 (eg. $2K→$10, $1.6K→$8)。输了 +1 个起步, 赢了 -1 个起步, 最低 1 起步。每次爆仓/翻倍后按新口袋重算起步。回测过去 1 年 (2025-04-29 → 2026-04-28, 146,396 期)。",
        "factory": strat_dalembert,
        "data_source": "1y",
    },
    {
        "id": "dalembert_10y",
        "name": "连3单押双 爬楼梯 (过去 10 年)",
        "desc": "同样的策略,回测过去 10 年 (2016-04-29 → 2026-04-28, ~1.46M 期)。10 年订单太多,只保留爆仓/翻倍当天的逐笔订单,其他日子显示当日聚合统计。",
        "factory": strat_dalembert,
        "data_source": "10y",
    },
    {
        "id": "dalembert_tp_1y",
        "name": "连3单押双 爬楼梯+1%止盈 (过去 1 年)",
        "desc": "同样的信号 (连 3 单押双) 和爬楼梯下注,但加入 1% 止盈重置:口袋从锚点涨够 1% (≥锚点×1.01) → 立刻回到第 1 级,锚点更新为当前口袋,起步按新锚点÷200 重算。频繁锁小利润避免吐回去。回测过去 1 年。",
        "factory": strat_dalembert_take_profit,
        "data_source": "1y",
    },
]


def run_backtest(strategy_id, strategy_factory, draws, keep_all_trades=True):
    """跑回测,生成完整数据"""
    strategy_fn = strategy_factory()
    state = State(
        total=START_TOTAL, table=START_TOTAL // 5,
        table_init=START_TOTAL // 5, anchor=START_TOTAL,
    )
    history = []

    daily = defaultdict(lambda: {"date": None, "open": 0, "high": 0, "low": 0, "close": 0,
                                  "bets": 0, "wins": 0, "pnl": 0, "events": []})
    trades_by_day = defaultdict(list)
    events = []  # 全局事件列表 (爆仓 / 翻倍)

    peak = START_TOTAL
    target_hit_at = None

    for i, draw in enumerate(draws):
        date = draw["date"]
        time = draw["time"]
        issue = draw["issue"]
        draw_sum = draw["sum"]

        # 当天初始化
        if daily[date]["date"] is None:
            daily[date]["date"] = date
            daily[date]["open"] = state.total
            daily[date]["high"] = state.total
            daily[date]["low"] = state.total
            daily[date]["close"] = state.total

        # 翻倍检查
        if state.total >= state.anchor * 2:
            old_total = state.total
            old_anchor = state.anchor
            state.anchor = state.total
            state.table_init = state.total // 5
            state.table = state.table_init
            state.realloc += 1
            state.consec_loss = 0
            if hasattr(strategy_fn, "reset"):
                strategy_fn.reset()
            event = {
                "type": "realloc",
                "date": date, "time": time, "issue": issue,
                "total_before": old_total, "total_after": state.total,
                "new_table": state.table_init, "new_reserve": state.total - state.table_init,
                "anchor_before": old_anchor, "anchor_after": state.anchor,
                "msg": f"🎉 翻倍! 总本金 ${old_total:,} 达到锚点 ${old_anchor*2:,},重新分配:口袋 ${state.table_init:,} + 备用金 ${state.total - state.table_init:,}",
            }
            events.append(event)
            daily[date]["events"].append(event)
            trades_by_day[date].append({"type": "event", **event})

        if state.total >= TARGET and not target_hit_at:
            target_hit_at = {"date": date, "time": time, "total": state.total}

        # 策略决策
        result = strategy_fn(state, history, draw_sum)
        history.append({"sum": draw_sum, "bs": draw["bs"], "oe": draw["oe"]})
        if len(history) > 50: history = history[-50:]

        if result is None:
            daily[date]["close"] = state.total
            daily[date]["high"] = max(daily[date]["high"], state.total)
            daily[date]["low"] = min(daily[date]["low"], state.total)
            continue

        side, amount, reason = result
        amount = max(1, min(int(amount), 12000, state.table))
        if amount < 1:
            continue

        delta = settle(side, amount, draw_sum)
        won = delta > 0
        state.total += delta
        state.table += delta

        # 通知策略更新内部状态
        if hasattr(strategy_fn, "update"):
            strategy_fn.update(won)

        # 马丁连输计数
        state.consec_loss = state.consec_loss + 1 if not won else 0

        # 爆仓检查
        bust_event = None
        if state.table <= 0:
            new_table = state.total // 5
            new_reserve = state.total - new_table
            bust_event = {
                "type": "bust",
                "date": date, "time": time, "issue": issue,
                "total": state.total,
                "new_table": new_table, "new_reserve": new_reserve,
                "msg": f"💀 爆仓! 口袋空了。从备用金拿 1/5 = ${new_table:,} 当新口袋,备用金还剩 ${new_reserve:,}",
            }
            state.table_init = new_table
            state.table = new_table
            state.busts += 1
            state.consec_loss = 0
            if hasattr(strategy_fn, "reset"):
                strategy_fn.reset()
            events.append(bust_event)
            daily[date]["events"].append(bust_event)

        if state.total > peak: peak = state.total

        # 记录订单
        trade = {
            "type": "trade",
            "issue": issue, "time": time, "side": side,
            "amount": amount, "win": won, "delta": delta,
            "balance_after": state.total,
            "table_after": state.table,
            "reserve_after": state.total - state.table,
            "draw_sum": draw_sum, "bs": draw["bs"], "oe": draw["oe"],
            "reason": reason,
        }
        trades_by_day[date].append(trade)
        if bust_event:
            trades_by_day[date].append({"type": "event", **bust_event})

        daily[date]["bets"] += 1
        if won: daily[date]["wins"] += 1
        daily[date]["pnl"] += delta
        daily[date]["close"] = state.total
        daily[date]["high"] = max(daily[date]["high"], state.total)
        daily[date]["low"] = min(daily[date]["low"], state.total)

        if state.total <= 0: break

    # 整理
    daily_list = [daily[d] for d in sorted(daily.keys())]

    summary = {
        "strategy_id": strategy_id,
        "start_total": START_TOTAL,
        "end_total": state.total,
        "peak_total": peak,
        "pnl": state.total - START_TOTAL,
        "pnl_pct": (state.total - START_TOTAL) / START_TOTAL * 100,
        "peak_pct": (peak - START_TOTAL) / START_TOTAL * 100,
        "total_bets": sum(d["bets"] for d in daily_list),
        "total_wins": sum(d["wins"] for d in daily_list),
        "win_rate": sum(d["wins"] for d in daily_list) / max(1, sum(d["bets"] for d in daily_list)) * 100,
        "busts": state.busts,
        "realloc": state.realloc,
        "target_hit": target_hit_at,
        "current_table": state.table,
        "current_reserve": state.total - state.table,
        "days": len(daily_list),
    }

    # 长期回测时,只保留事件日的订单详情以减小 JSON 体积
    if not keep_all_trades:
        event_dates = set(ev["date"] for ev in events)
        trades_by_day_filtered = {d: trades_by_day[d] for d in event_dates if d in trades_by_day}
    else:
        trades_by_day_filtered = dict(trades_by_day)

    return {
        "summary": summary,
        "daily": daily_list,
        "trades_by_day": trades_by_day_filtered,
        "events": events,
        "keep_all_trades": keep_all_trades,
    }


def load_draws(data_source):
    """加载数据,根据 data_source 切片"""
    if data_source == "1y":
        conn = sqlite3.connect(DB_1Y)
        query = "SELECT issue, sum, bigsmall, oddeven, date, time FROM draws ORDER BY ts_utc ASC"
    elif data_source == "10y":
        conn = sqlite3.connect(DB_FULL)
        # 过去 10 年: 2016-04-29 起
        query = "SELECT issue, sum, bigsmall, oddeven, date, time FROM draws WHERE date >= '2016-04-29' ORDER BY ts_utc ASC"
    else:
        raise ValueError(f"unknown data_source: {data_source}")
    c = conn.cursor()
    c.execute(query)
    draws = [{"issue": r[0], "sum": r[1], "bs": r[2], "oe": r[3], "date": r[4], "time": r[5]}
             for r in c.fetchall()]
    conn.close()
    return draws


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    strategies_meta = []
    for st in STRATEGIES:
        data_source = st.get("data_source", "1y")
        print(f"\n>>> 跑策略: {st['name']} (data={data_source})")
        draws = load_draws(data_source)
        print(f"    加载 {len(draws):,} 期 ({draws[0]['date']} → {draws[-1]['date']})")

        # 长期回测不保留全部 trade detail
        keep_all = data_source == "1y"
        result = run_backtest(st["id"], st["factory"], draws, keep_all_trades=keep_all)
        s = result["summary"]
        s["data_source"] = data_source
        s["date_start"] = draws[0]["date"]
        s["date_end"] = draws[-1]["date"]
        s["total_draws"] = len(draws)
        print(f"    终值 ${s['end_total']:,}, PnL {s['pnl_pct']:+.1f}%, 峰值 ${s['peak_total']:,}, 爆仓 {s['busts']}, 翻倍 {s['realloc']}")

        out_path = os.path.join(OUT_DIR, f"{st['id']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        print(f"    写入 {out_path} ({os.path.getsize(out_path)/1024:.0f} KB)")

        strategies_meta.append({
            "id": st["id"],
            "name": st["name"],
            "desc": st["desc"],
            "summary": s,
        })

    # 元数据
    meta = {
        "strategies": strategies_meta,
        "framework": {
            "start_total": START_TOTAL,
            "table_ratio": "1/5",
            "reserve_ratio": "4/5",
            "target": TARGET,
            "max_bet": 12000,
            "rules_summary": "起始 $10K → 口袋 $2K + 备用金 $8K。爆仓 → 拿剩余 1/5 当新口袋。总额 ≥ 锚点×2 → 重新分配 (1/5 + 4/5)。达 $1M 停手。",
        },
    }
    with open(os.path.join(OUT_DIR, "strategies.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 全部完成。元数据写入 data/strategies.json")


if __name__ == "__main__":
    main()
