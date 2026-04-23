import {
  TRADING_MINUTES,
  formatMinuteNow,
  getTodayDate,
  minuteToIndex,
  normalizeToStepMinute,
  readIntradayCache,
} from './cache.js';

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

const LUNCH_START_INDEX = minuteToIndex('11:33');
const LUNCH_END_INDEX = minuteToIndex('12:57');

const isLunchBreak = (minute) => {
  const [h, m] = String(minute || '').split(':').map((v) => parseInt(v, 10));
  if (!Number.isFinite(h) || !Number.isFinite(m)) return false;
  const total = h * 60 + m;
  return total > 690 && total < 780;
};

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
    const values = labels.map(() => Number(fallbackValue.toFixed(4)));
    const currentIdx = Math.max(minuteToIndex(formatMinuteNow()), 0);
    for (let i = currentIdx + 1; i < values.length; i += 1) {
      values[i] = null;
    }
    return { labels, values, currentIdx };
  }

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

  const lunchAnchor = values[LUNCH_START_INDEX - 1] ?? values[LUNCH_START_INDEX] ?? lastKnown;
  if (Number.isFinite(lunchAnchor)) {
    for (let i = LUNCH_START_INDEX; i <= LUNCH_END_INDEX; i += 1) {
      values[i] = lunchAnchor;
    }
  }

  if (isLunchBreak(nowMinute)) {
    currentIdx = Math.max(currentIdx, LUNCH_END_INDEX);
  }

  for (let i = currentIdx + 1; i < values.length; i += 1) {
    values[i] = null;
  }

  return { labels, values, currentIdx };
};

export const renderIntradayChart = (fundCode, basic, intradayData) => {
  const chartEl = document.getElementById('intradayChart');
  if (!chartEl) return;

  const series = buildIntradaySeries(fundCode, intradayData);
  if (!series) {
    intradayChartInstance = disposeChart(intradayChartInstance);
    chartEl.innerHTML = '<div class="text-muted text-center py-5">暂无当日走势数据，稍后刷新后再查看。</div>';
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
    chartEl.innerHTML = '<div class="text-muted text-center py-5">暂无有效走势数据，请稍后刷新后再查看。</div>';
    return;
  }

  intradayChartInstance = ensureChartInstance(intradayChartInstance, chartEl);
  intradayChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        if (!params || params.length === 0) return '';
        const point = params[0];
        if (point.value === null || point.value === undefined || point.value === '-') {
          return `${point.axisValue}<br/>估算涨跌幅：-`;
        }
        return `${point.axisValue}<br/>估算涨跌幅：${Number(point.value).toFixed(2)}%`;
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
        formatter: (value) => value
      }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { formatter: (value) => `${Number(value).toFixed(2)}%` }
    },
    series: [{
      data: pctValues,
      type: 'line',
      smooth: false,
      showSymbol: false,
      connectNulls: false,
      lineStyle: { width: 2, color: '#e5484d' }
    }]
  }, true);
};

export const renderHistoryChart = (historyData) => {
  const chartEl = document.getElementById('historyChart');
  if (!chartEl) return;

  const rows = historyData && Array.isArray(historyData.data) ? historyData.data : [];
  if (rows.length === 0) {
    historyChartInstance = disposeChart(historyChartInstance);
    chartEl.innerHTML = '<div class="text-muted text-center py-4">暂无历史净值数据。</div>';
    return;
  }

  clearChartHost(historyChartInstance, chartEl);
  historyChartInstance = ensureChartInstance(historyChartInstance, chartEl);
  historyChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        if (!params || params.length === 0) return '';
        const point = params[0];
        const row = rows[point.dataIndex] || {};
        const change = parseFloat(row.change);
        const changeText = Number.isFinite(change) ? `${change.toFixed(2)}%` : '-';
        return `${point.axisValue}<br/>单位净值：${Number(point.value).toFixed(4)}<br/>日涨跌幅：${changeText}`;
      }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: { type: 'category', data: rows.map((row) => row.date), boundaryGap: false },
    yAxis: { type: 'value', scale: true },
    series: [{
      data: rows.map((row) => Number(parseFloat(row.value || 0).toFixed(4))),
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2, color: '#1677ff' }
    }]
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
          if (!mobile) return value;
          return mobileTicks.has(value) ? value : '';
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
