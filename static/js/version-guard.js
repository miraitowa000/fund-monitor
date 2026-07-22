const APP_VERSION_STORAGE_KEY = 'fundMonitorAppVersion';
const APP_VERSION = '2026-05-25-portfolio-fixes';
const LOCAL_CACHE_KEYS = [
  'fundIntradaySnapshotsV1',
  'fundMonitorReleaseNoticeSeen'
];

const clearAppLocalCaches = () => {
  try {
    LOCAL_CACHE_KEYS.forEach((key) => localStorage.removeItem(key));
  } catch {}
};

export const ensureFreshAppVersion = () => {
  try {
    const current = localStorage.getItem(APP_VERSION_STORAGE_KEY);
    if (current === APP_VERSION) return;
    clearAppLocalCaches();
    localStorage.setItem(APP_VERSION_STORAGE_KEY, APP_VERSION);
  } catch {}
};
