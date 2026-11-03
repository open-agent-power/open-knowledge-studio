'use strict';
// Navigation hints contain URLs and scroll positions only, never review contents.
window.OksNavigation = (() => {
  function localPath(value) {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.length > 4096) return null;
    try {
      const url = new URL(value, location.origin);
      if (url.origin !== location.origin || !['/', '/tasks', '/review', '/debug', '/start', '/versions'].includes(url.pathname)) return null;
      url.searchParams.delete('return_to');
      return url.pathname + url.search + url.hash;
    } catch { return null; }
  }
  function here() { return localPath(location.pathname + location.search + location.hash); }
  function fromTask(href) {
    const url = new URL(href, location.origin);
    if (url.origin === location.origin && ['/', '/review', '/tasks', '/debug', '/start', '/versions'].includes(url.pathname)) url.searchParams.set('return_to', here());
    return url.pathname + url.search + url.hash;
  }
  const origin = localPath(new URLSearchParams(location.search).get('return_to'));
  function mount() {
    if (!document.querySelector('.studio')) {
      document.body.classList.add('workspace-page');
      const header = document.querySelector('body > .topbar');
      header.classList.add('workspace-topbar');
      const refresh = header.querySelector('#refresh') || header.querySelector('a.quiet');
      const label = document.createElement('span'); label.className = 'workspace-title';
      label.textContent = ({'/tasks':'目标','/review':'学习 / 待审建议','/debug':'学习 / 使用记录','/start':'工作台','/versions':'学习 / 方法'})[location.pathname] || '工作区';
      const tools = document.createElement('div'); tools.className = 'workspace-tools';
      for (const [text, href] of [['工作台','/start'],['学习审核','/review'],['个人方法','/versions'],['知识热力图','/debug#heatmap']]) {
        const link = document.createElement('a'); link.textContent = text; link.href = href;
        if (new URL(href,location.origin).pathname === location.pathname) link.setAttribute('aria-current','page');
        tools.append(link);
      }
      if (refresh) {
        if(refresh.tagName==='A'){refresh.href=location.href;refresh.addEventListener('click',event=>{if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();location.reload();});}
        tools.append(refresh);
      }
      header.replaceChildren(label, tools);
      const rail = document.createElement('aside'); rail.className = 'workspace-rail'; rail.setAttribute('aria-label','主导航');
      const brand = document.createElement('a'); brand.className = 'workspace-brand'; brand.href = '/start'; brand.textContent = 'oks.'; brand.setAttribute('aria-label','OKS 工作台'); rail.append(brand);
      const paths = {
        discussion:'<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M6 8.5v7M8.5 17c6 0 9.5-3 9.5-7.5"/>',
        goals:'<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1"/>',
        learning:'<path d="M12 5v15M3 4c4-1 7 0 9 2 2-2 5-3 9-2v15c-4-1-7 0-9 2-2-2-5-3-9-2Z"/>',
        messages:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/>',
        members:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>'
      };
      const nav = document.createElement('nav'); nav.setAttribute('aria-label','工作区');
      const secondary = document.createElement('nav'); secondary.className='workspace-secondary'; secondary.setAttribute('aria-label','讨论辅助');
      for (const [text, href, icon, active] of [['讨论','/#collaboration','discussion',false],['目标','/tasks','goals',location.pathname==='/tasks'],['学习','/#wiki','learning',['/review','/debug','/versions'].includes(location.pathname)],['通信','/#messages','messages',false],['成员','/#agents','members',false]]) {
        const link = document.createElement('a'); link.href = href==='/tasks'&&origin?.startsWith('/tasks')?origin:href; link.setAttribute('aria-label',text==='通信'?'通信记录':text);
        // Only fixed, repository-owned icon markup is inserted here.
        link.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24">'+paths[icon]+'</svg><span>'+text+'</span>';
        if(active)link.setAttribute('aria-current','page'); (['messages','members'].includes(icon)?secondary:nav).append(link);
      }
      rail.append(nav,secondary); document.body.prepend(rail);
    }
    const utilityHost=document.querySelector('.workspace-tools')||document.querySelector('.top-actions');
    if(utilityHost){
      const menu=document.createElement('details');menu.className='workspace-mobile-tools';
      const summary=document.createElement('summary');summary.textContent='更多';menu.append(summary);
      const links=document.createElement('div');
      for(const [text,href] of [['工作台','/start'],['学习审核','/review'],['个人方法','/versions'],['知识热力图','/debug#heatmap']]){const link=document.createElement('a');link.textContent=text;link.href=fromTask(href);links.append(link);}
      menu.append(links);utilityHost.prepend(menu);
    }
    if (origin) {
      const link = document.createElement('a'); link.className = 'workspace-return'; link.href = origin;
      link.textContent = origin.startsWith('/tasks') ? '← 返回目标' : origin.startsWith('/review') ? '← 返回审核' : origin.startsWith('/debug') ? '← 返回知识使用' : '← 返回来源';
      (document.querySelector('.workspace-topbar') || document.querySelector('.frame > .topbar'))?.prepend(link);
    }
  }
  mount();
  if(origin?.startsWith('/tasks')){const goal=document.querySelector('[data-route="/tasks"]');if(goal)goal.dataset.route=origin;}
  return {localPath, here, fromTask, origin};
})();
