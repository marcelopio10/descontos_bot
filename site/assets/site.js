(function () {
  const FALLBACK_DESCRIPTION = 'Oferta selecionada pelo descontos.bot com base nos dados públicos coletados. Confira preço, disponibilidade e condições finais na loja.';

  function money(value) {
    if (value === null || value === undefined || value === '') return '';
    return Number(value).toLocaleString('pt-BR', {
      style: 'currency',
      currency: 'BRL',
    });
  }

  function formatTimestamp(value) {
    if (!value) return 'Preço coletado em horário não informado. O valor pode variar.';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Preço coletado em horário não informado. O valor pode variar.';
    return `Preço coletado em ${date.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })}. O valor pode variar.`;
  }

  function text(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
  }

  async function loadPayload() {
    const response = await fetch('offers.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function offerMarketplace(offer) {
    return offer.marketplace && offer.marketplace.name ? offer.marketplace.name : 'Marketplace';
  }

  function offerMarketplaceCode(offer) {
    return offer.marketplace && offer.marketplace.code ? offer.marketplace.code : '';
  }

  function renderCard(offer) {
    const detailUrl = offer.detail_url || `/oferta.html?slug=${encodeURIComponent(offer.slug)}`;
    const oldPrice = offer.original_price && Number(offer.original_price) > Number(offer.current_price)
      ? `<span class="old-price">${money(offer.original_price)}</span>`
      : '';
    const discount = Number(offer.discount_pct || 0) > 0
      ? `<span class="discount">${Number(offer.discount_pct).toFixed(0)}% menor</span>`
      : '';
    return `
      <article class="offer-card">
        <img src="${text(offer.image_url)}" alt="${text(offer.title)}" loading="lazy">
        <div class="offer-card-body">
          <span class="marketplace">${text(offerMarketplace(offer))}</span>
          <div class="offer-name">${text(offer.title)}</div>
          <div class="price-row">
            <span class="current-price">${money(offer.current_price)}</span>
            ${oldPrice}
          </div>
          ${discount}
          <div class="collected">${formatTimestamp(offer.price_collected_at)}</div>
          <div class="card-actions">
            <a class="btn btn-secondary" href="${detailUrl}">Detalhes</a>
            <a class="btn btn-primary" href="${text(offer.affiliate_link)}" target="_blank" rel="sponsored nofollow noopener">Ver na loja</a>
          </div>
        </div>
      </article>
    `;
  }

  function initHome() {
    const grid = document.getElementById('offersGrid');
    const count = document.getElementById('offerCount');
    const generated = document.getElementById('generatedAt');
    const buttons = Array.from(document.querySelectorAll('.filter'));
    let offers = [];
    let activeMarketplace = 'all';

    function render() {
      const filtered = activeMarketplace === 'all'
        ? offers
        : offers.filter((offer) => offerMarketplaceCode(offer) === activeMarketplace);
      grid.innerHTML = filtered.length
        ? filtered.slice(0, 48).map(renderCard).join('')
        : '<div class="state-message">Nenhuma oferta encontrada para este filtro.</div>';
    }

    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        buttons.forEach((item) => item.classList.remove('is-active'));
        button.classList.add('is-active');
        activeMarketplace = button.dataset.marketplace;
        render();
      });
    });

    grid.innerHTML = '<div class="state-message">Carregando ofertas...</div>';
    loadPayload()
      .then((payload) => {
        offers = (payload.offers || []).slice().sort(
          (a, b) => Number(b.discount_pct || 0) - Number(a.discount_pct || 0),
        );
        count.textContent = offers.length;
        generated.textContent = payload.generated_at
          ? `Atualizado em ${new Date(payload.generated_at).toLocaleString('pt-BR')}`
          : 'Atualização não informada';
        render();
      })
      .catch(() => {
        grid.innerHTML = '<div class="state-message">Não foi possível carregar offers.json.</div>';
        count.textContent = '0';
        generated.textContent = 'Falha ao sincronizar';
      });
  }

  function initOfferPage() {
    const detail = document.getElementById('offerDetail');
    const slug = new URLSearchParams(window.location.search).get('slug');
    if (!slug) {
      detail.innerHTML = '<div class="state-message">Oferta não informada.</div>';
      return;
    }

    detail.innerHTML = '<div class="state-message">Carregando oferta...</div>';
    loadPayload()
      .then((payload) => {
        const offer = (payload.offers || []).find((item) => item.slug === slug);
        if (!offer) {
          detail.innerHTML = '<div class="state-message">Oferta não encontrada.</div>';
          return;
        }
        const oldPrice = offer.original_price && Number(offer.original_price) > Number(offer.current_price)
          ? `<span class="old-price">${money(offer.original_price)}</span>`
          : '';
        const discount = Number(offer.discount_pct || 0) > 0
          ? `<span class="discount">${Number(offer.discount_pct).toFixed(0)}% menor</span>`
          : '';
        detail.innerHTML = `
          <img class="detail-image" src="${text(offer.image_url)}" alt="${text(offer.title)}">
          <div class="detail-copy">
            <p class="eyebrow">${text(offerMarketplace(offer))}</p>
            <h1 class="offer-title">${text(offer.title)}</h1>
            <div class="detail-meta">
              <div class="price-row">
                <span class="current-price">${money(offer.current_price)}</span>
                ${oldPrice}
              </div>
              ${discount}
            </div>
            <p class="collected">${formatTimestamp(offer.price_collected_at)}</p>
            <p class="description">${text(offer.short_description || FALLBACK_DESCRIPTION)}</p>
            <p class="disclosure-inline">${text(payload.disclosure || 'Como Associado da Amazon, ganho por compras qualificadas.')}</p>
            <br>
            <div class="detail-actions">
              <a class="btn btn-secondary" href="/">Ver outras ofertas</a>
              <a class="btn btn-primary" href="${text(offer.affiliate_link)}" target="_blank" rel="sponsored nofollow noopener">Ver na loja</a>
            </div>
          </div>
        `;
        document.title = `${offer.title} | descontos.bot`;
      })
      .catch(() => {
        detail.innerHTML = '<div class="state-message">Não foi possível carregar offers.json.</div>';
      });
  }

  window.DescontosBot = {
    initHome,
    initOfferPage,
  };
}());
