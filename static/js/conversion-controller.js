import {
  createFundConversion,
  previewFundConversion,
  searchFunds,
} from './api.js';

const { ref, computed } = window.Vue;

const pad2 = (value) => String(value).padStart(2, '0');
const formatDateText = (date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
const today = () => formatDateText(new Date());

const dateFromText = (value) => {
  const raw = String(value || '');
  const matched = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!matched) return new Date();
  return new Date(Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]));
};

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
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const floorShares = (value) => {
  const n = parseNumber(value);
  if (!Number.isFinite(n)) return NaN;
  return Math.floor(n * 100) / 100;
};

const formatAvailableShares = (value) => {
  const n = floorShares(value);
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

const formatNav = (value) => {
  const n = parseNumber(value);
  return Number.isFinite(n) ? n.toFixed(4) : '-';
};

let conversionSearchSeq = 0;

const emptyForm = () => ({
  shares: '',
  submitted_date: today(),
  time_slot: 'BEFORE_1500',
  from_fee_rate: '0',
  to_fee_rate: '0',
  supplement_fee_rate: '0',
});

export const createConversionController = ({
  authUser,
  clientId,
  openAuthModal,
  closeHoldingActionModal,
  refreshData,
}) => {
  const conversionModalOpen = ref(false);
  const conversionConfirmOpen = ref(false);
  const conversionFund = ref(null);
  const conversionTarget = ref(null);
  const conversionForm = ref(emptyForm());
  const conversionError = ref('');
  const conversionSaving = ref(false);
  const conversionPreviewLoading = ref(false);
  const conversionPreviewData = ref(null);
  const conversionSearchKeyword = ref('');
  const conversionSearchResults = ref([]);
  const conversionSearchLoading = ref(false);
  const conversionDatePickerOpen = ref(false);
  const conversionDatePickerMonth = ref(new Date());

  const requireAuth = () => {
    if (authUser.value) return true;
    closeHoldingActionModal?.();
    openAuthModal?.('login');
    return false;
  };

  const openConversionModal = (fund) => {
    if (!requireAuth()) return;
    if (!fund?.code) return;
    closeHoldingActionModal?.();
    conversionFund.value = fund;
    conversionTarget.value = null;
    conversionForm.value = emptyForm();
    conversionError.value = '';
    conversionPreviewData.value = null;
    conversionSearchKeyword.value = '';
    conversionSearchResults.value = [];
    conversionConfirmOpen.value = false;
    conversionModalOpen.value = true;
  };

  const closeConversionModal = (force = false) => {
    if (conversionSaving.value && !force) return;
    conversionModalOpen.value = false;
    conversionConfirmOpen.value = false;
    conversionFund.value = null;
    conversionTarget.value = null;
    conversionForm.value = emptyForm();
    conversionError.value = '';
    conversionPreviewData.value = null;
    conversionSearchKeyword.value = '';
    conversionSearchResults.value = [];
    conversionDatePickerOpen.value = false;
    conversionDatePickerMonth.value = new Date();
  };

  const setConvertAllShares = () => {
    const shares = floorShares(conversionFund.value?.holding_shares);
    if (Number.isFinite(shares) && shares > 0) {
      conversionForm.value.shares = shares.toFixed(2);
    }
  };

  const conversionCalendarTitle = () => {
    const month = conversionDatePickerMonth.value;
    return `${month.getFullYear()}\u5e74${pad2(month.getMonth() + 1)}\u6708`;
  };

  const getConversionCalendarDays = () => {
    const month = conversionDatePickerMonth.value;
    const year = month.getFullYear();
    const monthIndex = month.getMonth();
    const first = new Date(year, monthIndex, 1);
    const start = new Date(year, monthIndex, 1 - first.getDay());
    const selected = conversionForm.value.submitted_date;
    const current = today();
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

  const toggleConversionDatePicker = () => {
    if (!conversionDatePickerOpen.value) {
      conversionDatePickerMonth.value = dateFromText(conversionForm.value.submitted_date);
    }
    conversionDatePickerOpen.value = !conversionDatePickerOpen.value;
  };

  const closeConversionDatePicker = () => {
    conversionDatePickerOpen.value = false;
  };

  const shiftConversionCalendarMonth = (offset) => {
    const month = conversionDatePickerMonth.value;
    conversionDatePickerMonth.value = new Date(month.getFullYear(), month.getMonth() + offset, 1);
  };

  const selectConversionDate = (value) => {
    conversionForm.value.submitted_date = value;
    conversionDatePickerMonth.value = dateFromText(value);
    conversionDatePickerOpen.value = false;
  };

  const searchConversionTargets = async () => {
    const keyword = String(conversionSearchKeyword.value || '').trim();
    conversionTarget.value = null;
    conversionPreviewData.value = null;
    if (!keyword) {
      conversionSearchResults.value = [];
      return;
    }
    const seq = ++conversionSearchSeq;
    conversionSearchLoading.value = true;
    try {
      const result = await searchFunds(keyword, 8);
      if (seq !== conversionSearchSeq) return;
      const fromCode = String(conversionFund.value?.code || '').padStart(6, '0');
      conversionSearchResults.value = (Array.isArray(result) ? result : []).filter((item) => String(item.code || '').padStart(6, '0') !== fromCode);
    } finally {
      if (seq === conversionSearchSeq) {
        conversionSearchLoading.value = false;
      }
    }
  };

  const selectConversionTarget = (item) => {
    conversionTarget.value = item;
    conversionSearchKeyword.value = item?.name ? `${item.name} ${item.code}` : item?.code || '';
    conversionSearchResults.value = [];
    conversionPreviewData.value = null;
  };

  const buildPayload = () => {
    if (!conversionFund.value?.code) throw new Error('请选择转出基金');
    if (!conversionTarget.value?.code) throw new Error('请选择转入基金');
    const shares = parseNumber(conversionForm.value.shares);
    if (!Number.isFinite(shares) || shares <= 0) throw new Error('请输入正确的转出份额');
    return {
      from_fund_code: conversionFund.value.code,
      to_fund_code: conversionTarget.value.code,
      shares,
      submitted_date: conversionForm.value.submitted_date,
      time_slot: conversionForm.value.time_slot,
      from_fee_rate: parseNumber(conversionForm.value.from_fee_rate || 0) || 0,
      to_fee_rate: parseNumber(conversionForm.value.to_fee_rate || 0) || 0,
      supplement_fee_rate: parseNumber(conversionForm.value.supplement_fee_rate || 0) || 0,
    };
  };

  const openConversionConfirm = async () => {
    conversionError.value = '';
    conversionPreviewLoading.value = true;
    try {
      const payload = buildPayload();
      const result = await previewFundConversion(clientId.value, payload);
      if (result?.error || result?.success === false) {
        conversionError.value = result?.error || '转换预览失败';
        return;
      }
      conversionPreviewData.value = result;
      conversionConfirmOpen.value = true;
    } catch (error) {
      conversionError.value = error?.message || '转换预览失败';
    } finally {
      conversionPreviewLoading.value = false;
    }
  };

  const closeConversionConfirm = () => {
    if (conversionSaving.value) return;
    conversionConfirmOpen.value = false;
  };

  const submitConversion = async () => {
    if (conversionSaving.value) return;
    conversionSaving.value = true;
    conversionError.value = '';
    try {
      const result = await createFundConversion(clientId.value, buildPayload());
      if (result?.error || result?.success === false) {
        conversionError.value = result?.error || '转换提交失败';
        return;
      }
      closeConversionModal(true);
      refreshData?.().catch((error) => console.error('Failed to refresh data after conversion:', error));
    } catch (error) {
      conversionError.value = error?.message || '转换提交失败';
    } finally {
      conversionSaving.value = false;
    }
  };

  const conversionConfirmRows = computed(() => {
    const preview = conversionPreviewData.value || {};
    const fund = conversionFund.value || {};
    const target = conversionTarget.value || {};
    return [
      ['转出基金', `${fund.name || fund.code || '-'} #${fund.code || ''}`],
      ['转入基金', `${target.name || target.code || '-'} #${target.code || ''}`],
      ['申请日期', preview.submitted_date || conversionForm.value.submitted_date || '-'],
      ['交易时段', (preview.time_slot || conversionForm.value.time_slot) === 'AFTER_1500' ? '15:00后' : '15:00前'],
      ['转出净值日', preview.from_nav_date || '-'],
      ['转出确认日', preview.from_confirm_date || '-'],
      ['转入净值日', preview.to_nav_date || '-'],
      ['转入确认日', preview.to_confirm_date || '-'],
      ['转出份额', `${formatShares(preview.from_shares)} 份`],
      ['转出净值', formatNav(preview.from_nav)],
      ['预计转出金额', formatMoney(preview.from_amount)],
      ['费用合计', formatMoney((parseNumber(preview.from_fee) || 0) + (parseNumber(preview.to_fee) || 0) + (parseNumber(preview.supplement_fee) || 0))],
      ['预计转入金额', formatMoney(preview.to_amount)],
      ['转入净值', formatNav(preview.to_nav)],
      ['预计转入份额', preview.to_shares ? `${formatShares(preview.to_shares)} 份` : '待确认'],
      ['状态', preview.confirmed ? '已确认' : '待确认'],
    ];
  });

  return {
    conversionModalOpen,
    conversionConfirmOpen,
    conversionFund,
    conversionTarget,
    conversionForm,
    conversionError,
    conversionSaving,
    conversionPreviewLoading,
    conversionPreviewData,
    conversionSearchKeyword,
    conversionSearchResults,
    conversionSearchLoading,
    conversionDatePickerOpen,
    openConversionModal,
    closeConversionModal,
    setConvertAllShares,
    searchConversionTargets,
    selectConversionTarget,
    openConversionConfirm,
    closeConversionConfirm,
    submitConversion,
    conversionConfirmRows,
    formatConversionMoney: formatMoney,
    formatConversionShares: formatShares,
    formatAvailableConversionShares: formatAvailableShares,
    conversionCalendarTitle,
    getConversionCalendarDays,
    toggleConversionDatePicker,
    closeConversionDatePicker,
    shiftConversionCalendarMonth,
    selectConversionDate,
  };
};
