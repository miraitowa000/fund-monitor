import { loadFundDetail as fetchFundDetail } from './api.js';
import { renderHistoryChart, renderIntradayChart, resizeDetailCharts } from './charts.js';
import { EMPTY_DETAIL } from './formatters.js';

const hasDetailData = (data) => {
  const hasBasic = !!(data.basic && (data.basic.name || data.basic.gsz || data.basic.dwjz));
  const hasHistory = !!(data.history?.data && data.history.data.length > 0);
  const hasHoldings = !!(data.holdings?.holdings && data.holdings.holdings.length > 0);
  return hasBasic || hasHistory || hasHoldings;
};

export const createDetailController = ({
  detailFund,
  detailLoading,
  detailError,
  currentFundCode,
  currentFundName,
  detailBasicView,
  funds,
  nextTick,
  hasLoadedAnyDetail,
  pendingFundCode,
}) => {
  const renderDetailVisuals = async () => {
    if (!currentFundCode.value) return;
    await nextTick();
    renderIntradayChart(
      currentFundCode.value,
      detailBasicView?.value || detailFund.value.basic,
      detailFund.value.intraday
    );
    renderHistoryChart(detailFund.value.history);
    resizeDetailCharts();
  };

  const loadDetail = async (code) => {
    detailLoading.value = true;
    detailError.value = '';
    try {
      const hit = (funds.value || []).find((fund) => fund.code === code);
      const data = await fetchFundDetail(code);
      if (hasDetailData(data)) {
        currentFundCode.value = code;
        currentFundName.value = hit?.name || data.basic?.name || '';
        detailFund.value = data;
        hasLoadedAnyDetail.value = true;
        pendingFundCode.value = '';
        await renderDetailVisuals();
        return;
      }
      detailError.value = '获取基金详情失败，请稍后重试。';
    } catch (error) {
      console.error('详情获取失败:', error);
      detailError.value = '网络异常，请检查连接后重试。';
    } finally {
      if (pendingFundCode.value === code) {
        pendingFundCode.value = '';
      }
      detailLoading.value = false;
    }
  };

  const showDetail = async (code) => {
    pendingFundCode.value = code;
    detailError.value = '';
    if (!hasLoadedAnyDetail.value) detailFund.value = EMPTY_DETAIL();
    await loadDetail(code);
  };

  return {
    showDetail,
    loadFundDetail: loadDetail,
    renderDetailVisuals
  };
};
