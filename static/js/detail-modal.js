import { loadFundDetail as fetchFundDetail } from './api.js';
import { renderHistoryChart, renderIntradayChart, resizeDetailCharts } from './charts.js';
import { EMPTY_DETAIL } from './formatters.js';

let modalInstance = null;

const hasDetailData = (data) => {
  const hasBasic = !!(data.basic && (data.basic.name || data.basic.gsz || data.basic.dwjz));
  const hasHistory = !!(data.history?.data && data.history.data.length > 0);
  const hasHoldings = !!(data.holdings?.holdings && data.holdings.holdings.length > 0);
  return hasBasic || hasHistory || hasHoldings;
};

export const createDetailController = ({ detailFund, detailLoading, detailError, currentFundCode, currentFundName, funds, nextTick }) => {
  const renderCharts = () => {
    if (!currentFundCode.value || !detailFund.value?.basic) return;
    renderIntradayChart(currentFundCode.value, detailFund.value.basic, detailFund.value.intraday);
    renderHistoryChart(detailFund.value.history);
    resizeDetailCharts();
  };

  const ensureModal = () => {
    if (modalInstance) return modalInstance;
    const modalEl = document.getElementById('detailModal');
    modalInstance = new window.bootstrap.Modal(modalEl);
    modalEl.addEventListener('shown.bs.modal', () => {
      setTimeout(renderCharts, 0);
    });
    modalEl.addEventListener('shown.bs.tab', (event) => {
      const target = event.target?.getAttribute('data-bs-target');
      if (target === '#tab-intraday') {
        renderIntradayChart(currentFundCode.value, detailFund.value.basic, detailFund.value.intraday);
        resizeDetailCharts();
      } else if (target === '#tab-history') {
        renderHistoryChart(detailFund.value.history);
        resizeDetailCharts();
      }
    });
    return modalInstance;
  };

  const loadDetail = async (code) => {
    detailLoading.value = true;
    detailError.value = '';
    try {
      const data = await fetchFundDetail(code);
      if (hasDetailData(data)) {
        detailFund.value = data;
        await nextTick();
        setTimeout(renderCharts, 0);
        return;
      }
      detailError.value = '获取基金详情失败，请稍后重试';
    } catch (error) {
      console.error('详情获取失败:', error);
      detailError.value = '网络错误，请检查连接';
    } finally {
      detailLoading.value = false;
    }
  };

  const showDetail = async (code) => {
    currentFundCode.value = code;
    const hit = (funds.value || []).find((fund) => fund.code === code);
    currentFundName.value = hit?.name || '';
    detailError.value = '';
    detailFund.value = EMPTY_DETAIL();

    ensureModal().show();
    const intradayTabBtn = document.getElementById('tab-intraday-btn');
    if (intradayTabBtn) {
      window.bootstrap.Tab.getOrCreateInstance(intradayTabBtn).show();
    }
    await loadDetail(code);
  };

  return {
    showDetail,
    loadFundDetail: loadDetail,
  };
};
