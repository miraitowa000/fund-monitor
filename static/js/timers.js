export const getFundsInterval = (statusText) => {
  if (statusText === '集合竞价') return 30000;
  if (statusText === '开盘中') return 60000;
  if (statusText === '午盘休息') return 120000;
  return 300000;
};

export const getIdxInterval = (statusText) => {
  if (statusText === '集合竞价' || statusText === '开盘中') return 15000;
  if (statusText === '午盘休息') return 30000;
  return 120000;
};

export const createRefreshTimers = ({ getStatusText, fetchFunds, fetchIndexes }) => {
  let fundsTimer = null;
  let idxTimer = null;
  let fundsActive = false;
  let idxActive = false;

  const stop = () => {
    fundsActive = false;
    idxActive = false;
    if (fundsTimer) clearTimeout(fundsTimer);
    if (idxTimer) clearTimeout(idxTimer);
    fundsTimer = null;
    idxTimer = null;
  };

  const scheduleFunds = () => {
    if (!fundsActive) return;
    fundsTimer = setTimeout(async () => {
      if (!fundsActive) return;
      await fetchFunds();
      scheduleFunds();
    }, getFundsInterval(getStatusText()));
  };

  const scheduleIndexes = () => {
    if (!idxActive) return;
    idxTimer = setTimeout(async () => {
      if (!idxActive) return;
      await fetchIndexes();
      scheduleIndexes();
    }, getIdxInterval(getStatusText()));
  };

  const start = () => {
    stop();
    fundsActive = true;
    idxActive = true;
    scheduleFunds();
    scheduleIndexes();
  };

  return { start, stop };
};
