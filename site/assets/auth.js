/**
 * Login do site privado: envia credenciais para /api/login e redireciona para a
 * rota interna pedida em `?next=`. Bloqueia open redirect (só caminho relativo).
 */
(function () {
  var form = document.getElementById('loginForm');
  if (!form) return;

  var errorBox = document.getElementById('loginError');
  var submit = document.getElementById('loginSubmit');

  // Só aceita caminho interno: começa com "/", não é protocol-relative ("//")
  // e não embute esquema. Caso contrário, cai no destino padrão seguro.
  function safeNext(raw) {
    if (!raw || typeof raw !== 'string') return '/dashboard';
    if (raw.charAt(0) !== '/' || raw.charAt(1) === '/') return '/dashboard';
    if (raw.indexOf('://') !== -1 || raw.indexOf('\\') !== -1) return '/dashboard';
    return raw;
  }

  function getNext() {
    try {
      return safeNext(new URLSearchParams(window.location.search).get('next'));
    } catch (e) {
      return '/dashboard';
    }
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.add('is-visible');
  }

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    errorBox.classList.remove('is-visible');
    submit.disabled = true;

    var payload = {
      user: document.getElementById('user').value,
      password: document.getElementById('password').value,
    };

    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (response) {
        if (response.ok) {
          window.location.assign(getNext());
          return null;
        }
        return response
          .json()
          .catch(function () { return {}; })
          .then(function (data) {
            showError((data && data.error) || 'Usuário ou senha inválidos.');
            submit.disabled = false;
          });
      })
      .catch(function () {
        showError('Falha de conexão. Tente novamente.');
        submit.disabled = false;
      });
  });
})();
