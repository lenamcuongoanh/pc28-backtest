// PC28 策略回测前端
const fmtMoney = (n) => "$" + Math.round(n).toLocaleString();
const fmtPct = (n) => (n >= 0 ? "+" : "") + n.toFixed(2) + "%";

let strategiesMeta = null;
let currentData = null;
let equityChart = null;
let pnlChart = null;
let equitySeries = null;
let reserveSeries = null;
let pnlSeries = null;
let drawsCache = {}; // {data_source: {date: [[issue,time,sum,bs,oe], ...]}}

async function init() {
  const meta = await (await fetch("data/strategies.json")).json();
  strategiesMeta = meta;
  renderStrategyOptions(meta);

  // 加载第一个策略
  const select = document.getElementById("strategy-select");
  select.addEventListener("change", () => loadStrategy(select.value));
  loadStrategy(meta.strategies[0].id);
}

function renderStrategyOptions(meta) {
  const select = document.getElementById("strategy-select");
  select.innerHTML = "";
  meta.strategies.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    select.appendChild(opt);
  });
}

async function loadDrawsForSource(dataSource) {
  if (drawsCache[dataSource] !== undefined) return drawsCache[dataSource];
  try {
    const res = await fetch(`data/draws_${dataSource}_all.json`);
    if (res.ok) {
      drawsCache[dataSource] = await res.json();
    } else {
      drawsCache[dataSource] = null;
    }
  } catch {
    drawsCache[dataSource] = null;
  }
  return drawsCache[dataSource];
}

async function loadStrategy(id) {
  const data = await (await fetch(`data/${id}.json`)).json();
  currentData = data;

  const meta = strategiesMeta.strategies.find((s) => s.id === id);
  document.getElementById("strategy-desc").textContent = meta.desc;

  // 后台预加载 draws 索引(若可用)
  const dataSource = data.summary?.data_source || "1y";
  loadDrawsForSource(dataSource);

  renderStats(data.summary);
  renderEquityChart(data.daily, data.events);
  renderPnlChart(data.daily, data.events);
  renderEvents(data.events);
  setupYearPickerAndRenderCalendar(data);
  closeDayDetail();
}

function setupYearPickerAndRenderCalendar(data) {
  const years = Array.from(new Set(data.daily.map((d) => d.date.slice(0, 4)))).sort();
  const wrap = document.getElementById("year-picker-wrap");
  const sel = document.getElementById("year-select");
  if (years.length <= 1) {
    wrap.style.display = "none";
    renderCalendar(data.daily, data.events);
    return;
  }
  wrap.style.display = "flex";
  sel.innerHTML = years.map((y) => `<option value="${y}">${y}</option>`).join("");
  // 默认选最后一年 (最近)
  sel.value = years[years.length - 1];
  sel.onchange = () => {
    const year = sel.value;
    const filteredDaily = data.daily.filter((d) => d.date.startsWith(year));
    const filteredEvents = data.events.filter((ev) => ev.date.startsWith(year));
    renderCalendar(filteredDaily, filteredEvents);
  };
  sel.onchange();
}

function renderStats(s) {
  document.getElementById("stat-start").textContent = fmtMoney(s.start_total);
  document.getElementById("stat-end").textContent = fmtMoney(s.end_total);
  const pnlEl = document.getElementById("stat-pnl");
  pnlEl.textContent = `${fmtMoney(s.pnl)} (${fmtPct(s.pnl_pct)})`;
  pnlEl.style.color = s.pnl >= 0 ? "#4caf50" : "#f44336";
  document.getElementById("stat-peak").textContent = `${fmtMoney(s.peak_total)} (${fmtPct(s.peak_pct)})`;
  document.getElementById("stat-table").textContent = fmtMoney(s.current_table);
  document.getElementById("stat-reserve").textContent = fmtMoney(s.current_reserve);
  document.getElementById("stat-bets").textContent = `${s.total_bets.toLocaleString()} / ${s.win_rate.toFixed(2)}%`;

  // 计算最大回撤
  const dailyArr = currentData.daily;
  let peak = s.start_total, maxDD = 0;
  dailyArr.forEach((d) => {
    if (d.high > peak) peak = d.high;
    const dd = (peak - d.low) / peak;
    if (dd > maxDD) maxDD = dd;
  });
  document.getElementById("stat-dd").textContent = (maxDD * 100).toFixed(1) + "%";

  document.getElementById("stat-busts").textContent = s.busts;
  document.getElementById("stat-realloc").textContent = s.realloc;
}

function dateToTs(dateStr) {
  // dateStr: "2025-04-29"
  const [y, m, d] = dateStr.split("-").map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / 1000);
}

