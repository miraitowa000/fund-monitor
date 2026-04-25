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
