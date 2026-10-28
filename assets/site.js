'use strict';
const root = document.documentElement;
const themeButton = document.querySelector('#theme-toggle');
const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#nav');

function setTheme(theme) {
  const value = theme === 'light' ? 'light' : 'dark';
  root.dataset.theme = value;
  if (themeButton) themeButton.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
  try { localStorage.setItem('telecode-theme', value); } catch (_) {}
}
setTheme(root.dataset.theme || 'dark');
themeButton?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

navToggle?.addEventListener('click', () => {
  const open = navToggle.getAttribute('aria-expanded') !== 'true';
  navToggle.setAttribute('aria-expanded', String(open));
  navToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  nav?.classList.toggle('open', open);
});
nav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  nav.classList.remove('open');
  navToggle?.setAttribute('aria-expanded', 'false');
}));

document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const text = button.dataset.copy || '';
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = 'Copied';
    window.setTimeout(() => { button.textContent = 'Copy'; }, 1600);
  } catch (_) {
    button.textContent = 'Copy unavailable';
    window.setTimeout(() => { button.textContent = 'Copy'; }, 1600);
  }
}));

const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if ('IntersectionObserver' in window && !reduceMotion) {
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      observer.unobserve(entry.target);
    }
  }), { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
} else {
  document.querySelectorAll('.reveal').forEach(el => el.classList.add('visible'));
}

const preview = document.querySelector('#model-preview b');
document.querySelectorAll('.provider').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.provider').forEach(item => item.classList.toggle('selected', item === button));
  if (preview) preview.textContent = `${button.dataset.provider} models available`;
}));
document.querySelectorAll('.phone-controls button').forEach(button => button.addEventListener('click', () => {
  const label = button.dataset.preview;
  if (preview) preview.textContent = label;
}));
