/**
 * Live Teleprompter — 主控台逻辑
 * 负责：slide 渲染、翻页控制、口播稿同步、投屏窗口管理
 */

(function () {
  'use strict';

  // ── State ──────────────────────────────────────
  let currentSlide = 0;
  let totalSlides = 0;
  let castWindow = null;
  let scriptFontSize = 18;
  const FONT_STEP = 2;
  const FONT_MIN = 12;
  const FONT_MAX = 32;

  // BroadcastChannel for syncing with cast window
  const channel = new BroadcastChannel('teleprompter');

  // ── DOM References ─────────────────────────────
  const $slideContainer = document.getElementById('slideContainer');
  const $thumbnailsStrip = document.getElementById('thumbnailsStrip');
  const $scriptBody = document.getElementById('scriptBody');
  const $deckTitle = document.getElementById('deckTitle');
  const $currentPage = document.getElementById('currentPage');
  const $totalPages = document.getElementById('totalPages');
  const $slideCounter = document.getElementById('slideCounter');
  const $btnPrev = document.getElementById('btnPrev');
  const $btnNext = document.getElementById('btnNext');
  const $btnImport = document.getElementById('btnImport');
  const $btnCast = document.getElementById('btnCast');
  const $fontDecrease = document.getElementById('fontDecrease');
  const $fontIncrease = document.getElementById('fontIncrease');
  const $statusDot = document.getElementById('statusDot');
  const $statusText = document.getElementById('statusText');
  const $themeToggle = document.getElementById('themeToggle');

  // ── Theme Toggle ────────────────────────────────
  const STORAGE_KEY = 'teleprompter-theme';
  const currentTheme = localStorage.getItem(STORAGE_KEY) || 'dark';

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if ($themeToggle) {
      $themeToggle.textContent = theme === 'eye-care' ? '☀' : '☾';
    }
    localStorage.setItem(STORAGE_KEY, theme);
  }

  applyTheme(currentTheme);

  // ── Slide Rendering ────────────────────────────

  function renderSlideHTML(slide, isFullSize) {
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

    // Page number (skip on cover)
    if (slide.layout !== 'cover' && isFullSize) {
      inner += `<div class="slide__page-number">第 ${slide.id} 页</div>`;
    }

    return `<div class="slide ${layoutClass}">${inner}</div>`;
  }

  // ── Initialize ─────────────────────────────────

  function init() {
    if (typeof TELEPROMPTER_DATA === 'undefined') {
      showWelcome();
      return;
    }

    const data = TELEPROMPTER_DATA;
    totalSlides = data.slides.length;

    // Set title
    $deckTitle.textContent = data.title;
    $totalPages.textContent = totalSlides;
    $slideCounter.textContent = totalSlides;

    // Render all script sections
    renderAllScripts(data.slides);

    // Render thumbnails
    renderThumbnails(data.slides);

    // Go to first slide
    goToSlide(0);

    // Bind events
    bindEvents();

    // Listen for cast window heartbeat
    channel.onmessage = handleChannelMessage;
  }

  function showWelcome() {
    document.getElementById('app').innerHTML = `
      <div class="welcome-screen">
        <div class="welcome-screen__icon">T</div>
        <div class="welcome-screen__title">Live Teleprompter</div>
        <div class="welcome-screen__desc">
          请先通过 Claude 导入内容文件，<br/>
          生成演示文稿和口播稿后即可使用。
        </div>
      </div>
    `;
  }

  // ── Script Sections ────────────────────────────

  function renderAllScripts(slides) {
    $scriptBody.innerHTML = slides.map((s, i) => `
      <div class="script-section" data-slide-index="${i}" id="script-${i}">
        <div class="script-section__label">${s.script?.label || `第 ${s.id} 页`}</div>
        <div class="script-section__text">${s.script?.text || ''}</div>
      </div>
    `).join('');
  }

  // ── Thumbnails ─────────────────────────────────

  function renderThumbnails(slides) {
    $thumbnailsStrip.innerHTML = slides.map((s, i) => `
      <div class="thumb" data-index="${i}" id="thumb-${i}">
        <div class="mini-slide">
          <div class="mini-slide__title">${stripHTML(s.title || s.quote || '')}</div>
        </div>
        <div class="thumb__number">${s.id}</div>
      </div>
    `).join('');
  }

  function stripHTML(str) {
    return str.replace(/<[^>]*>/g, '').replace(/\n/g, ' ');
  }

  // ── Navigation ─────────────────────────────────

  function goToSlide(index) {
    if (index < 0 || index >= totalSlides) return;

    currentSlide = index;
    const slide = TELEPROMPTER_DATA.slides[index];

    // Render main slide
    $slideContainer.innerHTML = renderSlideHTML(slide, true);

    // Update page indicator
    $currentPage.textContent = index + 1;

    // Update nav buttons
    $btnPrev.disabled = index === 0;
    $btnNext.disabled = index === totalSlides - 1;

    // Update thumbnail active state
    document.querySelectorAll('.thumb').forEach((t, i) => {
      t.classList.toggle('active', i === index);
    });

    // Scroll active thumbnail into view
    const activeThumb = document.getElementById(`thumb-${index}`);
    if (activeThumb) {
      activeThumb.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }

    // Sync script
    syncScript(index);

    // Broadcast to cast window
    channel.postMessage({ type: 'navigate', slideIndex: index });
  }

  function nextSlide() { goToSlide(currentSlide + 1); }
  function prevSlide() { goToSlide(currentSlide - 1); }

  // ── Script Sync ────────────────────────────────

  function syncScript(index) {
    // Update active state
    document.querySelectorAll('.script-section').forEach((s, i) => {
      s.classList.toggle('active', i === index);
    });

    // Scroll to active section
    const activeSection = document.getElementById(`script-${index}`);
    if (activeSection) {
      activeSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // ── Font Size ──────────────────────────────────

  function changeFontSize(delta) {
    scriptFontSize = Math.min(FONT_MAX, Math.max(FONT_MIN, scriptFontSize + delta));
    document.documentElement.style.setProperty('--script-font-size', scriptFontSize + 'px');
  }

  // ── Cast Window ────────────────────────────────

  let castConnected = false;

  function openCastWindow() {
    if (castWindow && !castWindow.closed) {
      castWindow.focus();
      // 重新发送当前 slide，确保同步
      channel.postMessage({ type: 'navigate', slideIndex: currentSlide });
      return;
    }

    castWindow = window.open(
      'cast.html',
      'teleprompter-cast',
      'width=1280,height=720,menubar=no,toolbar=no,location=no,status=no'
    );

    // 投屏窗口加载后会发送 'cast-ready'，触发同步
    // 额外延迟发送一次，防止 BroadcastChannel 初始化竞态
    setTimeout(() => {
      channel.postMessage({ type: 'navigate', slideIndex: currentSlide });
    }, 500);
  }

  function updateCastStatus(isConnected) {
    castConnected = isConnected;
    $statusDot.classList.toggle('connected', isConnected);
    $statusText.textContent = isConnected ? '投屏已连接' : '投屏未连接';

    // 更新按钮文字
    if ($btnCast) {
      $btnCast.innerHTML = isConnected
        ? '<span class="ctrl-btn__icon">🖥️</span> 投屏中'
        : '<span class="ctrl-btn__icon">🖥️</span> 打开投屏';
    }
  }

  function handleChannelMessage(event) {
    const msg = event.data;

    switch (msg.type) {
      case 'cast-ready':
        // 投屏窗口已打开并准备好接收
        updateCastStatus(true);
        // 立即推送当前 slide 给投屏窗口
        channel.postMessage({ type: 'navigate', slideIndex: currentSlide });
        break;

      case 'cast-closed':
        updateCastStatus(false);
        break;

      case 'heartbeat-pong':
        // 投屏窗口还活着，保持连接状态
        updateCastStatus(true);
        break;
    }
  }

  // ── File Import ────────────────────────────────

  function handleImport() {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.js,.json';
    fileInput.style.display = 'none';

    fileInput.addEventListener('change', (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (evt) => {
        try {
          // Try to evaluate as JS (data.js format)
          const content = evt.target.result;
          // Use Function constructor to safely evaluate
          const fn = new Function(content + '\nreturn TELEPROMPTER_DATA;');
          const data = fn();
          if (data && data.slides) {
            // Replace global data
            window.TELEPROMPTER_DATA = data;
            // Re-initialize
            totalSlides = data.slides.length;
            $deckTitle.textContent = data.title;
            $totalPages.textContent = totalSlides;
            $slideCounter.textContent = totalSlides;
            renderAllScripts(data.slides);
            renderThumbnails(data.slides);
            goToSlide(0);
            // Rebind thumbnail clicks
            bindThumbnailClicks();
          }
        } catch (err) {
          console.error('文件加载失败:', err);
          alert('文件格式不正确，请使用 Claude 生成的 data.js 文件。');
        }
      };
      reader.readAsText(file);
    });

    document.body.appendChild(fileInput);
    fileInput.click();
    document.body.removeChild(fileInput);
  }

  // ── Event Binding ──────────────────────────────

  function bindThumbnailClicks() {
    document.querySelectorAll('.thumb').forEach(thumb => {
      thumb.addEventListener('click', () => {
        const idx = parseInt(thumb.dataset.index, 10);
        goToSlide(idx);
      });
    });
  }

  function bindEvents() {
    // Navigation buttons
    $btnPrev.addEventListener('click', prevSlide);
    $btnNext.addEventListener('click', nextSlide);

    // Keyboard
    document.addEventListener('keydown', (e) => {
      switch (e.key) {
        case 'ArrowLeft':
        case 'ArrowUp':
          e.preventDefault();
          prevSlide();
          break;
        case 'ArrowRight':
        case 'ArrowDown':
        case ' ':
          e.preventDefault();
          nextSlide();
          break;
        case 'Home':
          e.preventDefault();
          goToSlide(0);
          break;
        case 'End':
          e.preventDefault();
          goToSlide(totalSlides - 1);
          break;
      }
    });

    // Thumbnails
    bindThumbnailClicks();

    // Font size
    $fontDecrease.addEventListener('click', () => changeFontSize(-FONT_STEP));
    $fontIncrease.addEventListener('click', () => changeFontSize(FONT_STEP));

    // Cast window
    $btnCast.addEventListener('click', openCastWindow);

    // Import
    $btnImport.addEventListener('click', handleImport);

    // Theme toggle
    if ($themeToggle) {
      $themeToggle.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'eye-care' ? 'dark' : 'eye-care';
        applyTheme(next);
      });
    }

    // 心跳检测：每 2 秒 ping 投屏窗口，3 秒内无响应视为断开
    let heartbeatTimeout = null;

    setInterval(() => {
      if (castWindow && !castWindow.closed) {
        channel.postMessage({ type: 'heartbeat-ping' });
        // 如果 3 秒内没收到 pong，标记断开
        clearTimeout(heartbeatTimeout);
        heartbeatTimeout = setTimeout(() => {
          if (castConnected) updateCastStatus(false);
        }, 3000);
      } else if (castWindow && castWindow.closed) {
        castWindow = null;
        updateCastStatus(false);
      }
    }, 2000);
  }

  // ── Start ──────────────────────────────────────
  init();

})();
