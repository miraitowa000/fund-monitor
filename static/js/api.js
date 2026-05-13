const withClientHeaders = (clientId, headers = {}) => ({
  ...headers,
  'X-Client-Id': clientId
});

export const fetchIndexesRaw = async () => {
  try {
    const response = await fetch('/api/indexes');
    return await response.json();
  } catch (error) {
    console.error('获取指数数据失败:', error);
    return [];
  }
};

export const loadFundDetail = async (code) => {
  const response = await fetch(`/api/fund/${code}`);
  return await response.json();
};

export const loadFundHistory = async (code, days) => {
  const response = await fetch(`/api/fund/${code}/history?days=${days}`);
  return await response.json();
};

export const searchFunds = async (keyword, limit = 10) => {
  const q = String(keyword || '').trim();
  if (!q) return [];
  const response = await fetch(`/api/fund/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(limit)}`);
  return await response.json();
};

export const fetchUserFundsMeta = async (clientId) => {
  const response = await fetch('/api/user/funds-meta', {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const fetchDashboardBootstrap = async (clientId, codes = []) => {
  const response = await fetch('/api/dashboard/bootstrap', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ codes })
  });
  return await response.json();
};

export const fetchMarketStatus = async () => {
  const response = await fetch('/api/market/status');
  return await response.json();
};

export const createFundGroup = async (clientId, name) => {
  const response = await fetch('/api/user/groups', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name })
  });
  return await response.json();
};

export const renameFundGroup = async (clientId, groupId, name) => {
  const response = await fetch(`/api/user/groups/${groupId}`, {
    method: 'PUT',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name })
  });
  return await response.json();
};

export const deleteFundGroup = async (clientId, groupId) => {
  const response = await fetch(`/api/user/groups/${groupId}`, {
    method: 'DELETE',
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const saveUserFund = async (clientId, code, groupId) => {
  const response = await fetch('/api/user/funds', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ code, group_id: groupId || null })
  });
  return await response.json();
};

export const moveUserFundGroup = async (clientId, code, groupId) => {
  const response = await fetch(`/api/user/funds/${code}/group`, {
    method: 'PUT',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ group_id: groupId })
  });
  return await response.json();
};

export const deleteUserFund = async (clientId, code) => {
  const response = await fetch(`/api/user/funds/${code}`, {
    method: 'DELETE',
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const updateUserFundPosition = async (clientId, code, payload) => {
  const response = await fetch(`/api/user/funds/${code}/position`, {
    method: 'PUT',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const fetchPortfolio = async (clientId) => {
  const response = await fetch('/api/user/portfolio', {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const fetchDailyEarnings = async (clientId, start, end) => {
  const params = new URLSearchParams();
  if (start) params.set('start', start);
  if (end) params.set('end', end);
  const query = params.toString();
  const response = await fetch(`/api/user/earnings/daily${query ? `?${query}` : ''}`, {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const fetchAuthMe = async (clientId) => {
  const response = await fetch('/api/auth/me', {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const registerAccount = async (clientId, account, password) => {
  const response = await fetch('/api/auth/register', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ account, password })
  });
  return await response.json();
};

export const loginAccount = async (account, password) => {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password })
  });
  return await response.json();
};

export const fetchFundTransactions = async (clientId, code) => {
  const response = await fetch(`/api/user/funds/${code}/transactions`, {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const createFundTransaction = async (clientId, code, payload) => {
  const response = await fetch(`/api/user/funds/${code}/transactions`, {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const previewFundTransaction = async (clientId, code, payload) => {
  const response = await fetch(`/api/user/funds/${code}/transactions/preview`, {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const deleteFundTransaction = async (clientId, transactionId) => {
  const response = await fetch(`/api/user/transactions/${transactionId}`, {
    method: 'DELETE',
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const previewFundConversion = async (clientId, payload) => {
  const response = await fetch('/api/user/fund-conversions/preview', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const createFundConversion = async (clientId, payload) => {
  const response = await fetch('/api/user/fund-conversions', {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const fetchDcaPlan = async (clientId, code) => {
  const response = await fetch(`/api/user/funds/${code}/dca-plan`, {
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};

export const saveDcaPlan = async (clientId, code, payload) => {
  const response = await fetch(`/api/user/funds/${code}/dca-plan`, {
    method: 'POST',
    headers: withClientHeaders(clientId, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload)
  });
  return await response.json();
};

export const deleteDcaPlan = async (clientId, code) => {
  const response = await fetch(`/api/user/funds/${code}/dca-plan`, {
    method: 'DELETE',
    headers: withClientHeaders(clientId)
  });
  return await response.json();
};
