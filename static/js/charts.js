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

  if (known.length === 0) return null;

  const values = new Array(labels.length).fill(null);
  known.forEach((point) => {
    values[point.idx] = Number(point.value.toFixed(4));
  });

  const currentIdx = minuteToIndex(formatMinuteNow());
  let lastKnown = null;
  for (let i = 0; i <= currentIdx; i += 1) {
    if (Number.isFinite(values[i])) lastKnown = values[i];
    else if (lastKnown !== null) values[i] = lastKnown;
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
    chartEl.innerHTML = '<div class="text-muted text-center py-5">暂无当日走势数据，先刷新几次后再查看详情</div>';
    return;
  }

  chartEl.innerHTML = '';
  const base = basic ? parseFloat(basic.dwjz) : NaN;
  const pctValues = series.values.map((value) => {
    if (value === null || !Number.isFinite(value) || !Number.isFinite(base) || base === 0) return null;
    return Number((((value - base) / base) * 100).toFixed(4));
  });

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
      showSymbol: true,
      symbolSize: 5,
      connectNulls: false,
      lineStyle: { width: 2, color: '#dc3545' }
    }]
  });
};

export const renderHistoryChart = (historyData) => {
  const chartEl = document.getElementById('historyChart');
  if (!chartEl) return;

  const rows = historyData && Array.isArray(historyData.data) ? historyData.data : [];
  historyChartInstance = disposeChart(historyChartInstance);
  if (rows.length === 0) {
    chartEl.innerHTML = '<div class="text-muted text-center py-4">暂无近 30 天历史净值数据</div>';
    return;
  }

  chartEl.innerHTML = '';
  historyChartInstance = echarts.init(chartEl);
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
      lineStyle: { width: 2, color: '#0d6efd' }
    }]
  });
};

export const resizeDetailCharts = () => {
  if (intradayChartInstance) intradayChartInstance.resize();
  if (historyChartInstance) historyChartInstance.resize();
};

export const disposeCharts = () => {
  intradayChartInstance = disposeChart(intradayChartInstance);
  historyChartInstance = disposeChart(historyChartInstance);
};
