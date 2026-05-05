# -*- coding: utf-8 -*-
import logging
import time
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

_DEFAULT_URL = "http://127.0.0.1:8787"
_POLL_INTERVAL = 2   # segundos entre polls em wait_for_login
_LOGIN_TIMEOUT = 180  # segundos máximos esperando connected=True


class WhatsAppPoster:
    """
    Cliente HTTP para o wa-service (Node.js + Baileys).
    Mantém a mesma interface pública do poster anterior baseado em Playwright,
    de modo que orchestrator.py não precisa de nenhuma alteração.
    """

    def __init__(self, target_name: str, base_url: str = _DEFAULT_URL):
        self.target_name = target_name
        self.base_url = base_url.rstrip("/")

    def start(self):
        """Verifica que o wa-service está no ar. Falha rápido se não estiver."""
        try:
            resp = requests.get(f"{self.base_url}/status", timeout=5)
            resp.raise_for_status()
            log.info(f"wa-service acessível em {self.base_url}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"wa-service não encontrado em {self.base_url}. "
                "Execute 'npm start' dentro de wa_service/ e tente novamente."
            )

    def wait_for_login(self):
        """
        Aguarda até que o wa-service reporte connected=True.
        Na primeira execução pós-QR o serviço pode demorar alguns segundos
        para completar o handshake com os servidores da Meta.
        """
        log.info("Aguardando conexão WhatsApp via wa-service...")
        deadline = time.time() + _LOGIN_TIMEOUT
        while time.time() < deadline:
            try:
                data = requests.get(f"{self.base_url}/status", timeout=5).json()
                if data.get("connected"):
                    log.info(f"WhatsApp conectado. JID: {data.get('jid')}")
                    return
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)
        raise TimeoutError(
            f"WhatsApp não conectou em {_LOGIN_TIMEOUT}s. "
            "Verifique se o QR foi escaneado no terminal do wa-service."
        )

    def post_offers(self, offers_data: list[dict]):
        """
        Recebe lista de dicts: [{"id": "...", "image_path": "...jpg", "text_path": "...txt"}]
        Repassa ao wa-service via POST /send e loga o resultado.
        """
        if not offers_data:
            return

        payload = {"target": self.target_name, "items": offers_data}
        try:
            resp = requests.post(
                f"{self.base_url}/send",
                json=payload,
                timeout=600,  # lote de 10 items × ~9s = ~90s + margem
            )
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Falha ao contatar wa-service: {exc}") from exc

        if resp.status_code == 503:
            raise RuntimeError(
                "wa-service retornou 503: WhatsApp desconectado durante o envio."
            )
        if not resp.ok:
            raise RuntimeError(
                f"wa-service retornou {resp.status_code}: {resp.text[:200]}"
            )

        result = resp.json()
        sent = result.get("sent", 0)
        errors = result.get("errors", 0)
        log.info(f"Lote finalizado: {sent} sucesso, {errors} erros.")
        if errors:
            for failure in result.get("failures", []):
                log.warning(f"  Falha em {failure['id']}: {failure['reason']}")

    def close(self):
        """No-op: o wa-service fica vivo entre ciclos do orquestrador."""
        log.info("WhatsAppPoster encerrado (wa-service permanece ativo).")
