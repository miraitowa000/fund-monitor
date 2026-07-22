import {
  TRADING_MINUTES,
  formatMinuteNow,
  getTodayDate,
  minuteToIndex,
  normalizeToStepMinute,
  readIntradayCache,
} from './cache.js?v=__APP_ASSET_VERSION__';

let intradayChartInstance = null;
let historyChartInstance = null;
let portfolioProfitChartInstance = null;

const isMobileViewport = () => window.matchMedia('(max-width: 860px)').matches;

const disposeChart = (chart) => {
  if (chart) chart.dispose();
  return null;
};

const ensureChartInstance = (chart, chartEl) => {
  if (!chartEl) return null;
  if (!chart) return echarts.init(chartEl);
  if (typeof chart.isDisposed === 'function' && chart.isDisposed()) {
    return echarts.init(chartEl);
  }
  if (typeof chart.getDom === 'function' && chart.getDom() !== chartEl) {
    chart.dispose();
    return echarts.init(chartEl);
  }
  return chart;
};

const clearChartHost = (chart, chartEl) => {
  if (!chartEl) return;
  if (!chart || (typeof chart.getDom === 'function' && chart.getDom() !== chartEl)) {
    chartEl.innerHTML = '';
  }
};

const formatIntradayAxisLabel = (value) => (value === '11:30' ? '11:30/13:00' : value);

const buildIntradaySeries = (fundCode, intradayFallback) => {
  const labels = TRADING_MINUTES.slice();
  const points = {};
  const today = getTodayDate();
  const cache = readIntradayCache();
  const cached = cache[today] && cache[today][fundCode] ? cache[today][fundCode] : {};

  Object.keys(cached).forEach((minute) => {
    const value = parseFloat(cached[minute]);
    const normalized = normalizeToStepMinute(minute);
    if (normalized && Number.isFinite(value)) points[normalized] = value;
  });

  if (intradayFallback && Array.isArray(intradayFallback.data)) {
    intradayFallback.data.forEach((point) => {
      const normalized = normalizeToStepMinute(point.time || '');
      const value = parseFloat(point.value);
      if (normalized && Number.isFinite(value)) points[normalized] = value;
    });
  }

  const known = [];
  labels.forEach((label, idx) => {
    const value = parseFloat(points[label]);
    if (Number.isFinite(value)) known.push({ idx, value });
  });

  if (known.length === 0) {
    const fallbackPoint = Array.isArray(intradayFallback?.data)
      ? intradayFallback.data.find((point) => Number.isFinite(parseFloat(point?.value)))
      : null;
    const fallbackValue = parseFloat(fallbackPoint?.value);
    if (!Number.isFinite(fallbackValue)) return null;
    const values = new Array(labels.length).fill(null);
    const currentIdx = Math.max(minuteToIndex(formatMinuteNow()), 0);
    values[currentIdx] = Number(fallbackValue.toFixed(4));
    return { labels, values, currentIdx, knownCount: 1, knownIndexes: new Set([Math.min(currentIdx, labels.length - 1)]), sparse: false };
  }

  const knownSpan = known.length > 1 ? known[known.length - 1].idx - known[0].idx : 0;
  const knownIndexes = new Set(known.map((point) => point.idx));
  const sparseSeries = known.length < 4 || knownSpan < 6;

  const values = new Array(labels.length).fill(null);
  known.forEach((point) => {
    values[point.idx] = Number(point.value.toFixed(4));
  });

  const nowMinute = formatMinuteNow();
  let currentIdx = minuteToIndex(nowMinute);

  let lastKnown = null;
  for (let i = 0; i <= currentIdx; i += 1) {
    if (Number.isFinite(values[i])) lastKnown = values[i];
    else if (lastKnown !== null) values[i] = lastKnown;
  }

  if (sparseSeries) {
    const firstKnown = known[0];
    for (let i = 0; i < firstKnown.idx; i += 1) {
      values[i] = firstKnown.value;
    }
  }

  for (let i = currentIdx + 1; i < values.length; i += 1) {
    values[i] = null;
  }

  return { labels, values, currentIdx, knownCount: known.length, knownSpan, knownIndexes, sparse: false };
};

const renderChartEmpty = (chartEl, message) => {
  chartEl.innerHTML = `<div class="chart-empty-state">${message}</div>`;
};

