(function () {
  var root = document.documentElement;
  root.classList.add('js');

  function applyTheme(t) {
    root.setAttribute('data-theme', t);
    try { localStorage.setItem('vt-site-theme', t); } catch (e) {}
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.setAttribute('aria-label', t === 'dark' ? '切换到浅色主题' : '切换到深色主题');
      btn.querySelector('.sun').style.display = t === 'dark' ? 'block' : 'none';
      btn.querySelector('.moon').style.display = t === 'dark' ? 'none' : 'block';
    });
  }

  var saved = null;
  try { saved = localStorage.getItem('vt-site-theme'); } catch (e) {}
  var initial = saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(initial);

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-theme-toggle]');
    if (toggle) {
      applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
      return;
    }
    var navToggle = e.target.closest('[data-nav-toggle]');
    if (navToggle) {
      document.querySelector('.main-nav').classList.toggle('open');
      return;
    }
    if (!e.target.closest('.main-nav') && !e.target.closest('[data-nav-toggle]')) {
      document.querySelector('.main-nav').classList.remove('open');
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(root.getAttribute('data-theme') || 'light');

    var io = 'IntersectionObserver' in window
      ? new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
          });
        }, { threshold: .12 })
      : null;
    document.querySelectorAll('.reveal').forEach(function (el) {
      if (io) io.observe(el); else el.classList.add('in');
    });

    document.querySelectorAll('[data-year]').forEach(function (el) {
      el.textContent = new Date().getFullYear();
    });
  });
})();
