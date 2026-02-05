(function () {
  const BAD = ["sidebar-collapse", "sidebar-closed"];

  function fix() {
    const b = document.body;
    if (!b) return;
    BAD.forEach(c => b.classList.remove(c));
  }

  document.addEventListener("DOMContentLoaded", fix);
})();

