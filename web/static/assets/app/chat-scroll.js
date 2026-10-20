/** Rolagem automática do feed da conversa.
 *
 *  O conteúdo novo é seguido enquanto o usuário estiver no fim da conversa. Subir
 *  para ler interrompe o acompanhamento; voltar ao fim o religa.
 *
 *  O estado vem da posição real da rolagem (e da direção do movimento), e não de
 *  eventos soltos: é isso que faz o feed voltar a ser acompanhado assim que o
 *  usuário retorna ao fim, em vez de ficar travado fora da conversa. */

const DEFAULT_THRESHOLD = 80;
const TOUCH_SLOP = 4;
const SMOOTH_MS = 500;
const MAX_RETRIES = 40;

export function createScrollFollow({ threshold = DEFAULT_THRESHOLD, onChange = () => {}, timers = globalThis } = {}) {
  let element = null;
  // O feed está sendo acompanhado?
  let following = true;
  // Última posição de rolagem observada: serve para saber se o movimento foi para cima.
  let lastTop = null;
  // Verdadeiro enquanto a nossa rolagem suave está em curso.
  let autoScrolling = false;
  let autoTimer = null;
  let retries = 0;
  let touchY = null;

  function nearBottom() {
    if (!element) return true;
    return element.scrollHeight - element.scrollTop - element.clientHeight < threshold;
  }

  function setFollowing(value) {
    if (following === value) return;
    following = value;
    onChange(value);
  }

  function clearTimer() {
    if (!autoTimer) return;
    timers.clearTimeout(autoTimer);
    autoTimer = null;
  }

  /** Interrompe a rolagem suave em andamento (sem arrastar o usuário). */
  function cancelAutoScroll() {
    clearTimer();
    if (!autoScrolling) return;
    autoScrolling = false;
    // "instant" ignora o scroll-behavior: smooth do CSS — é o que realmente cancela.
    if (element) element.scrollTo({ top: element.scrollTop, behavior: "instant" });
  }

  /** O usuário saiu do fim da conversa (subiu para ler). */
  function leaveBottom() {
    cancelAutoScroll();
    setFollowing(false);
  }

  function handleScroll(next) {
    element = next || element;
    if (!element) return;
    const top = element.scrollTop;
    const wentUp = lastTop !== null && top < lastTop - 1;
    lastTop = top;
    if (wentUp) {
      leaveBottom();
      return;
    }
    if (autoScrolling) {
      // Ainda é a nossa rolagem: a conversa continua colada no fim.
      setFollowing(true);
      return;
    }
    const bottom = nearBottom();
    if (bottom && !following) {
      // O usuário voltou ao fim: o feed volta a ser acompanhado e a conversa
      // gruda no fim de novo, sem exigir mais rolagem.
      setFollowing(true);
      followContent(element);
      return;
    }
    setFollowing(bottom);
  }

  function handleWheel(next, deltaY) {
    element = next || element;
    // Roda para cima (deltaY negativo) é o usuário subindo na conversa.
    if (typeof deltaY !== "number" || deltaY >= 0) return;
    leaveBottom();
  }

  function handleTouchStart(next, event) {
    element = next || element;
    const touch = event && event.touches && event.touches[0];
    touchY = touch ? touch.clientY : null;
  }

  function handleTouchMove(next, event) {
    element = next || element;
    const touch = event && event.touches && event.touches[0];
    if (touchY === null || !touch) return;
    const delta = touch.clientY - touchY;
    touchY = touch.clientY;
    // Dedo descendo: o conteúdo sobe, ou seja, o usuário olha para o topo.
    if (delta > TOUCH_SLOP) leaveBottom();
  }

  function handleTouchEnd() {
    touchY = null;
  }

  /** Conteúdo novo: rola para o fim enquanto o usuário estiver acompanhando. */
  function followContent(next) {
    element = next || element;
    if (!element || !following) return false;
    autoScrolling = true;
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
    // A posição de referência é a de agora: a rolagem suave só pode ir para baixo.
    lastTop = element.scrollTop;
    clearTimer();
    autoTimer = timers.setTimeout(() => {
      autoTimer = null;
      autoScrolling = false;
      if (!element) return;
      if (nearBottom()) {
        retries = 0;
        setFollowing(true);
        return;
      }
      // A rolagem suave não chegou ao fim (conteúdo grande): continua acompanhando.
      if (retries >= MAX_RETRIES) {
        setFollowing(nearBottom());
        return;
      }
      retries += 1;
      followContent(element);
    }, SMOOTH_MS);
    return true;
  }

  /** Botão "rolar para o fim": volta ao fim e religa o acompanhamento do feed. */
  function scrollToBottom(next) {
    element = next || element;
    if (!element) return;
    setFollowing(true);
    followContent(element);
  }

  /** Conversa nova: o acompanhamento recomeça, colado no fim. */
  function reset() {
    clearTimer();
    autoScrolling = false;
    lastTop = null;
    retries = 0;
    setFollowing(true);
  }

  function isFollowing() {
    return following;
  }

  return {
    handleScroll,
    handleWheel,
    handleTouchStart,
    handleTouchMove,
    handleTouchEnd,
    followContent,
    scrollToBottom,
    reset,
    isFollowing,
  };
}
