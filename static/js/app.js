import {
  bootstrapUserFunds,
  createFundGroup,
  deleteFundGroup,
  deleteUserFund,
  fetchFundsRaw,
  fetchIndexesRaw,
  fetchUserFundsMeta,
  loadFundHistory,
  moveUserFundGroup,
  renameFundGroup,
  saveUserFund,
} from './api.js';
import { disposeCharts, renderHistoryChart, resizeDetailCharts } from './charts.js';
import { createDetailController } from './detail-modal.js';
import {
  EMPTY_DETAIL,
  clearSavedCodes,
  formatChange,
  getColorClass,
  getIndexCardClass,
  getMarketStatus,
  getSortIcon,
  loadClientId,
  loadSavedCodes,
} from './formatters.js';
import { createRefreshTimers } from './timers.js';

const THEME_STORAGE_KEY = 'fundMonitorTheme';
const RELEASE_NOTICE_STORAGE_KEY = 'fundMonitorReleaseNoticeSeen';
const RELEASE_NOTICE_VERSION = 'release-2026-04-20-ui-upgrade';
const RELEASE_NOTICE_ITEMS = [
  { id: '1', text: '新增分组管理功能，支持基金分组、分组筛选和基金快速移动分组' },
  { id: '2', text: '优化页面整体布局、详情联动区和移动端交互，支持浅色 / 深色主题切换' },
  { id: '3', text: '修复分组切换、详情刷新、历史净值查询和 QDII 基金走势图显示等问题' },
  { id: '4', text: '后续计划：继续补充持仓成本、持仓市值、今日收益、累计收益和交易记录等功能' }
];
const { createApp, ref, onMounted, onUnmounted, computed, nextTick } = window.Vue;

