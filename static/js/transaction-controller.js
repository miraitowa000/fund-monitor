import {
  createFundTransaction,
  deleteFundTransaction,
  fetchFundTransactions,
  previewFundTransaction,
} from './api.js';

const { ref } = window.Vue;

const pad2 = (value) => String(value).padStart(2, '0');

const dateFromText = (value) => {
  const raw = String(value || '');
  const matched = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!matched) return new Date();
  return new Date(Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]));
};

const formatDateText = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;

const today = () => {
  const d = new Date();
  return formatDateText(d);
};

const emptyForm = () => ({
  submitted_date: today(),
  time_slot: 'BEFORE_1500',
  amount: '',
  shares: '',
  fee_rate: '0',
  note: ''
});

const parseNumber = (value) => {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : NaN;
};

const formatMoney = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return '-';
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatShares = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return '-';
  return n.toFixed(6).replace(/\.?0+$/, '');
};

const formatConfirmShares = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatNav = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return '-';
  return n.toFixed(4);
};

const transactionTypeLabel = (item = {}) => {
  if (item.type === 'SELL') return '减仓';
  if (item.type === 'CONVERT_OUT') return '转换转出';
  if (item.type === 'CONVERT_IN') return '转换转入';
  if (item.is_dca) return '定投';
  return '加仓';
};

