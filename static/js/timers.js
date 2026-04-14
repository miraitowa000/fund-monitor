export const createRefreshTimers = ({ fetchFunds, fetchIndexes }) => {
  let fundsTimer = null;
  let idxTimer = null;

  const stop = () => {
    if (fundsTimer) clearInterval(fundsTimer);
    if (idxTimer) clearInterval(idxTimer);
    fundsTimer = null;
    idxTimer = null;
  };

  const start = () => {
    stop();
    fundsTimer = setInterval(fetchFunds, 60000);
    idxTimer = setInterval(fetchIndexes, 15000);
  };

  return { start, stop };
};
