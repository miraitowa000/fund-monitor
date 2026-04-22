import {
  bootstrapUserFunds,
  createFundGroup,
  deleteFundGroup,
  deleteUserFund,
  fetchPortfolio,
  fetchFundsRaw,
  fetchIndexesRaw,
  fetchUserFundsMeta,
  loadFundHistory,
  moveUserFundGroup,
  renameFundGroup,
  saveUserFund,
  updateUserFundPosition,
} from './api.js';
import {
  disposeCharts,
  renderHistoryChart,
  renderPortfolioProfitChart,
  resizeDetailCharts
} from './charts.js';
import {
  TRADING_MINUTES,
  formatMinuteNow,
  getTodayDate,
  minuteToIndex,
  normalizeToStepMinute,
  readIntradayCache,
  toMinute,
} from './cache.js';
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
const RELEASE_NOTICE_VERSION = 'release-2026-04-22-profit-upgrade';
const RELEASE_NOTICE_ITEMS = [
  { id: '1', text: '首页收益概览升级，支持查看总持仓市值、当日收益和持有收益。' },
  { id: '2', text: '新增组合当日收益走势图，收益变化更直观。' },
  { id: '3', text: '基金列表新增仓位占比展示，持仓信息更清晰。' },
  { id: '4', text: '编辑持仓、分组管理和删除基金弹窗体验已优化，深色模式同步适配。' }
];

const { createApp, ref, onMounted, onUnmounted, computed, nextTick, watch } = window.Vue;

const LUNCH_START_INDEX = minuteToIndex('11:33');
const LUNCH_END_INDEX = minuteToIndex('12:57');

