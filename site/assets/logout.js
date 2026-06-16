/**
 * Encerra a sessão do site privado: limpa o cookie via /api/logout e volta para
 * a home pública. Usado pelo link `[data-logout]` das páginas protegidas.
 */
(function () {
  var link = document.querySelector('[data-logout]');
  if (!link) return;
  link.addEventListener('click', function (event) {
    event.preventDefault();
    fetch('/api/logout', { method: 'POST' })
      .catch(function () {})
      .then(function () {
        window.location.assign('/');
      });
  });
})();