function renderEquityChart(daily, events) {
  const container = document.getElementById("equity-chart");
  container.innerHTML = "";
  equityChart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#16181c" }, textColor: "#8b98a5" },
    grid: { vertLines: { color: "#2f3336" }, horzLines: { color: "#2f3336" } },
    timeScale: { timeVisible: false, secondsVisible: false, rightOffset: 5 },
    rightPriceScale: { borderColor: "#2f3336" },
    crosshair: { mode: 0 },
    height: 360,
  });

  // 总额线
  equitySeries = equityChart.addLineSeries({
    color: "#4caf50",
    lineWidth: 2,
    priceFormat: { type: "custom", formatter: fmtMoney },
  });
  // 备用金线
  reserveSeries = equityChart.addLineSeries({
    color: "#ff9800",
    lineWidth: 1,
    lineStyle: 2, // dashed
    priceFormat: { type: "custom", formatter: fmtMoney },
  });

  const equityData = daily.map((d) => ({ time: dateToTs(d.date), value: d.close }));
  equitySeries.setData(equityData);

  // 备用金 = close - end-of-day table
  // 但 daily 里没存 reserve 历史。简化:用最后一笔订单的 reserve_after,或不画
  // 暂时只画 close 线(总额),备用金线在没数据时用粗略估算
  // -- 改为画 close (总额) 和 close - 最后 trade 的 table_after
  // 实际上 trades_by_day 里有 reserve_after,可以构造
  const reserveData = [];
  daily.forEach((d) => {
    const trades = currentData.trades_by_day[d.date] || [];
    const lastTrade = [...trades].reverse().find((t) => t.type === "trade");
    if (lastTrade) {
      reserveData.push({ time: dateToTs(d.date), value: lastTrade.reserve_after });
    } else {
      // 当天没下注,用前一天的 reserve
      const lastVal = reserveData.length ? reserveData[reserveData.length - 1].value : 8000;
      reserveData.push({ time: dateToTs(d.date), value: lastVal });
    }
  });
  reserveSeries.setData(reserveData);

  // 事件 markers
  const markers = events.map((ev) => ({
    time: dateToTs(ev.date),
    position: ev.type === "bust" ? "belowBar" : "aboveBar",
    color: ev.type === "bust" ? "#f44336" : "#4caf50",
    shape: ev.type === "bust" ? "arrowDown" : "arrowUp",
    text: ev.type === "bust" ? "💀" : "🎉",
  }));
  if (markers.length) equitySeries.setMarkers(markers);
}

function renderPnlChart(daily, events) {
  const container = document.getElementById("pnl-chart");
  container.innerHTML = "";
  pnlChart = LightweightCharts.createChart(container, {
    layout: { background: { color: "#16181c" }, textColor: "#8b98a5" },
    grid: { vertLines: { color: "#2f3336" }, horzLines: { color: "#2f3336" } },
    timeScale: { timeVisible: false, secondsVisible: false, rightOffset: 5 },
    rightPriceScale: { borderColor: "#2f3336" },
    crosshair: { mode: 0 },
    height: 360,
  });

  pnlSeries = pnlChart.addCandlestickSeries({
    upColor: "#4caf50",
    downColor: "#f44336",
    borderUpColor: "#4caf50",
    borderDownColor: "#f44336",
    wickUpColor: "#4caf50",
    wickDownColor: "#f44336",
    priceFormat: { type: "custom", formatter: fmtMoney },
  });

  const candleData = daily.map((d) => ({
    time: dateToTs(d.date),
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
  }));
  pnlSeries.setData(candleData);

  const markers = events.map((ev) => ({
    time: dateToTs(ev.date),
    position: ev.type === "bust" ? "belowBar" : "aboveBar",
    color: ev.type === "bust" ? "#f44336" : "#4caf50",
    shape: ev.type === "bust" ? "arrowDown" : "arrowUp",
    text: ev.type === "bust" ? "💀" : "🎉",
  }));
  if (markers.length) pnlSeries.setMarkers(markers);

  // tooltip on hover
  pnlChart.subscribeCrosshairMove((param) => {
    if (!param.time || !param.seriesData.size) return;
    // 这里可以做自定义 tooltip,默认 lightweight-charts 已经显示 OHLC
  });
}

function renderEvents(events) {
  const list = document.getElementById("events-list");
  if (!events.length) {
    list.innerHTML = '<p style="color:#8b98a5;font-size:13px">本策略没有触发爆仓 / 翻倍事件 (口袋钱够稳)</p>';
    return;
  }
  list.innerHTML = events
    .map((ev, i) => {
      const cls = ev.type === "bust" ? "bust" : "realloc";
      return `<div class="event-item ${cls}" onclick="openDay('${ev.date}')">
        <span class="event-time">${ev.date} ${ev.time}</span>
        <span class="event-msg">${ev.msg}</span>
      </div>`;
    })
    .join("");
}

