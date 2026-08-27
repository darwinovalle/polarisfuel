(() => {
  const modal = document.getElementById("introModal");
  const backdrop = document.getElementById("introModalBackdrop");
  const closeButton = document.getElementById("introModalClose");
  const continueButton = document.getElementById("introModalContinue");

  if (!modal || !backdrop || !closeButton || !continueButton) {
    return;
  }

  let isOpen = false;

  function openModal() {
    if (isOpen) {
      return;
    }

    isOpen = true;
    backdrop.hidden = false;
    modal.hidden = false;

    window.requestAnimationFrame(() => {
      backdrop.classList.add("is-visible");
      modal.classList.add("is-open");
    });

    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("intro-modal-open");
    continueButton.focus();
  }

  function closeModal() {
    if (!isOpen) {
      return;
    }

    isOpen = false;
    backdrop.classList.remove("is-visible");
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("intro-modal-open");

    window.setTimeout(() => {
      if (!isOpen) {
        backdrop.hidden = true;
        modal.hidden = true;
      }
    }, 240);
  }

  closeButton.addEventListener("click", closeModal);
  continueButton.addEventListener("click", closeModal);
  backdrop.addEventListener("click", closeModal);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeModal();
    }
  });

  openModal();
})();
