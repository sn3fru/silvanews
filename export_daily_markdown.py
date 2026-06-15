#!/usr/bin/env python3
"""
Exporta TODAS as notícias do dia em Markdown com frontmatter.

Dois tipos de arquivo:
  - Artigos que pertencem a um cluster: inclui resumo do cluster + texto raw
  - Artigos orfãos (sem cluster): só texto raw com metadados

Estrutura de saída:
  ../exportacoes_diarias/
    YYYY-MM-DD/
      clusters/
        62512_P1_megafusao-ferroviaria.md     (cluster com resumo + artigos raw)
      artigos/
        82001_valor-economico_titulo.md       (artigo individual)

Uso:
  python export_daily_markdown.py                    # exporta hoje
  python export_daily_markdown.py --date 2026-06-08  # data específica
  python export_daily_markdown.py --days 7           # últimos 7 dias
  python export_daily_markdown.py --clean            # limpa pasta antes de exportar
  python export_daily_markdown.py --debug            # diagnóstico do banco
"""

import os
import sys
import re
import unicodedata
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / "backend" / ".env")

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
from backend.utils import normalizar_fonte_display
from sqlalchemy import func, text

EXPORT_ROOT = Path(__file__).parent.parent / "exportacoes_diarias"

PRIORITY_SHORT = {
    "P1_CRITICO": "P1",
    "P2_ESTRATEGICO": "P2",
    "P3_MONITORAMENTO": "P3",
    "P3_REVISAR": "P3",
    "PENDING": "RAW",
    "IRRELEVANTE": "IRR",
}


def slugify(val: str, max_len: int = 60) -> str:
    if not val:
        return "sem-titulo"
    s = unicodedata.normalize("NFKD", val)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s-]", "", s.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:max_len].rstrip("-") or "sem-titulo"


def escape_yaml(val: str) -> str:
    if not val:
        return '""'
    if any(c in val for c in (':', '#', '{', '}', '[', ']', ',', '&', '*', '?', '|', '>', '<', '=', '!', '%', '@', '`', '"', "'")):
        return '"' + val.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return val


def resolve_fonte(artigo: ArtigoBruto) -> str:
    fonte_raw = artigo.jornal or ""
    meta = artigo.metadados or {}
    if not fonte_raw:
        fonte_raw = (
            meta.get("fonte_original")
            or meta.get("jornal")
            or meta.get("arquivo_origem", "").replace(".pdf", "").replace(".json", "")
            or ""
        )
    return normalizar_fonte_display(fonte_raw) or fonte_raw or "Desconhecida"


# ---------------------------------------------------------------------------
# Costura de fragmentos (notícia cortada entre páginas pelo OCR)
# ---------------------------------------------------------------------------

def _texto_de(a: ArtigoBruto) -> str:
    return (a.texto_processado or a.texto_bruto or "").strip()


def _pagina_raw(a: ArtigoBruto) -> Optional[str]:
    val = a.pagina
    if val in (None, "", "N/A"):
        meta = a.metadados or {}
        val = meta.get("pagina")
    if val in (None, "", "N/A"):
        return None
    return str(val).strip()


def _pagina_num(a: ArtigoBruto) -> int:
    """Primeiro número encontrado na página (para ordenar fragmentos). 999999 se ausente."""
    raw = _pagina_raw(a)
    if not raw:
        return 999999
    m = re.search(r"\d+", raw)
    return int(m.group()) if m else 999999


def _paginas_label(artigos: List[ArtigoBruto]) -> str:
    """Rótulo compacto das páginas dos fragmentos: 'p. 4-5' ou 'p. 4, 7'."""
    nums = sorted({_pagina_num(a) for a in artigos if _pagina_num(a) != 999999})
    if not nums:
        return ""
    if len(nums) == 1:
        return f"p. {nums[0]}"
    contiguo = nums == list(range(nums[0], nums[-1] + 1))
    if contiguo:
        return f"p. {nums[0]}-{nums[-1]}"
    return "p. " + ", ".join(str(n) for n in nums)


_WORD_RE = re.compile(r"\S+")


def _norm_word(w: str) -> str:
    """Normaliza uma palavra para comparação de overlap: minúscula, sem pontuação nas bordas."""
    return re.sub(r"^\W+|\W+$", "", w.lower())


