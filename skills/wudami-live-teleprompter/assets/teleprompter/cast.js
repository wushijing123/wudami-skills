/**
 * Live Teleprompter — 投屏窗口逻辑
 * 通过 BroadcastChannel 自动连接主控台，实时同步 slide 切换
 */

(function () {
  'use strict';

  const channel = new BroadcastChannel('teleprompter');
  const $container = document.getElementById('castSlideContainer');
  let connected = false;
  let currentSlideIndex = 0;

  // ── Slide Rendering ────────────────────────────

  function renderSlideHTML(slide) {
    const layoutClass = `slide--${slide.layout}`;
    let inner = '';

    switch (slide.layout) {
      case 'cover':
        inner = `
          ${slide.year ? `<div class="slide__year">${slide.year}</div>` : ''}
          <div class="slide__title">${slide.title}</div>
          ${slide.subtitle ? `<div class="slide__subtitle">${slide.subtitle}</div>` : ''}
        `;
        break;

      case 'bullets':
        inner = `
          <div class="slide__title">${slide.title}</div>
          <ul class="slide__bullets">
            ${(slide.bullets || []).map(b => `<li>${b}</li>`).join('')}
          </ul>
        `;
        break;

      case 'comparison':
        inner = `
          <div class="slide__title">${slide.title}</div>
          <div class="slide__comparison">
            <div class="slide__comparison-col">
              <h3>${slide.left?.heading || ''}</h3>
              <ul>${(slide.left?.items || []).map(i => `<li>${i}</li>`).join('')}</ul>
            </div>
            <div class="slide__comparison-col">
              <h3>${slide.right?.heading || ''}</h3>
              <ul>${(slide.right?.items || []).map(i => `<li>${i}</li>`).join('')}</ul>
            </div>
          </div>
        `;
        break;

      case 'quote':
        inner = `
          <div class="slide__quote-mark">"</div>
          <div class="slide__quote-text">${slide.quote || ''}</div>
          ${slide.author ? `<div class="slide__quote-author">${slide.author}</div>` : ''}
        `;
        break;

      case 'closing':
        inner = `
          <div class="slide__title">${slide.title}</div>
          ${slide.subtitle ? `<div class="slide__subtitle">${slide.subtitle}</div>` : ''}
        `;
        break;

      default:
        inner = `<div class="slide__title">${slide.title || ''}</div>`;
    }

    return `<div class="slide ${layoutClass}">${inner}</div>`;
  }

  // ── Navigate ───────────────────────────────────

  function navigateToSlide(index) {
    if (typeof TELEPROMPTER_DATA === 'undefined') return;
    const slides = TELEPROMPTER_DATA.slides;
    if (index < 0 || index >= slides.length) return;

    currentSlideIndex = index;
    $container.innerHTML = renderSlideHTML(slides[index]);
  }

  // ── Connection Status Overlay ──────────────────

  function showConnected() {
    // 移除等待连接的遮罩
    const old = document.getElementById('connectOverlay');
    if (old) old.remove();

    // 显示"已连接"提示，2秒后自动消失
    const overlay = document.createElement('div');
    overlay.id = 'connectOverlay';
    overlay.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.85);
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      z-index: 999; transition: opacity 0.6s ease;
      font-family: 'Inter', 'Noto Sans SC', sans-serif;
    `;
    overlay.innerHTML = `
      <div style="
        width: 14px; height: 14px; border-radius: 50%;
        background: #4caf50; box-shadow: 0 0 16px #4caf50;
        margin-bottom: 20px;
        animation: castPulse 1.5s infinite;
      "></div>
      <div style="color: #e8e2d6; font-size: 20px; font-weight: 600;">投屏已连接</div>
      <div style="color: #9a9489; font-size: 14px; margin-top: 10px;">正在同步主控台画面...</div>
      <style>
        @keyframes castPulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.6); opacity: 0.5; }
        }
      </style>
    `;
    document.body.appendChild(overlay);

    setTimeout(() => {
      overlay.style.opacity = '0';
      setTimeout(() => overlay.remove(), 600);
    }, 2000);
  }

  function showWaiting() {
    const old = document.getElementById('connectOverlay');
    if (old) old.remove();

    const overlay = document.createElement('div');
    overlay.id = 'connectOverlay';
    overlay.style.cssText = `
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.92);
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      z-index: 999;
      font-family: 'Inter', 'Noto Sans SC', sans-serif;
    `;
    overlay.innerHTML = `
      <div style="
        width: 14px; height: 14px; border-radius: 50%;
        background: #c9a449; box-shadow: 0 0 12px rgba(201,164,73,0.5);
        margin-bottom: 20px;
        animation: waitPulse 2s infinite;
      "></div>
      <div style="color: #e8e2d6; font-size: 20px; font-weight: 600;">正在连接主控台...</div>
      <div style="color: #9a9489; font-size: 14px; margin-top: 10px;">请确保主控台已打开</div>
      <style>
        @keyframes waitPulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.4); opacity: 0.4; }
        }
      </style>
    `;
    document.body.appendChild(overlay);
  }

  // ── Channel Communication ──────────────────────

  channel.onmessage = (event) => {
    const msg = event.data;

    switch (msg.type) {
      case 'navigate':
        // 收到主控台的翻页指令
        if (!connected) {
          connected = true;
          showConnected();
        }
        navigateToSlide(msg.slideIndex);
        break;

      case 'heartbeat-ping':
        // 回复主控台的心跳检测
        channel.postMessage({ type: 'heartbeat-pong' });
        break;
    }
  };

  // ── 主动请求连接 ───────────────────────────────

  // 显示等待状态
  showWaiting();

  // 发送 ready 信号，让主控台知道投屏窗口已打开
  function requestSync() {
    channel.postMessage({ type: 'cast-ready' });
  }

  // 立即发送一次
  requestSync();

  // 每秒重试，直到收到主控台的 navigate 响应
  const retryInterval = setInterval(() => {
    if (connected) {
      clearInterval(retryInterval);
    } else {
      requestSync();
    }
  }, 1000);

  // 30秒后停止重试
  setTimeout(() => clearInterval(retryInterval), 30000);

  // ── 关闭通知 ───────────────────────────────────

  window.addEventListener('beforeunload', () => {
    channel.postMessage({ type: 'cast-closed' });
  });

  // ── 初始化 ─────────────────────────────────────

  if (typeof TELEPROMPTER_DATA !== 'undefined' && TELEPROMPTER_DATA.slides.length > 0) {
    navigateToSlide(0);
    document.title = `投屏 — ${TELEPROMPTER_DATA.title}`;
  }

})();
