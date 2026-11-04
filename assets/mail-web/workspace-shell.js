"use strict";
// URL-only navigation state. Never persist source documents or private reviews.
window.OksNavigation = (() => {
  const routes = ["/", "/tasks", "/review", "/debug", "/start", "/versions"];
  function localPath(value) {
    if (
      typeof value !== "string" ||
      !value.startsWith("/") ||
      value.startsWith("//") ||
      value.length > 4096
    )
      return null;
    try {
      const url = new URL(value, location.origin);
      if (url.origin !== location.origin || !routes.includes(url.pathname))
        return null;
      url.searchParams.delete("return_to");
      return url.pathname + url.search + url.hash;
    } catch {
      return null;
    }
  }
  function here() {
    return localPath(location.pathname + location.search + location.hash);
  }
  function fromTask(href) {
    const url = new URL(href, location.origin);
    if (url.origin === location.origin && routes.includes(url.pathname))
      url.searchParams.set("return_to", here());
    return url.pathname + url.search + url.hash;
  }
  const origin = localPath(
    new URLSearchParams(location.search).get("return_to"),
  );
  const embedded = new URLSearchParams(location.search).get("panel") === "1";
  function mount() {
    if (embedded) {
      document.body.classList.add("studio-panel");
      document.addEventListener(
        "click",
        (event) => {
          const route = event.target.closest("[data-route]");
          if (route) {
            const url = new URL(route.dataset.route, location.origin);
            if (
              url.origin === location.origin &&
              routes.includes(url.pathname)
            ) {
              url.searchParams.set("panel", "1");
              route.dataset.route = url.pathname + url.search + url.hash;
            }
          }
          const link = event.target.closest("a[href]");
          if (
            !link ||
            link.target === "_blank" ||
            link.hasAttribute("download")
          )
            return;
          const url = new URL(link.href, location.origin);
          if (url.origin === location.origin && routes.includes(url.pathname)) {
            url.searchParams.set("panel", "1");
            link.href = url.pathname + url.search + url.hash;
          }
        },
        true,
      );
      return;
    }
    if (!document.querySelector(".studio")) {
      document.body.classList.add("workspace-page");
      const header = document.querySelector("body > .topbar");
      if (!header) return;
      header.classList.add("workspace-topbar");
      const label = document.createElement("span");
      label.className = "workspace-title";
      label.textContent =
        {
          "/tasks": "目标 / 执行记录",
          "/review": "学习 / 审核",
          "/debug": "学习 / 统计",
          "/start": "学习 / 概览",
          "/versions": "学习 / 技能版本",
        }[location.pathname] || "OKS";
      // Keep existing refresh handlers valid without adding a global utility menu.
      const refresh = header.querySelector("#refresh");
      const tools = document.createElement("div");
      tools.className = "workspace-tools";
      if (refresh) tools.append(refresh);
      header.replaceChildren(label, tools);
      const rail = document.createElement("aside");
      rail.className = "workspace-rail";
      rail.setAttribute("aria-label", "主导航");
      const brand = document.createElement("a");
      brand.className = "workspace-brand";
      brand.href = "/";
      brand.textContent = "oks.";
      rail.append(brand);
      const nav = document.createElement("nav");
      for (const [text, tab] of [
        ["讨论", "discuss"],
        ["目标", "goals"],
        ["学习", "learning"],
      ]) {
        const link = document.createElement("a");
        link.textContent = text;
        link.href = "/#tab=" + tab;
        if ((location.pathname === "/tasks" ? "goals" : "learning") === tab)
          link.setAttribute("aria-current", "page");
        nav.append(link);
      }
      rail.append(nav);
      document.body.prepend(rail);
    }
    if (origin) {
      const header =
        document.querySelector(".workspace-topbar") ||
        document.querySelector(".frame > .topbar");
      if (header) {
        const link = document.createElement("a");
        link.className = "workspace-return";
        link.href = origin;
        link.textContent = "← 返回来源";
        header.prepend(link);
      }
    }
  }
  mount();
  return { localPath, here, fromTask, origin };
})();

if (new URLSearchParams(location.search).get("detail") === "1") document.body.classList.add("review-detail-only");
