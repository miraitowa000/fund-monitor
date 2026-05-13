import {
  createFundGroup,
  deleteFundGroup,
  deleteUserFund,
  fetchDashboardBootstrap,
  fetchAuthMe,
  fetchDailyEarnings,
  fetchPortfolio,
  fetchIndexesRaw,
  fetchMarketStatus,
  fetchUserFundsMeta,
  loadFundHistory,
  loginAccount,
  moveUserFundGroup,
  renameFundGroup,
  registerAccount,
  saveUserFund,
  searchFunds,
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
import { buildPortfolioViewState } from './dashboard-state.js';
import { createConversionController } from './conversion-controller.js';
import { createDetailController } from './detail-modal.js';
import { createDcaController } from './dca-controller.js';
import {
  EMPTY_DETAIL,
  clearSavedCodes,
  createClientId,
  formatChange,
  getColorClass,
  getIndexCardClass,
  getMarketStatus,
  getSortIcon,
  loadClientId,
  loadSavedCodes,
  saveClientId,
} from './formatters.js';
import { createRefreshTimers } from './timers.js';
import { createTransactionController } from './transaction-controller.js';

const THEME_STORAGE_KEY = 'fundMonitorTheme';
const RELEASE_NOTICE_STORAGE_KEY = 'fundMonitorReleaseNoticeSeen';
const RELEASE_NOTICE_VERSION = 'release-2026-05-13-trading-earnings';
const RELEASE_NOTICE_TITLE = '更新说明';
const RELEASE_NOTICE_ITEMS = [
  { id: '1', text: '新增登录注册，支持交易数据按账号保存。' },
  { id: '2', text: '新增加仓、减仓、定投、转换等交易记录功能。' },
  { id: '3', text: '新增我的收益，支持按日、月、年查看盈亏。' },
  { id: '4', text: '优化移动端布局和持仓操作体验。' },
  { id: '5', text: '修复收益统计、今日走势等展示问题。' }
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
    const clientId = ref(loadClientId());
    const codeInput = ref('');
    const selectedGroupId = ref('');
    const newGroupName = ref('');
    const savedCodes = ref([]);
    const userFunds = ref([]);
    const fundGroups = ref([]);
    const activeGroupId = ref('all');
    const funds = ref([]);
    const portfolioItems = ref([]);
    const fundListVersion = ref(0);
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
    const isTodayTradingDay = ref(true);
    const sortDir = ref('none');
    const detailFund = ref(EMPTY_DETAIL());
    const detailLoading = ref(false);
    const detailError = ref('');
    const currentFundCode = ref('');
    const currentFundName = ref('');
    const renameGroupName = ref('');
    const editingGroupId = ref('');
    const editingGroupName = ref('');
    const mobileGroupActionsId = ref('');
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
    const quickSearchInput = ref('');
    const quickSearchResults = ref([]);
    const quickSearchLoading = ref(false);
    const quickSearchError = ref('');
    const quickSearchOpen = ref(false);
    const quickAddSelection = ref([]);
    const quickAddConfirmOpen = ref(false);
    const quickAddGroupId = ref('');
    const quickAddGroupMenuOpen = ref(false);
    const quickAddSaving = ref(false);
    const summaryExpanded = ref(true);
    const isMobileView = ref(false);
    const deletingFund = ref(false);
    const fundActionError = ref('');
    const pendingDeleteFund = ref({
      code: '',
      name: ''
    });
    const holdingActionFund = ref(null);
    const clearingAllFunds = ref(false);
    const savingPosition = ref(false);
    const positionActionError = ref('');
    const authUser = ref(null);
    const authMenuOpen = ref(false);
    const authModalOpen = ref(false);
    const authMode = ref('login');
    const authLoading = ref(false);
    const authError = ref('');
    const authForm = ref({
      account: '',
      password: ''
    });
    const mobileActiveTab = ref('home');
    const earningsViewOpen = ref(false);
    const earningsLoading = ref(false);
    const earningsLoaded = ref(false);
    const earningsError = ref('');
    const earningsMode = ref('amount');
    const earningsViewMode = ref('day');
    const earningsCursorMonth = ref(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
    const earningsCursorYear = ref(new Date().getFullYear());
    const earningsSelectedDate = ref('');
    const earningsSelectedMonth = ref('');
    const earningsSelectedYear = ref('');
    const earningsRankTab = ref('profit');
    const dailyEarnings = ref({
      summary: {},
      days: []
    });

    let clockTimer = null;
    let renameGroupModal = null;
    let deleteGroupModal = null;
    let positionModal = null;
    let deleteFundModal = null;
    let clearAllModal = null;
    let resizeHandler = null;
    let latestHistoryRequestId = 0;
    let quickSearchTimer = null;
    let outsideClickHandler = null;
    let visibilityChangeHandler = null;
    let fundsRefreshPromise = null;
    let indexesRefreshPromise = null;
    let stickyPanelResizeObserver = null;
    let portfolioRenderTimer = null;
    let latestEarningsRequestId = 0;
    const earningsRangeCache = new Map();

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

    const formatInlineCurrency = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `¥${n.toFixed(2)}`;
    };

    const formatPercentText = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return `${formatChange(n * 100, 2)}%`;
    };

    const formatNavValue = (val) => {
      const n = parseNumber(val);
      if (!Number.isFinite(n)) return '-';
      return n.toFixed(4);
    };

    const accountDisplayName = computed(() => {
      const account = String(authUser.value?.account || '').trim();
      if (!account) return '未登录';
      if (account.includes('@')) {
        const [name, domain] = account.split('@');
        const maskedName = name.length > 2 ? `${name.slice(0, 2)}***` : `${name.slice(0, 1)}***`;
        return `${maskedName}@${domain}`;
      }
      if (/^\d{11}$/.test(account)) {
        return `${account.slice(0, 3)}****${account.slice(7)}`;
      }
      return account;
    });

    const resetAuthForm = () => {
      authForm.value = { account: '', password: '' };
      authError.value = '';
    };

    const loadAuthState = async () => {
      try {
        const result = await fetchAuthMe(clientId.value);
        authUser.value = result?.registered ? result : null;
      } catch {
        authUser.value = null;
      }
    };

    const toggleAuthMenu = () => {
      authMenuOpen.value = !authMenuOpen.value;
    };

    const switchMobileTab = (tab) => {
      mobileActiveTab.value = tab === 'mine' ? 'mine' : 'home';
      if (mobileActiveTab.value === 'home') {
        nextTick(() => {
          resizeDetailCharts();
        });
      }
    };

    const openAuthModal = (mode = 'login') => {
      authMode.value = mode === 'register' ? 'register' : 'login';
      authMenuOpen.value = false;
      resetAuthForm();
      authModalOpen.value = true;
    };

    const closeAuthModal = () => {
      if (authLoading.value) return;
      authModalOpen.value = false;
      resetAuthForm();
    };

    const switchAuthMode = (mode) => {
      authMode.value = mode === 'register' ? 'register' : 'login';
      authError.value = '';
    };

    const submitAuthForm = async () => {
      const account = authForm.value.account.trim();
      const password = authForm.value.password;
      if (!account || !password) {
        authError.value = '请输入账号和密码';
        return;
      }
      authLoading.value = true;
      authError.value = '';
      try {
        const result = authMode.value === 'register'
          ? await registerAccount(clientId.value, account, password)
          : await loginAccount(account, password);
        if (result?.error || result?.success === false || !result?.user) {
          authError.value = result?.error || '操作失败，请稍后重试';
          return;
        }
        const nextClientId = saveClientId(result.user.client_id);
        if (nextClientId) {
          clientId.value = nextClientId;
        }
        authUser.value = result.user;
        authModalOpen.value = false;
        resetAuthForm();
        currentFundCode.value = '';
        currentFundName.value = '';
        detailFund.value = EMPTY_DETAIL();
        detailError.value = '';
        detailTab.value = 'overview';
        historyData.value = { success: false, data: [] };
        historyFundCode.value = '';
        await fetchData();
      } finally {
        authLoading.value = false;
      }
    };

    const logoutAccount = async () => {
      const anonymousClientId = saveClientId(createClientId());
      clientId.value = anonymousClientId || createClientId();
      authUser.value = null;
      authMenuOpen.value = false;
      earningsViewOpen.value = false;
      dailyEarnings.value = { summary: {}, days: [] };
      currentFundCode.value = '';
      currentFundName.value = '';
      detailFund.value = EMPTY_DETAIL();
      detailError.value = '';
      detailTab.value = 'overview';
      historyData.value = { success: false, data: [] };
      historyFundCode.value = '';
      await fetchData();
    };

    const openMyEarnings = () => {
      authMenuOpen.value = false;
      if (!authUser.value) {
        openAuthModal('login');
        return;
      }
      alert('我的收益功能后续接入');
    };

    const formatDateForApi = (date) => {
      const y = date.getFullYear();
      const m = String(date.getMonth() + 1).padStart(2, '0');
      const d = String(date.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    };

    const getMonthEarningsRange = () => {
      const cursor = earningsCursorMonth.value;
      const startDate = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
      const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
      const todayDate = new Date();
      const endDate = monthEnd > todayDate ? todayDate : monthEnd;
      return { start: formatDateForApi(startDate), end: formatDateForApi(endDate) };
    };

    const clampEndDate = (date) => {
      const today = new Date();
      return date > today ? today : date;
    };

    const getEarningsYearRange = (year) => ({
      start: formatDateForApi(new Date(year, 0, 1)),
      end: formatDateForApi(clampEndDate(new Date(year, 11, 31)))
    });

    const getEarningsYearWindow = () => {
      const endYear = Math.min(earningsCursorYear.value, new Date().getFullYear());
      const startYear = endYear - 5;
      return { startYear, endYear };
    };

    const getEarningsRequestRanges = () => {
      if (earningsViewMode.value === 'day') {
        return [getMonthEarningsRange()];
      }
      if (earningsViewMode.value === 'month') {
        return [getEarningsYearRange(earningsCursorMonth.value.getFullYear())];
      }
      const { startYear, endYear } = getEarningsYearWindow();
      return Array.from({ length: endYear - startYear + 1 }, (_, index) => (
        getEarningsYearRange(startYear + index)
      ));
    };

    const formatCompactSigned = (value, digits = 2) => {
      const n = parseNumber(value);
      if (!Number.isFinite(n)) return '0.00';
      const sign = n > 0 ? '+' : '';
      return `${sign}${n.toFixed(digits)}`;
    };

    const getDefaultEarningsRange = () => {
      const endDate = new Date();
      const startDate = new Date(endDate.getFullYear(), endDate.getMonth(), 1);
      const toText = (date) => {
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
      };
      return { start: toText(startDate), end: toText(endDate) };
    };

    const loadDailyEarnings = async () => {
      if (!authUser.value) return;
      const requestId = ++latestEarningsRequestId;
      earningsLoading.value = true;
      earningsError.value = '';
      try {
        const ranges = getEarningsRequestRanges();
        const results = await Promise.all(ranges.map(async (range) => {
          const cacheKey = `${range.start}:${range.end}`;
          if (earningsRangeCache.has(cacheKey)) {
            return earningsRangeCache.get(cacheKey);
          }
          const result = await fetchDailyEarnings(clientId.value, range.start, range.end);
          if (result?.error || result?.success === false) {
            throw new Error(result?.error || '加载收益数据失败');
          }
          earningsRangeCache.set(cacheKey, result);
          return result;
        }));
        if (requestId !== latestEarningsRequestId) return;
        const days = results.flatMap((item) => Array.isArray(item.days) ? item.days : []);
        const totalProfit = days.reduce((sum, item) => sum + (parseNumber(item.profit) || 0), 0);
        const totalBase = days.reduce((sum, item) => sum + (parseNumber(item.base_amount) || 0), 0);
        dailyEarnings.value = {
          summary: {
            total_profit: Number(totalProfit.toFixed(2)),
            total_rate: totalBase > 0 ? Number((totalProfit / totalBase).toFixed(4)) : null,
            profit_days: days.filter((item) => (parseNumber(item.profit) || 0) > 0).length,
            loss_days: days.filter((item) => (parseNumber(item.profit) || 0) < 0).length,
            flat_days: days.filter((item) => (parseNumber(item.profit) || 0) === 0).length,
          },
          days
        };
        earningsLoaded.value = true;
      } catch (error) {
        if (requestId !== latestEarningsRequestId) return;
        earningsError.value = error?.message || '加载收益数据失败';
        if (!earningsLoaded.value) {
          dailyEarnings.value = { summary: {}, days: [] };
        }
      } finally {
        if (requestId === latestEarningsRequestId) {
          earningsLoading.value = false;
        }
      }
    };

    const openMyEarningsPage = () => {
      authMenuOpen.value = false;
      if (!authUser.value) {
        openAuthModal('login');
        return;
      }
      earningsViewOpen.value = true;
      if (isMobileView.value) mobileActiveTab.value = 'mine';
      loadDailyEarnings();
    };

    const closeMyEarnings = () => {
      earningsViewOpen.value = false;
    };

    const setEarningsMode = (mode) => {
      earningsMode.value = mode === 'rate' ? 'rate' : 'amount';
    };

    const setEarningsViewMode = (mode) => {
      const nextMode = ['day', 'month', 'year'].includes(mode) ? mode : 'day';
      if (earningsViewMode.value === nextMode) return;
      earningsViewMode.value = nextMode;
      earningsSelectedDate.value = '';
      earningsSelectedMonth.value = '';
      earningsSelectedYear.value = '';
      loadDailyEarnings();
    };

    const setEarningsRankTab = (tab) => {
      earningsRankTab.value = tab === 'loss' ? 'loss' : 'profit';
    };

    const shiftEarningsPeriod = (offset) => {
      if (earningsViewMode.value === 'year') {
        const nextYear = earningsCursorYear.value + offset * 6;
        earningsCursorYear.value = Math.min(nextYear, new Date().getFullYear());
        earningsSelectedDate.value = '';
        earningsSelectedMonth.value = '';
        earningsSelectedYear.value = '';
        loadDailyEarnings();
        return;
      }
      const current = earningsCursorMonth.value;
      const next = earningsViewMode.value === 'month'
        ? new Date(current.getFullYear() + offset, 0, 1)
        : new Date(current.getFullYear(), current.getMonth() + offset, 1);
      const thisMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
      const capped = next > thisMonth ? thisMonth : next;
      earningsCursorMonth.value = capped;
      earningsSelectedDate.value = '';
      earningsSelectedMonth.value = '';
      earningsSelectedYear.value = '';
      loadDailyEarnings();
    };

    const shiftEarningsMonth = shiftEarningsPeriod;

    const formatEarningsValue = (day) => {
      if (earningsMode.value === 'rate') {
        return formatPercentText(day?.rate);
      }
      return formatCurrency(day?.profit);
    };

    const formatEarningsCellValue = (day) => {
      if (!day) return '0.00';
      if (earningsMode.value === 'rate') {
        const n = parseNumber(day.rate);
        if (!Number.isFinite(n)) return '0.00%';
        return `${formatCompactSigned(n * 100)}%`;
      }
      return formatCompactSigned(day.profit);
    };

    const earningsValueClass = (day) => {
      return getColorClass(earningsMode.value === 'rate' ? day?.rate : day?.profit);
    };

    const earningsCalendarTitle = computed(() => {
      if (earningsViewMode.value === 'month') {
        return `${earningsCursorMonth.value.getFullYear()}年`;
      }
      if (earningsViewMode.value === 'year') {
        const { startYear, endYear } = getEarningsYearWindow();
        return `${startYear}-${endYear}年`;
      }
      const cursor = earningsCursorMonth.value;
      return `${cursor.getFullYear()}年${String(cursor.getMonth() + 1).padStart(2, '0')}月`;
    });

    const earningsSummaryTitle = computed(() => {
      if (earningsViewMode.value === 'month') return '本年收益';
      if (earningsViewMode.value === 'year') return '累计收益';
      return '本月收益';
    });

    const earningsBoardTitle = computed(() => {
      if (earningsViewMode.value === 'month') return '月度盈亏';
      if (earningsViewMode.value === 'year') return '年度盈亏';
      return '每日盈亏';
    });

    const getEarningsDayByDate = (date) => (
      earningsMergedDays.value.find((day) => day.date === date) || null
    );

    const earningsTodayLiveDay = computed(() => {
      const today = getTodayDate();
      const items = (portfolioItems.value || [])
        .filter((fund) => fund?.has_position)
        .map((fund) => {
          const profit = parseNumber(fund.daily_profit);
          const base = parseNumber(fund.holding_shares) * parseNumber(fund.previous_nav);
          if (!Number.isFinite(profit) || !Number.isFinite(base) || base <= 0) return null;
          return {
            code: fund.code,
            name: fund.name || fund.code,
            shares: parseNumber(fund.holding_shares),
            nav: parseNumber(fund.current_nav),
            previous_nav: parseNumber(fund.previous_nav),
            profit: Number(profit.toFixed(2)),
            base_amount: Number(base.toFixed(2)),
            rate: profit / base
          };
        })
        .filter(Boolean);
      if (items.length === 0) return null;
      const totalProfit = items.reduce((sum, item) => sum + item.profit, 0);
      const totalBase = items.reduce((sum, item) => sum + item.base_amount, 0);
      return {
        date: today,
        profit: Number(totalProfit.toFixed(2)),
        rate: totalBase > 0 ? Number((totalProfit / totalBase).toFixed(4)) : null,
        base_amount: Number(totalBase.toFixed(2)),
        source: 'live',
        items
      };
    });

    const earningsMergedDays = computed(() => {
      const liveDay = earningsTodayLiveDay.value;
      const days = (dailyEarnings.value.days || []).filter((day) => (
        !liveDay || day.date !== liveDay.date
      ));
      return liveDay ? [liveDay, ...days] : days;
    });

    const aggregateEarningsDays = (filterFn) => {
      let profit = 0;
      let baseAmount = 0;
      let profitDays = 0;
      let lossDays = 0;
      earningsMergedDays.value.forEach((day) => {
        if (!filterFn(day)) return;
        const dayProfit = parseNumber(day.profit) || 0;
        const dayBase = parseNumber(day.base_amount) || 0;
        profit += dayProfit;
        baseAmount += dayBase;
        if (dayProfit > 0) profitDays += 1;
        if (dayProfit < 0) lossDays += 1;
      });
      return {
        profit: Number(profit.toFixed(2)),
        base_amount: Number(baseAmount.toFixed(2)),
        rate: baseAmount > 0 ? Number((profit / baseAmount).toFixed(4)) : null,
        profit_days: profitDays,
        loss_days: lossDays
      };
    };

    const earningsVisibleDays = computed(() => {
      if (earningsViewMode.value === 'day' && earningsSelectedDate.value) {
        const day = getEarningsDayByDate(earningsSelectedDate.value);
        return day ? [day] : [];
      }
      if (earningsViewMode.value === 'month' && earningsSelectedMonth.value) {
        return earningsMergedDays.value.filter((day) => String(day.date || '').startsWith(earningsSelectedMonth.value));
      }
      if (earningsViewMode.value === 'year' && earningsSelectedYear.value) {
        return earningsMergedDays.value.filter((day) => String(day.date || '').startsWith(`${earningsSelectedYear.value}-`));
      }
      return earningsMergedDays.value;
    });

    const earningsDisplaySummary = computed(() => {
      const days = earningsVisibleDays.value;
      const totalProfit = days.reduce((sum, item) => sum + (parseNumber(item.profit) || 0), 0);
      const totalBase = days.reduce((sum, item) => sum + (parseNumber(item.base_amount) || 0), 0);
      return {
        total_profit: Number(totalProfit.toFixed(2)),
        total_rate: totalBase > 0 ? Number((totalProfit / totalBase).toFixed(4)) : null,
        profit_days: days.filter((item) => (parseNumber(item.profit) || 0) > 0).length,
        loss_days: days.filter((item) => (parseNumber(item.profit) || 0) < 0).length,
        flat_days: days.filter((item) => (parseNumber(item.profit) || 0) === 0).length,
      };
    });

    const earningsDisplaySummaryTitle = computed(() => {
      if (earningsViewMode.value === 'day' && earningsSelectedDate.value) {
        return `${earningsSelectedDate.value} 收益`;
      }
      if (earningsViewMode.value === 'month' && earningsSelectedMonth.value) {
        const [year, month] = earningsSelectedMonth.value.split('-');
        return `${year}年${parseInt(month, 10)}月收益`;
      }
      if (earningsViewMode.value === 'year' && earningsSelectedYear.value) {
        return `${earningsSelectedYear.value}年收益`;
      }
      return earningsSummaryTitle.value;
    });

    const earningsSummaryBadge = computed(() => {
      if (earningsViewMode.value !== 'day') return '';
      const today = getTodayDate();
      const viewingToday = earningsSelectedDate.value === today || (!earningsSelectedDate.value && getMonthEarningsRange().end === today);
      if (!viewingToday || !earningsTodayLiveDay.value) return '';
      const source = portfolioSummary.value?.nav_source;
      return source === 'confirmed' ? '已更新' : '实时估算';
    });

    const selectEarningsDate = (cell) => {
      if (!cell || cell.future) return;
      if (earningsSelectedDate.value === cell.date) {
        earningsSelectedDate.value = '';
        return;
      }
      earningsSelectedDate.value = cell.date;
      if (cell.outside) {
        const [year, month] = cell.date.split('-').map((value) => parseInt(value, 10));
        earningsCursorMonth.value = new Date(year, month - 1, 1);
        loadDailyEarnings();
      }
    };

    const selectEarningsMonth = (cell) => {
      if (!cell || cell.future) return;
      earningsSelectedMonth.value = earningsSelectedMonth.value === cell.key ? '' : cell.key;
    };

    const selectEarningsYear = (cell) => {
      if (!cell) return;
      earningsSelectedYear.value = earningsSelectedYear.value === cell.key ? '' : cell.key;
    };

    const earningsCalendarDays = computed(() => {
      const range = getMonthEarningsRange();
      const [year, month] = range.start.split('-').map((value) => parseInt(value, 10));
      const first = new Date(year, month - 1, 1);
      const start = new Date(year, month - 1, 1 - first.getDay());
      const byDate = new Map(earningsMergedDays.value.map((day) => [day.date, day]));
      const todayText = range.end;
      return Array.from({ length: 42 }, (_, index) => {
        const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
        const value = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
        const day = byDate.get(value) || null;
        return {
          date: value,
          day: date.getDate(),
          outside: date.getMonth() !== month - 1,
          today: value === todayText,
          future: value > todayText,
          selected: value === earningsSelectedDate.value,
          data: day,
          value: formatEarningsCellValue(day),
          className: day ? earningsValueClass(day) : ''
        };
      });
    });

    const earningsMonthCells = computed(() => {
      const year = earningsCursorMonth.value.getFullYear();
      const currentYear = new Date().getFullYear();
      const currentMonth = new Date().getMonth() + 1;
      return Array.from({ length: 12 }, (_, index) => {
        const month = index + 1;
        const data = aggregateEarningsDays((day) => {
          const [dayYear, dayMonth] = String(day.date || '').split('-').map((value) => parseInt(value, 10));
          return dayYear === year && dayMonth === month;
        });
        const future = year > currentYear || (year === currentYear && month > currentMonth);
        return {
          key: `${year}-${String(month).padStart(2, '0')}`,
          label: `${month}月`,
          future,
          selected: earningsSelectedMonth.value === `${year}-${String(month).padStart(2, '0')}`,
          data,
          value: formatEarningsCellValue(data),
          className: getColorClass(earningsMode.value === 'rate' ? data.rate : data.profit)
        };
      });
    });

    const earningsYearCells = computed(() => {
      const { startYear, endYear } = getEarningsYearWindow();
      return Array.from({ length: endYear - startYear + 1 }, (_, index) => {
        const year = startYear + index;
        const data = aggregateEarningsDays((day) => {
          const dayYear = parseInt(String(day.date || '').slice(0, 4), 10);
          return dayYear === year;
        });
        return {
          key: String(year),
          label: `${year}年`,
          selected: earningsSelectedYear.value === String(year),
          data,
          value: formatEarningsCellValue(data),
          className: getColorClass(earningsMode.value === 'rate' ? data.rate : data.profit)
        };
      });
    });

    const earningsRankItems = computed(() => {
      const bucket = new Map();
      earningsVisibleDays.value.forEach((day) => {
        (day.items || []).forEach((item) => {
          const code = item.code || '-';
          const current = bucket.get(code) || {
            code,
            name: fundMetaMap.value[code]?.name || (portfolioItems.value || []).find((fund) => fund.code === code)?.name || code,
            profit: 0,
            base_amount: 0,
            days: 0
          };
          const profit = parseNumber(item.profit);
          const base = parseNumber(item.base_amount);
          current.profit += Number.isFinite(profit) ? profit : 0;
          current.base_amount += Number.isFinite(base) ? base : 0;
          current.days += 1;
          bucket.set(code, current);
        });
      });
      const rows = Array.from(bucket.values()).map((item) => ({
        ...item,
        profit: Number(item.profit.toFixed(2)),
        rate: item.base_amount > 0 ? item.profit / item.base_amount : null
      }));
      const sorted = earningsRankTab.value === 'loss'
        ? rows.filter((item) => item.profit < 0).sort((a, b) => a.profit - b.profit)
        : rows.filter((item) => item.profit > 0).sort((a, b) => b.profit - a.profit);
      return sorted.slice(0, 5);
    });

    const earningsRankMaxValue = computed(() => (
      Math.max(...earningsRankItems.value.map((item) => Math.abs(parseNumber(item.profit) || 0)), 1)
    ));

    const closeHoldingActionModal = () => {
      holdingActionFund.value = null;
    };

    const openHoldingActionModal = (fund) => {
      if (!fund) return;
      holdingActionFund.value = fund;
    };

    const requireAuthForTradeAction = () => {
      if (authUser.value) return true;
      closeHoldingActionModal();
      openAuthModal('login');
      return false;
    };

    const openTradePlaceholder = (type) => {
      if (!requireAuthForTradeAction()) return;
      const labels = {
        buy: '加仓',
        sell: '减仓',
        dca: '定投',
        convert: '转换',
        history: '交易记录'
      };
      alert(`${labels[type] || '交易'}功能后续接入`);
    };

    const transactions = createTransactionController({
      authUser,
      clientId,
      openAuthModal,
      closeHoldingActionModal,
      refreshData: () => fetchData(),
    });

    const dca = createDcaController({
      authUser,
      clientId,
      openAuthModal,
      closeHoldingActionModal,
      refreshData: () => fetchData(),
    });

    const conversion = createConversionController({
      authUser,
      clientId,
      openAuthModal,
      closeHoldingActionModal,
      refreshData: () => fetchData(),
    });

    const getDisplayEstimatedNav = (fund) => {
      if (!fund) return '-';
      if (fund.nav_confirmed) {
        return formatNavValue(fund.confirmed_nav || fund.dwjz);
      }
      return formatNavValue(fund.gsz);
    };

    const getDisplayUnitNav = (fund) => {
      if (!fund) return '-';
      return formatNavValue(fund.confirmed_nav || fund.dwjz);
    };

    const renderPortfolioProfitVisuals = async () => {
      await nextTick();
      renderPortfolioProfitChart(portfolioIntradayChartData.value);
      resizeDetailCharts();
    };

    const schedulePortfolioProfitRender = () => {
      if (portfolioRenderTimer) {
        clearTimeout(portfolioRenderTimer);
        portfolioRenderTimer = null;
      }
      portfolioRenderTimer = setTimeout(() => {
        portfolioRenderTimer = null;
        renderPortfolioProfitVisuals();
      }, 250);
    };

    const renderActiveHistoryChart = async () => {
      await nextTick();
      renderHistoryChart(historyData.value);
      resizeDetailCharts();
    };

    const isMobileViewport = () => window.matchMedia('(max-width: 860px)').matches;

    const updateDesktopStickyOffsets = () => {
      const appEl = document.getElementById('app');
      const topSearchPanel = appEl?.querySelector('[data-sticky-panel="top-search"]');
      if (!appEl || !topSearchPanel) return;
      const panelHeight = Math.ceil(topSearchPanel.getBoundingClientRect().height || 0);
      appEl.style.setProperty('--page-top-search-panel-height', `${panelHeight}px`);
    };

    const bindStickyPanelObserver = () => {
      const appEl = document.getElementById('app');
      const topSearchPanel = appEl?.querySelector('[data-sticky-panel="top-search"]');
      if (!topSearchPanel) return;
      updateDesktopStickyOffsets();
      if (typeof ResizeObserver === 'undefined') return;
      stickyPanelResizeObserver?.disconnect();
      stickyPanelResizeObserver = new ResizeObserver(() => {
        updateDesktopStickyOffsets();
      });
      stickyPanelResizeObserver.observe(topSearchPanel);
    };

    const syncBodyDetailState = (open) => {
      document.body.classList.toggle('detail-modal-open', Boolean(open));
    };

    const loadLazyImage = (img) => {
      if (!(img instanceof HTMLImageElement)) return;
      if (img.dataset.loaded === 'true') return;
      const source = String(img.dataset.src || '').trim();
      if (!source) return;
      img.src = source;
      img.dataset.loaded = 'true';
    };

    const loadLazyImagesInContainer = (container) => {
      if (!(container instanceof Element)) return;
      container.querySelectorAll('img[data-src]').forEach((img) => {
        loadLazyImage(img);
      });
    };

    const bindModalLazyImages = () => {
      const qrModalEl = document.getElementById('qrModal');
      if (qrModalEl) {
        qrModalEl.addEventListener('show.bs.modal', () => {
          loadLazyImagesInContainer(qrModalEl);
        }, { once: true });
      }

      const donateModalEl = document.getElementById('donateModal');
      if (donateModalEl) {
        donateModalEl.addEventListener('show.bs.modal', () => {
          const activePane = donateModalEl.querySelector('.tab-pane.active, .tab-pane.show.active');
          if (activePane) {
            loadLazyImagesInContainer(activePane);
          } else {
            loadLazyImagesInContainer(donateModalEl);
          }
        }, { once: true });

        donateModalEl.querySelectorAll('[data-bs-toggle="tab"]').forEach((tab) => {
          tab.addEventListener('shown.bs.tab', (event) => {
            const selector = event?.target?.getAttribute('data-bs-target');
            if (!selector) return;
            const pane = donateModalEl.querySelector(selector);
            loadLazyImagesInContainer(pane);
          });
        });
      }
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

    // 大户场景下避免在 key 里拼接所有 code（会造成巨大字符串分配与 diff 压力）
    const fundListRenderKey = computed(() => `${activeGroupId.value}-${sortDir.value}-${fundListVersion.value}`);
    const sortIcon = computed(() => getSortIcon(sortDir.value));

    const marketNowText = computed(() => {
      const hh = String(now.value.getHours()).padStart(2, '0');
      const mm = String(now.value.getMinutes()).padStart(2, '0');
      const ss = String(now.value.getSeconds()).padStart(2, '0');
      return `${hh}:${mm}:${ss}`;
    });

    const marketStatus = computed(() => getMarketStatus(now.value, isTodayTradingDay.value));

    const isPageVisible = () => typeof document === 'undefined' || document.visibilityState === 'visible';
    const isTradingSessionOpen = () => marketStatus.value.className === 'market-open';

    const mobileTickerIndexes = computed(() => {
      if (!Array.isArray(indexes.value) || indexes.value.length === 0) return [];
      return indexes.value.concat(indexes.value);
    });

    const quickSearchResultsView = computed(() => quickSearchResults.value.map((item) => ({
      ...item,
      isExisting: savedCodes.value.includes(item.code),
      isSelected: quickAddSelection.value.some((selected) => selected.code === item.code),
    })));

    const quickAddButtonText = computed(() => {
      const count = quickAddSelection.value.length;
      return count > 0 ? `添加${count}只` : '添加';
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
        label: '总持仓市值',
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
      const labelSet = new Set(labels);
      const positionItems = portfolioItems.value.filter((item) => item?.has_position);
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
          if (!normalized || !Number.isFinite(nav) || !labelSet.has(normalized)) return;
          pointMap[normalized] = nav;
        });

        if (String(item.current_nav_source || '') === 'estimated') {
          const liveMinute = normalizeToStepMinute(toMinute(item.gztime) || nowMinute);
          const liveNav = parseNumber(item.current_nav);
          if (liveMinute && Number.isFinite(liveNav) && labelSet.has(liveMinute)) {
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
      fundMetaMap.value[currentFundCode.value]?.group_name || '全部'
    ));

    const quickAddGroupLabel = computed(() => {
      if (!quickAddGroupId.value) return '不分组';
      const matchedGroup = fundGroups.value.find((group) => String(group.id) === String(quickAddGroupId.value));
      return matchedGroup?.name || '不分组';
    });

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

      if (selectedGroupId.value && !fundGroups.value.some((group) => String(group.id) === String(selectedGroupId.value))) {
        selectedGroupId.value = '';
      }

      if (quickAddGroupId.value && !fundGroups.value.some((group) => String(group.id) === String(quickAddGroupId.value))) {
        quickAddGroupId.value = '';
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

    const refreshSnapshot = async () => {
      const snapshot = await fetchUserFundsMeta(clientId.value);
      syncSnapshot(snapshot);
      return snapshot;
    };

    const applyPortfolioPayload = (portfolio) => {
      const nextState = buildPortfolioViewState(
        portfolio,
        fundMetaMap.value,
        portfolioSummary.value
      );
      funds.value = nextState.funds;
      portfolioItems.value = nextState.items;
      portfolioSummary.value = nextState.summary;
      fundListVersion.value += 1;
      return nextState.items;
    };

    const applyBootstrapPayload = (payload) => {
      const snapshot = payload?.snapshot || {};
      const portfolio = payload?.portfolio || {};

      syncSnapshot(snapshot);
      const normalizedItems = applyPortfolioPayload(portfolio);
      indexes.value = Array.isArray(payload?.indexes) ? payload.indexes : [];

      if (payload?.bootstrapped_legacy) {
        clearSavedCodes();
      }

      return normalizedItems;
    };

    const fetchFunds = async (options = {}) => {
      const { force = false, silent = false } = options;
      if (!force && (!isPageVisible() || !isTradingSessionOpen() || savedCodes.value.length === 0)) {
        return;
      }
      if (fundsRefreshPromise) {
        return fundsRefreshPromise;
      }

      const task = (async () => {
        if (!silent) {
          loading.value = true;
        }
        try {
          applyPortfolioPayload(await fetchPortfolio(clientId.value));
          lastUpdateTime.value = new Date().toLocaleTimeString();
          await renderPortfolioProfitVisuals();
        } catch (error) {
          console.error('刷新组合数据失败:', error);
        } finally {
          if (!silent) {
            loading.value = false;
          }
        }
      })();

      fundsRefreshPromise = task;
      try {
        return await task;
      } finally {
        if (fundsRefreshPromise === task) {
          fundsRefreshPromise = null;
        }
      }
    };

    const fetchIndexes = async (options = {}) => {
      const { force = false } = options;
      if (!force && (!isPageVisible() || !isTradingSessionOpen())) {
        return;
      }
      if (indexesRefreshPromise) {
        return indexesRefreshPromise;
      }

      const task = (async () => {
        indexes.value = await fetchIndexesRaw();
      })();

      indexesRefreshPromise = task;
      try {
        return await task;
      } finally {
        if (indexesRefreshPromise === task) {
          indexesRefreshPromise = null;
        }
      }
    };

    const loadMarketStatus = async () => {
      try {
        const result = await fetchMarketStatus();
        if (result?.success !== false && typeof result?.is_trading_day === 'boolean') {
          isTodayTradingDay.value = result.is_trading_day;
        }
      } catch (error) {
        console.warn('Failed to load market status:', error);
      }
    };

    const fetchData = async () => {
      loading.value = true;
      try {
        const legacyCodes = loadSavedCodes();
        const quoteList = applyBootstrapPayload(await fetchDashboardBootstrap(clientId.value, legacyCodes));
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

        schedulePortfolioProfitRender();
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

    const loadCurrentDetailTransactions = async () => {
      if (!currentFundCode.value) return false;
      const fund = funds.value.find((item) => item.code === currentFundCode.value) || {
        code: currentFundCode.value,
        name: currentFundName.value || detailBasicView.value?.name || currentFundCode.value
      };
      return await transactions.loadTransactionHistoryForFund(fund);
    };

    const setDetailTab = async (tab) => {
      if (detailTab.value === tab) {
        if (tab === 'overview') await renderDetailVisuals();
        if (tab === 'history') await ensureHistoryRange(historyRangeDays.value);
        if (tab === 'transactions') await loadCurrentDetailTransactions();
        return;
      }

      if (tab === 'transactions') {
        if (!currentFundCode.value) {
          detailTab.value = tab;
          return;
        }
        detailTab.value = tab;
        await loadCurrentDetailTransactions();
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
      if (detailTab.value === 'transactions') await loadCurrentDetailTransactions();
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

      const groupId = selectedGroupId.value || '';
      const results = await Promise.all(incoming.map((code) => saveUserFund(clientId.value, code, groupId)));
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
      const result = await createFundGroup(clientId.value, newGroupName.value.trim());
      if (result.error) {
        alert(result.error);
        return;
      }

      newGroupName.value = '';
      addingGroupInline.value = false;
      mobileGroupActionsId.value = '';
      await refreshSnapshot();
      selectedGroupId.value = String(result.id);
    };

    const openInlineGroupCreate = async () => {
      editingGroupId.value = '';
      editingGroupName.value = '';
      mobileGroupActionsId.value = '';
      groupActionError.value = '';
      addingGroupInline.value = true;
      await nextTick();
      const input = document.getElementById('inlineGroupNameInput');
      input?.focus();
    };

    const closeInlineGroupCreate = () => {
      addingGroupInline.value = false;
      newGroupName.value = '';
      mobileGroupActionsId.value = '';
    };

    const clearQuickSearchTimer = () => {
      if (!quickSearchTimer) return;
      clearTimeout(quickSearchTimer);
      quickSearchTimer = null;
    };

    const performQuickSearch = async (keyword) => {
      const q = String(keyword || '').trim();
      if (!q) {
        quickSearchResults.value = [];
        quickSearchError.value = '';
        return;
      }
      quickSearchLoading.value = true;
      quickSearchError.value = '';
      try {
        const result = await searchFunds(q, 10);
        if (String(quickSearchInput.value || '').trim() !== q) return;
        quickSearchResults.value = Array.isArray(result) ? result : [];
      } catch {
        quickSearchResults.value = [];
        quickSearchError.value = '搜索失败，请稍后重试';
      } finally {
        if (String(quickSearchInput.value || '').trim() === q) {
          quickSearchLoading.value = false;
        }
      }
    };

    const scheduleQuickSearch = (keyword) => {
      clearQuickSearchTimer();
      const q = String(keyword || '').trim();
      if (!q) {
        quickSearchLoading.value = false;
        quickSearchError.value = '';
        quickSearchResults.value = [];
        quickSearchOpen.value = false;
        return;
      }
      quickSearchOpen.value = true;
      quickSearchTimer = setTimeout(() => {
        performQuickSearch(q);
      }, 200);
    };

    const handleQuickSearchFocus = () => {
      if (quickSearchResultsView.value.length > 0 || quickSearchLoading.value || String(quickSearchInput.value || '').trim()) {
        quickSearchOpen.value = true;
      }
    };

    const focusQuickSearchFirst = () => {
      quickSearchOpen.value = true;
    };

    const toggleQuickAddSelection = (item) => {
      if (!item || !item.code) return;
      const idx = quickAddSelection.value.findIndex((selected) => selected.code === item.code);
      if (idx >= 0) {
        quickAddSelection.value.splice(idx, 1);
        return;
      }
      quickAddSelection.value.push({
        code: item.code,
        name: item.name || item.code
      });
    };

    const removeQuickAddSelection = (code) => {
      quickAddSelection.value = quickAddSelection.value.filter((item) => item.code !== code);
      if (quickAddSelection.value.length === 0 && !String(quickSearchInput.value || '').trim()) {
        quickSearchOpen.value = false;
      }
    };

    const openQuickAddConfirm = () => {
      if (quickAddSelection.value.length === 0) return;
      quickAddGroupId.value = activeGroupId.value !== 'all' ? String(activeGroupId.value) : '';
      quickAddGroupMenuOpen.value = false;
      quickAddConfirmOpen.value = true;
      quickSearchOpen.value = false;
    };

    const closeQuickAddConfirm = () => {
      quickAddGroupMenuOpen.value = false;
      quickAddConfirmOpen.value = false;
    };

    const toggleQuickAddGroupMenu = () => {
      if (!quickAddConfirmOpen.value) return;
      quickAddGroupMenuOpen.value = !quickAddGroupMenuOpen.value;
    };

    const selectQuickAddGroup = (groupId) => {
      quickAddGroupId.value = groupId ? String(groupId) : '';
      quickAddGroupMenuOpen.value = false;
    };

    const confirmQuickAddFunds = async () => {
      if (quickAddSelection.value.length === 0) return;
      quickAddSaving.value = true;
      try {
        const groupId = quickAddGroupId.value || '';
        const results = await Promise.all(
          quickAddSelection.value.map((item) => saveUserFund(clientId.value, item.code, groupId))
        );
        const error = results.find((item) => item.error);
        if (error) {
          alert(error.error || '添加基金失败');
          return;
        }
        quickAddSelection.value = [];
        quickSearchInput.value = '';
        quickSearchResults.value = [];
        quickSearchOpen.value = false;
        quickAddGroupMenuOpen.value = false;
        quickAddConfirmOpen.value = false;
        await fetchData();
      } finally {
        quickAddSaving.value = false;
      }
    };

    const toggleSummaryExpanded = () => {
      if (!isMobileView.value) return;
      summaryExpanded.value = !summaryExpanded.value;
    };

    const handleGroupTabClick = async (group) => {
      if (!group) return;
      const groupId = String(group.id);
      if (String(activeGroupId.value) === groupId && !editingGroupId.value) {
        if (isMobileView.value) {
          mobileGroupActionsId.value = groupId !== 'all' ? groupId : '';
        }
        return;
      }
      if (String(activeGroupId.value) !== groupId) {
        editingGroupId.value = '';
        editingGroupName.value = '';
        groupActionError.value = '';
      }
      mobileGroupActionsId.value = isMobileView.value && groupId !== 'all' ? groupId : '';
      await switchGroup(group.id);
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
      startInlineGroupEdit(activeGroup.value);
    };

    const closeRenameGroupModal = () => {
      groupActionError.value = '';
      renameGroupModal?.hide();
    };

    const confirmRenameGroup = async () => {
      await submitInlineGroupEdit();
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
      const result = await deleteFundGroup(clientId.value, activeGroup.value.id);
      if (result.error) {
        groupActionError.value = result.error;
        deletingGroup.value = false;
        return;
      }
      deletingGroup.value = false;
      closeDeleteGroupModal();
      editingGroupId.value = '';
      editingGroupName.value = '';
      mobileGroupActionsId.value = '';
      activeGroupId.value = 'all';
      await fetchData();
    };

    const startInlineGroupEdit = async (group) => {
      if (!group || group.id === 'all' || group.is_default) return;
      addingGroupInline.value = false;
      editingGroupId.value = String(group.id);
      editingGroupName.value = String(group.name || '');
      mobileGroupActionsId.value = String(group.id);
      groupActionError.value = '';
      await nextTick();
      const input = document.getElementById(`inlineGroupEditInput-${group.id}`);
      input?.focus();
      input?.select?.();
    };

    const cancelInlineGroupEdit = () => {
      editingGroupId.value = '';
      editingGroupName.value = '';
      groupActionError.value = '';
      if (!isMobileView.value) return;
      mobileGroupActionsId.value = '';
    };

    const submitInlineGroupEdit = async () => {
      if (!editingGroupId.value) return;
      const nextName = editingGroupName.value.trim();
      if (!nextName) {
        groupActionError.value = '分组名称不能为空';
        return;
      }
      renamingGroup.value = true;
      groupActionError.value = '';
      const result = await renameFundGroup(clientId.value, editingGroupId.value, nextName);
      if (result.error) {
        groupActionError.value = result.error;
        renamingGroup.value = false;
        return;
      }
      renamingGroup.value = false;
      editingGroupId.value = '';
      editingGroupName.value = '';
      mobileGroupActionsId.value = '';
      await fetchData();
    };

    const changeFundGroup = async (code, groupId) => {
      const result = await moveUserFundGroup(clientId.value, code, groupId);
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
      closeHoldingActionModal();
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
        const result = await updateUserFundPosition(clientId.value, positionForm.value.code, {
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
      closeHoldingActionModal();
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
        await deleteUserFund(clientId.value, code);
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
        await Promise.all(savedCodes.value.map((code) => deleteUserFund(clientId.value, code)));
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

    const timers = createRefreshTimers({
      fetchFunds: () => fetchFunds({ silent: true }),
      fetchIndexes: () => fetchIndexes({ silent: true })
    });

    const startClockTimer = () => {
      if (clockTimer) clearInterval(clockTimer);
      clockTimer = setInterval(() => {
        now.value = new Date();
        if (now.value.getHours() === 0 && now.value.getMinutes() === 0 && now.value.getSeconds() < 2) {
          loadMarketStatus();
        }
      }, 1000);
    };

    const stopClockTimer = () => {
      if (clockTimer) clearInterval(clockTimer);
      clockTimer = null;
    };

    onMounted(() => {
      initTheme();
      checkReleaseNotice();
      loadAuthState();
      loadMarketStatus();
      fetchData();
      nextTick(() => {
        ensureGroupModals();
        bindModalLazyImages();
        bindStickyPanelObserver();
      });
      startClockTimer();
      timers.start();
      isMobileView.value = isMobileViewport();
      outsideClickHandler = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        if (!target.closest('.topbar-fund-search')) {
          quickSearchOpen.value = false;
        }
        if (!target.closest('.user-menu')) {
          authMenuOpen.value = false;
        }
        if (!target.closest('.group-panel') && !editingGroupId.value) {
          mobileGroupActionsId.value = '';
        }
      };
      document.addEventListener('click', outsideClickHandler);
      visibilityChangeHandler = () => {
        if (!isPageVisible()) return;
        fetchFunds({ silent: true });
        fetchIndexes({ silent: true });
      };
      document.addEventListener('visibilitychange', visibilityChangeHandler);
      resizeHandler = () => {
        isMobileView.value = isMobileViewport();
        if (!isMobileView.value) {
          summaryExpanded.value = true;
          mobileActiveTab.value = 'home';
          editingGroupId.value = '';
          editingGroupName.value = '';
          mobileGroupActionsId.value = '';
          groupActionError.value = '';
        }
        updateDesktopStickyOffsets();
        resizeDetailCharts();
        if (!isMobileViewport()) {
          closeMobileDetail();
        }
      };
      window.addEventListener('resize', resizeHandler);
    });

    watch(
      () => [portfolioIntradayChartData.value, theme.value],
      () => {
        schedulePortfolioProfitRender();
      }
    );

    onUnmounted(() => {
      timers.stop();
      stopClockTimer();
      clearQuickSearchTimer();
      if (portfolioRenderTimer) {
        clearTimeout(portfolioRenderTimer);
        portfolioRenderTimer = null;
      }
      disposeCharts();
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler);
        resizeHandler = null;
      }
      if (outsideClickHandler) {
        document.removeEventListener('click', outsideClickHandler);
        outsideClickHandler = null;
      }
      if (visibilityChangeHandler) {
        document.removeEventListener('visibilitychange', visibilityChangeHandler);
        visibilityChangeHandler = null;
      }
      stickyPanelResizeObserver?.disconnect();
      stickyPanelResizeObserver = null;
      syncBodyDetailState(false);
    });

    watch(quickSearchInput, (value) => {
      scheduleQuickSearch(value);
    });

    watch(
      () => quickAddSelection.value.length,
      async () => {
        await nextTick();
        updateDesktopStickyOffsets();
      }
    );

    return {
      codeInput,
      selectedGroupId,
      newGroupName,
      savedCodes,
      clientId,
      authUser,
      authMenuOpen,
      authModalOpen,
      authMode,
      authLoading,
      authError,
      authForm,
      mobileActiveTab,
      earningsViewOpen,
      earningsLoading,
      earningsError,
      earningsMode,
      earningsViewMode,
      earningsLoaded,
      earningsSelectedDate,
      earningsSelectedMonth,
      earningsSelectedYear,
      earningsRankTab,
      dailyEarnings,
      earningsCalendarTitle,
      earningsSummaryTitle,
      earningsDisplaySummaryTitle,
      earningsDisplaySummary,
      earningsSummaryBadge,
      earningsBoardTitle,
      earningsCalendarDays,
      earningsMonthCells,
      earningsYearCells,
      earningsTodayLiveDay,
      earningsMergedDays,
      earningsRankItems,
      earningsRankMaxValue,
      accountDisplayName,
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
      editingGroupId,
      editingGroupName,
      mobileGroupActionsId,
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
      quickSearchInput,
      quickSearchResults,
      quickSearchResultsView,
      quickSearchLoading,
      quickSearchError,
      quickSearchOpen,
        quickAddSelection,
        quickAddConfirmOpen,
        quickAddGroupId,
        quickAddGroupMenuOpen,
        quickAddGroupLabel,
        quickAddSaving,
        quickAddButtonText,
      summaryExpanded,
      isMobileView,
      deletingFund,
      fundActionError,
      pendingDeleteFund,
      holdingActionFund,
      clearingAllFunds,
      savingPosition,
      positionActionError,
      releaseNoticeOpen,
      releaseNoticeVersion: RELEASE_NOTICE_VERSION,
      releaseNoticeTitle: RELEASE_NOTICE_TITLE,
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
      toggleAuthMenu,
      switchMobileTab,
      openAuthModal,
      closeAuthModal,
      switchAuthMode,
      submitAuthForm,
      logoutAccount,
      openMyEarnings: openMyEarningsPage,
      closeMyEarnings,
      loadDailyEarnings,
      setEarningsMode,
      setEarningsViewMode,
      selectEarningsDate,
      selectEarningsMonth,
      selectEarningsYear,
      setEarningsRankTab,
      shiftEarningsPeriod,
      shiftEarningsMonth,
      formatEarningsValue,
      earningsValueClass,
      openHoldingActionModal,
      closeHoldingActionModal,
      openTradePlaceholder,
      openConversionModal: conversion.openConversionModal,
      closeConversionModal: conversion.closeConversionModal,
      conversionModalOpen: conversion.conversionModalOpen,
      conversionConfirmOpen: conversion.conversionConfirmOpen,
      conversionFund: conversion.conversionFund,
      conversionTarget: conversion.conversionTarget,
      conversionForm: conversion.conversionForm,
      conversionError: conversion.conversionError,
      conversionSaving: conversion.conversionSaving,
      conversionPreviewLoading: conversion.conversionPreviewLoading,
      conversionSearchKeyword: conversion.conversionSearchKeyword,
      conversionSearchResults: conversion.conversionSearchResults,
      conversionSearchLoading: conversion.conversionSearchLoading,
      conversionDatePickerOpen: conversion.conversionDatePickerOpen,
      setConvertAllShares: conversion.setConvertAllShares,
      searchConversionTargets: conversion.searchConversionTargets,
      selectConversionTarget: conversion.selectConversionTarget,
      openConversionConfirm: conversion.openConversionConfirm,
      closeConversionConfirm: conversion.closeConversionConfirm,
      submitConversion: conversion.submitConversion,
      conversionConfirmRows: conversion.conversionConfirmRows,
      formatConversionMoney: conversion.formatConversionMoney,
      formatConversionShares: conversion.formatConversionShares,
      formatAvailableConversionShares: conversion.formatAvailableConversionShares,
      conversionCalendarTitle: conversion.conversionCalendarTitle,
      getConversionCalendarDays: conversion.getConversionCalendarDays,
      toggleConversionDatePicker: conversion.toggleConversionDatePicker,
      closeConversionDatePicker: conversion.closeConversionDatePicker,
      shiftConversionCalendarMonth: conversion.shiftConversionCalendarMonth,
      selectConversionDate: conversion.selectConversionDate,
      dcaModalOpen: dca.dcaModalOpen,
      dcaFund: dca.dcaFund,
      dcaForm: dca.dcaForm,
      dcaPlan: dca.dcaPlan,
      dcaLoading: dca.dcaLoading,
      dcaSaving: dca.dcaSaving,
      dcaDeleting: dca.dcaDeleting,
      dcaError: dca.dcaError,
      dcaFieldErrors: dca.dcaFieldErrors,
      dcaDatePickerOpen: dca.dcaDatePickerOpen,
      dcaDatePickerPlacement: dca.dcaDatePickerPlacement,
      dcaCycleOptions: dca.dcaCycleOptions,
      dcaMonthlyDays: dca.dcaMonthlyDays,
      dcaWeekdayOptions: dca.dcaWeekdayOptions,
      dcaNextRunText: dca.dcaNextRunText,
      dcaCycleText: dca.dcaCycleText,
      openDcaModal: dca.openDcaModal,
      closeDcaModal: dca.closeDcaModal,
      submitDcaPlan: dca.submitDcaPlan,
      removeDcaPlan: dca.removeDcaPlan,
      clearDcaFieldError: dca.clearDcaFieldError,
      formatDcaDate: dca.formatDcaDate,
      dcaCalendarTitle: dca.dcaCalendarTitle,
      getDcaCalendarDays: dca.getDcaCalendarDays,
      toggleDcaDatePicker: dca.toggleDcaDatePicker,
      closeDcaDatePicker: dca.closeDcaDatePicker,
      shiftDcaCalendarMonth: dca.shiftDcaCalendarMonth,
      selectDcaDate: dca.selectDcaDate,
      transactionModalOpen: transactions.transactionModalOpen,
      transactionMode: transactions.transactionMode,
      transactionFund: transactions.transactionFund,
      transactionForm: transactions.transactionForm,
      transactionSaving: transactions.transactionSaving,
      transactionError: transactions.transactionError,
      transactionHistoryOpen: transactions.transactionHistoryOpen,
      transactionConfirmOpen: transactions.transactionConfirmOpen,
      transactionConfirmError: transactions.transactionConfirmError,
      transactionPreviewLoading: transactions.transactionPreviewLoading,
      transactionHistoryFund: transactions.transactionHistoryFund,
      transactionHistoryLoading: transactions.transactionHistoryLoading,
      transactionHistoryError: transactions.transactionHistoryError,
      transactionHistoryItems: transactions.transactionHistoryItems,
      deletingTransactionId: transactions.deletingTransactionId,
      transactionDatePickerOpen: transactions.transactionDatePickerOpen,
      openTransactionModal: transactions.openTransactionModal,
      closeTransactionModal: transactions.closeTransactionModal,
      closeTransactionConfirm: transactions.closeTransactionConfirm,
      openTransactionConfirm: transactions.openTransactionConfirm,
      submitTransaction: transactions.submitTransaction,
      openTransactionHistory: transactions.openTransactionHistory,
      loadTransactionHistoryForFund: transactions.loadTransactionHistoryForFund,
      closeTransactionHistory: transactions.closeTransactionHistory,
      removeTransaction: transactions.removeTransaction,
      transactionPreview: transactions.transactionPreview,
      transactionConfirmTitle: transactions.transactionConfirmTitle,
      transactionConfirmActionText: transactions.transactionConfirmActionText,
      transactionConfirmRows: transactions.transactionConfirmRows,
      formatTransactionDate: transactions.formatTransactionDate,
      transactionCalendarTitle: transactions.transactionCalendarTitle,
      getTransactionCalendarDays: transactions.getTransactionCalendarDays,
      toggleTransactionDatePicker: transactions.toggleTransactionDatePicker,
      closeTransactionDatePicker: transactions.closeTransactionDatePicker,
      shiftTransactionCalendarMonth: transactions.shiftTransactionCalendarMonth,
      selectTransactionDate: transactions.selectTransactionDate,
      formatTransactionMoney: transactions.formatTransactionMoney,
      formatTransactionShares: transactions.formatTransactionShares,
      formatTransactionNav: transactions.formatTransactionNav,
      transactionTypeLabel: transactions.transactionTypeLabel,
      confirmReleaseNotice,
      setDetailTab,
      ensureHistoryRange,
      toggleSort,
      toggleSummaryExpanded,
      addFunds,
      addGroup,
      openInlineGroupCreate,
      closeInlineGroupCreate,
      startInlineGroupEdit,
      cancelInlineGroupEdit,
      submitInlineGroupEdit,
      handleQuickSearchFocus,
      focusQuickSearchFirst,
      toggleQuickAddSelection,
        removeQuickAddSelection,
        openQuickAddConfirm,
        closeQuickAddConfirm,
        toggleQuickAddGroupMenu,
        selectQuickAddGroup,
        confirmQuickAddFunds,
      openRenameGroupModal,
      closeRenameGroupModal,
      confirmRenameGroup,
      openDeleteGroupModal,
      closeDeleteGroupModal,
      confirmDeleteGroup,
      changeFundGroup,
      handleGroupTabClick,
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
      formatInlineCurrency,
      getDisplayEstimatedNav,
      getDisplayUnitNav,
      formatNavValue,
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
