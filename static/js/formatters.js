const SAVED_CODES_KEY = 'myFundCodes';

export const EMPTY_DETAIL = () => ({
  basic: {},
  holdings: { holdings: [] },
  history: { data: [] },
  intraday: { data: [] }
});

export const loadSavedCodes = () => {
  try {
    return JSON.parse(localStorage.getItem(SAVED_CODES_KEY) || '[]');
  } catch {
    return [];
  }
};

export const saveCodes = (codes) => {
  localStorage.setItem(SAVED_CODES_KEY, JSON.stringify(codes));
};

export const toNumber = (val) => {
  if (val === null || val === undefined) return NaN;
  if (typeof val === 'number') return val;
  const match = String(val).trim().match(/-?\d+(\.\d+)?/);
  return match ? parseFloat(match[0]) : NaN;
};

export const formatChange = (val, digits = 2, withSign = true) => {
  const n = toNumber(val);
  if (!Number.isFinite(n)) return '-';
  if (n === 0) return `0.${'0'.repeat(digits)}`;
  return withSign ? `${n > 0 ? '+' : ''}${n.toFixed(digits)}` : n.toFixed(digits);
};

export const getColorClass = (val) => {
  const n = toNumber(val);
  if (!Number.isFinite(n) || n === 0) return '';
  return n > 0 ? 'up' : 'down';
};

export const getIndexCardClass = (val) => {
  const n = toNumber(val);
  if (!Number.isFinite(n) || n === 0) return 'index-flat';
  return n > 0 ? 'index-up' : 'index-down';
};

export const getSortIcon = (sortDir) => {
  if (sortDir === 'asc') return '^';
  if (sortDir === 'desc') return 'v';
  return '↕';
};

export const getMarketStatus = (date) => {
  const minutes = date.getHours() * 60 + date.getMinutes();
  if (minutes >= 540 && minutes < 570) return { text: '集合竞价', className: 'market-preopen' };
  if (minutes >= 570 && minutes < 690) return { text: '开盘中', className: 'market-open' };
  if (minutes >= 690 && minutes < 780) return { text: '午盘休息', className: 'market-break' };
  if (minutes >= 780 && minutes < 900) return { text: '开盘中', className: 'market-open' };
  if (minutes >= 900) return { text: '已收盘', className: 'market-closed' };
  return { text: '未开盘', className: 'market-pending' };
};