const isLunchBreakMinute = (minute) => {
  const [h, m] = String(minute || '').split(':').map((v) => parseInt(v, 10));
  if (!Number.isFinite(h) || !Number.isFinite(m)) return false;
  const total = h * 60 + m;
  return total > 690 && total < 780;
};

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
    const portfolioItems = ref([]);
    const portfolioSummary = ref({
      total_holding_amount: 0,
      total_daily_profit: 0,
      total_holding_profit: 0,
      total_holding_profit_rate: 0,
      position_fund_count: 0,
      unpositioned_fund_count: 0,
      nav_source: null,
      updated_at: ''
    });
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
    const historyFundCode = ref('');
    const mobileDetailOpen = ref(false);
    const releaseNoticeOpen = ref(false);
    const positionForm = ref({
      code: '',
      name: '',
      holding_amount: '',
      holding_profit: ''
    });
    const deletingFund = ref(false);
    const fundActionError = ref('');
    const pendingDeleteFund = ref({
      code: '',
      name: ''
    });
    const clearingAllFunds = ref(false);
    const savingPosition = ref(false);
    const positionActionError = ref('');

    let clockTimer = null;
    let renameGroupModal = null;
    let deleteGroupModal = null;
    let positionModal = null;
    let deleteFundModal = null;
    let clearAllModal = null;
    let resizeHandler = null;
    let latestHistoryRequestId = 0;

    const parseNumber = (val) => {
      const n = parseFloat(val);
      return Number.isFinite(n) ? n : NaN;
    };

    const formatHoldingChange = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `${formatChange(n, 2)}%`;
    };

    const formatCurrency = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    };

    const formatPercentText = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `${formatChange(n * 100, 2)}%`;
    };

    const renderPortfolioProfitVisuals = async () => {
      await nextTick();
      renderPortfolioProfitChart(portfolioIntradayChartData.value);
      resizeDetailCharts();
    };

    const renderActiveHistoryChart = async () => {
      await nextTick();
      renderHistoryChart(historyData.value);
      resizeDetailCharts();
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
      } catch {}
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
      } catch {}
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
      if (!Array.isArray(portfolioItems.value)) return [];
      if (activeGroupId.value === 'all') return portfolioItems.value.slice();
      return portfolioItems.value.filter((fund) => String(fund.group_id || '') === String(activeGroupId.value));
    });

    const sortedFunds = computed(() => {
      if (filteredFunds.value.length === 0) return [];
      if (sortDir.value === 'none') return filteredFunds.value.slice();
      return filteredFunds.value.slice().sort((a, b) => {
        const av = parseNumber(a.daily_change_pct || '0');
        const bv = parseNumber(b.daily_change_pct || '0');
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
          label: '已更新净值',
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

    const portfolioSummaryCards = computed(() => ([
      {
        key: 'holding_amount',
        label: activeGroupId.value === 'all' ? '总持仓市值' : '分组持仓市值',
        value: formatCurrency(portfolioSummary.value.total_holding_amount),
        meta: '',
        valueClass: '',
        metaClass: ''
      },
      {
        key: 'daily_profit',
        label: '今日收益',
        value: formatCurrency(portfolioSummary.value.total_daily_profit),
        meta: (
          Number.isFinite(parseNumber(portfolioSummary.value.total_daily_profit))
          && Number.isFinite(parseNumber(portfolioSummary.value.total_holding_amount))
          && parseNumber(portfolioSummary.value.total_holding_amount) > 0
        )
          ? `今日 ${formatPercentText(parseNumber(portfolioSummary.value.total_daily_profit) / parseNumber(portfolioSummary.value.total_holding_amount))}`
          : '',
        valueClass: getColorClass(portfolioSummary.value.total_daily_profit),
        metaClass: (
          Number.isFinite(parseNumber(portfolioSummary.value.total_daily_profit))
          && Number.isFinite(parseNumber(portfolioSummary.value.total_holding_amount))
          && parseNumber(portfolioSummary.value.total_holding_amount) > 0
        )
          ? getColorClass(parseNumber(portfolioSummary.value.total_daily_profit) / parseNumber(portfolioSummary.value.total_holding_amount))
          : ''
      },
      {
        key: 'holding_profit',
        label: '持有收益',
        value: formatCurrency(portfolioSummary.value.total_holding_profit),
        meta: portfolioSummary.value.total_holding_amount > 0 && portfolioSummary.value.total_holding_profit_rate != null
          ? `累计 ${formatPercentText(portfolioSummary.value.total_holding_profit_rate)}`
          : '',
        valueClass: getColorClass(portfolioSummary.value.total_holding_profit),
        metaClass: portfolioSummary.value.total_holding_amount > 0 && portfolioSummary.value.total_holding_profit_rate != null
          ? getColorClass(portfolioSummary.value.total_holding_profit_rate)
          : ''
      }
    ]));

    const portfolioIntradayChartData = computed(() => {
      const labels = TRADING_MINUTES.slice();
      const positionItems = filteredFunds.value.filter((item) => item?.has_position);
      if (positionItems.length === 0) {
        return {
          labels,
          values: [],
          currentIdx: Math.max(minuteToIndex(formatMinuteNow()), 0),
          hasData: false
        };
      }

      const cache = readIntradayCache();
      const todayCache = cache[getTodayDate()] || {};
      const nowMinute = formatMinuteNow();
      let currentIdx = Math.max(minuteToIndex(nowMinute), 0);
      if (isLunchBreakMinute(nowMinute)) {
        currentIdx = Math.max(currentIdx, LUNCH_END_INDEX);
      }

      const totals = labels.map(() => null);

      positionItems.forEach((item) => {
        const shares = parseNumber(item.holding_shares);
        const previousNav = parseNumber(item.previous_nav);
        if (!Number.isFinite(shares) || shares <= 0 || !Number.isFinite(previousNav) || previousNav <= 0) {
          return;
        }

        const pointMap = {};
        const cachedPoints = todayCache[item.code] || {};
        Object.keys(cachedPoints).forEach((minute) => {
          const normalized = normalizeToStepMinute(minute);
          const nav = parseNumber(cachedPoints[minute]);
          if (!normalized || !Number.isFinite(nav) || !labels.includes(normalized)) return;
          pointMap[normalized] = nav;
        });

        if (String(item.current_nav_source || '') === 'estimated') {
          const liveMinute = normalizeToStepMinute(toMinute(item.gztime) || nowMinute);
          const liveNav = parseNumber(item.current_nav);
          if (liveMinute && Number.isFinite(liveNav) && labels.includes(liveMinute)) {
            pointMap[liveMinute] = liveNav;
          }
        }

        const series = new Array(labels.length).fill(null);
        labels.forEach((label, idx) => {
          const nav = parseNumber(pointMap[label]);
          if (Number.isFinite(nav)) series[idx] = nav;
        });

        const knownIndexes = series.reduce((acc, value, idx) => {
          if (Number.isFinite(value)) acc.push(idx);
          return acc;
        }, []);
        if (knownIndexes.length === 0) return;

        let lastKnown = null;
        for (let i = 0; i <= currentIdx; i += 1) {
          if (Number.isFinite(series[i])) {
            lastKnown = series[i];
            continue;
          }
          if (lastKnown !== null) series[i] = lastKnown;
        }

        const lunchAnchor = series[LUNCH_START_INDEX - 1] ?? series[LUNCH_START_INDEX] ?? null;
        if (Number.isFinite(lunchAnchor) && currentIdx >= LUNCH_START_INDEX) {
          for (let i = LUNCH_START_INDEX; i <= Math.min(LUNCH_END_INDEX, currentIdx); i += 1) {
            series[i] = lunchAnchor;
          }
        }

        if (knownIndexes.length === 1) {
          const singleValue = series[knownIndexes[0]];
          for (let i = 0; i <= currentIdx; i += 1) {
            if (!Number.isFinite(series[i])) series[i] = singleValue;
          }
        }

        for (let i = currentIdx + 1; i < series.length; i += 1) {
          series[i] = null;
        }

        for (let i = 0; i < series.length; i += 1) {
          if (!Number.isFinite(series[i])) continue;
          const profit = Number((shares * (series[i] - previousNav)).toFixed(2));
          totals[i] = Number(((totals[i] ?? 0) + profit).toFixed(2));
        }
      });

      return {
        labels,
        values: totals,
        currentIdx,
        hasData: totals.some((value) => Number.isFinite(value))
      };
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

    const currentPortfolioItem = computed(() => (
      (portfolioItems.value || []).find((item) => item.code === currentFundCode.value) || null
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
        nav_confirmed: Boolean(displayDate !== '-' && confirmedDate !== '-' && displayDate === confirmedDate),
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

    const normalizePortfolioItems = (items) => (
      Array.isArray(items) ? items.map((item) => ({
        ...item,
        nav_confirmed: item.current_nav_source === 'confirmed',
        confirmed_nav: item.current_nav_source === 'confirmed' ? item.current_nav : '',
        confirmed_change: item.current_nav_source === 'confirmed' ? item.daily_change_pct : '',
        gsz: item.current_nav_source === 'estimated' ? item.current_nav : '',
        gszzl: item.current_nav_source === 'estimated' ? item.daily_change_pct : '',
        gztime: item.current_nav_source === 'estimated' ? item.current_nav_date : '',
        jzrq: item.current_nav_source === 'confirmed' ? item.current_nav_date : '',
        dwjz: item.previous_nav ?? '',
      })) : []
    );

    const fetchFunds = async () => {
      loading.value = true;
      try {
        const [quoteList, portfolio] = await Promise.all([
          fetchFundsRaw(savedCodes.value),
          fetchPortfolio(clientId)
        ]);
        funds.value = attachGroupMeta(quoteList);
        portfolioItems.value = normalizePortfolioItems(portfolio?.items);
        portfolioSummary.value = portfolio?.summary || portfolioSummary.value;
        lastUpdateTime.value = new Date().toLocaleTimeString();
        await renderPortfolioProfitVisuals();
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
        const [quoteList, idxRes, portfolio] = await Promise.all([
          fetchFundsRaw(savedCodes.value),
          fetchIndexesRaw(),
          fetchPortfolio(clientId)
        ]);
        funds.value = attachGroupMeta(quoteList);
        indexes.value = idxRes;
        portfolioItems.value = normalizePortfolioItems(portfolio?.items);
        portfolioSummary.value = portfolio?.summary || portfolioSummary.value;
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
            historyData.value = { success: false, data: [] };
            historyFundCode.value = '';
          }
        }

        if (!currentFundCode.value && quoteList.length > 0) {
          await showDetailInternal(quoteList[0].code);
        }

        if (currentFundCode.value && historyRangeDays.value === 30) {
          historyData.value = detailFund.value?.history || { success: false, data: [] };
          historyFundCode.value = currentFundCode.value;
        }

        if (currentFundCode.value && detailTab.value === 'overview' && hasLoadedAnyDetail.value) {
          await renderDetailVisuals();
        }

        await renderPortfolioProfitVisuals();
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
      if (detailTab.value === tab) {
        if (tab === 'overview') await renderDetailVisuals();
        if (tab === 'history') await ensureHistoryRange(historyRangeDays.value);
        return;
      }

      detailTab.value = tab;
      if (tab === 'overview') await renderDetailVisuals();
      if (tab === 'history') await ensureHistoryRange(historyRangeDays.value);
    };

    const showDetail = async (code) => {
      openMobileDetail();
      const switchingFund = currentFundCode.value && currentFundCode.value !== code;
      if (!currentFundCode.value || switchingFund) {
        detailTab.value = 'overview';
      }
      await showDetailInternal(code);
      if (currentFundCode.value !== code) return;
      historyRangeDays.value = 30;
      historyFundCode.value = code;
      historyData.value = detailFund.value?.history || { success: false, data: [] };
      if (detailTab.value === 'overview') await renderDetailVisuals();
      if (detailTab.value === 'history') await ensureHistoryRange(30);
    };

    const ensureHistoryRange = async (days) => {
      const code = currentFundCode.value;
      if (!code) return;
      if (historyRangeDays.value === days && historyFundCode.value === code && historyData.value?.data?.length) {
        if (detailTab.value === 'history') await renderActiveHistoryChart();
        return;
      }

      historyRangeDays.value = days;
      if (days === 30 && detailFund.value?.history?.data?.length) {
        historyData.value = detailFund.value.history;
        historyFundCode.value = code;
        if (detailTab.value === 'history') await renderActiveHistoryChart();
        return;
      }

      const requestId = latestHistoryRequestId + 1;
      latestHistoryRequestId = requestId;
      historyLoading.value = true;
      try {
        const data = await loadFundHistory(code, days);
        if (requestId !== latestHistoryRequestId || currentFundCode.value !== code) return;
        historyData.value = data && Array.isArray(data.data) ? data : { success: false, data: [] };
        historyFundCode.value = code;
        if (detailTab.value === 'history') await renderActiveHistoryChart();
      } finally {
        if (requestId === latestHistoryRequestId) {
          historyLoading.value = false;
        }
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
      if (!positionModal) {
        const el = document.getElementById('positionModal');
        if (el) positionModal = window.bootstrap.Modal.getOrCreateInstance(el);
      }
      if (!deleteFundModal) {
        const el = document.getElementById('deleteFundModal');
        if (el) deleteFundModal = window.bootstrap.Modal.getOrCreateInstance(el);
      }
      if (!clearAllModal) {
        const el = document.getElementById('clearAllModal');
        if (el) clearAllModal = window.bootstrap.Modal.getOrCreateInstance(el);
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

    const openPositionModal = (fund) => {
      if (!fund) return;
      ensureGroupModals();
      positionActionError.value = '';
      positionForm.value = {
        code: fund.code,
        name: fund.name || '',
        holding_amount: fund.snapshot_holding_amount != null ? String(fund.snapshot_holding_amount) : '',
        holding_profit: fund.snapshot_holding_profit != null ? String(fund.snapshot_holding_profit) : ''
      };
      positionModal?.show();
    };

    const closePositionModal = () => {
      positionActionError.value = '';
      positionModal?.hide();
    };

    const savePosition = async () => {
      if (!positionForm.value.code) return;
      savingPosition.value = true;
      positionActionError.value = '';
      try {
        const result = await updateUserFundPosition(clientId, positionForm.value.code, {
          holding_amount: positionForm.value.holding_amount,
          holding_profit: positionForm.value.holding_profit
        });
        if (result.error || result.success === false) {
          positionActionError.value = result.error || '保存持仓失败';
          return;
        }
        closePositionModal();
        await fetchData();
      } finally {
        savingPosition.value = false;
      }
    };

    const openDeleteFundModal = (fund) => {
      if (!fund?.code) return;
      ensureGroupModals();
      fundActionError.value = '';
      pendingDeleteFund.value = {
        code: fund.code,
        name: fund.name || ''
      };
      deleteFundModal?.show();
    };

    const closeDeleteFundModal = () => {
      fundActionError.value = '';
      deleteFundModal?.hide();
    };

    const openClearAllModal = () => {
      ensureGroupModals();
      clearAllModal?.show();
    };

    const closeClearAllModal = () => {
      clearAllModal?.hide();
    };

    const removeFund = async () => {
      const code = pendingDeleteFund.value.code;
      if (!code) return;
      deletingFund.value = true;
      fundActionError.value = '';
      try {
        await deleteUserFund(clientId, code);
      } catch {
        fundActionError.value = '删除基金失败';
        return;
      } finally {
        deletingFund.value = false;
      }
      closeDeleteFundModal();
      if (currentFundCode.value === code) {
        currentFundCode.value = '';
        currentFundName.value = '';
        detailFund.value = EMPTY_DETAIL();
        detailError.value = '';
        detailTab.value = 'overview';
        historyData.value = { success: false, data: [] };
        historyFundCode.value = '';
        closeMobileDetail();
      }
      await fetchData();
    };

    const clearAll = async () => {
      if (savedCodes.value.length === 0) return;
      clearingAllFunds.value = true;
      try {
        await Promise.all(savedCodes.value.map((code) => deleteUserFund(clientId, code)));
        closeClearAllModal();
        await fetchData();
        funds.value = [];
        portfolioItems.value = [];
        currentFundCode.value = '';
        currentFundName.value = '';
        detailFund.value = EMPTY_DETAIL();
        detailError.value = '';
        detailTab.value = 'overview';
        historyData.value = { success: false, data: [] };
        historyFundCode.value = '';
        closeMobileDetail();
      } finally {
        clearingAllFunds.value = false;
      }
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

    watch(
      () => [portfolioIntradayChartData.value, activeGroupId.value, theme.value],
      () => {
        renderPortfolioProfitVisuals();
      }
    );

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
      portfolioItems,
      portfolioSummary,
      positionForm,
      deletingFund,
      fundActionError,
      pendingDeleteFund,
      clearingAllFunds,
      savingPosition,
      positionActionError,
      releaseNoticeOpen,
      releaseNoticeVersion: RELEASE_NOTICE_VERSION,
      releaseNoticeItems: RELEASE_NOTICE_ITEMS,
      monitorSummaryCards,
      portfolioSummaryCards,
      portfolioIntradayChartData,
      selectedFundGroupName,
      intradayDataTag,
      topTenHoldings,
      historyPreview,
      selectedFundQuote,
      currentPortfolioItem,
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
      openPositionModal,
      closePositionModal,
      savePosition,
      openDeleteFundModal,
      closeDeleteFundModal,
      openClearAllModal,
      closeClearAllModal,
      removeFund,
      clearAll,
      fetchData,
      formatHoldingChange,
      formatCurrency,
      formatPercentText,
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
