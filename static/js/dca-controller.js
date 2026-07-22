import {
  deleteDcaPlan,
  fetchDcaPlan,
  saveDcaPlan,
} from './api.js?v=__APP_ASSET_VERSION__';

const { ref, computed, nextTick } = window.Vue;

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
  enabled: true,
  amount: '',
  fee_rate: '0',
  cycle: 'monthly',
  first_date: today(),
  weekly_day: 0,
  monthly_day: 8,
});

const parseNumber = (value) => {
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : NaN;
};

const cycleLabels = {
  daily: '每日',
  weekly: '每周',
  biweekly: '每两周',
  monthly: '每月',
};

const weekdayOptions = [
  { value: 0, label: '周一' },
  { value: 1, label: '周二' },
  { value: 2, label: '周三' },
  { value: 3, label: '周四' },
  { value: 4, label: '周五' },
];

export const createDcaController = ({
  authUser,
  clientId,
  openAuthModal,
  closeHoldingActionModal,
  refreshData,
}) => {
  const dcaModalOpen = ref(false);
  const dcaFund = ref(null);
  const dcaForm = ref(emptyForm());
  const dcaPlan = ref(null);
  const dcaLoading = ref(false);
  const dcaSaving = ref(false);
  const dcaDeleting = ref(false);
  const dcaError = ref('');
  const dcaFieldErrors = ref({});
  const dcaDatePickerOpen = ref(false);
  const dcaDatePickerMonth = ref(dateFromText(today()));
  const dcaDatePickerPlacement = ref('down');

  const requireAuth = () => {
    if (authUser.value) return true;
    closeHoldingActionModal?.();
    openAuthModal?.('login');
    return false;
  };

  const normalizePlanToForm = (plan) => {
    if (!plan) return emptyForm();
    return {
      enabled: Boolean(plan.enabled),
      amount: plan.amount != null ? String(plan.amount) : '',
      fee_rate: plan.fee_rate != null ? String(plan.fee_rate) : '0',
      cycle: plan.cycle || 'monthly',
      first_date: plan.first_date || today(),
      weekly_day: plan.weekly_day != null ? Number(plan.weekly_day) : 0,
      monthly_day: plan.monthly_day != null ? Number(plan.monthly_day) : 8,
    };
  };

  const loadDcaPlan = async (fund) => {
    dcaLoading.value = true;
    dcaError.value = '';
    dcaFieldErrors.value = {};
    try {
      const result = await fetchDcaPlan(clientId.value, fund.code);
      if (result?.error || result?.success === false) {
        dcaError.value = result?.error || '加载定投计划失败';
        dcaPlan.value = null;
        dcaForm.value = emptyForm();
        return;
      }
      dcaPlan.value = result.plan || null;
      dcaForm.value = normalizePlanToForm(result.plan);
      dcaDatePickerMonth.value = dateFromText(dcaForm.value.first_date);
    } catch {
      dcaError.value = '加载定投计划失败';
      dcaPlan.value = null;
      dcaForm.value = emptyForm();
    } finally {
      dcaLoading.value = false;
    }
  };

  const openDcaModal = async (fund) => {
    if (!requireAuth()) return;
    if (!fund?.code) return;
    closeHoldingActionModal?.();
    dcaFund.value = fund;
    dcaPlan.value = null;
    dcaForm.value = emptyForm();
    dcaDatePickerMonth.value = dateFromText(dcaForm.value.first_date);
    dcaDatePickerOpen.value = false;
    dcaError.value = '';
    dcaFieldErrors.value = {};
    dcaModalOpen.value = true;
    await loadDcaPlan(fund);
  };

  const closeDcaModal = (options = {}) => {
    const { force = false } = options;
    if (!force && (dcaSaving.value || dcaDeleting.value)) return;
    dcaModalOpen.value = false;
    dcaFund.value = null;
    dcaPlan.value = null;
    dcaForm.value = emptyForm();
    dcaDatePickerOpen.value = false;
    dcaError.value = '';
    dcaFieldErrors.value = {};
  };

  const clearDcaFieldError = (field) => {
    if (!dcaFieldErrors.value[field]) return;
    dcaFieldErrors.value = {
      ...dcaFieldErrors.value,
      [field]: ''
    };
  };

  const formatDcaDate = (value) => String(value || '').replaceAll('-', '/');

  const dcaCalendarTitle = () => {
    const month = dcaDatePickerMonth.value;
    return `${month.getFullYear()}年${pad2(month.getMonth() + 1)}月`;
  };

  const getDcaCalendarDays = () => {
    const month = dcaDatePickerMonth.value;
    const year = month.getFullYear();
    const monthIndex = month.getMonth();
    const first = new Date(year, monthIndex, 1);
    const firstWeekday = first.getDay();
    const start = new Date(year, monthIndex, 1 - firstWeekday);
    const selected = dcaForm.value.first_date;
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

  const updateDcaDatePickerPlacement = (target) => {
    const el = target?.closest?.('.transaction-date-wrap') || target;
    const rect = el?.getBoundingClientRect?.();
    if (!rect) {
      dcaDatePickerPlacement.value = 'down';
      return;
    }
    const estimatedHeight = 338;
    const below = window.innerHeight - rect.bottom;
    const above = rect.top;
    dcaDatePickerPlacement.value = below < estimatedHeight && above > below ? 'up' : 'down';
  };

  const toggleDcaDatePicker = async (event) => {
    if (!dcaDatePickerOpen.value) {
      dcaDatePickerMonth.value = dateFromText(dcaForm.value.first_date);
      updateDcaDatePickerPlacement(event?.currentTarget);
    }
    dcaDatePickerOpen.value = !dcaDatePickerOpen.value;
    if (dcaDatePickerOpen.value) {
      await nextTick();
      updateDcaDatePickerPlacement(event?.currentTarget);
    }
  };

  const closeDcaDatePicker = () => {
    dcaDatePickerOpen.value = false;
  };

  const shiftDcaCalendarMonth = (offset) => {
    const month = dcaDatePickerMonth.value;
    dcaDatePickerMonth.value = new Date(month.getFullYear(), month.getMonth() + offset, 1);
  };

  const selectDcaDate = (value) => {
    dcaForm.value.first_date = value;
    dcaDatePickerMonth.value = dateFromText(value);
    dcaDatePickerOpen.value = false;
    clearDcaFieldError('first_date');
  };

  const buildPayload = () => {
    const form = dcaForm.value;
    const amount = parseNumber(form.amount);
    const feeRate = parseNumber(form.fee_rate || 0);
    const errors = {};
    if (!Number.isFinite(amount) || amount <= 0) {
      errors.amount = '请输入大于 0 的定投金额';
    }
    if (!Number.isFinite(feeRate) || feeRate < 0) {
      errors.fee_rate = '费率不能为负数';
    }
    if (!form.first_date) {
      errors.first_date = '请选择首次定投日期';
    }
    dcaFieldErrors.value = errors;
    if (Object.keys(errors).length > 0) {
      throw new Error('请检查定投计划信息');
    }
    return {
      enabled: Boolean(form.enabled),
      amount,
      fee_rate: feeRate,
      cycle: form.cycle,
      first_date: form.first_date,
      weekly_day: Number(form.weekly_day),
      monthly_day: Number(form.monthly_day),
    };
  };

  const submitDcaPlan = async () => {
    if (!dcaFund.value?.code) return;
    dcaSaving.value = true;
    dcaError.value = '';
    dcaFieldErrors.value = {};
    try {
      const payload = buildPayload();
      const result = await saveDcaPlan(clientId.value, dcaFund.value.code, payload);
      if (result?.error || result?.success === false) {
        dcaError.value = result?.error || '保存定投计划失败';
        return;
      }
      dcaPlan.value = result.plan || null;
      dcaForm.value = normalizePlanToForm(result.plan);
      closeDcaModal({ force: true });
      refreshData?.().catch((error) => {
        console.error('Failed to refresh data after saving DCA plan:', error);
      });
    } catch (error) {
      dcaError.value = error?.message || '保存定投计划失败';
    } finally {
      dcaSaving.value = false;
    }
  };

  const removeDcaPlan = async () => {
    if (!dcaFund.value?.code || !dcaPlan.value) return;
    dcaDeleting.value = true;
    dcaError.value = '';
    try {
      const result = await deleteDcaPlan(clientId.value, dcaFund.value.code);
      if (result?.error || result?.success === false) {
        dcaError.value = result?.error || '删除定投计划失败';
        return;
      }
      dcaPlan.value = null;
      dcaForm.value = emptyForm();
      await refreshData?.();
      closeDcaModal({ force: true });
    } catch {
      dcaError.value = '删除定投计划失败';
    } finally {
      dcaDeleting.value = false;
    }
  };

  const dcaCycleOptions = computed(() => ([
    { value: 'daily', label: '每日' },
    { value: 'weekly', label: '每周' },
    { value: 'biweekly', label: '每两周' },
    { value: 'monthly', label: '每月' },
  ]));

  const dcaMonthlyDays = computed(() => Array.from({ length: 28 }, (_, index) => index + 1));

  const dcaNextRunText = computed(() => {
    const next = dcaPlan.value?.next_run_date;
    if (!next) return '保存后由系统计算';
    return next;
  });

  const dcaCycleText = computed(() => cycleLabels[dcaForm.value.cycle] || '每月');

  return {
    dcaModalOpen,
    dcaFund,
    dcaForm,
    dcaPlan,
    dcaLoading,
    dcaSaving,
    dcaDeleting,
    dcaError,
    dcaFieldErrors,
    dcaDatePickerOpen,
    dcaDatePickerPlacement,
    dcaCycleOptions,
    dcaMonthlyDays,
    dcaWeekdayOptions: weekdayOptions,
    dcaNextRunText,
    dcaCycleText,
    openDcaModal,
    closeDcaModal,
    submitDcaPlan,
    removeDcaPlan,
    clearDcaFieldError,
    formatDcaDate,
    dcaCalendarTitle,
    getDcaCalendarDays,
    toggleDcaDatePicker,
    closeDcaDatePicker,
    shiftDcaCalendarMonth,
    selectDcaDate,
  };
};