export const renderIntradayChart = (fundCode, basic, intradayData) => {
  const chartEl = document.getElementById('intradayChart');
  if (!chartEl) return;

  const series = buildIntradaySeries(fundCode, intradayData);
  if (!series) {
    intradayChartInstance = disposeChart(intradayChartInstance);
    renderChartEmpty(chartEl, '暂无当日走势数据，稍后刷新后再查看。');
    return;
  }

  clearChartHost(intradayChartInstance, chartEl);
  const base = basic ? parseFloat(basic.dwjz) : NaN;
  const fallbackChange = basic ? parseFloat(basic.confirmed_change || basic.gszzl) : NaN;
  let pctValues = series.values.map((value) => {
    if (value === null || !Number.isFinite(value) || !Number.isFinite(base) || base === 0) return null;
    return Number((((value - base) / base) * 100).toFixed(4));
  });

  if (!pctValues.some((value) => Number.isFinite(value)) && Number.isFinite(fallbackChange)) {
    pctValues = series.values.map((value) => (value === null ? null : Number(fallbackChange.toFixed(4))));
  }

  const finitePctValues = pctValues.filter((value) => Number.isFinite(value));
  const nearZeroSeries = finitePctValues.length > 0 && finitePctValues.every((value) => Math.abs(value) < 0.0001);
  if (nearZeroSeries && Number.isFinite(fallbackChange) && Math.abs(fallbackChange) >= 0.0001) {
    pctValues = series.values.map((value) => (value === null ? null : Number(fallbackChange.toFixed(4))));
  }

  if (!pctValues.some((value) => Number.isFinite(value))) {
    intradayChartInstance = disposeChart(intradayChartInstance);
    renderChartEmpty(chartEl, '暂无有效走势数据，请稍后刷新后再查看。');
    return;
  }

  const sparseSeries = false;
  const chartSeries = pctValues;

  intradayChartInstance = ensureChartInstance(intradayChartInstance, chartEl);
  intradayChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const point = Array.isArray(params) ? params[0] : params;
        if (!point) return '';
        const label = point.axisValue ?? point.name ?? series.labels?.[point.dataIndex] ?? '';
        if (point.value === null || point.value === undefined || point.value === '-') {
          return `${label}<br/>估算涨跌幅：-`;
        }
        return `${label}<br/>估算涨跌幅：${Number(point.value).toFixed(2)}%`;
      }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: series.labels,
      boundaryGap: false,
      max: series.currentIdx,
      axisLabel: {
        interval: 9,
        showMinLabel: true,
        showMaxLabel: true,
        hideOverlap: false,
        formatter: formatIntradayAxisLabel
      }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: (value) => `${Number(value).toFixed(2)}%` }
    },
    series: [{
      data: chartSeries,
      type: 'line',
      smooth: false,
      showSymbol: false,
      connectNulls: true,
      symbolSize: 4,
      itemStyle: { color: '#e5484d' },
      lineStyle: { width: 2, color: '#e5484d' }
    }]
  }, true);
};

const normalizeHistoryChartPayload = (payload) => {
  if (payload && (payload.history || payload.comparison || payload.transactions)) {
    return payload;
  }
  return { history: payload, comparison: null, transactions: [] };
};

const parseNumber = (value) => {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : NaN;
};

const buildFundReturnSeries = (rows) => {
  if (!Array.isArray(rows) || rows.length === 0) return [];
  const base = parseNumber(rows[0]?.value);
  if (!Number.isFinite(base) || base <= 0) return [];
  return rows.map((row) => ({
    date: row.date,
    value: Number((((parseNumber(row.value) - base) / base) * 100).toFixed(2)),
  })).filter((row) => row.date && Number.isFinite(row.value));
};

const normalizeTradeType = (type) => String(type || '').toUpperCase();

const isBuyTrade = (item) => ['BUY', 'SIP_BUY', 'CONVERT_IN'].includes(normalizeTradeType(item?.type));

const isSellTrade = (item) => ['SELL', 'CONVERT_OUT'].includes(normalizeTradeType(item?.type));

const tradeDateOf = (item) => String(
  item?.status === 'PENDING'
    ? (item?.nav_date || item?.trade_date || item?.submitted_date || '')
    : (item?.nav_date || item?.trade_date || item?.submitted_date || '')
).slice(0, 10);

