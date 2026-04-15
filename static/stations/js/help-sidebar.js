(() => {
  const toggleButton = document.getElementById("helpSidebarToggle");
  const sidebar = document.getElementById("helpSidebar");
  const closeButton = document.getElementById("helpSidebarClose");
  const backdrop = document.getElementById("helpSidebarBackdrop");

  if (!toggleButton || !sidebar || !closeButton || !backdrop) {
    return;
  }

  let lastFocusedElement = null;

  function isOpen() {
    return sidebar.classList.contains("is-open");
  }

  function setOpen(nextOpen) {
    if (nextOpen) {
      lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      sidebar.classList.add("is-open");
      sidebar.setAttribute("aria-hidden", "false");
      backdrop.hidden = false;
      window.requestAnimationFrame(() => {
        backdrop.classList.add("is-visible");
      });
      toggleButton.setAttribute("aria-expanded", "true");
      document.body.classList.add("help-sidebar-open");
      closeButton.focus();
      return;
    }

    sidebar.classList.remove("is-open");
    sidebar.setAttribute("aria-hidden", "true");
    backdrop.classList.remove("is-visible");
    toggleButton.setAttribute("aria-expanded", "false");
    document.body.classList.remove("help-sidebar-open");

    window.setTimeout(() => {
      if (!isOpen()) {
        backdrop.hidden = true;
      }
    }, 220);

    if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
      lastFocusedElement.focus();
    }
  }

  toggleButton.addEventListener("click", () => {
    setOpen(!isOpen());
  });

  closeButton.addEventListener("click", () => {
    setOpen(false);
  });

  backdrop.addEventListener("click", () => {
    setOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && isOpen()) {
      setOpen(false);
    }
  });
})();