def _stitch_texts(a: str, b: str, max_words: int = 120, min_words: int = 6) -> str:
    """
    Costura dois fragmentos da MESMA notícia removendo sobreposição de borda.

    O OCR página-a-página pode (a) cortar a notícia no meio (sem overlap) ou
    (b) repetir um trecho na virada de página. Esta função detecta um overlap
    de palavras entre o fim de `a` e o início de `b` e o remove, preservando a
    formatação original do restante de `b`.
    """
    a = (a or "").rstrip()
    b = (b or "").lstrip()
    if not a:
        return b
    if not b:
        return a

    a_tokens = list(_WORD_RE.finditer(a))
    b_tokens = list(_WORD_RE.finditer(b))
    wa = [m.group(0) for m in a_tokens]
    wb = [m.group(0) for m in b_tokens]

    win = min(max_words, len(wa), len(wb))
    la = [_norm_word(w) for w in wa[-win:]] if win else []
    lb = [_norm_word(w) for w in wb[:win]] if win else []

    best = 0
    for k in range(win, min_words - 1, -1):
        if la[-k:] == lb[:k] and all(la[-k:]):
            best = k
            break

    if best:
        # Remove o trecho duplicado do FIM de `a` e mantém `b` inteiro (a cópia
        # de `b` traz a continuação/pontuação corretas). Junta inline.
        cut_idx = len(a_tokens) - best
        if cut_idx <= 0:
            return b
        a = a[:a_tokens[cut_idx].start()].rstrip()
        return (a + " " + b).strip()

    # Sem overlap: decide entre continuação de frase (junta com espaço) ou
    # bloco separado (parágrafo novo).
    fim_sem_pontuacao = a[-1:] not in ".!?:…”\"')]}"
    inicio_minusculo = b[:1].islower()
    if fim_sem_pontuacao and inicio_minusculo:
        return a + " " + b
    return a + "\n\n" + b


def _agrupar_fragmentos(artigos: List[ArtigoBruto]) -> List[List[ArtigoBruto]]:
    """
    Dentro de UM cluster (= um evento), agrupa artigos pela mesma fonte/jornal.
    Vários artigos da mesma fonte no mesmo evento ≈ a mesma matéria fatiada em
    páginas pelo OCR. Cada grupo é ordenado por página para costura posterior.
    Preserva a ordem determinística (pela menor página / id de cada grupo).
    """
    grupos: dict = {}
    ordem: List[str] = []
    for a in artigos:
        chave = resolve_fonte(a)
        if chave not in grupos:
            grupos[chave] = []
            ordem.append(chave)
        grupos[chave].append(a)

    resultado: List[List[ArtigoBruto]] = []
    for chave in ordem:
        frags = sorted(grupos[chave], key=lambda x: (_pagina_num(x), x.id))
        resultado.append(frags)
    # Ordena grupos pela posição original (menor página, depois menor id)
    resultado.sort(key=lambda frags: (_pagina_num(frags[0]), frags[0].id))
    return resultado


def _escolher_titulo(frags: List[ArtigoBruto]) -> str:
    """Entre fragmentos, prefere o título mais informativo (mais longo não vazio)."""
    titulos = [(f.titulo_extraido or "").strip() for f in frags]
    titulos = [t for t in titulos if t]
    if not titulos:
        return "Sem título"
    return max(titulos, key=len)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_cluster_md(cluster: ClusterEvento, artigos: List[ArtigoBruto]) -> str:
    """1 cluster = resumo consolidado + texto raw de cada artigo."""
    fontes_unicas = []
    seen = set()
    for a in artigos:
        nome = resolve_fonte(a)
        if nome not in seen:
            seen.add(nome)
            fontes_unicas.append(nome)

    data_str = cluster.created_at.strftime("%Y-%m-%d") if cluster.created_at else ""

    lines = [
        "---",
        f"titulo: {escape_yaml(cluster.titulo_cluster)}",
        f"data: {data_str}",
        f"prioridade: {cluster.prioridade}",
        f"tag: {escape_yaml(cluster.tag or '')}",
        f"fontes: [{', '.join(escape_yaml(f) for f in fontes_unicas)}]",
        f"total_artigos: {len(artigos)}",
        f"cluster_id: {cluster.id}",
        "---",
    ]

    body = [f"# {cluster.titulo_cluster}\n"]

    resumo = (cluster.resumo_cluster or "").strip()
    if resumo and not resumo.startswith("Falha na classific"):
        body.append("## Resumo\n")
        body.append(resumo)
        body.append("")

    for frags in _agrupar_fragmentos(artigos):
        body.append(_artigo_section(frags))

    return "\n".join(lines) + "\n\n" + "\n".join(body) + "\n"


