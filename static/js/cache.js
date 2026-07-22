export const INTRADAY_CACHE_KEY = 'fundIntradaySnapshotsV1';
export const INTRADAY_STEP_MINUTES = 3;

const MORNING_START_MINUTE = 9 * 60 + 30;
const MORNING_END_MINUTE = 11 * 60 + 30;
const AFTERNOON_START_MINUTE = 13 * 60;
const AFTERNOON_END_MINUTE = 15 * 60;

const minuteText = (totalMinutes) => {
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
};

export const TRADING_MINUTES = (() => {
  const list = [];
  for (let minute = MORNING_START_MINUTE; minute <= MORNING_END_MINUTE; minute += INTRADAY_STEP_MINUTES) {
    list.push(minuteText(minute));
  }
  for (let minute = AFTERNOON_START_MINUTE + INTRADAY_STEP_MINUTES; minute <= AFTERNOON_END_MINUTE; minute += INTRADAY_STEP_MINUTES) {
    list.push(minuteText(minute));
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
  const total = h * 60 + mm;
  let raw = total - MORNING_START_MINUTE;
  if (total > MORNING_END_MINUTE && total <= AFTERNOON_START_MINUTE) {
    raw = MORNING_END_MINUTE - MORNING_START_MINUTE;
  } else if (total > AFTERNOON_START_MINUTE) {
    raw = (MORNING_END_MINUTE - MORNING_START_MINUTE)
      + (total - AFTERNOON_START_MINUTE);
  }
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
  const normalized = bucket === AFTERNOON_START_MINUTE ? '11:30' : minuteText(bucket);
  return TRADING_MINUTES[minuteToIndex(normalized)] || normalized;
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

export const mergeIntradaySeriesToCache = (seriesMap, dateText = getTodayDate()) => {
  if (!seriesMap || typeof seriesMap !== 'object') return false;
  const cache = readIntradayCache();
  Object.keys(cache).forEach((d) => {
    if (d !== dateText) delete cache[d];
  });
  cache[dateText] = cache[dateText] || {};
  let changed = false;

  Object.keys(seriesMap).forEach((code) => {
    const normalizedCode = String(code || '').padStart(6, '0');
    const points = seriesMap[code];
    if (!/^\d{6}$/.test(normalizedCode) || !points || typeof points !== 'object') return;
    const codeMap = cache[dateText][normalizedCode] || {};
    Object.keys(points).forEach((minute) => {
      const normalizedMinute = normalizeToStepMinute(minute);
      const nav = parseFloat(points[minute]);
      if (!normalizedMinute || !Number.isFinite(nav)) return;
      if (codeMap[normalizedMinute] !== nav) {
        codeMap[normalizedMinute] = nav;
        changed = true;
      }
    });
    cache[dateText][normalizedCode] = codeMap;
  });

  if (changed) writeIntradayCache(cache);
  return changed;
};

export const saveFundSnapshotsToCache = (fundList) => {
  if (!Array.isArray(fundList) || fundList.length === 0) return;
  const today = getTodayDate();
  const cache = readIntradayCache();
  Object.keys(cache).forEach((d) => {
    if (d !== today) delete cache[d];
  });
  cache[today] = cache[today] || {};
  const todayMap = cache[today];

  // 大户保护：限制写入规模，避免 localStorage JSON 过大导致卡顿/阻塞
  const maxFundsToStore = 200;
  const funds = fundList.slice(0, maxFundsToStore);
  const minute = toMinute(funds[0]?.gztime) || formatMinuteNow();
  let changed = false;

  funds.forEach((f) => {
    if (!f || !f.code) return;
    const price = parseFloat(f.gsz);
    if (!Number.isFinite(price)) return;
    const codeMinute = toMinute(f.gztime) || minute;
    const codeMap = todayMap[f.code] || {};
    const prev = codeMap[codeMinute];
    if (prev === price) {
      todayMap[f.code] = codeMap;
      return;
    }
    codeMap[codeMinute] = price;
    todayMap[f.code] = codeMap;
    changed = true;
  });

  if (changed) {
    writeIntradayCache(cache);
  }
};
