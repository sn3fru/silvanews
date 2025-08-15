from __future__ import annotations

"""
Agente 'Estagiário' — Conversa sobre TODAS as notícias do dia (em construção)

Objetivo:
- Fornecer uma interface de consulta inteligente sobre os eventos do dia
  sem alterar a lógica atual do pipeline/FE.

Regras:
- Não duplica lógica de negócio do pipeline
- Consulta o banco via funções existentes do backend
- Seleciona apenas dados úteis por prioridade/tag conforme a pergunta

Status: EM CONSTRUÇÃO 🚧
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import os

try:
    # Imports relativos ao backend já existente
    from backend.database import SessionLocal
    from backend.crud import (
        get_clusters_for_feed_by_date,
        get_cluster_details_by_id,
        get_metricas_by_date,
    )
    from backend.utils import get_date_brasil
    # Opcional: acesso direto ao modelo para contagens precisas
    from backend.database import ClusterEvento
except Exception:
    # Evita crash em ambientes onde backend não está configurado
    SessionLocal = None # type: ignore


@dataclass
class AgentAnswer:
    ok: bool
    text: str
    data: Optional[Dict[str, Any]] = None


class EstagiarioAgent:
    """Agente de consulta de alto nível sobre as notícias do dia."""

    def __init__(self) -> None:
        if SessionLocal is None:
            raise RuntimeError("Backend indisponível para EstagiárioAgent")
        # Carrega KB
        try:
            kb_path = Path(__file__).parent / "knowledge" / "KB_SITE.md"
            self.kb_text = kb_path.read_text(encoding="utf-8")
            print(f"[Estagiario] KB carregado: {kb_path}")
        except Exception as e:
            self.kb_text = ""
            print(f"[Estagiario] KB indisponível: {e}")
        # LLM opcional
        self.model = None
        try:
            import google.generativeai as genai  # type: ignore
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel('gemini-2.0-flash')
                print("[Estagiario] LLM configurado (Gemini)")
            else:
                print("[Estagiario] LLM não configurado (GEMINI_API_KEY ausente)")
        except Exception as e:
            print(f"[Estagiario] LLM indisponível: {e}")

        # Catálogo de prioridades e tags permitidas
        self.prioridades_permitidas = [
            "P1_CRITICO", "P2_ESTRATEGICO", "P3_MONITORAMENTO", "IRRELEVANTE"
        ]
        try:
            from backend.prompts import TAGS_SPECIAL_SITUATIONS  # type: ignore
            self.tags_permitidas = [t.get('nome') for t in TAGS_SPECIAL_SITUATIONS if isinstance(t, dict) and t.get('nome')]
        except Exception:
            self.tags_permitidas = [
                "Jurídico", "M&A", "Mercado de Capitais", "Política Econômica",
                "Internacional", "Tecnologia e Setores Estratégicos", "Distressed Assets", "Outros"
            ]

    def _open_db(self):
        print("[Estagiario] Abrindo sessão DB...")
        return SessionLocal()

    def _fetch_clusters(
        self,
        db,
        target_date: Optional[datetime.date] = None,
        priority: Optional[str] = None,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        """Carrega todas as páginas para a prioridade informada (ou todas)."""
        if target_date is None:
            target_date = get_date_brasil()

        page = 1
        itens: List[Dict[str, Any]] = []
        print(f"[Estagiario] Fetch clusters date={target_date.isoformat()} priority={priority or 'ALL'} page_size={page_size}")
        while True:
            resp = get_clusters_for_feed_by_date(
                db, target_date, page=page, page_size=page_size, load_full_text=False, priority=priority
            )
            clusters = resp.get("clusters", [])
            itens.extend(clusters)
            pag = resp.get("paginacao", {})
            print(f"[Estagiario]  page={page} carregados={len(clusters)} acumulado={len(itens)} tem_proxima={bool(pag.get('tem_proxima'))}")
            if not pag or not pag.get("tem_proxima"):
                break
            page += 1
        return itens

    def _llm_answer(self, question: str, retrieved: List[Dict[str, Any]]) -> Optional[str]:
        if not self.model:
            return None
        try:
            # Monta contexto curto com itens recuperados
            exemplos = []
            for it in retrieved[:12]:
                exemplos.append({
                    "id": it.get("id"),
                    "titulo": it.get("titulo") or it.get("titulo_final"),
                    "resumo": it.get("resumo") or it.get("resumo_final"),
                    "tag": it.get("tag"),
                    "prioridade": it.get("prioridade"),
                    "fontes": it.get("fontes", []),
                    "artigos": it.get("artigos", []),
                })
            prompt = (
                "Você é um analista do BTG na mesa de Special Situations. Produza um RELATÓRIO em Markdown, direto ao ponto,"
                " usando as notícias como insumos. Vá além de listar notícias; sintetize insights e impactos.\n\n"
                "KB (resumo):\n" + (self.kb_text[:6000]) + "\n\n"
                "Amostra de dados (clusters do dia):\n" + str(exemplos) + "\n\n"
                "Instruções de resposta (obrigatório):\n"
                "- Proibido descrever etapas, ferramentas ou plano.\n"
                "- Estruture com (exemplo de seções): ## Panorama, ## Principais Sinais (bullets), ## Preços/Promoções (tabela, se cabível), ## Riscos, ## Oportunidades, ## Ações sugeridas.\n"
                "- Traga nomes de autores e jornais quando disponíveis; cite prioridades/tags quando agregarem contexto.\n"
                "- Evite frases como 'Com base nos dados fornecidos'.\n"
                "- Finalize com 'Notícias pesquisadas:' numerada no formato [ID] Título — URL (Jornal).\n\n"
                "Pergunta do usuário: " + question + "\n"
            )
            print("[Estagiario] Síntese LLM iniciada...")
            resp = self.model.generate_content(prompt, generation_config={
                'temperature': 0.3,
                'top_p': 0.8,
                'max_output_tokens': 5_000
            })
            txt = (resp.text or "").strip()
            print(f"[Estagiario] Síntese LLM concluída. Len={len(txt)}")
            return txt or None
        except Exception as e:
            print(f"[Estagiario] Falha LLM: {e}")
            return None

    def _compose_markdown_from_retrieved(self, question: str, retrieved: List[Dict[str, Any]]) -> str:
        titulo_secao = "## Resposta"
        bullets: List[str] = []
        fontes_items: List[str] = []
        for it in retrieved[:8]:
            t = (it.get("titulo") or it.get("titulo_final") or "").strip()
            r = (it.get("resumo") or it.get("resumo_final") or "").strip()
            pr = (it.get("prioridade") or "").strip()
            tg = (it.get("tag") or "").strip()
            bullets.append(f"- {t} ({pr}{' · ' + tg if tg else ''}) — {r}")
            for f in it.get("fontes", [])[:2]:
                fid = f.get('id') or it.get('id')
                ft = (f.get('titulo') or t or '').strip()
                url = (f.get('url') or '').strip()
                j = (f.get('jornal') or '').strip()
                if url:
                    fontes_items.append(f"[{fid}] {ft} — [{url}]({url}){f' ({j})' if j else ''}")
                else:
                    fontes_items.append(f"[{fid}] {ft}{f' ({j})' if j else ''}")
        md = titulo_secao + "\n" + ("\n".join(bullets) if bullets else "- (sem itens)")
        if fontes_items:
            numeradas = [f"{i}. {txt}" for i, txt in enumerate(fontes_items, start=1)]
            md += "\n\n### Notícias pesquisadas:\n" + "\n".join(numeradas)
        return md

    def _llm_summarize_from_raw(self, question: str, clusters_detalhes: List[Dict[str, Any]]) -> Optional[str]:
        if not self.model or not clusters_detalhes:
            return None
        try:
            # Prepara amostra enxuta de textos brutos
            pacote: List[Dict[str, Any]] = []
            for c in clusters_detalhes[:4]:
                artigos = []
                for a in (c.get("artigos") or [])[:3]:
                    trecho = (a.get("texto_completo") or "")[:1200]
                    artigos.append({
                        "id": a.get("id"),
                        "titulo": a.get("titulo"),
                        "jornal": a.get("jornal"),
                        "url": a.get("url_original"),
                        "trecho": trecho
                    })
                pacote.append({
                    "cluster_id": c.get("id"),
                    "titulo": c.get("titulo_final"),
                    "prioridade": c.get("prioridade"),
                    "tag": c.get("tag"),
                    "artigos": artigos
                })
            instr = (
                "Você é analista da mesa de Special Situations do BTG. Escreva um RESUMO em Markdown, direto ao ponto,"
                " usando apenas os textos abaixo (amostra de artigos brutos).\n\n"
                "Regras obrigatórias:\n"
                "- Proibido explicar o plano, ferramentas ou etapas. Responda o que foi pedido.\n"
                "- Estruture com títulos (##) e bullets.\n"
                "- Conclua com seção 'Notícias pesquisadas:' numerada com [ID] Título — URL (Jornal).\n\n"
                f"Pergunta: {question}\n\n"
                f"Artigos (amostra): {pacote}\n"
            )
            print("[Estagiario] Síntese LLM (raw) iniciada...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.2, 'top_p': 0.8, 'max_output_tokens': 896})
            txt = (resp.text or "").strip()
            print(f"[Estagiario] Síntese LLM (raw) concluída. Len={len(txt)}")
            return txt or None
        except Exception as e:
            print(f"[Estagiario] Falha na síntese raw: {e}")
            return None

    def _llm_select_candidates(self, question: str, candidates: List[Dict[str, Any]]) -> List[int]:
        """Usa o LLM para triagem semântica: escolhe IDs mais relevantes para a pergunta."""
        if not self.model or not candidates:
            return []
        try:
            prio_weight = {"P1_CRITICO": 3, "P2_ESTRATEGICO": 2, "P3_MONITORAMENTO": 1}
            # Prioriza por P1>P2>P3 e limita a 60 itens para não estourar contexto
            ordered = sorted(candidates, key=lambda c: prio_weight.get(c.get("prioridade") or "P3_MONITORAMENTO", 1), reverse=True)
            sample = [
                {
                    "id": c.get("id"),
                    "titulo": c.get("titulo_final") or "",
                    "resumo": c.get("resumo_final") or "",
                    "tag": c.get("tag") or "",
                    "prioridade": c.get("prioridade") or ""
                }
                for c in ordered[:60]
                if c.get("id") is not None
            ]
            instr = (
                "Você fará UMA TRIAGEM semântica de potenciais oportunidades para a pergunta abaixo.\n"
                "Devolva APENAS um JSON no formato {\"ids\": [<id>, ...]} com os IDs mais relevantes (10–15).\n"
                "Critérios: prioridade (P1>P2>P3), aderência temática, ação potencial.\n"
                "NÃO explique, NÃO use texto fora do JSON.\n\n"
                f"Pergunta: {question}\n\n"
                f"Itens (amostra): {sample}\n"
            )
            print("[Estagiario] Triagem LLM (seleção de candidatos) iniciada...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 256})
            txt = (resp.text or "").strip()
            import json, re
            ids: List[int] = []
            try:
                data = json.loads(txt)
                ids = [int(x) for x in data.get("ids", []) if isinstance(x, (int, str))]
            except Exception:
                # Regex de fallback para extrair números
                nums = re.findall(r"\d+", txt)
                ids = [int(n) for n in nums[:15]]
            ids = list(dict.fromkeys(ids))  # remove duplicatas mantendo ordem
            print(f"[Estagiario] Triagem LLM selecionou {len(ids)} IDs")
            return ids
        except Exception as e:
            print(f"[Estagiario] Falha na triagem LLM: {e}")
            return []

    def _infer_filters(self, question: str) -> Dict[str, Any]:
        """Inferir prioridades, tags e keywords a partir da pergunta para reduzir o universo."""
        import unicodedata
        def norm(s: str) -> str:
            s = s.lower()
            return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
        nq = norm(question)
        # Prioridades
        priorities = []
        if "p1" in nq: priorities.append("P1_CRITICO")
        if "p2" in nq: priorities.append("P2_ESTRATEGICO")
        if "p3" in nq: priorities.append("P3_MONITORAMENTO")
        # Tags heurísticas
        tag_map = {
            "internacional": ["eua", "russia", "rússia", "china", "guerra", "san\u00e7\u00f5es", "geopolit"],
            "juridico": ["rj", "recuperacao judicial", "judicial", "stj", "stf", "justica"],
            "m&a": ["m&a", "fusao", "fusão", "aquisi", "venda de ativo", "desinvest"],
            "mercado_de_capitais": ["ipo", "follow on", "debent", "oferta", "capta\u00e7\u00e3o"],
            "politica_economica": ["congresso", "camara", "senado", "tributar", "fiscal", "arcabou\u00e7o"],
            "tecnologia": ["ia", "tecnolog", "software", "plataforma", "dados"],
            "distressed": ["default", "inadimpl", "calote", "reestrutura", "distressed"],
            "autos": ["carro", "veiculo", "automovel", "montadora", "concessionaria", "ev", "eletrico"],
            "energia": ["energia", "petroleo", "gas", "opec", "opep", "hidrel", "solar", "eolica"],
        }
        tags = set()
        for tag, keys in tag_map.items():
            if any(k in nq for k in keys):
                tags.add(tag)
        # Keywords principais
        tokens = [t for t in nq.split() if len(t) >= 3 and t.isalpha()]
        stops = set(["noticias", "noticia", "todas", "com", "para", "das", "dos", "de", "da", "do", "sobre", "quais", "seriam", "hoje", "mesa", "special", "situations"])
        keywords = [t for t in tokens if t not in stops][:10]
        print(f"[Estagiario] Filtros inferidos → priorities={priorities or 'ALL'} tags={list(tags)} keywords={keywords}")
        return {"priorities": priorities, "tags": list(tags), "keywords": keywords}

    def _rank_clusters(self, keywords: List[str], clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        print("[Estagiario] Ranqueando clusters...")
        prio_weight = {"P1_CRITICO": 3, "P2_ESTRATEGICO": 2, "P3_MONITORAMENTO": 1}
        scored = []
        for c in clusters:
            pr = c.get("prioridade") or "P3_MONITORAMENTO"
            base = prio_weight.get(pr, 1)
            blob = ((c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")).lower()
            kw_hits = sum(1 for k in keywords if k in blob)
            score = base * 10 + kw_hits
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [c for _, c in scored]
        print(f"[Estagiario] Ranking concluído. total={len(ranked)} top_score={scored[0][0] if scored else 0}")
        return ranked

    def _fetch_details_for(self, db, cluster_ids: List[int], limit: int = 6) -> List[Dict[str, Any]]:
        print(f"[Estagiario] Carregando detalhes para {min(len(cluster_ids), limit)} clusters...")
        detalhes = []
        for cid in cluster_ids[:limit]:
            try:
                d = get_cluster_details_by_id(db, cid)
                if d:
                    detalhes.append(d)
            except Exception as e:
                print(f"[Estagiario] Falha ao carregar detalhes do cluster {cid}: {e}")
        print(f"[Estagiario] Detalhes carregados: {len(detalhes)}")
        return detalhes

    def _count_irrelevantes_clusters(self, db, target_date: datetime.date) -> int:
        """Conta clusters de um dia com prioridade/tag irrelevante (preciso)."""
        try:
            from sqlalchemy import func, and_
            cnt = db.query(func.count(ClusterEvento.id)).filter(
                and_(func.date(ClusterEvento.created_at) == target_date,
                     ClusterEvento.status == 'ativo',
                     ((ClusterEvento.prioridade == 'IRRELEVANTE') | (ClusterEvento.tag == 'IRRELEVANTE')))
            ).scalar() or 0
            print(f"[Estagiario] Irrelevantes (preciso) na data={target_date}: {cnt}")
            return int(cnt)
        except Exception as e:
            print(f"[Estagiario] Falha ao contar irrelevantes precisos: {e}")
            return 0

    def answer(self, question: str, date_str: Optional[str] = None) -> AgentAnswer:
        """
        Responde perguntas com base nas notícias do dia, usando prioridades/tags.
        Exemplos suportados:
        - 1) "liste quantas noticias classificamos como irrelevantes"
        - 2) "quais noticias tem promocoes de carros até 200mil?"
        - 3) "Resuma os principais Impactos das noticias de prioridade p1 para a relacao EUA x RUssia"
        """
        print("[Estagiario] ================= INÍCIO =================")
        print(f"[Estagiario] Pergunta: {question}")
        db = self._open_db()
        try:
            target_date = None
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except Exception:
                    target_date = get_date_brasil()
            if target_date is None:
                target_date = get_date_brasil()
            print(f"[Estagiario] Data alvo: {target_date.isoformat()}")

            q = (question or "").lower()

            # Executor ReAct (opcional por flag) para casos genéricos
            if os.getenv("ESTAGIARIO_REACT") == "1":
                try:
                    from .executor import EstagiarioExecutor
                    execu = EstagiarioExecutor()
                    out = execu.run(user_input=question, chat_history=[])
                    final = out.get("final") or "Em construção"
                    trace = out.get("trace") or []
                    return AgentAnswer(True, final, {"react_trace": trace})
                except Exception as e:
                    print(f"[Estagiario] Falha executor ReAct: {e}")
                    # cai para heurística abaixo

            # Caso: comandos de edição (seguros e sempre unitários)
            if q.startswith("atualize ") or q.startswith("troque ") or q.startswith("mude ") or q.startswith("merge ") or q.startswith("unir ") or q.startswith("unifica "):
                print("[Estagiario] Caso: comando de edição")
                import re
                # update prioridade: "atualize prioridade do cluster 123 para p2"
                m = re.search(r"prioridade.*cluster\s+(\d+)\s+para\s+(p1|p2|p3|irrelevante)", q)
                if m:
                    cluster_id = int(m.group(1))
                    alvo = m.group(2).upper()
                    mapa = {"P1": "P1_CRITICO", "P2": "P2_ESTRATEGICO", "P3": "P3_MONITORAMENTO", "IRRELEVANTE": "IRRELEVANTE"}
                    nova_pr = mapa.get(alvo)
                    if nova_pr and nova_pr in self.prioridades_permitidas:
                        from backend.crud import update_cluster_priority
                        ok = update_cluster_priority(db, cluster_id, nova_pr, motivo=f"Estagiario: ajuste solicitado '{question}'")
                        return AgentAnswer(bool(ok), ("✅ Prioridade atualizada." if ok else "Falha ao atualizar prioridade."))
                    return AgentAnswer(False, "Prioridade não permitida.")

                # update tag: "troque a tag do cluster 456 para Internacional"
                m = re.search(r"tag.*cluster\s+(\d+)\s+para\s+([\wãáàâêíçõéú-]+)", q)
                if m:
                    cluster_id = int(m.group(1))
                    tag = m.group(2)
                    # valida contra catálogo
                    if any(tag.lower() == t.lower() for t in self.tags_permitidas):
                        from backend.crud import update_cluster_tags
                        ok = update_cluster_tags(db, cluster_id, [tag], motivo=f"Estagiario: ajuste solicitado '{question}'")
                        return AgentAnswer(bool(ok), ("✅ Tag atualizada." if ok else "Falha ao atualizar tag."))
                    return AgentAnswer(False, "Tag não permitida.")

                # merge: "merge o cluster 111 no 222" (sempre unitário; nunca múltiplos)
                m = re.search(r"merge.*cluster\s+(\d+)\s+no\s+(\d+)", q)
                if m:
                    origem = int(m.group(1))
                    destino = int(m.group(2))
                    if origem == destino:
                        return AgentAnswer(False, "IDs de origem e destino iguais.")
                    from backend.crud import merge_clusters
                    res = merge_clusters(db, destino_id=destino, fontes_ids=[origem], motivo=f"Estagiario: merge solicitado '{question}'")
                    # não reescreve título/tag/prioridade por padrão; mantém destino como autoridade
                    return AgentAnswer(True, f"✅ Merge efetuado. Artigos movidos: {res.get('artigos_movidos',0)}; Clusters encerrados: {res.get('clusters_descartados',0)}.")

                return AgentAnswer(False, "Comando de edição não reconhecido. Exemplos: 'atualize prioridade do cluster 123 para p2', 'troque a tag do cluster 456 para Internacional', 'merge o cluster 111 no 222'.")

            # Caso 1: contagem de IRRELEVANTES
            if "irrelevante" in q and ("quantas" in q or "liste" in q or "conta" in q):
                print("[Estagiario] Caso: contar irrelevantes")
                irrelevantes = self._count_irrelevantes_clusters(db, target_date)
                print("[Estagiario] Resposta pronta")
                return AgentAnswer(True, f"Irrelevantes hoje: {irrelevantes}")

            # Caso 2: promoções de carros (dinâmico; sem preço padrão)
            if ("carro" in q or "carros" in q) and ("promo" in q or "promoção" in q or "promocao" in q or "desconto" in q or "oferta" in q):
                print("[Estagiario] Caso: promoções de carros (dinâmico)")
                import re
                # Extrai preço alvo se presente (ex.: 200 mil, 200k, 200.000, r$ 200.000)
                preco_alvo = None
                m = re.search(r"r\$\s*([\d\.]+)", q)
                if m:
                    try:
                        preco_alvo = int(m.group(1).replace('.', ''))
                    except Exception:
                        preco_alvo = None
                if not preco_alvo:
                    m = re.search(r"(\d+)\s*mil", q)
                    if m:
                        try:
                            preco_alvo = int(m.group(1)) * 1000
                        except Exception:
                            preco_alvo = None
                if not preco_alvo:
                    m = re.search(r"(\d+)\s*k", q)
                    if m:
                        try:
                            preco_alvo = int(m.group(1)) * 1000
                        except Exception:
                            preco_alvo = None

                candidatos = self._fetch_clusters(db, target_date, priority=None)
                print(f"[Estagiario] Candidatos: {len(candidatos)} preço_alvo={preco_alvo}")
                achados = []
                termos_base = ["carro", "automóvel", "veículo", "concessionária", "oferta", "desconto", "promo", "ipva", "financiamento"]
                termos_ev = ["elétrico", "eletrico", "ev", "veículo elétrico", "veiculo eletrico"]
                for c in candidatos:
                    t = (c.get("titulo_final") or "").lower()
                    r = (c.get("resumo_final") or "").lower()
                    blob = t + "\n" + r
                    if any(k in blob for k in termos_base):
                        # Se o usuário falou "elétrico", dá preferência a EV
                        if ("elétrico" in q or "eletrico" in q) and not any(ev in blob for ev in termos_ev):
                            continue
                        if preco_alvo:
                            # Heurística: aceitar se houver menção numérica plausível (mil/k/valores próximos)
                            if re.search(r"(\d+\.?\d*\s*mil|r\$\s*[\d\.]+|\d+\s*k)", blob):
                                achados.append({"id": c["id"], "titulo": c.get("titulo_final"), "resumo": c.get("resumo_final")})
                        else:
                            achados.append({"id": c["id"], "titulo": c.get("titulo_final"), "resumo": c.get("resumo_final")})
                print(f"[Estagiario] Achados: {len(achados)}")
                if not achados:
                    return AgentAnswer(True, "Nenhuma promoção de carros encontrada hoje.")
                llm_txt = self._llm_answer(question, achados)
                if llm_txt:
                    return AgentAnswer(True, llm_txt, {"itens": achados[:10]})
                return AgentAnswer(True, f"{len(achados)} ofertas encontradas.", {"itens": achados[:10]})

            # Caso 3: impactos por prioridade (P1/P2/P3) na relação EUA x Rússia — resiliente e multi-stratégia
            if ("eua" in q and ("russia" in q or "rússia" in q)) and ("p1" in q or "prioridade p1" in q or "p2" in q or "prioridade p2" in q or "p3" in q or "prioridade p3" in q):
                prios = []
                if ("p1" in q or "prioridade p1" in q): prios.append("P1_CRITICO")
                if ("p2" in q or "prioridade p2" in q): prios.append("P2_ESTRATEGICO")
                if ("p3" in q or "prioridade p3" in q): prios.append("P3_MONITORAMENTO")
                if not prios:
                    prios = ["P1_CRITICO"]
                print(f"[Estagiario] Caso: impactos {','.join(prios)} EUA–Rússia")
                # 1) Coleta por prioridades solicitadas
                candidatos: List[Dict[str, Any]] = []
                for p in prios:
                    lista = self._fetch_clusters(db, target_date, priority=p)
                    print(f"[Estagiario] {p} carregados: {len(lista)}")
                    candidatos.extend(lista)
                # 2) Heurística léxica inicial
                chaves = ["eua", "estados unidos", "washington", "rússia", "russia", "putin", "kremlin", "nato", "otan", "sanção", "sancao", "guerra", "ucrania", "ucrânia"]
                relevantes = []
                for c in candidatos:
                    L = ((c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")).lower()
                    if any(k in L for k in chaves):
                        relevantes.append(c)
                print(f"[Estagiario] Relevantes (lexical): {len(relevantes)}")
                # 3) Triagem semântica via LLM se ainda pouca aderência
                base_para_triagem = relevantes if len(relevantes) >= 3 else candidatos
                selecionados_ids = self._llm_select_candidates("Impactos na relação EUA–Rússia", base_para_triagem)
                if selecionados_ids:
                    idset = set(selecionados_ids)
                    selecionados = [c for c in base_para_triagem if c.get("id") in idset]
                else:
                    selecionados = relevantes[:12] if relevantes else candidatos[:12]
                print(f"[Estagiario] Selecionados p/ síntese: {len(selecionados)}")
                if not selecionados:
                    return AgentAnswer(True, "Nenhum impacto relevante encontrado nas prioridades solicitadas.")
                # 4) Detalhes + síntese (resumos) → fallback raw
                top_ids = [c.get("id") for c in selecionados[:10] if c.get("id") is not None]
                detalhes = self._fetch_details_for(db, top_ids, limit=6)
                retrieved = []
                for d in detalhes:
                    retrieved.append({
                        "id": d.get("id"),
                        "titulo": d.get("titulo_final") or d.get("titulo_cluster") or d.get("titulo"),
                        "resumo": d.get("resumo_final") or d.get("resumo_cluster") or d.get("resumo"),
                        "tag": d.get("tag"),
                        "prioridade": d.get("prioridade"),
                        "fontes": d.get("fontes", []),
                    })
                llm_txt = self._llm_answer(question, retrieved if retrieved else selecionados)
                if llm_txt and len(llm_txt) > 80:
                    return AgentAnswer(True, llm_txt, {"itens": selecionados[:12]})
                if detalhes:
                    raw_txt = self._llm_summarize_from_raw(question, detalhes)
                    if raw_txt and len(raw_txt) > 80:
                        return AgentAnswer(True, raw_txt, {"itens": selecionados[:12]})
                # 5) Amostra em Markdown
                simples = []
                for c in selecionados[:8]:
                    simples.append({
                        "id": c.get('id'),
                        "titulo": c.get('titulo_final'),
                        "resumo": c.get('resumo_final'),
                        "prioridade": c.get('prioridade'),
                        "tag": c.get('tag'),
                        "fontes": []
                    })
                md = self._compose_markdown_from_retrieved(question, simples)
                return AgentAnswer(True, md, {"itens": selecionados[:12]})

            # Caso 4: busca genérica com plano (inferir filtros → filtrar → ranquear → aprofundar → síntese Markdown)
            try:
                print("[Estagiario] Caso: busca genérica por palavras-chave (com plano)")
                filtros = self._infer_filters(q)
                # Coleta priorizada por prioridades inferidas ou ALL
                candidatos: List[Dict[str, Any]] = []
                if filtros["priorities"]:
                    for p in filtros["priorities"]:
                        candidatos.extend(self._fetch_clusters(db, target_date, priority=p))
                else:
                    candidatos = self._fetch_clusters(db, target_date, priority=None)
                print(f"[Estagiario] Candidatos (pré-tag): {len(candidatos)}")
                # Filtra por tags inferidas (se houver)
                if filtros["tags"]:
                    candidatos = [c for c in candidatos if any(tg in (c.get("tag") or '').lower() for tg in filtros["tags"]) ]
                print(f"[Estagiario] Após filtro de tags: {len(candidatos)}")
                # Opcional: filtragem leve por keyword (evita perder muito recall)
                if filtros["keywords"] and len(candidatos) > 160:
                    def contains_kw(c):
                        L = ((c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")).lower()
                        return any(k in L for k in filtros["keywords"])
                    candidatos = [c for c in candidatos if contains_kw(c)]
                    print(f"[Estagiario] Após filtro leve de keywords: {len(candidatos)}")
                if not candidatos:
                    raise ValueError("Nenhum candidato após filtros")
                # Triagem semântica via LLM para escolher 10-15 mais promissores
                selected_ids = self._llm_select_candidates(question, candidatos)
                # Se falhar, usa ranking por prioridade/keywords
                if not selected_ids:
                    ranked = self._rank_clusters(filtros["keywords"], candidatos)
                    top_ids = [c.get("id") for c in ranked[:12] if c.get("id") is not None]
                else:
                    top_ids = selected_ids[:12]
                detalhes = self._fetch_details_for(db, top_ids, limit=8)
                # Monta retrieved enriquecido com fontes
                retrieved: List[Dict[str, Any]] = []
                for d in detalhes:
                    retrieved.append({
                        "id": d.get("id"),
                        "titulo": d.get("titulo_final") or d.get("titulo_cluster") or d.get("titulo"),
                        "resumo": d.get("resumo_final") or d.get("resumo_cluster") or d.get("resumo"),
                        "tag": d.get("tag"),
                        "prioridade": d.get("prioridade"),
                        "fontes": d.get("fontes", []),
                        "artigos": d.get("artigos", []),
                    })
                # Síntese LLM em Markdown
                base_para_sintese = retrieved if retrieved else [c for c in candidatos if (c.get("id") in top_ids)][:10]
                llm_txt = self._llm_answer(question, base_para_sintese)
                if llm_txt and len(llm_txt) > 500:
                    return AgentAnswer(True, llm_txt, {"itens": base_para_sintese[:15]})
                # Se a síntese acima falhar, tenta construir resumo a partir dos artigos brutos
                if detalhes:
                    raw_txt = self._llm_summarize_from_raw(question, detalhes)
                    if raw_txt:
                        return AgentAnswer(True, raw_txt, {"itens": base_para_sintese[:15]})
                # Fallback em Markdown simples com rastreabilidade
                id_set = set(top_ids)
                simples = [
                    {
                        "id": c.get('id'),
                        "titulo": c.get('titulo_final'),
                        "resumo": c.get('resumo_final'),
                        "prioridade": c.get('prioridade'),
                        "tag": c.get('tag'),
                        "fontes": [],
                        "artigos": [],
                    }
                    for c in candidatos if c.get('id') in id_set
                ][:8]
                md = self._compose_markdown_from_retrieved(question, simples)
                return AgentAnswer(True, md, {"itens": simples[:15]})
            except Exception as _e_generic:
                print(f"[Estagiario] Falha na busca genérica: {_e_generic}")

            # Fallback: responde com métricas gerais do dia
            print("[Estagiario] Fallback: métricas do dia")
            metricas = get_metricas_by_date(db, target_date)
            print(f"[Estagiario] Métricas: {metricas}")
            return AgentAnswer(True, "Em construção 🚧 — Faça uma pergunta específica.", {"metricas": metricas})

        except Exception as e:
            print(f"[Estagiario] ERRO: {e}")
            return AgentAnswer(False, f"Falha no agente: {e}")
        finally:
            try:
                print("[Estagiario] Fechando sessão DB...")
                db.close()
            except Exception:
                pass
            print("[Estagiario] =================  FIM  =================")


