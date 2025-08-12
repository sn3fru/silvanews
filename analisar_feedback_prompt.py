"""
Protótipo: analisador de feedback (like/dislike) para sugerir ajustes de prompt

Objetivo
- Ler itens de feedback (tabela feedback_noticias) e artigos/clusters relacionados
- Gerar um resumo com exemplos positivos/negativos, distribuição por tag/prioridade
- Propor um ajuste incremental do prompt de agrupamento (sem alterar nada em produção)
- Emitir um diff (unified) entre o prompt atual e o proposto para revisão humana

Uso
  conda activate pymc2
  python analisar_feedback_prompt.py --limit 200 --output reports/prompt_diff_feedback.md

Observações
- Não altera arquivos de prompt. Apenas gera um relatório (Markdown) com o diff
- Pode ser estendido para outros prompts (resumo final, sanitização, etc.)
"""

from __future__ import annotations

import argparse
import collections
import os
from dataclasses import dataclass
from typing import List, Dict, Optional
import difflib

try:
    # Imports do pacote do projeto
    from btg_alphafeed.backend.database import SessionLocal, ArtigoBruto, ClusterEvento, FeedbackNoticia
    from btg_alphafeed.backend.prompts import PROMPT_AGRUPAMENTO_V1  # type: ignore
except Exception:
    # Fallback relativo ao executar a partir da pasta do projeto
    from backend.database import SessionLocal, ArtigoBruto, ClusterEvento, FeedbackNoticia  # type: ignore
    try:
        from backend.prompts import PROMPT_AGRUPAMENTO_V1  # type: ignore
    except Exception:
        PROMPT_AGRUPAMENTO_V1 = ""  # Se não existir, segue com vazio


@dataclass
class FeedbackExample:
    artigo_id: int
    feedback: str  # 'like' | 'dislike'
    titulo: Optional[str]
    jornal: Optional[str]
    tag: Optional[str]
    prioridade: Optional[str]
    cluster_id: Optional[int]


def coletar_feedback(limit: int = 200) -> List[FeedbackExample]:
    """Coleta os últimos itens de feedback com contexto de artigo e cluster."""
    session = SessionLocal()
    try:
        # Busca últimos feedbacks (mais recentes primeiro)
        fbs: List[FeedbackNoticia] = (
            session.query(FeedbackNoticia)
            .order_by(FeedbackNoticia.created_at.desc())
            .limit(limit)
            .all()
        )

        exemplos: List[FeedbackExample] = []
        artigo_ids = [fb.artigo_id for fb in fbs]
        if not artigo_ids:
            return exemplos

        # Pré-carrega artigos e clusters em mapas para reduzir roundtrips
        artigos = (
            session.query(ArtigoBruto)
            .filter(ArtigoBruto.id.in_(artigo_ids))
            .all()
        )
        artigo_by_id: Dict[int, ArtigoBruto] = {a.id: a for a in artigos}

        cluster_ids = list({a.cluster_id for a in artigos if a.cluster_id})
        clusters = (
            session.query(ClusterEvento)
            .filter(ClusterEvento.id.in_(cluster_ids))
            .all()
        ) if cluster_ids else []
        cluster_by_id: Dict[int, ClusterEvento] = {c.id: c for c in clusters}

        for fb in fbs:
            art = artigo_by_id.get(fb.artigo_id)
            cl: Optional[ClusterEvento] = cluster_by_id.get(art.cluster_id) if art and art.cluster_id else None
            exemplos.append(
                FeedbackExample(
                    artigo_id=fb.artigo_id,
                    feedback=fb.feedback,
                    titulo=(art.titulo_extraido if art else None),
                    jornal=(art.jornal if art else None),
                    tag=(cl.tag if cl else art.tag if art else None),
                    prioridade=(cl.prioridade if cl else art.prioridade if art else None),
                    cluster_id=(cl.id if cl else art.cluster_id if art else None),
                )
            )
        return exemplos
    finally:
        session.close()


def sintetizar_padroes(exemplos: List[FeedbackExample]) -> Dict[str, Dict[str, int]]:
    """Gera contagens por tag e prioridade separando likes/dislikes."""
    cont = {
        "likes_por_tag": collections.Counter(),
        "dislikes_por_tag": collections.Counter(),
        "likes_por_prioridade": collections.Counter(),
        "dislikes_por_prioridade": collections.Counter(),
    }
    for ex in exemplos:
        if ex.feedback == "like":
            if ex.tag:
                cont["likes_por_tag"][ex.tag] += 1
            if ex.prioridade:
                cont["likes_por_prioridade"][ex.prioridade] += 1
        else:
            if ex.tag:
                cont["dislikes_por_tag"][ex.tag] += 1
            if ex.prioridade:
                cont["dislikes_por_prioridade"][ex.prioridade] += 1
    # Converte para dict normal
    return {k: dict(v) for k, v in cont.items()}


