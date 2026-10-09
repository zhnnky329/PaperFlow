/* Stable ordinary DOM; no article rerender during translation/progress updates. */
(async () => {
  const id = document.body.dataset.paper;
  const endpoint = `/api/v1/papers/${id}/reading-position?mode=local_html`;
  const root = document.documentElement;
  root.style.setProperty('--reader-width', `${document.body.dataset.width}px`);
  root.style.setProperty('--reader-size', `${document.body.dataset.size}px`);
  document.querySelector('#help').onclick = () => document.querySelector('dialog').showModal();
  document.querySelector('#close-help').onclick = () => document.querySelector('dialog').close();
  const prefs = value => fetch('/api/v1/settings', {method:'PATCH', headers:{'Content-Type':'application/json','X-PaperFlow':'1'}, body:JSON.stringify(value)}).catch(() => {});
  document.querySelector('#theme').onclick = () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    prefs({theme:root.dataset.theme});
  };
  for (const [control, variable] of [['font', '--reader-size'], ['width', '--reader-width']]) {
    document.getElementById(control).oninput = e => root.style.setProperty(variable, `${e.target.value}px`);
    document.getElementById(control).onchange = e => prefs({[control === 'font' ? 'font_scale' : 'reader_width']:Number(e.target.value)});
  }
  for (const node of document.querySelectorAll('math')) {
    // Marker text math is LaTeX; actual MathML with child elements stays native.
    if (!node.children.length && window.katex) {
      const text = node.textContent.trim().replace(/^\$\$?|\$\$?$/g, '');
      const display = node.getAttribute('display') === 'block';
      const container = document.createElement(display ? 'div' : 'span');
      container.className = 'math-rendered notranslate';
      container.setAttribute('translate', 'no');
      container.dataset.mathSource = 'marker';
      container.textContent = text;
      try {
        if (text.length <= 20000) window.katex.render(text, container, {displayMode: display,
          throwOnError: false, trust: false, strict: 'ignore', maxExpand: 500});
        node.replaceWith(container);
      } catch { node.replaceWith(container); }

    }
  }
  let restored = false;
  let timer;
  try {
    const response = await fetch(endpoint);
    const position = await response.json();
    await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
    if (!location.hash) {
      const anchor = document.getElementById(position.html_anchor);
      if (position.scroll_ratio > 0) scrollTo(0, position.scroll_ratio * Math.max(0, document.documentElement.scrollHeight - innerHeight));
      else if (anchor) anchor.scrollIntoView();
    }
  } finally { restored = true; }
  const save = () => {
    if (!restored) return;
    let anchor = '';
    for (const node of document.querySelectorAll('article h1,article h2,article h3,article h4')) {
      if (node.getBoundingClientRect().top <= 120) anchor = node.id;
    }
    const ratio = Math.min(1, Math.max(0, scrollY / Math.max(1, root.scrollHeight - innerHeight)));
    fetch(endpoint, {method:'PUT', keepalive:true, headers:{'Content-Type':'application/json','X-PaperFlow':'1'},
      body:JSON.stringify({html_anchor:anchor,scroll_ratio:ratio})}).catch(() => {});
  };
  addEventListener('scroll', () => {
    let current = '';
    for (const node of document.querySelectorAll('article h1,article h2,article h3,article h4')) {
      if (node.getBoundingClientRect().top <= 140) current = node.id;
    }
    for (const link of document.querySelectorAll('aside a')) link.classList.toggle('active', link.getAttribute('href') === '#' + current);
    clearTimeout(timer);timer=setTimeout(save, 700);
  }, {passive:true});
  addEventListener('pagehide', save);
})();