function colorForPnl(pnl) {
  if (pnl === 0) return "#2a2d33";
  if (pnl > 0) {
    const intensity = Math.min(1, Math.abs(pnl) / 500);
    return `rgba(76, 175, 80, ${0.2 + intensity * 0.7})`;
  } else {
    const intensity = Math.min(1, Math.abs(pnl) / 500);
    return `rgba(244, 67, 54, ${0.2 + intensity * 0.7})`;
  }
}

const MONTH_LABELS = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

function renderCalendar(daily, events) {
  const cal = document.getElementById("calendar");
  cal.innerHTML = "";
  const eventDays = new Set();
  events.forEach((ev) => eventDays.add(ev.date + "-" + ev.type));

  // 按 YYYY-MM 分组
  const monthGroups = {};
  daily.forEach((d) => {
    const ym = d.date.slice(0, 7);
    if (!monthGroups[ym]) monthGroups[ym] = [];
    monthGroups[ym].push(d);
  });

  const sortedMonths = Object.keys(monthGroups).sort();
  sortedMonths.forEach((ym) => {
    const block = document.createElement("div");
    block.className = "month-block";
    const [y, m] = ym.split("-");
    const monthLabel = MONTH_LABELS[parseInt(m) - 1];
    const monthDays = monthGroups[ym];
    const monthPnl = monthDays.reduce((sum, d) => sum + d.pnl, 0);
    const monthBets = monthDays.reduce((sum, d) => sum + d.bets, 0);
    const pnlColor = monthPnl >= 0 ? "#a8e6cf" : "#ffaaa5";
    block.innerHTML = `<div class="month-label">${y}年 ${monthLabel} <span style="color:${pnlColor};font-weight:400;margin-left:10px">月度 ${monthPnl >= 0 ? "+" : ""}${fmtMoney(monthPnl)} · 下注 ${monthBets} 次</span></div><div class="month-grid"></div>`;
    const grid = block.querySelector(".month-grid");

    monthDays.forEach((d) => {
      const cell = document.createElement("div");
      cell.className = "day-cell";
      cell.style.background = colorForPnl(d.pnl);
      if (eventDays.has(d.date + "-bust")) cell.classList.add("bust");
      if (eventDays.has(d.date + "-realloc")) cell.classList.add("realloc");
      const dayNum = parseInt(d.date.split("-")[2]);
      cell.innerHTML = `<span class="day-num">${dayNum}</span><span class="day-pnl">${d.pnl >= 0 ? "+" : ""}${d.pnl}</span>`;
      cell.title = `${d.date}\n开: ${fmtMoney(d.open)}\n收: ${fmtMoney(d.close)}\n盈亏: ${d.pnl >= 0 ? "+" : ""}${fmtMoney(d.pnl)}\n下注: ${d.bets} (赢 ${d.wins})`;
      cell.addEventListener("click", () => openDay(d.date));
      grid.appendChild(cell);
    });
    cal.appendChild(block);
  });
}

