// nettap.dev page behaviour: nav state, mobile menu, copy button, reveal on scroll.
const nav = document.querySelector('.nav');
const onScroll = () => nav.toggleAttribute('data-scrolled', window.scrollY > 8);
window.addEventListener('scroll', onScroll, { passive: true });
onScroll();

const toggle = document.querySelector('.nav__toggle');
const panel = document.getElementById('nav-panel');
function setMenu(open) {
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  panel.toggleAttribute('data-open', open);
}
toggle.addEventListener('click', () => setMenu(toggle.getAttribute('aria-expanded') !== 'true'));
panel.addEventListener('click', (e) => { if (e.target.closest('a')) setMenu(false); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && panel.hasAttribute('data-open')) { setMenu(false); toggle.focus(); }
});

const copyBtn = document.querySelector('[data-copy]');
const copyStatus = document.getElementById('copy-status');
copyBtn?.addEventListener('click', async () => {
  const text = document.getElementById(copyBtn.dataset.copy).dataset.commands;
  try {
    await navigator.clipboard.writeText(text);
    copyStatus.textContent = 'Copied';
  } catch {
    copyStatus.textContent = "Couldn't copy. Select the commands and copy them by hand.";
  }
  setTimeout(() => { copyStatus.textContent = 'Copy'; }, 2400);
});

const revealer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) { entry.target.classList.add('is-in'); revealer.unobserve(entry.target); }
  }
}, { rootMargin: '0px 0px -8% 0px' });
document.querySelectorAll('[data-reveal]').forEach((el) => revealer.observe(el));

// Features page: mark the jump-bar pill for the group in view, and keep it visible in the bar.
const jump = document.querySelector('.fnav');
if (jump) {
  const bar = jump.querySelector('ul');
  const links = new Map([...jump.querySelectorAll('a')].map((a) => [a.hash.slice(1), a]));
  const spy = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      links.forEach((a, id) => a.setAttribute('aria-current', String(id === entry.target.id)));
      const a = links.get(entry.target.id);
      bar.scrollTo({ left: a.offsetLeft - bar.clientWidth / 2 + a.offsetWidth / 2, behavior: 'smooth' });
    }
  }, { rootMargin: '-40% 0px -55% 0px' });
  links.forEach((_, id) => { const el = document.getElementById(id); if (el) spy.observe(el); });
}
