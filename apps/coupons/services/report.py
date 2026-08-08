from __future__ import annotations

from html import escape
from pathlib import Path

from django.conf import settings
from django.utils import timezone


def write_coupon_report(run, *, path: str | Path, rejected=None, posts=None, publication_rows=None):
    rejected = rejected or []
    posts = posts or []
    publication_rows = publication_rows or []
    rows = ''.join(
        f'<tr><td>{escape(str(item.get("marketplace", "")))}</td><td>{escape(str(item.get("reason", "")))}</td><td>{escape(str(item.get("source_url", "")))}</td></tr>'
        for item in rejected
    )
    post_rows = ''.join(
        f'<article><h3>{escape(str(item.get("marketplace", "")))}</h3><pre>{escape(str(item.get("post", "")))}</pre><p>Destino: {escape(str(item.get("published_url", "")))}</p></article>'
        for item in posts
    )
    delivery_rows = ''.join(
        f'<tr><td>{escape(str(item.get("channel", "")))}</td><td>{escape(str(item.get("status", "")))}</td><td>{escape(str(item.get("error", "")))}</td></tr>'
        for item in publication_rows
    )
    decision_rows = ''.join(
        f'<tr><td>{escape(str(candidate.marketplace))}</td><td>{escape(str(getattr(getattr(candidate, "decision", None), "classification", "deterministic_rejected")))}</td><td>{escape(str(getattr(getattr(candidate, "decision", None), "reason", candidate.rejection_reason)))}</td></tr>'
        for candidate in run.candidates.select_related('decision').all()
    )
    html = f'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Cupons {run.started_at:%Y-%m-%d}</title>
    <style>body{{font:16px system-ui;max-width:1100px;margin:2rem auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:.5rem}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:1rem}}</style>
    <h1>Pipeline de cupons — {run.started_at:%Y-%m-%d}</h1><p>Status: <b>{escape(run.status)}</b> | Início: {run.started_at:%d/%m/%Y %H:%M} | Candidatos: {run.candidates_found} | Selecionados: {run.selected_count}</p>
    <h2>Fontes e Observer</h2><pre>{escape(str(run.sources_json))}</pre><pre>{escape(str(run.observer_pattern_json))}</pre>
    <h2>Resultado da curadoria IA</h2><table><tr><th>Marketplace</th><th>Classificação</th><th>Justificativa</th></tr>{decision_rows}</table>
    <h2>Rejeitados</h2><table><tr><th>Marketplace</th><th>Motivo</th><th>Fonte</th></tr>{rows}</table>'''
    html += f'''<h2>Posts gerados</h2>{post_rows or '<p>Nenhum.</p>'}
    <h2>Publicação por canal</h2><table><tr><th>Canal</th><th>Status</th><th>Erro</th></tr>{delivery_rows}</table>
    <h2>Erros e fallbacks</h2><pre>{escape(str(run.errors_json))}</pre></html>'''
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding='utf-8')
    return destination