async function openDay(date) {
  const detail = document.getElementById("day-detail");
  detail.style.display = "block";
  detail.scrollIntoView({ behavior: "smooth", block: "start" });

  const dailyEntry = currentData.daily.find((d) => d.date === date);
  const trades = currentData.trades_by_day[date] || [];
  const dataSource = currentData.summary?.data_source || "1y";

  document.getElementById("day-detail-title").textContent = `📅 ${date} 全日明细`;

  if (dailyEntry) {
    document.getElementById("day-detail-summary").innerHTML = `
      <span>开盘 <strong>${fmtMoney(dailyEntry.open)}</strong></span>
      <span>最高 <strong>${fmtMoney(dailyEntry.high)}</strong></span>
      <span>最低 <strong>${fmtMoney(dailyEntry.low)}</strong></span>
      <span>收盘 <strong>${fmtMoney(dailyEntry.close)}</strong></span>
      <span>当日盈亏 <strong style="color:${dailyEntry.pnl >= 0 ? "#4caf50" : "#f44336"}">${dailyEntry.pnl >= 0 ? "+" : ""}${fmtMoney(dailyEntry.pnl)}</strong></span>
      <span>下注 <strong>${dailyEntry.bets} 笔</strong> (赢 ${dailyEntry.wins})</span>
    `;
  }

  const tbody = document.getElementById("day-detail-trades");
  tbody.innerHTML = '<p style="color:#8b98a5;padding:16px">加载中…</p>';

  // 加载 draws 索引
  const drawsIndex = await loadDrawsForSource(dataSource);
  const drawsForDay = drawsIndex?.[date] || null;

  // 把 trades 按 issue 索引,event 按时间索引
  const tradeByIssue = {};
  const eventsList = [];
  trades.forEach((t) => {
    if (t.msg) {
      eventsList.push(t);
    } else if (t.issue) {
      tradeByIssue[t.issue] = t;
    }
  });

  let html = `<div class="trade-row header">
    <span>时间</span><span>期号</span><span>开奖</span><span>触发/押</span><span>金额</span><span>结果</span><span>余额</span><span>口袋/备用</span>
  </div>`;

  if (drawsForDay) {
    // 完整模式:列出当日所有期开奖,合并 trades 和 events
    // 先按 issue 排序所有 draw
    const drawsSorted = drawsForDay.slice().sort((a, b) => a[0] - b[0]);
    drawsSorted.forEach(([issue, time, sum, bs, oe]) => {
      const trade = tradeByIssue[issue];
      // 先输出与该期 issue 时间最接近 (相同) 的 events
      const matchingEvents = eventsList.filter((e) => e.issue === issue);
      matchingEvents.forEach((e) => {
        const evCls = e.msg.includes("爆仓") ? "event-bust" : "event-realloc";
        html += `<div class="trade-row ${evCls}">${e.msg}</div>`;
      });
      if (trade) {
        const cls = trade.win ? "win" : "lose";
        const result = trade.win ? `+${fmtMoney(trade.delta)}` : `${fmtMoney(trade.delta)}`;
        html += `<div class="trade-row ${cls}">
          <span>${trade.time}</span>
          <span>${trade.issue}</span>
          <span>${trade.draw_sum} ${trade.bs}${trade.oe}</span>
          <span>${trade.reason || trade.side} → ${trade.side}</span>
          <span>${fmtMoney(trade.amount)}</span>
          <span>${trade.win ? "✅" : "❌"} ${result}</span>
          <span>${fmtMoney(trade.balance_after)}</span>
          <span>${fmtMoney(trade.table_after)} / ${fmtMoney(trade.reserve_after)}</span>
        </div>`;
      } else {
        // 仅开奖,无下注
        html += `<div class="trade-row no-bet">
          <span>${time}</span>
          <span>${issue}</span>
          <span>${sum} ${bs}${oe}</span>
          <span style="color:#5a6772">— 未下注 —</span>
          <span>—</span>
          <span>—</span>
          <span>—</span>
          <span>—</span>
        </div>`;
      }
    });
  } else {
    // 降级模式:无 draws 索引 (10y/30y),只显示 trades
    if (!trades.length) {
      if (!currentData.keep_all_trades && dailyEntry && dailyEntry.bets > 0) {
        tbody.innerHTML = `<p style="color:#8b98a5;padding:16px">本日下注 <strong>${dailyEntry.bets}</strong> 次, 赢 <strong>${dailyEntry.wins}</strong>, 亏 <strong>${dailyEntry.bets - dailyEntry.wins}</strong>, 当日盈亏 <strong style="color:${dailyEntry.pnl >= 0 ? "#4caf50" : "#f44336"}">${dailyEntry.pnl >= 0 ? "+" : ""}${fmtMoney(dailyEntry.pnl)}</strong><br>(10/30 年回测为节省体积,只保留爆仓/翻倍当天的逐笔订单。完整开奖明细仅 1 年回测可见。)</p>`;
      } else {
        tbody.innerHTML = '<p style="color:#8b98a5;padding:16px">当天无下注 (信号未触发)。10/30 年回测不显示完整开奖明细以节省加载。</p>';
      }
      return;
    }
    trades.forEach((t) => {
      if (t.msg) {
        const evCls = t.msg.includes("爆仓") ? "event-bust" : "event-realloc";
        html += `<div class="trade-row ${evCls}">${t.msg}</div>`;
      } else {
        const cls = t.win ? "win" : "lose";
        const result = t.win ? `+${fmtMoney(t.delta)}` : `${fmtMoney(t.delta)}`;
        html += `<div class="trade-row ${cls}">
          <span>${t.time}</span>
          <span>${t.issue}</span>
          <span>${t.draw_sum} ${t.bs}${t.oe}</span>
          <span>${t.reason || t.side} → ${t.side}</span>
          <span>${fmtMoney(t.amount)}</span>
          <span>${t.win ? "✅" : "❌"} ${result}</span>
          <span>${fmtMoney(t.balance_after)}</span>
          <span>${fmtMoney(t.table_after)} / ${fmtMoney(t.reserve_after)}</span>
        </div>`;
      }
    });
  }

  tbody.innerHTML = html;
}

function closeDayDetail() {
  document.getElementById("day-detail").style.display = "none";
}

window.openDay = openDay;
window.closeDayDetail = closeDayDetail;

init();