def build_artigo_md(artigo: ArtigoBruto) -> str:
    """1 artigo avulso (sem cluster)."""
    fonte = resolve_fonte(artigo)
    titulo = artigo.titulo_extraido or "Sem título"
    data_pub = artigo.data_publicacao or artigo.created_at
    data_str = data_pub.strftime("%Y-%m-%d") if data_pub else ""
    prio = artigo.prioridade or "PENDING"
    tag = artigo.tag or ""

    lines = [
        "---",
        f"titulo: {escape_yaml(titulo)}",
        f"fonte: {escape_yaml(fonte)}",
        f"data: {data_str}",
        f"prioridade: {prio}",
        f"tag: {escape_yaml(tag)}",
    ]
    if artigo.url_original:
        lines.append(f"url: {escape_yaml(artigo.url_original)}")
    if artigo.autor:
        lines.append(f"autor: {escape_yaml(artigo.autor)}")
    if artigo.categoria:
        lines.append(f"categoria: {escape_yaml(artigo.categoria)}")
    lines.append(f"artigo_id: {artigo.id}")
    lines.append("---")

    body = [f"# {titulo}\n"]
    if artigo.url_original:
        body.append(f"**Fonte:** [{fonte}]({artigo.url_original}) | {data_str}\n")
    else:
        body.append(f"**Fonte:** {fonte} | {data_str}\n")

    texto = (artigo.texto_processado or artigo.texto_bruto or "").strip()
    if texto:
        body.append(texto)
        body.append("")

    return "\n".join(lines) + "\n\n" + "\n".join(body) + "\n"


def _artigo_section(frags: List[ArtigoBruto]) -> str:
    """
    Bloco markdown de UMA notícia dentro de um cluster.

    `frags` são os fragmentos da mesma fonte (ordenados por página). Quando há
    mais de um, eles representam a mesma matéria fatiada em páginas pelo OCR e
    são costurados em um texto contínuo. Com um único fragmento, o resultado é
    idêntico ao comportamento anterior.
    """
    if not isinstance(frags, list):
        frags = [frags]

    base = frags[0]
    fonte = resolve_fonte(base)
    titulo = _escolher_titulo(frags)
    data_art = base.data_publicacao.strftime("%d/%m/%Y") if base.data_publicacao else ""

    # Costura os textos na ordem das páginas, removendo sobreposição de borda.
    texto = ""
    for f in frags:
        t = _texto_de(f)
        if not t:
            continue
        texto = t if not texto else _stitch_texts(texto, t)

    pag_label = _paginas_label(frags)
    meta_linha = " | ".join(p for p in (data_art, pag_label) if p)

    parts = [f"## {titulo}\n"]
    if base.url_original:
        parts.append(f"**Fonte:** [{fonte}]({base.url_original}){(' | ' + meta_linha) if meta_linha else ''}\n")
    else:
        parts.append(f"**Fonte:** {fonte}{(' | ' + meta_linha) if meta_linha else ''}\n")

    if texto:
        parts.append(texto)
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_date(target_date: date, clean: bool = False) -> dict:
    """Exporta TODOS os artigos do dia. Retorna stats."""
    db = SessionLocal()
    try:
        day_dir = EXPORT_ROOT / target_date.strftime("%Y-%m-%d")
        clusters_dir = day_dir / "clusters"
        artigos_dir = day_dir / "artigos"

        day_dir.mkdir(parents=True, exist_ok=True)
        clusters_dir.mkdir(exist_ok=True)
        artigos_dir.mkdir(exist_ok=True)

        if clean:
            for sub in (clusters_dir, artigos_dir):
                for old_file in sub.glob("*.md"):
                    old_file.unlink()

        stats = {"clusters": 0, "artigos_cluster": 0, "artigos_orfaos": 0}

        # --- Clusters (com seus artigos) ---
        clusters = (
            db.query(ClusterEvento)
            .filter(
                func.date(ClusterEvento.created_at) == target_date,
                ClusterEvento.status == "ativo",
            )
            .order_by(
                text(
                    "CASE WHEN prioridade = 'P1_CRITICO' THEN 1 "
                    "WHEN prioridade = 'P2_ESTRATEGICO' THEN 2 "
                    "WHEN prioridade = 'P3_MONITORAMENTO' THEN 3 ELSE 4 END"
                ),
                ClusterEvento.created_at.desc(),
            )
            .all()
        )

        for cluster in clusters:
            artigos = (
                db.query(ArtigoBruto)
                .filter(ArtigoBruto.cluster_id == cluster.id)
                .order_by(ArtigoBruto.id.asc())
                .all()
            )
            if not artigos:
                continue

            prio_short = PRIORITY_SHORT.get(cluster.prioridade, "RAW")
            titulo_slug = slugify(cluster.titulo_cluster)
            filename = f"{cluster.id}_{prio_short}_{titulo_slug}.md"

            content = build_cluster_md(cluster, artigos)
            (clusters_dir / filename).write_text(content, encoding="utf-8")
            stats["clusters"] += 1
            stats["artigos_cluster"] += len(artigos)

        # --- Artigos orfãos (sem cluster) ---
        orfaos = (
            db.query(ArtigoBruto)
            .filter(
                func.date(ArtigoBruto.created_at) == target_date,
                ArtigoBruto.cluster_id.is_(None),
            )
            .order_by(ArtigoBruto.id.asc())
            .all()
        )

        for artigo in orfaos:
            texto = (artigo.texto_processado or artigo.texto_bruto or "").strip()
            if not texto:
                continue

            fonte_slug = slugify(resolve_fonte(artigo), max_len=20)
            titulo_slug = slugify(artigo.titulo_extraido or "sem-titulo")
            filename = f"{artigo.id}_{fonte_slug}_{titulo_slug}.md"

            content = build_artigo_md(artigo)
            (artigos_dir / filename).write_text(content, encoding="utf-8")
            stats["artigos_orfaos"] += 1

        total = stats["artigos_cluster"] + stats["artigos_orfaos"]
        print(
            f"  [{target_date}] {total} artigos exportados "
            f"({stats['clusters']} clusters com {stats['artigos_cluster']} artigos "
            f"+ {stats['artigos_orfaos']} artigos avulsos) -> {day_dir}"
        )
        return stats

    finally:
        db.close()