export const createTransactionController = ({
  authUser,
  clientId,
  openAuthModal,
  closeHoldingActionModal,
  refreshData,
}) => {
  const transactionModalOpen = ref(false);
  const transactionMode = ref('buy');
  const transactionFund = ref(null);
  const transactionForm = ref(emptyForm());
  const transactionSaving = ref(false);
  const transactionError = ref('');
  const transactionDatePickerOpen = ref(false);
  const transactionDatePickerMonth = ref(dateFromText(today()));
  const transactionConfirmOpen = ref(false);
  const transactionConfirmPayload = ref(null);
  const transactionConfirmPreview = ref(null);
  const transactionConfirmError = ref('');
  const transactionPreviewLoading = ref(false);

  const transactionHistoryOpen = ref(false);
  const transactionHistoryFund = ref(null);
  const transactionHistoryLoading = ref(false);
  const transactionHistoryError = ref('');
  const transactionHistoryItems = ref([]);
  const deletingTransactionId = ref(null);

  const requireAuth = () => {
    if (authUser.value) return true;
    closeHoldingActionModal?.();
    openAuthModal?.('login');
    return false;
  };

  const openTransactionModal = (mode, fund) => {
    if (!requireAuth()) return;
    if (!fund?.code) return;
    closeHoldingActionModal?.();
    transactionMode.value = mode === 'sell' ? 'sell' : 'buy';
    transactionFund.value = fund;
    transactionForm.value = emptyForm();
    transactionDatePickerMonth.value = dateFromText(transactionForm.value.submitted_date);
    transactionDatePickerOpen.value = false;
    transactionError.value = '';
    transactionConfirmError.value = '';
    transactionConfirmOpen.value = false;
    transactionConfirmPayload.value = null;
    transactionConfirmPreview.value = null;
    transactionModalOpen.value = true;
  };

  const closeTransactionModal = (force = false) => {
    if (transactionSaving.value && !force) return;
    transactionModalOpen.value = false;
    transactionFund.value = null;
    transactionError.value = '';
    transactionForm.value = emptyForm();
    transactionDatePickerOpen.value = false;
    transactionConfirmOpen.value = false;
    transactionConfirmPayload.value = null;
    transactionConfirmPreview.value = null;
    transactionConfirmError.value = '';
  };

  const closeTransactionConfirm = () => {
    if (transactionSaving.value) return;
    transactionConfirmOpen.value = false;
    transactionConfirmError.value = '';
  };

  const formatTransactionDate = (value) => String(value || '').replaceAll('-', '/');

  const transactionCalendarTitle = () => {
    const month = transactionDatePickerMonth.value;
    return `${month.getFullYear()}年${pad2(month.getMonth() + 1)}月`;
  };

  const getTransactionCalendarDays = () => {
    const month = transactionDatePickerMonth.value;
    const year = month.getFullYear();
    const monthIndex = month.getMonth();
    const first = new Date(year, monthIndex, 1);
    const firstWeekday = first.getDay();
    const start = new Date(year, monthIndex, 1 - firstWeekday);
    const selected = transactionForm.value.submitted_date;
    const current = formatDateText(new Date());

    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start.getFullYear(), start.getMonth(), start.getDate() + index);
      const value = formatDateText(date);
      return {
        value,
        day: date.getDate(),
        outside: date.getMonth() !== monthIndex,
        selected: value === selected,
        today: value === current,
      };
    });
  };

  const toggleTransactionDatePicker = () => {
    if (!transactionDatePickerOpen.value) {
      transactionDatePickerMonth.value = dateFromText(transactionForm.value.submitted_date);
    }
    transactionDatePickerOpen.value = !transactionDatePickerOpen.value;
  };

  const closeTransactionDatePicker = () => {
    transactionDatePickerOpen.value = false;
  };

  const shiftTransactionCalendarMonth = (offset) => {
    const month = transactionDatePickerMonth.value;
    transactionDatePickerMonth.value = new Date(month.getFullYear(), month.getMonth() + offset, 1);
  };

  const selectTransactionDate = (value) => {
    transactionForm.value.submitted_date = value;
    transactionDatePickerMonth.value = dateFromText(value);
    transactionDatePickerOpen.value = false;
  };

  const buildPayload = () => {
    const form = transactionForm.value;
    const feeRate = parseNumber(form.fee_rate || 0);
    if (!Number.isFinite(feeRate) || feeRate < 0) {
      throw new Error('费率不能为负数');
    }
    const payload = {
      type: transactionMode.value === 'sell' ? 'SELL' : 'BUY',
      submitted_date: form.submitted_date,
      time_slot: form.time_slot,
      fee_rate: feeRate,
      note: form.note || ''
    };
    if (transactionMode.value === 'sell') {
      const shares = parseNumber(form.shares);
      if (!Number.isFinite(shares) || shares <= 0) {
        throw new Error('减仓份额必须大于 0');
      }
      payload.shares = shares;
    } else {
      const amount = parseNumber(form.amount);
      if (!Number.isFinite(amount) || amount <= 0) {
        throw new Error('加仓金额必须大于 0');
      }
      payload.amount = amount;
    }
    return payload;
  };

  const openTransactionConfirm = async () => {
    transactionError.value = '';
    transactionConfirmError.value = '';
    transactionPreviewLoading.value = true;
    try {
      const payload = buildPayload();
      const preview = await previewFundTransaction(clientId.value, transactionFund.value.code, payload);
      if (preview?.error || preview?.success === false) {
        transactionError.value = preview?.error || '生成交易确认失败';
        return;
      }
      transactionConfirmPayload.value = payload;
      transactionConfirmPreview.value = preview;
      transactionDatePickerOpen.value = false;
      transactionConfirmOpen.value = true;
    } catch (error) {
      transactionError.value = error?.message || '请检查交易信息';
    } finally {
      transactionPreviewLoading.value = false;
    }
  };

  const submitTransaction = async () => {
    if (!transactionFund.value?.code) return;
    const payload = transactionConfirmPayload.value || buildPayload();
    transactionSaving.value = true;
    transactionError.value = '';
    transactionConfirmError.value = '';
    try {
      const result = await createFundTransaction(clientId.value, transactionFund.value.code, payload);
      if (result?.error || result?.success === false) {
        transactionConfirmError.value = result?.error || '保存交易失败';
        return;
      }
      closeTransactionModal(true);
      await refreshData?.();
    } catch (error) {
      transactionConfirmError.value = error?.message || '保存交易失败';
    } finally {
      transactionSaving.value = false;
    }
  };

  const transactionConfirmTitle = () => (transactionMode.value === 'sell' ? '卖出确认' : '买入确认');

  const transactionConfirmActionText = () => {
    if (transactionSaving.value) return '保存中...';
    return transactionMode.value === 'sell' ? '确认卖出' : '确认买入';
  };

  const transactionConfirmRows = () => {
    const payload = transactionConfirmPayload.value || {};
    const preview = transactionConfirmPreview.value || {};
    const fund = transactionFund.value || {};
    const feeRate = parseNumber(preview.fee_rate ?? payload.fee_rate ?? 0);
    const navText = preview.confirmed && preview.nav ? formatNav(preview.nav) : '待查询（加入队列）';
    const rows = [
      ['基金名称', fund.name || fund.code || '-'],
    ];

    if (transactionMode.value === 'sell') {
      rows.push(['卖出份额', `${formatConfirmShares(preview.shares ?? payload.shares)} 份`]);
      rows.push(['卖出费率', `${Number.isFinite(feeRate) ? feeRate.toFixed(2) : '0.00'}%`]);
      rows.push(['参考净值', navText]);
      rows.push(['预计金额', preview.confirmed ? formatMoney(preview.amount) : '待确认']);
      rows.push(['卖出日期', preview.trade_date || payload.submitted_date || '-']);
    } else {
      rows.push(['买入金额', formatMoney(preview.amount ?? payload.amount)]);
      rows.push(['买入费率', `${Number.isFinite(feeRate) ? feeRate.toFixed(2) : '0.00'}%`]);
      rows.push(['参考净值', navText]);
      rows.push(['预估份额', preview.confirmed ? `${formatConfirmShares(preview.shares)} 份` : '待确认']);
      rows.push(['预计手续费', formatMoney(preview.fee)]);
      rows.push(['买入日期', preview.trade_date || payload.submitted_date || '-']);
    }

    rows.push(['交易时段', (preview.time_slot || payload.time_slot) === 'AFTER_1500' ? '15:00后' : '15:00前']);
    return rows;
  };

  const loadTransactionHistory = async (fund) => {
    if (!fund?.code) return;
    transactionHistoryLoading.value = true;
    transactionHistoryError.value = '';
    try {
      const result = await fetchFundTransactions(clientId.value, fund.code);
      if (result?.error || result?.success === false) {
        transactionHistoryItems.value = [];
        transactionHistoryError.value = result?.error || '加载交易记录失败';
        return;
      }
      transactionHistoryItems.value = Array.isArray(result.transactions) ? result.transactions : [];
    } catch {
      transactionHistoryItems.value = [];
      transactionHistoryError.value = '加载交易记录失败';
    } finally {
      transactionHistoryLoading.value = false;
    }
  };

  const openTransactionHistory = async (fund) => {
    if (!requireAuth()) return;
    if (!fund?.code) return;
    closeHoldingActionModal?.();
    transactionHistoryFund.value = fund;
    transactionHistoryItems.value = [];
    transactionHistoryError.value = '';
    transactionHistoryOpen.value = true;
    await loadTransactionHistory(fund);
  };

  const loadTransactionHistoryForFund = async (fund) => {
    if (!authUser.value) {
      transactionHistoryFund.value = fund || null;
      transactionHistoryItems.value = [];
      transactionHistoryError.value = '';
      transactionHistoryLoading.value = false;
      return false;
    }
    if (!fund?.code) return false;
    transactionHistoryFund.value = fund;
    transactionHistoryItems.value = [];
    transactionHistoryError.value = '';
    await loadTransactionHistory(fund);
    return true;
  };

  const closeTransactionHistory = () => {
    if (deletingTransactionId.value) return;
    transactionHistoryOpen.value = false;
    transactionHistoryFund.value = null;
    transactionHistoryItems.value = [];
    transactionHistoryError.value = '';
  };

  const removeTransaction = async (transactionId) => {
    if (!transactionId || !transactionHistoryFund.value?.code) return;
    deletingTransactionId.value = transactionId;
    transactionHistoryError.value = '';
    try {
      const result = await deleteFundTransaction(clientId.value, transactionId);
      if (result?.error || result?.success === false) {
        transactionHistoryError.value = result?.error || '删除交易失败';
        return;
      }
      await loadTransactionHistory(transactionHistoryFund.value);
      await refreshData?.();
    } catch {
      transactionHistoryError.value = '删除交易失败';
    } finally {
      deletingTransactionId.value = null;
    }
  };

  const transactionPreview = () => {
    const form = transactionForm.value;
    const feeRate = parseNumber(form.fee_rate || 0);
    if (!Number.isFinite(feeRate) || feeRate < 0) return '';
    if (transactionMode.value === 'sell') {
      const shares = parseNumber(form.shares);
      if (!Number.isFinite(shares) || shares <= 0) return '';
      return '系统将按确认日净值计算减仓金额';
    }
    const amount = parseNumber(form.amount);
    if (!Number.isFinite(amount) || amount <= 0) return '';
    const fee = amount * feeRate / 100;
    return `预计手续费 ${formatMoney(fee)}，份额按确认日净值计算`;
  };

  return {
    transactionModalOpen,
    transactionMode,
    transactionFund,
    transactionForm,
    transactionSaving,
    transactionError,
    transactionDatePickerOpen,
    transactionConfirmOpen,
    transactionConfirmError,
    transactionPreviewLoading,
    transactionHistoryOpen,
    transactionHistoryFund,
    transactionHistoryLoading,
    transactionHistoryError,
    transactionHistoryItems,
    deletingTransactionId,
    openTransactionModal,
    closeTransactionModal,
    closeTransactionConfirm,
    openTransactionConfirm,
    submitTransaction,
    openTransactionHistory,
    loadTransactionHistoryForFund,
    closeTransactionHistory,
    removeTransaction,
    transactionPreview,
    transactionConfirmTitle,
    transactionConfirmActionText,
    transactionConfirmRows,
    formatTransactionDate,
    transactionCalendarTitle,
    getTransactionCalendarDays,
    toggleTransactionDatePicker,
    closeTransactionDatePicker,
    shiftTransactionCalendarMonth,
    selectTransactionDate,
    formatTransactionMoney: formatMoney,
    formatTransactionShares: formatShares,
    formatTransactionNav: formatNav,
    transactionTypeLabel,
  };
};