const app = createApp({
  setup() {
    const clientId = loadClientId();
    const codeInput = ref('');
    const selectedGroupId = ref('');
    const newGroupName = ref('');
    const savedCodes = ref([]);
    const userFunds = ref([]);
    const fundGroups = ref([]);
    const activeGroupId = ref('all');
    const funds = ref([]);
    const indexes = ref([]);
    const loading = ref(false);
    const lastUpdateTime = ref('-');
    const now = ref(new Date());
    const sortDir = ref('none');
    const detailFund = ref(EMPTY_DETAIL());
    const detailLoading = ref(false);
    const detailError = ref('');
    const currentFundCode = ref('');
    const currentFundName = ref('');
    const renameGroupName = ref('');
    const editingFundCode = ref('');
    const groupActionError = ref('');
    const deletingGroup = ref(false);
    const renamingGroup = ref(false);
    const addingGroupInline = ref(false);
    const theme = ref('light');
    const detailTab = ref('overview');
    const hasLoadedAnyDetail = ref(false);
    const pendingFundCode = ref('');
    const historyRangeDays = ref(30);
    const historyLoading = ref(false);
    const historyData = ref({ success: false, data: [] });
    const mobileDetailOpen = ref(false);
    const releaseNoticeOpen = ref(false);
    let clockTimer = null;
    let renameGroupModal = null;
    let deleteGroupModal = null;
    let resizeHandler = null;

    const parseNumber = (val) => {
      const n = parseFloat(val);
      return Number.isFinite(n) ? n : NaN;
    };

    const formatHoldingChange = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `${formatChange(n, 2)}%`;
    };

    const isMobileViewport = () => window.matchMedia('(max-width: 860px)').matches;

    const syncBodyDetailState = (open) => {
      document.body.classList.toggle('detail-modal-open', Boolean(open));
    };

    const openMobileDetail = () => {
      if (!isMobileViewport()) return;
      mobileDetailOpen.value = true;
      syncBodyDetailState(true);
    };

    const closeMobileDetail = () => {
      mobileDetailOpen.value = false;
      syncBodyDetailState(false);
    };

    const applyTheme = (value) => {
      theme.value = value === 'dark' ? 'dark' : 'light';
      document.body.dataset.theme = theme.value;
      try {
        localStorage.setItem(THEME_STORAGE_KEY, theme.value);
      } catch {
        // ignore localStorage failures
      }
    };

    const initTheme = () => {
      try {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        applyTheme(saved || 'light');
      } catch {
        applyTheme('light');
      }
    };

    const toggleTheme = () => {
      applyTheme(theme.value === 'dark' ? 'light' : 'dark');
      nextTick(() => {
        resizeDetailCharts();
      });
    };

    const checkReleaseNotice = () => {
      try {
        const seenVersion = localStorage.getItem(RELEASE_NOTICE_STORAGE_KEY);
        releaseNoticeOpen.value = seenVersion !== RELEASE_NOTICE_VERSION;
      } catch {
        releaseNoticeOpen.value = true;
      }
    };

    const confirmReleaseNotice = () => {
      try {
        localStorage.setItem(RELEASE_NOTICE_STORAGE_KEY, RELEASE_NOTICE_VERSION);
      } catch {
        // ignore localStorage failures
      }
      releaseNoticeOpen.value = false;
    };

    const fundMetaMap = computed(() => {
      const map = {};
      userFunds.value.forEach((item) => {
        map[item.code] = item;
      });
      return map;
    });

    const tabGroups = computed(() => [
      { id: 'all', name: '全部', count: userFunds.value.length, is_default: false },
      ...fundGroups.value
    ]);

    const activeGroup = computed(() => (
      fundGroups.value.find((group) => String(group.id) === String(activeGroupId.value)) || null
    ));

    const filteredFunds = computed(() => {
      if (!Array.isArray(funds.value)) return [];
      if (activeGroupId.value === 'all') return funds.value.slice();
      return funds.value.filter((fund) => String(fundMetaMap.value[fund.code]?.group_id || '') === String(activeGroupId.value));
    });

    const sortedFunds = computed(() => {
      if (filteredFunds.value.length === 0) return [];
      if (sortDir.value === 'none') return filteredFunds.value.slice();
      return filteredFunds.value.slice().sort((a, b) => {
        const av = parseNumber(a.nav_confirmed ? a.confirmed_change : a.gszzl || '0');
        const bv = parseNumber(b.nav_confirmed ? b.confirmed_change : b.gszzl || '0');
        return sortDir.value === 'asc' ? av - bv : bv - av;
      });
    });

    const fundListRenderKey = computed(() => `${activeGroupId.value}-${sortedFunds.value.map((item) => item.code).join(',')}`);

    const sortIcon = computed(() => getSortIcon(sortDir.value));

    const marketNowText = computed(() => {
      const hh = String(now.value.getHours()).padStart(2, '0');
      const mm = String(now.value.getMinutes()).padStart(2, '0');
      const ss = String(now.value.getSeconds()).padStart(2, '0');
      return `${hh}:${mm}:${ss}`;
    });

    const marketStatus = computed(() => getMarketStatus(now.value));

    const mobileTickerIndexes = computed(() => {
      if (!Array.isArray(indexes.value) || indexes.value.length === 0) return [];
      return indexes.value.concat(indexes.value);
    });

    const monitorSummaryCards = computed(() => {
      const totalFunds = userFunds.value.length;
      const confirmedCount = funds.value.filter((fund) => fund.nav_confirmed).length;
      const upCount = funds.value.filter((fund) => parseNumber(fund.nav_confirmed ? fund.confirmed_change : fund.gszzl) > 0).length;
      const customGroupCount = fundGroups.value.filter((group) => !group.is_default).length;

      return [
        {
          key: 'funds',
          label: '关注基金数',
          value: String(totalFunds),
          meta: totalFunds > 0 ? `当前筛选 ${activeGroupId.value === 'all' ? '全部基金' : (activeGroup.value?.name || '当前分组')}` : '暂无基金',
          valueClass: ''
        },
        {
          key: 'confirmed',
          label: '已确认净值',
          value: String(confirmedCount),
          meta: totalFunds > 0 ? `占比 ${Math.round((confirmedCount / totalFunds) * 100)}%` : '等待数据',
          valueClass: ''
        },
        {
          key: 'up',
          label: '上涨基金',
          value: String(upCount),
          meta: totalFunds > 0 ? `下跌 ${Math.max(totalFunds - upCount, 0)} 只` : '等待数据',
          valueClass: upCount > 0 ? 'up' : ''
        },
        {
          key: 'groups',
          label: '自定义分组',
          value: String(customGroupCount),
          meta: `默认分组 ${fundGroups.value.length > 0 ? 1 : 0} 个`,
          valueClass: ''
        }
      ];
    });

    const selectedFundGroupName = computed(() => (
      fundMetaMap.value[currentFundCode.value]?.group_name || '默认分组'
    ));

    const intradayDataTag = computed(() => {
      const basic = detailBasicView.value || {};
      const sourceTime = basic.nav_confirmed ? (basic.confirmed_date || basic.jzrq) : basic.gztime;
      if (!sourceTime || sourceTime === '-') return '';
      return `基于 ${sourceTime} 数据`;
    });

    const topTenHoldings = computed(() => {
      const list = detailFund.value?.holdings?.holdings || [];
      return list.slice(0, 10);
    });

    const historyPreview = computed(() => {
      const rows = historyData.value?.data || detailFund.value?.history?.data || [];
      return rows.slice().reverse().slice(0, 8);
    });

    const historyRangeOptions = [
      { label: '近一月', days: 30 },
      { label: '近三月', days: 90 },
      { label: '半年', days: 180 },
      { label: '一年', days: 365 }
    ];

    const selectedFundQuote = computed(() => (
      (funds.value || []).find((item) => item.code === currentFundCode.value) || null
    ));

    const activeRowFundCode = computed(() => pendingFundCode.value || currentFundCode.value);

    const detailBasicView = computed(() => {
      const basic = detailFund.value?.basic || {};
      const quote = selectedFundQuote.value || {};
      const displayDate = quote.display_date || basic.display_date || '-';
      const confirmedDate = quote.confirmed_date || basic.confirmed_date || quote.jzrq || basic.jzrq || '-';
      const baseDate = quote.base_date || basic.base_date || quote.jzrq || basic.jzrq || '-';
      return {
        name: basic.name || quote.name || currentFundName.value || '',
        code: currentFundCode.value || basic.code || quote.code || '',
        nav_confirmed: Boolean(
          displayDate !== '-'
            && confirmedDate !== '-'
            && displayDate === confirmedDate
        ),
        confirmed_nav: quote.confirmed_nav || basic.confirmed_nav || '-',
        confirmed_change: quote.confirmed_change || basic.confirmed_change || '-',
        gsz: quote.gsz || basic.gsz || '-',
        gszzl: quote.gszzl || basic.gszzl || '-',
        dwjz: quote.dwjz || basic.dwjz || '-',
        gztime: quote.gztime || basic.gztime || '-',
        jzrq: quote.jzrq || basic.jzrq || '-',
        display_date: displayDate,
        confirmed_date: confirmedDate,
        base_date: baseDate,
        name_source: basic.name ? 'detail' : 'quote'
      };
    });

    const syncSnapshot = (snapshot) => {
      userFunds.value = Array.isArray(snapshot?.funds) ? snapshot.funds : [];
      fundGroups.value = Array.isArray(snapshot?.groups) ? snapshot.groups : [];
      savedCodes.value = userFunds.value.map((item) => item.code);

      if ((!selectedGroupId.value || !fundGroups.value.some((group) => String(group.id) === String(selectedGroupId.value))) && fundGroups.value.length > 0) {
        selectedGroupId.value = String(fundGroups.value[0].id);
      }

      if (!tabGroups.value.some((group) => String(group.id) === String(activeGroupId.value))) {
        activeGroupId.value = 'all';
      }
    };

    const toggleSort = () => {
      if (sortDir.value === 'none') sortDir.value = 'desc';
      else if (sortDir.value === 'desc') sortDir.value = 'asc';
      else sortDir.value = 'none';
    };

    const loadUserState = async () => {
      let snapshot = await fetchUserFundsMeta(clientId);
      const legacyCodes = loadSavedCodes();

      if ((!snapshot.initialized && (!snapshot.funds || snapshot.funds.length === 0)) && legacyCodes.length > 0) {
        await bootstrapUserFunds(clientId, legacyCodes);
        clearSavedCodes();
        snapshot = await fetchUserFundsMeta(clientId);
      }

      syncSnapshot(snapshot);
      return snapshot;
    };

    const attachGroupMeta = (quoteList) => quoteList.map((item) => ({
      ...item,
      group_id: fundMetaMap.value[item.code]?.group_id || null,
      group_name: fundMetaMap.value[item.code]?.group_name || ''
    }));

    const fetchFunds = async () => {
      loading.value = true;
      try {
        const quoteList = await fetchFundsRaw(savedCodes.value);
        funds.value = attachGroupMeta(quoteList);
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
        await loadUserState();
        const [quoteList, idxRes] = await Promise.all([
          fetchFundsRaw(savedCodes.value),
          fetchIndexesRaw()
        ]);
        funds.value = attachGroupMeta(quoteList);
        indexes.value = idxRes;
        lastUpdateTime.value = new Date().toLocaleTimeString();

        if (currentFundCode.value) {
          const hit = quoteList.find((item) => item.code === currentFundCode.value);
          if (hit) {
            currentFundName.value = hit.name || currentFundName.value;
          } else {
            currentFundCode.value = '';
            currentFundName.value = '';
            detailFund.value = EMPTY_DETAIL();
            detailError.value = '';
            detailTab.value = 'overview';
            pendingFundCode.value = '';
          }
        }

        if (!currentFundCode.value && quoteList.length > 0) {
          await showDetailInternal(quoteList[0].code);
        }

        if (currentFundCode.value && historyRangeDays.value === 30) {
          historyData.value = detailFund.value?.history || { success: false, data: [] };
        }

        if (currentFundCode.value && detailTab.value === 'overview' && hasLoadedAnyDetail.value) {
          await renderDetailVisuals();
        }
      } finally {
        loading.value = false;
      }
    };

    const {
      showDetail: showDetailInternal,
      loadFundDetail,
      renderDetailVisuals
    } = createDetailController({
      detailFund,
      detailLoading,
      detailError,
      currentFundCode,
      currentFundName,
      detailBasicView,
      funds,
      nextTick,
      hasLoadedAnyDetail,
      pendingFundCode
    });

    const setDetailTab = async (tab) => {
      detailTab.value = tab;
      if (tab === 'overview') {
        await renderDetailVisuals();
      }
      if (tab === 'history') {
        await ensureHistoryRange(historyRangeDays.value);
        await nextTick();
        renderHistoryChart(historyData.value);
        resizeDetailCharts();
      }
    };

    const showDetail = async (code) => {
      openMobileDetail();
      const targetHistoryRange = detailTab.value === 'history' ? historyRangeDays.value : 30;
      if (!currentFundCode.value) detailTab.value = 'overview';
      await showDetailInternal(code);
      historyRangeDays.value = targetHistoryRange;
      historyData.value = targetHistoryRange === 30
        ? (detailFund.value?.history || { success: false, data: [] })
        : { success: false, data: [] };
      if (detailTab.value === 'overview') {
        await renderDetailVisuals();
      }
      if (detailTab.value === 'history') {
        await ensureHistoryRange(targetHistoryRange);
        await nextTick();
        renderHistoryChart(historyData.value);
        resizeDetailCharts();
      }
    };

    const ensureHistoryRange = async (days) => {
      if (!currentFundCode.value) return;
      if (historyRangeDays.value === days && historyData.value?.data?.length && days !== 30) return;

      historyRangeDays.value = days;
      if (days === 30 && detailFund.value?.history?.data?.length) {
        historyData.value = detailFund.value.history;
        await nextTick();
        renderHistoryChart(historyData.value);
        resizeDetailCharts();
        return;
      }

      historyLoading.value = true;
      try {
        const data = await loadFundHistory(currentFundCode.value, days);
        historyData.value = data && Array.isArray(data.data) ? data : { success: false, data: [] };
        await nextTick();
        renderHistoryChart(historyData.value);
        resizeDetailCharts();
      } finally {
        historyLoading.value = false;
      }
    };

    const addFunds = async () => {
      if (!codeInput.value) return;
      const incoming = codeInput.value.split(/[,\uFF0C\s]+/).filter((code) => code.trim());
      if (incoming.length === 0) return;

      const groupId = selectedGroupId.value || (fundGroups.value[0] ? String(fundGroups.value[0].id) : '');
      const results = await Promise.all(incoming.map((code) => saveUserFund(clientId, code, groupId)));
      const error = results.find((item) => item.error);
      if (error) {
        alert(error.error || '添加基金失败');
        return;
      }

      codeInput.value = '';
      await fetchData();
    };

    const addGroup = async () => {
      if (!newGroupName.value.trim()) return;
      const result = await createFundGroup(clientId, newGroupName.value.trim());
      if (result.error) {
        alert(result.error);
        return;
      }

      newGroupName.value = '';
      addingGroupInline.value = false;
      await loadUserState();
      selectedGroupId.value = String(result.id);
    };

    const openInlineGroupCreate = async () => {
      addingGroupInline.value = true;
      await nextTick();
      const input = document.getElementById('inlineGroupNameInput');
      input?.focus();
    };

    const closeInlineGroupCreate = () => {
      addingGroupInline.value = false;
      newGroupName.value = '';
    };

    const ensureGroupModals = () => {
      if (!window.bootstrap) return;
      if (!renameGroupModal) {
        const el = document.getElementById('renameGroupModal');
        if (el) renameGroupModal = window.bootstrap.Modal.getOrCreateInstance(el);
      }
      if (!deleteGroupModal) {
        const el = document.getElementById('deleteGroupModal');
        if (el) deleteGroupModal = window.bootstrap.Modal.getOrCreateInstance(el);
      }
    };

    const openRenameGroupModal = () => {
      if (!activeGroup.value || activeGroup.value.is_default) return;
      ensureGroupModals();
      renameGroupName.value = activeGroup.value.name;
      groupActionError.value = '';
      renameGroupModal?.show();
    };

    const closeRenameGroupModal = () => {
      groupActionError.value = '';
      renameGroupModal?.hide();
    };

    const confirmRenameGroup = async () => {
      if (!activeGroup.value || activeGroup.value.is_default) return;
      const nextName = renameGroupName.value.trim();
      if (!nextName) {
        groupActionError.value = '分组名称不能为空';
        return;
      }
      renamingGroup.value = true;
      groupActionError.value = '';
      const result = await renameFundGroup(clientId, activeGroup.value.id, nextName);
      if (result.error) {
        groupActionError.value = result.error;
        renamingGroup.value = false;
        return;
      }
      renamingGroup.value = false;
      closeRenameGroupModal();
      await fetchData();
    };

    const openDeleteGroupModal = () => {
      if (!activeGroup.value || activeGroup.value.is_default) return;
      ensureGroupModals();
      groupActionError.value = '';
      deleteGroupModal?.show();
    };

    const closeDeleteGroupModal = () => {
      groupActionError.value = '';
      deleteGroupModal?.hide();
    };

    const confirmDeleteGroup = async () => {
      if (!activeGroup.value || activeGroup.value.is_default) return;
      deletingGroup.value = true;
      groupActionError.value = '';
      const result = await deleteFundGroup(clientId, activeGroup.value.id);
      if (result.error) {
        groupActionError.value = result.error;
        deletingGroup.value = false;
        return;
      }
      deletingGroup.value = false;
      closeDeleteGroupModal();
      activeGroupId.value = 'all';
      await fetchData();
    };

    const changeFundGroup = async (code, groupId) => {
      if (!groupId) return;
      const result = await moveUserFundGroup(clientId, code, groupId);
      if (result.error) {
        alert(result.error);
        return;
      }
      editingFundCode.value = '';
      await fetchData();
      await nextTick();
    };

    const startEditFundGroup = async (code) => {
      editingFundCode.value = String(code);
      await nextTick();
    };

    const stopEditFundGroup = (code) => {
      if (String(editingFundCode.value) !== String(code)) return;
      editingFundCode.value = '';
    };

    const switchGroup = async (groupId) => {
      activeGroupId.value = String(groupId);
      await nextTick();
    };

    const removeFund = async (code) => {
      if (!confirm(`确定不再关注基金 ${code} 吗？`)) return;
      await deleteUserFund(clientId, code);
      if (currentFundCode.value === code) {
        currentFundCode.value = '';
        currentFundName.value = '';
        detailFund.value = EMPTY_DETAIL();
        detailError.value = '';
        detailTab.value = 'overview';
        closeMobileDetail();
      }
      await fetchData();
    };

    const clearAll = async () => {
      if (!confirm('确定清空所有关注基金吗？')) return;
      await Promise.all(savedCodes.value.map((code) => deleteUserFund(clientId, code)));
      await fetchData();
      funds.value = [];
      currentFundCode.value = '';
      currentFundName.value = '';
      detailFund.value = EMPTY_DETAIL();
      detailError.value = '';
      detailTab.value = 'overview';
      closeMobileDetail();
    };

    const timers = createRefreshTimers({ fetchFunds, fetchIndexes });

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

    onMounted(() => {
      initTheme();
      checkReleaseNotice();
      fetchData();
      nextTick(() => {
        ensureGroupModals();
      });
      startClockTimer();
      timers.start();
      resizeHandler = () => {
        resizeDetailCharts();
        if (!isMobileViewport()) {
          closeMobileDetail();
        }
      };
      window.addEventListener('resize', resizeHandler);
    });

    onUnmounted(() => {
      timers.stop();
      stopClockTimer();
      disposeCharts();
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler);
        resizeHandler = null;
      }
      syncBodyDetailState(false);
    });

    return {
      codeInput,
      selectedGroupId,
      newGroupName,
      savedCodes,
      userFunds,
      fundGroups,
      activeGroupId,
      activeGroup,
      tabGroups,
      funds,
      indexes,
      mobileTickerIndexes,
      loading,
      lastUpdateTime,
      marketNowText,
      marketStatus,
      sortDir,
      sortIcon,
      sortedFunds,
      fundMetaMap,
      fundListRenderKey,
      detailFund,
      detailLoading,
      detailError,
      currentFundCode,
      currentFundName,
      renameGroupName,
      editingFundCode,
      groupActionError,
      deletingGroup,
      renamingGroup,
      addingGroupInline,
      theme,
      detailTab,
      hasLoadedAnyDetail,
      pendingFundCode,
      activeRowFundCode,
      historyRangeDays,
      historyRangeOptions,
      historyLoading,
      historyData,
      mobileDetailOpen,
      releaseNoticeOpen,
      releaseNoticeVersion: RELEASE_NOTICE_VERSION,
      releaseNoticeItems: RELEASE_NOTICE_ITEMS,
      monitorSummaryCards,
      selectedFundGroupName,
      intradayDataTag,
      topTenHoldings,
      historyPreview,
      selectedFundQuote,
      detailBasicView,
      toggleTheme,
      confirmReleaseNotice,
      setDetailTab,
      ensureHistoryRange,
      toggleSort,
      addFunds,
      addGroup,
      openInlineGroupCreate,
      closeInlineGroupCreate,
      openRenameGroupModal,
      closeRenameGroupModal,
      confirmRenameGroup,
      openDeleteGroupModal,
      closeDeleteGroupModal,
      confirmDeleteGroup,
      changeFundGroup,
      startEditFundGroup,
      stopEditFundGroup,
      switchGroup,
      removeFund,
      clearAll,
      fetchData,
      formatHoldingChange,
      formatChange,
      getColorClass,
      getIndexCardClass,
      showDetail,
      closeMobileDetail,
      loadFundDetail
    };
  }
});

app.config.compilerOptions.delimiters = ['[[', ']]'];
app.mount('#app');
