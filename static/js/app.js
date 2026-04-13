import { fetchFundsRaw, fetchIndexesRaw } from './api.js';
import { disposeCharts } from './charts.js';
import { createDetailController } from './detail-modal.js';
import {
  EMPTY_DETAIL,
  formatChange,
  getColorClass,
  getIndexCardClass,
  getMarketStatus,
  getSortIcon,
  loadSavedCodes,
  saveCodes,
} from './formatters.js';
import { createRefreshTimers } from './timers.js';

const { createApp, ref, onMounted, onUnmounted, watch, computed, nextTick } = window.Vue;

createApp({
  setup() {
    const codeInput = ref('');
    const savedCodes = ref(loadSavedCodes());
    const funds = ref([]);
    const indexes = ref([]);
    const loading = ref(false);
    const lastUpdateTime = ref('-');
    const now = ref(new Date());
    const autoRefresh = ref(true);
    const sortDir = ref('none');
    const detailFund = ref(EMPTY_DETAIL());
    const detailLoading = ref(false);
    const detailError = ref('');
    const currentFundCode = ref('');
    const currentFundName = ref('');
    let clockTimer = null;

    const historyList = computed(() => {
      const data = detailFund.value.history?.data || [];
      return [...data].reverse().map((item) => ({
        date: item.date,
        value: (item.value || 0).toFixed(4),
        change: item.change || '0.00'
      }));
    });

    const sortIcon = computed(() => getSortIcon(sortDir.value));

    const marketNowText = computed(() => {
      const hh = String(now.value.getHours()).padStart(2, '0');
      const mm = String(now.value.getMinutes()).padStart(2, '0');
      const ss = String(now.value.getSeconds()).padStart(2, '0');
      return `${hh}:${mm}:${ss}`;
    });

    const marketStatus = computed(() => getMarketStatus(now.value));

    const sortedFunds = computed(() => {
      if (!Array.isArray(funds.value) || funds.value.length === 0) return [];
      if (sortDir.value === 'none') return funds.value.slice();
      return funds.value.slice().sort((a, b) => {
        const av = parseFloat(a.gszzl || '0');
        const bv = parseFloat(b.gszzl || '0');
        return sortDir.value === 'asc' ? av - bv : bv - av;
      });
    });

    const setSavedCodes = (codes) => {
      savedCodes.value = codes;
      saveCodes(codes);
    };

    const toggleSort = () => {
      if (sortDir.value === 'none') sortDir.value = 'desc';
      else if (sortDir.value === 'desc') sortDir.value = 'asc';
      else sortDir.value = 'none';
    };

    const fetchFunds = async () => {
      loading.value = true;
      try {
        funds.value = await fetchFundsRaw(savedCodes.value);
        lastUpdateTime.value = new Date().toLocaleTimeString();
      } finally {
        loading.value = false;
      }
    };

    const fetchIndexes = async () => {
      indexes.value = await fetchIndexesRaw();
    };

    const fetchData = async () => {
      loading.value = true;
      try {
        const [fundRes, idxRes] = await Promise.all([
          fetchFundsRaw(savedCodes.value),
          fetchIndexesRaw()
        ]);
        funds.value = fundRes;
        indexes.value = idxRes;
        lastUpdateTime.value = new Date().toLocaleTimeString();
      } finally {
        loading.value = false;
      }
    };

    const { showDetail, loadFundDetail } = createDetailController({
      detailFund,
      detailLoading,
      detailError,
      currentFundCode,
      currentFundName,
      funds,
      nextTick
    });

    const addFunds = () => {
      if (!codeInput.value) return;
      const incoming = codeInput.value.split(/[,，\s]+/).filter((code) => code.trim());
      const nextCodes = savedCodes.value.slice();
      let added = false;

      incoming.forEach((code) => {
        if (!nextCodes.includes(code)) {
          nextCodes.push(code);
          added = true;
        }
      });

      if (!added) {
        alert('输入的基金代码已存在或无效');
        return;
      }

      setSavedCodes(nextCodes);
      codeInput.value = '';
      fetchData();
    };

    const removeFund = (code) => {
      if (!confirm(`确定不再关注基金 ${code} 吗？`)) return;
      setSavedCodes(savedCodes.value.filter((item) => item !== code));
      fetchData();
    };

    const clearAll = () => {
      if (!confirm('确定清空所有关注基金吗？')) return;
      setSavedCodes([]);
      funds.value = [];
    };

    const timers = createRefreshTimers({
      getStatusText: () => marketStatus.value.text,
      fetchFunds,
      fetchIndexes
    });

    const startClockTimer = () => {
      if (clockTimer) clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        now.value = new Date();
      }, 1000);
    };

    const stopClockTimer = () => {
      if (clockTimer) clearInterval(clockTimer);
      clockTimer = null;
    };

    watch(autoRefresh, (enabled) => {
      if (enabled) timers.start();
      else timers.stop();
    });

    onMounted(() => {
      fetchData();
      startClockTimer();
      if (autoRefresh.value) timers.start();
    });

    onUnmounted(() => {
      timers.stop();
      stopClockTimer();
      disposeCharts();
    });

    return {
      codeInput,
      savedCodes,
      funds,
      indexes,
      loading,
      lastUpdateTime,
      marketNowText,
      marketStatus,
      autoRefresh,
      sortDir,
      sortIcon,
      sortedFunds,
      detailFund,
      detailLoading,
      detailError,
      currentFundCode,
      currentFundName,
      historyList,
      toggleSort,
      addFunds,
      removeFund,
      clearAll,
      fetchData,
      formatChange,
      getColorClass,
      getIndexCardClass,
      showDetail,
      loadFundDetail
    };
  }
}).mount('#app');
