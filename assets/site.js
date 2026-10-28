'use strict';
const root = document.documentElement;
const themeButton = document.querySelector('#theme-toggle');
const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#nav');
function setTheme(theme) {
  const value = theme === 'dark' ? 'dark' : 'light';
  root.dataset.theme = value;
  if (themeButton) themeButton.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
  try { localStorage.setItem('telecode-theme', value); } catch (_) {}
}
setTheme(root.dataset.theme || 'light');
themeButton?.addEventListener('click', () => setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));
navToggle?.addEventListener('click', () => {
  const open = navToggle.getAttribute('aria-expanded') !== 'true';
  navToggle.setAttribute('aria-expanded', String(open));
  navToggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
  nav?.classList.toggle('open', open);
});
nav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  nav.classList.remove('open'); navToggle?.setAttribute('aria-expanded', 'false');
}));
const preview = document.querySelector('#model-preview');
document.querySelectorAll('.provider').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.provider').forEach(item => item.classList.toggle('selected', item === button));
  if (preview) preview.textContent = `${button.dataset.provider} models available`;
}));
document.querySelectorAll('.phone-controls button').forEach(button => button.addEventListener('click', () => {
  if (preview) preview.textContent = button.dataset.preview || button.textContent;
}));
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
if ('IntersectionObserver' in window && !reduceMotion) {
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target); }
  }), { threshold: .12 });
  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
} else document.querySelectorAll('.reveal').forEach(el => el.classList.add('visible'));
