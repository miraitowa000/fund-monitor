import {
  hasUsableFundListData,
  loadFundListFromCache,
  saveFundListToCache,
  saveFundSnapshotsToCache,
} from './cache.js';

export const fetchFundsRaw = async (codes) => {
  try {
    if (!codes || codes.length === 0) return [];
    const response = await fetch('/api/funds', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codes })
    });

    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
      console.warn('获取基金数据失败（状态码:', response.status, '），返回本地缓存数据');
      return loadFundListFromCache() || [];
    }

    const data = await response.json();
    if (hasUsableFundListData(data)) {
      saveFundSnapshotsToCache(data);
      saveFundListToCache(data);
    }
    return data;
  } catch (error) {
    console.error('获取基金数据失败:', error);
    return loadFundListFromCache() || [];
  }
};

export const fetchIndexesRaw = async () => {
  try {
    const response = await fetch('/api/indexes');
    return await response.json();
  } catch (error) {
    console.error('指数获取失败:', error);
    return [];
  }
};

export const loadFundDetail = async (code) => {
  const response = await fetch(`/api/fund/${code}`);
  return await response.json();
};
