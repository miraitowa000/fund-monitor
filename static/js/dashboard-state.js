import { saveFundSnapshotsToCache } from './cache.js';

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

const attachGroupMeta = (quoteList, fundMetaMap) => quoteList.map((item) => ({
  ...item,
  group_id: fundMetaMap[item.code]?.group_id || null,
  group_name: fundMetaMap[item.code]?.group_name || ''
}));

export const buildPortfolioViewState = (portfolio, fundMetaMap, currentSummary) => {
  const normalizedItems = normalizePortfolioItems(portfolio?.items);
  saveFundSnapshotsToCache(normalizedItems);

  return {
    items: normalizedItems,
    funds: attachGroupMeta(normalizedItems, fundMetaMap || {}),
    summary: portfolio?.summary || currentSummary,
  };
};