def debug_database(target_date: date):
    db = SessionLocal()
    try:
        print(f"\n{'='*60}")
        print(f"DIAGNÓSTICO — {target_date}")
        print(f"{'='*60}")

        total_artigos = db.query(func.count(ArtigoBruto.id)).filter(
            func.date(ArtigoBruto.created_at) == target_date
        ).scalar()
        com_cluster = db.query(func.count(ArtigoBruto.id)).filter(
            func.date(ArtigoBruto.created_at) == target_date,
            ArtigoBruto.cluster_id.isnot(None),
        ).scalar()
        sem_cluster = db.query(func.count(ArtigoBruto.id)).filter(
            func.date(ArtigoBruto.created_at) == target_date,
            ArtigoBruto.cluster_id.is_(None),
        ).scalar()

        total_clusters = db.query(func.count(ClusterEvento.id)).filter(
            func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == "ativo",
        ).scalar()

        print(f"  Artigos total: {total_artigos}")
        print(f"    Em clusters: {com_cluster}")
        print(f"    Orfãos: {sem_cluster}")
        print(f"  Clusters ativos: {total_clusters}")

        for prio, cnt in db.query(
            ClusterEvento.prioridade, func.count(ClusterEvento.id)
        ).filter(
            func.date(ClusterEvento.created_at) == target_date,
            ClusterEvento.status == "ativo",
        ).group_by(ClusterEvento.prioridade).all():
            print(f"    {prio}: {cnt}")

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Exporta notícias do dia em Markdown")
    parser.add_argument("--date", type=str, help="Data específica (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=1, help="Dias retroativos (default: 1 = só hoje)")
    parser.add_argument("--debug", action="store_true", help="Mostra diagnóstico do banco")
    parser.add_argument("--clean", action="store_true", help="Remove .md antigos antes de exportar")
    args = parser.parse_args()

    if args.date:
        dates = [datetime.strptime(args.date, "%Y-%m-%d").date()]
    else:
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(args.days)]

    if args.debug:
        for d in sorted(dates):
            debug_database(d)
        return

    print(f"Exportando para: {EXPORT_ROOT}")
    totals = {"clusters": 0, "artigos_cluster": 0, "artigos_orfaos": 0}
    for d in sorted(dates):
        stats = export_date(d, clean=args.clean)
        for k in totals:
            totals[k] += stats.get(k, 0)

    total = totals["artigos_cluster"] + totals["artigos_orfaos"]
    print(f"\nTotal: {total} artigos em {len(dates)} dia(s).")


if __name__ == "__main__":
    main()
