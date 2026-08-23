from django.test import SimpleTestCase

from apps.curation.services.product_family import product_family_key


class ProductFamilyKeyTests(SimpleTestCase):
    def test_agrupa_anuncios_distintos_do_mesmo_tipo_de_produto(self):
        """Par real reportado em 2026-08-21: duas piscinas em 3h, IDs de anúncio
        diferentes (mercadolivre:MLB_PiscinaRetangularI e
        mercadolivre:MLB_PiscinaInfantilRet), logo invisíveis para o dedup por
        produto_canonico_id."""
        primeira = product_family_key('Piscina Retangular Inflável Pvc Verão Fundo Acolchoado Azul Azul')
        segunda = product_family_key('Piscina Infantil Retangular Inflável De Plástico Resistente Azul')

        self.assertEqual(primeira, 'piscina')
        self.assertEqual(primeira, segunda)

    def test_agrupa_sinonimos_do_mesmo_tipo(self):
        hardline = product_family_key('Power Bank Hardline 20000mAh Turbo para Celular com 3 Portas')
        dtimp = product_family_key('Carregador Portátil Power Bank Turbo 20000mah 22.5w universal')

        self.assertEqual(hardline, 'power_bank')
        self.assertEqual(hardline, dtimp)

    def test_ignora_prefixo_de_anuncio_patrocinado(self):
        self.assertEqual(
            product_family_key('Anúncio patrocinado – Tênis Olympikus Only 2 Masculino'),
            'tenis',
        )

    def test_nao_confunde_acessorio_com_o_produto_acessado(self):
        """Cabeça genérica antes do tipo casado significa 'serve para', não 'é'."""
        self.assertEqual(product_family_key('Suporte Para Celular e Tablet Dobrável'), 'suporte_celular')
        self.assertEqual(product_family_key('Mesa Ergonômica Para Notebook Com Altura Regulável'), 'mesa')

    def test_frase_composta_vence_palavra_solta_na_mesma_posicao(self):
        self.assertEqual(
            product_family_key('Jogo De Panelas Cerâmica Antiaderente 8 Peças'),
            'jogo_de_panelas',
        )

    def test_separa_produtos_diferentes(self):
        self.assertNotEqual(
            product_family_key('Tênis Masculino Grand Court Base 3.0 adidas'),
            product_family_key('Mochila Linear adidas'),
        )

    def test_titulo_sem_tipo_identificavel_retorna_vazio(self):
        """Família vazia significa 'sem restrição'. Se retornasse uma família
        comum, títulos ilegíveis bloqueariam uns aos outros em cadeia."""
        self.assertEqual(product_family_key(''), '')
        self.assertEqual(product_family_key('123 456'), '')


class SingularFallbackTests(SimpleTestCase):
    """Plural do fallback por palavra-cabeça (2026-08-21).

    'Kit 10 Cuecas Boxer' e 'Cueca Boxer Kit 3' caíam em famílias diferentes, o
    que enfraquecia tanto o espaçamento de publicação quanto a medida de
    consenso entre grupos do radar de concorrente, que usa a mesma chave.
    """

    def test_plural_e_singular_caem_na_mesma_familia(self):
        self.assertEqual(
            product_family_key('Kit 10 Cuecas Boxer Mash Algodão'),
            product_family_key('Cueca Boxer Mash Algodão Kit 3'),
        )

    def test_nao_mutila_palavra_curta_terminada_em_s(self):
        self.assertEqual(product_family_key('Mais Barato Impossivel Produto'), 'mais')

    def test_nao_mexe_em_tipo_reconhecido(self):
        self.assertEqual(product_family_key('Tênis Olympikus Corre Trilha 2'), 'tenis')
