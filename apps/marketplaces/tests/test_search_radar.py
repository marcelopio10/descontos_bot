from apps.marketplaces.services.search_radar import SEARCH_BRANDS, build_search_radar


def test_search_radar_exposes_expanded_brand_families(monkeypatch):
    monkeypatch.setattr(
        'apps.marketplaces.services.search_radar.build_observer_context',
        lambda **kwargs: {
            'opportunity_radar': {
                'brands': {'insider': 4, 'lattafa': 3, 'growth': 2},
                'categories': {'categoria:moda': 4},
                'marketplaces': {'mercadolivre': 8},
                'price_bands': {'50_100': 3},
                'coupons': {'CUPOM': 8, 'VALIDO10': 2},
            }
        },
    )
    radar = build_search_radar()
    terms = {row['term'] for row in radar['brands']}
    assert {'insider', 'lattafa', 'growth'} <= terms
    assert radar['generic_coupon_prevalence'] == 8
    assert radar['coupon_signals'] == {'VALIDO10': 2}


def test_brand_catalog_contains_required_families():
    assert 'insider' in SEARCH_BRANDS['moda']
    assert 'lattafa' in SEARCH_BRANDS['perfumes_arabes']
    assert 'growth' in SEARCH_BRANDS['suplementos']
    assert 'max titanium' in SEARCH_BRANDS['suplementos']
    assert 'dark lab' in SEARCH_BRANDS['suplementos']
