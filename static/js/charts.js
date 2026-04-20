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

const disposeChart = (chart) => {
  if (chart) chart.dispose();
  return null;
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

  // During the lunch break, keep the 11:30 estimate flat until 13:00
  // instead of dropping the chart to an implicit zero/null region.
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
  intradayChartInstance = disposeChart(intradayChartInstance);
  if (!series) {
    chartEl.innerHTML = '<div class="text-muted text-center py-5">暂无当日走势数据，稍后刷新后再查看。</div>';
    return;
  }

  chartEl.innerHTML = '';
  const base = basic ? parseFloat(basic.dwjz) : NaN;
  const fallbackChange = basic ? parseFloat(basic.confirmed_change || basic.gszzl) : NaN;
  let pctValues = series.values.map((value) => {
    if (value === null || !Number.isFinite(value) || !Number.isFinite(base) || base === 0) return null;
    return Number((((value - base) / base) * 100).toFixed(4));
  });

  // For overseas/QDII funds that do not provide intra-day snapshots,
  // keep a flat line based on the current list/detail change percentage.
  if (!pctValues.some((value) => Number.isFinite(value))) {
    if (Number.isFinite(fallbackChange)) {
      pctValues = series.values.map((value) => (value === null ? null : Number(fallbackChange.toFixed(4))));
    }
  }

  const finitePctValues = pctValues.filter((value) => Number.isFinite(value));
  const nearZeroSeries = finitePctValues.length > 0 && finitePctValues.every((value) => Math.abs(value) < 0.0001);
  if (nearZeroSeries && Number.isFinite(fallbackChange) && Math.abs(fallbackChange) >= 0.0001) {
    pctValues = series.values.map((value) => (value === null ? null : Number(fallbackChange.toFixed(4))));
  }

  if (!pctValues.some((value) => Number.isFinite(value))) {
    intradayChartInstance = disposeChart(intradayChartInstance);
    chartEl.innerHTML = '<div class="text-muted text-center py-5">鏆傛棤褰撴棩璧板娍鏁版嵁锛岀◢鍚庡埛鏂板悗鍐嶆煡鐪嬨€?/div>';
    return;
  }

  intradayChartInstance = echarts.init(chartEl);
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
  });
};

export const renderHistoryChart = (historyData) => {
  const chartEl = document.getElementById('historyChart');
  if (!chartEl) return;

  const rows = historyData && Array.isArray(historyData.data) ? historyData.data : [];
  if (rows.length === 0) {
    historyChartInstance = disposeChart(historyChartInstance);
    chartEl.innerHTML = '<div class="text-muted text-center py-4">暂无近 30 天历史净值数据。</div>';
    return;
  }

  if (!historyChartInstance) {
    chartEl.innerHTML = '';
    historyChartInstance = echarts.init(chartEl);
  }

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

export const resizeDetailCharts = () => {
  if (intradayChartInstance) intradayChartInstance.resize();
  if (historyChartInstance) historyChartInstance.resize();
};

export const disposeCharts = () => {
  intradayChartInstance = disposeChart(intradayChartInstance);
  historyChartInstance = disposeChart(historyChartInstance);
};