def montar_addendum_feedback(contagens: Dict[str, Dict[str, int]], exemplos: List[FeedbackExample]) -> str:
    """Monta um trecho de instruções adicionais baseado no feedback coletado.
    Não substitui o prompt: apenas adiciona orientações explícitas.
    """
    top_likes_tag = sorted(contagens["likes_por_tag"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_dislikes_tag = sorted(contagens["dislikes_por_tag"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_likes_prio = sorted(contagens["likes_por_prioridade"].items(), key=lambda x: x[1], reverse=True)[:5]
    top_dislikes_prio = sorted(contagens["dislikes_por_prioridade"].items(), key=lambda x: x[1], reverse=True)[:5]

    exemplos_like = [ex for ex in exemplos if ex.feedback == "like" and ex.titulo][:5]
    exemplos_dislike = [ex for ex in exemplos if ex.feedback == "dislike" and ex.titulo][:5]

    linhas = []
    linhas.append("\n\n=== AJUSTES ORIENTADOS POR FEEDBACK (NÃO REMOVER, APENAS APLICAR) ===\n")
    linhas.append("1) Preferências observadas (Tags com mais likes):")
    for tag, qtd in top_likes_tag:
        linhas.append(f"   - Dar prioridade a eventos relacionados a '{tag}' (likes: {qtd})")
    linhas.append("2) Evitar/baixar prioridade (Tags com mais dislikes):")
    for tag, qtd in top_dislikes_tag:
        linhas.append(f"   - Reduzir relevância/ponderação para '{tag}' quando marginal (dislikes: {qtd})")
    linhas.append("3) Padrões por prioridade (likes): " + ", ".join([f"{p}:{q}" for p, q in top_likes_prio]) )
    linhas.append("4) Padrões por prioridade (dislikes): " + ", ".join([f"{p}:{q}" for p, q in top_dislikes_prio]) )
    linhas.append("5) Exemplos positivos recentes (títulos):")
    for ex in exemplos_like:
        linhas.append(f"   - [{ex.prioridade}|{ex.tag}] {ex.titulo}")
    linhas.append("6) Exemplos negativos recentes (títulos):")
    for ex in exemplos_dislike:
        linhas.append(f"   - [{ex.prioridade}|{ex.tag}] {ex.titulo}")

    linhas.append("\nInstrução explícita ao modelo:")
    linhas.append("- Ao classificar e agrupar, alinhar-se às preferências acima; se um item estiver em categorias com alto índice de dislikes, só promova a P1/P2 se atender critérios fortes e explícitos. Caso contrário, mantenha em P3 ou 'IRRELEVANTE'.")

    return "\n".join(linhas)


def gerar_prompt_proposto(prompt_atual: str, addendum: str) -> str:
    if not prompt_atual:
        return addendum.strip()
    return (prompt_atual.rstrip() + "\n\n" + addendum.strip() + "\n").strip()


def gerar_markdown_relatorio(prompt_atual: str, prompt_proposto: str, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    diff_lines = list(
        difflib.unified_diff(
            prompt_atual.splitlines(),
            prompt_proposto.splitlines(),
            fromfile="PROMPT_AGRUPAMENTO_V1 (atual)",
            tofile="PROMPT_AGRUPAMENTO_V1 (proposto)",
            lineterm="",
            n=3,
        )
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Relatório de Ajuste de Prompt Orientado por Feedback\n\n")
        f.write("Este relatório é um protótipo. Ele não altera o prompt em produção.\n\n")

        f.write("## Prompt atual\n")
        f.write("```text\n" + prompt_atual + "\n```\n\n")

        f.write("## Prompt proposto (apenas para revisão)\n")
        f.write("```text\n" + prompt_proposto + "\n```\n\n")

        f.write("## Diff (unified)\n")
        f.write("```diff\n" + "\n".join(diff_lines) + "\n```\n")


def main():
    parser = argparse.ArgumentParser(description="Protótipo de ajuste de prompt guiado por feedback like/dislike")
    parser.add_argument("--limit", type=int, default=200, help="Quantidade de feedbacks mais recentes para analisar")
    parser.add_argument("--output", type=str, default="reports/prompt_diff_feedback.md", help="Caminho do relatório Markdown")
    args = parser.parse_args()

    exemplos = coletar_feedback(limit=args.limit)
    if not exemplos:
        print("Não há feedback suficiente para análise.")
        return

    contagens = sintetizar_padroes(exemplos)
    addendum = montar_addendum_feedback(contagens, exemplos)
    prompt_atual = PROMPT_AGRUPAMENTO_V1 or ""
    prompt_proposto = gerar_prompt_proposto(prompt_atual, addendum)
    gerar_markdown_relatorio(prompt_atual, prompt_proposto, args.output)

    print(f"✅ Relatório gerado em: {args.output}")
    print("(Este processo não altera nenhum arquivo de prompt em produção.)")


if __name__ == "__main__":
    main()


