export const INTRADAY_CACHE_KEY = 'fundIntradaySnapshotsV1';
export const INTRADAY_STEP_MINUTES = 3;

export const TRADING_MINUTES = (() => {
  const list = [];
  let h = 9;
  let m = 30;
  while (h < 15 || (h === 15 && m === 0)) {
    list.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
    m += INTRADAY_STEP_MINUTES;
    if (m >= 60) {
      h += 1;
      m = 0;
    }
  }
  return list;
})();

export const getTodayDate = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export const toMinute = (s) => {
  if (!s || typeof s !== 'string') return '';
  const m = s.match(/(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : '';
};

export const formatMinuteNow = () => {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

export const minuteToIndex = (minute) => {
  const m = toMinute(minute);
  if (!m) return -1;
  const [h, mm] = m.split(':').map((v) => parseInt(v, 10));
  if (!Number.isFinite(h) || !Number.isFinite(mm)) return -1;
  const raw = (h - 9) * 60 + (mm - 30);
  const idx = Math.floor(raw / INTRADAY_STEP_MINUTES);
  if (idx < 0) return 0;
  if (idx >= TRADING_MINUTES.length) return TRADING_MINUTES.length - 1;
  return idx;
};

export const normalizeToStepMinute = (minute) => {
  const m = toMinute(minute);
  if (!m) return '';
  const [rawH, rawM] = m.split(':').map((v) => parseInt(v, 10));
  if (!Number.isFinite(rawH) || !Number.isFinite(rawM)) return '';
  const bucket = Math.floor((rawH * 60 + rawM) / INTRADAY_STEP_MINUTES) * INTRADAY_STEP_MINUTES;
  const h = Math.floor(bucket / 60);
  const mm = bucket % 60;
  return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
};

export const readIntradayCache = () => {
  try {
    const raw = localStorage.getItem(INTRADAY_CACHE_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
};

export const writeIntradayCache = (data) => {
  localStorage.setItem(INTRADAY_CACHE_KEY, JSON.stringify(data));
};

export const saveFundSnapshotsToCache = (fundList) => {
  if (!Array.isArray(fundList) || fundList.length === 0) return;
  const today = getTodayDate();
  const cache = readIntradayCache();
  Object.keys(cache).forEach((d) => {
    if (d !== today) delete cache[d];
  });
  cache[today] = cache[today] || {};

  fundList.forEach((f) => {
    if (!f || !f.code) return;
    const price = parseFloat(f.gsz);
    if (!Number.isFinite(price)) return;
    const minute = toMinute(f.gztime) || formatMinuteNow();
    const codeMap = cache[today][f.code] || {};
    codeMap[minute] = price;
    cache[today][f.code] = codeMap;
  });

  writeIntradayCache(cache);
};