const formatTradeAmount = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return '-';
  return `CNY ${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const buildTradePoints = (transactions, valueByDate, type) => {
  const rows = [];
  (transactions || []).forEach((item) => {
    const isTarget = type === 'buy' ? isBuyTrade(item) : isSellTrade(item);
    if (!isTarget) return;
    const date = tradeDateOf(item);
    const value = valueByDate.get(date);
    if (!date || !Number.isFinite(value)) return;
    rows.push({
      value: [date, value],
      transaction: item,
      pending: item?.status === 'PENDING',
    });
  });
  return rows;
};

const tradeTooltip = (point) => {
  const tx = point?.data?.transaction || {};
  const label = isSellTrade(tx) ? '卖出' : (tx.is_dca ? '定投' : '买入');
  const status = tx.status === 'PENDING' ? '待确认' : '已确认';
  const date = tradeDateOf(tx) || point?.axisValue || '-';
  return [
    `${date} ${label} (${status})`,
    `金额：${formatTradeAmount(tx.amount)}`,
    `净值：${Number.isFinite(parseNumber(tx.nav)) ? parseNumber(tx.nav).toFixed(4) : '-'}`,
    `份额：${Number.isFinite(parseNumber(tx.shares)) ? parseNumber(tx.shares).toFixed(2) : '-'}`,
  ].join('<br/>');
};

export const renderHistoryChart = (rawPayload) => {
  const chartEl = document.getElementById('historyChart');
  if (!chartEl) return;

  const payload = normalizeHistoryChartPayload(rawPayload);
  const rows = payload.history && Array.isArray(payload.history.data) ? payload.history.data : [];
  const comparisonSeries = payload.comparison && Array.isArray(payload.comparison.series) ? payload.comparison.series : [];
  const fundSeries = comparisonSeries.find((item) => item.key === 'fund')?.data || buildFundReturnSeries(rows);
  if (fundSeries.length === 0) {
    historyChartInstance = disposeChart(historyChartInstance);
    renderChartEmpty(chartEl, '暂无业绩走势数据。');
    return;
  }

  const labels = fundSeries.map((row) => row.date);
  const valueByDate = new Map(fundSeries.map((row) => [row.date, row.value]));
  const comparisonColors = ['#0ea5e9', '#8b949e', '#f97316', '#64748b'];
  const lineSeries = [{
    name: '本基金',
    data: fundSeries.map((row) => [row.date, row.value]),
    type: 'line',
    smooth: true,
    showSymbol: false,
    connectNulls: true,
    lineStyle: { width: 2.4, color: '#ef4444' },
    itemStyle: { color: '#ef4444' },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: 'rgba(239, 68, 68, 0.14)' },
          { offset: 1, color: 'rgba(239, 68, 68, 0)' },
        ],
      },
    },
  }];

  comparisonSeries
    .filter((item) => item.key !== 'fund' && Array.isArray(item.data) && item.data.length)
    .forEach((item, index) => {
      const points = new Map(item.data.map((row) => [row.date, row.value]));
      lineSeries.push({
        name: item.name || `对比${index + 1}`,
        data: labels.map((date) => [date, points.has(date) ? points.get(date) : null]),
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: true,
        lineStyle: { width: 1.6, color: comparisonColors[index % comparisonColors.length] },
        itemStyle: { color: comparisonColors[index % comparisonColors.length] },
      });
    });

  const buyPoints = buildTradePoints(payload.transactions, valueByDate, 'buy');
  const sellPoints = buildTradePoints(payload.transactions, valueByDate, 'sell');

  clearChartHost(historyChartInstance, chartEl);
  historyChartInstance = ensureChartInstance(historyChartInstance, chartEl);
  historyChartInstance.setOption({
    legend: {
      data: lineSeries.map((item) => item.name),
      top: 0,
      right: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#64748b', fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      appendToBody: true,
      position: (point, params, dom, rect, size) => {
        const viewWidth = size.viewSize[0];
        const viewHeight = size.viewSize[1];
        const boxWidth = size.contentSize[0];
        const boxHeight = size.contentSize[1];
        let x = point[0] + 12;
        let y = point[1] + 12;
        if (x + boxWidth > viewWidth) x = point[0] - boxWidth - 12;
        if (y + boxHeight > viewHeight) y = Math.max(point[1] - boxHeight - 12, 8);
        return [Math.max(x, 8), Math.max(y, 8)];
      },
      formatter: (params) => {
        if (!params || params.length === 0) return '';
        const lines = [`${params[0].axisValue}`];
        params.forEach((point) => {
          if (point.seriesType === 'scatter') {
            lines.push(tradeTooltip(point));
            return;
          }
          const value = Array.isArray(point.value) ? point.value[1] : point.value;
          if (Number.isFinite(parseNumber(value))) {
            lines.push(`${point.marker}${point.seriesName}：${parseNumber(value).toFixed(2)}%`);
          }
        });
        return lines.join('<br/>');
      }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 34, containLabel: true },
    xAxis: { type: 'category', data: labels, boundaryGap: false },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.16)' } },
    },
    series: [
      ...lineSeries,
      {
        name: '买入',
        type: 'scatter',
        legendHoverLink: false,
        data: buyPoints,
        symbolSize: (value, params) => params?.data?.pending ? 7 : 8,
        itemStyle: {
          color: (params) => params?.data?.pending ? 'rgba(239, 68, 68, 0.32)' : '#ef4444',
          borderColor: '#fff',
          borderWidth: 1.5,
        },
        z: 8,
      },
      {
        name: '卖出',
        type: 'scatter',
        legendHoverLink: false,
        data: sellPoints,
        symbolSize: (value, params) => params?.data?.pending ? 7 : 8,
        itemStyle: {
          color: (params) => params?.data?.pending ? 'rgba(22, 163, 74, 0.32)' : '#16a34a',
          borderColor: '#fff',
          borderWidth: 1.5,
        },
        z: 8,
      },
    ],
  }, true);
};

export const renderPortfolioProfitChart = (chartData) => {
  const chartEl = document.getElementById('portfolioProfitChart');
  if (!chartEl) return;

  const labels = Array.isArray(chartData?.labels) ? chartData.labels : [];
  const values = Array.isArray(chartData?.values) ? chartData.values : [];
  const currentIdx = Number.isFinite(chartData?.currentIdx) ? chartData.currentIdx : labels.length - 1;
  const finiteValues = values.filter((value) => Number.isFinite(value));
  if (!labels.length || !finiteValues.length) {
    portfolioProfitChartInstance = disposeChart(portfolioProfitChartInstance);
    chartEl.innerHTML = '<div class="chart-empty-state">暂无可用的当日收益走势。</div>';
    return;
  }

  clearChartHost(portfolioProfitChartInstance, chartEl);
  portfolioProfitChartInstance = ensureChartInstance(portfolioProfitChartInstance, chartEl);
  const currentValue = finiteValues[finiteValues.length - 1];
  const positive = currentValue >= 0;
  const lineColor = positive ? '#e5484d' : '#16a34a';
  const areaStart = positive ? 'rgba(229, 72, 77, 0.18)' : 'rgba(22, 163, 74, 0.18)';
  const areaEnd = positive ? 'rgba(229, 72, 77, 0.02)' : 'rgba(22, 163, 74, 0.02)';
  const minValue = Math.min(...finiteValues);
  const maxValue = Math.max(...finiteValues);
  const boundPadding = Math.max((maxValue - minValue) * 0.18, 8);
  const mobile = isMobileViewport();
  const mobileTicks = new Set(['09:30', '11:30', '15:00']);

  portfolioProfitChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        if (!params || params.length === 0) return '';
        const point = params[0];
        if (!Number.isFinite(point.value)) {
          return `${point.axisValue}<br/>当日收益：-`;
        }
        return `${point.axisValue}<br/>当日收益：￥${Number(point.value).toLocaleString('zh-CN', {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2
        })}`;
      }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: false,
      max: currentIdx,
      axisLabel: {
        interval: mobile ? 0 : 9,
        showMinLabel: true,
        showMaxLabel: true,
        hideOverlap: mobile,
        fontSize: mobile ? 10 : 12,
        margin: mobile ? 10 : 12,
        formatter: (value) => {
          if (!mobile) return formatIntradayAxisLabel(value);
          return mobileTicks.has(value) ? formatIntradayAxisLabel(value) : '';
        }
      },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      scale: true,
      min: Number((minValue - boundPadding).toFixed(2)),
      max: Number((maxValue + boundPadding).toFixed(2)),
      axisLabel: {
        formatter: (value) => `￥${Number(value).toFixed(0)}`
      },
      splitLine: {
        lineStyle: {
          color: 'rgba(148, 163, 184, 0.12)'
        }
      }
    },
    series: [{
      data: values,
      type: 'line',
      smooth: 0.22,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 2.5, color: lineColor },
      itemStyle: { color: lineColor },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: areaStart },
          { offset: 1, color: areaEnd }
        ])
      },
      markLine: {
        silent: true,
        symbol: 'none',
        label: { show: false },
        lineStyle: {
          color: 'rgba(148, 163, 184, 0.32)',
          type: 'dashed'
        },
        data: [{ yAxis: 0 }]
      }
    }]
  }, true);
};

export const resizeDetailCharts = () => {
  if (intradayChartInstance && (!intradayChartInstance.isDisposed || !intradayChartInstance.isDisposed())) {
    intradayChartInstance.resize();
  }
  if (historyChartInstance && (!historyChartInstance.isDisposed || !historyChartInstance.isDisposed())) {
    historyChartInstance.resize();
  }
  if (portfolioProfitChartInstance && (!portfolioProfitChartInstance.isDisposed || !portfolioProfitChartInstance.isDisposed())) {
    portfolioProfitChartInstance.resize();
  }
};

export const disposeCharts = () => {
  intradayChartInstance = disposeChart(intradayChartInstance);
  historyChartInstance = disposeChart(historyChartInstance);
  portfolioProfitChartInstance = disposeChart(portfolioProfitChartInstance);
};
