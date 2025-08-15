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
                })
            prompt = (
                "Você é um analista do BTG na mesa de Special Situations. Responda em Markdown, direto ao ponto,"
                " com foco em ação e rastreabilidade (sempre inclua FONTES com URLs e IDs).\n\n"
                "KB (resumo):\n" + (self.kb_text[:6000]) + "\n\n"
                "Amostra de dados (clusters do dia):\n" + str(exemplos) + "\n\n"
                "Instruções de resposta (obrigatório):\n"
                "- Proibido descrever etapas, ferramentas ou plano ('Buscar clusters', 'Filtrar', 'Resultados esperados', 'Próximos passos') — apenas a resposta.\n"
                "- Vá direto ao ponto; sem frases como 'Com base nos dados fornecidos'.\n"
                "- Estruture com títulos (##) e bullets; use tabela apenas se indispensável.\n"
                "- Inclua prioridades/tags quando relevantes.\n"
                "- Finalize com a seção 'Notícias pesquisadas:' listando: [ID] Título — URL (Jornal).\n\n"
                "Pergunta do usuário: " + question + "\n"
            )
            print("[Estagiario] Síntese LLM iniciada...")
            resp = self.model.generate_content(prompt, generation_config={
                'temperature': 0.2,
                'top_p': 0.8,
                'max_output_tokens': 768
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

            # Caso 1: contagem de IRRELEVANTES
            if "irrelevante" in q and ("quantas" in q or "liste" in q or "conta" in q):
                print("[Estagiario] Caso: contar irrelevantes")
                irrelevantes = self._count_irrelevantes_clusters(db, target_date)
                print("[Estagiario] Resposta pronta")
                return AgentAnswer(True, f"Irrelevantes hoje: {irrelevantes}")

            # Caso 2: promoções de carros até 200 mil
            if ("carro" in q or "carros" in q) and ("promo" in q or "promoção" in q or "promocao" in q):
                print("[Estagiario] Caso: promoções de carros ≤ 200k")
                candidatos = self._fetch_clusters(db, target_date, priority=None)
                print(f"[Estagiario] Candidatos: {len(candidatos)}")
                achados = []
                for c in candidatos:
                    t = (c.get("titulo_final") or "").lower()
                    r = (c.get("resumo_final") or "").lower()
                    if any(k in t or k in r for k in ["carro", "automóvel", "veículo", "concessionária", "oferta", "desconto", "promo", "ipva", "financiamento"]):
                        # heurística simples de preço (inclui variações)
                        if any(k in r for k in ["100 mil", "150 mil", "200 mil", "r$ 100.000", "r$ 150.000", "r$ 200.000", "r$100 mil", "r$150 mil", "r$200 mil"]):
                            achados.append({"id": c["id"], "titulo": c.get("titulo_final"), "resumo": c.get("resumo_final")})
                print(f"[Estagiario] Achados: {len(achados)}")
                if not achados:
                    return AgentAnswer(True, "Nenhuma promoção de carros até 200 mil encontrada hoje.")
                llm_txt = self._llm_answer(question, achados)
                if llm_txt:
                    return AgentAnswer(True, llm_txt, {"itens": achados[:10]})
                return AgentAnswer(True, f"{len(achados)} ofertas encontradas.", {"itens": achados[:10]})

            # Caso 3: impactos por prioridade (P1/P2/P3) na relação EUA x Rússia
            if ("eua" in q and ("russia" in q or "rússia" in q)) and ("p1" in q or "prioridade p1" in q or "p2" in q or "prioridade p2" in q or "p3" in q or "prioridade p3" in q):
                alvo = "P1_CRITICO" if ("p1" in q or "prioridade p1" in q) else ("P2_ESTRATEGICO" if ("p2" in q or "prioridade p2" in q) else "P3_MONITORAMENTO")
                print(f"[Estagiario] Caso: impactos {alvo} EUA–Rússia")
                lista = self._fetch_clusters(db, target_date, priority=alvo)
                print(f"[Estagiario] {alvo} carregados: {len(lista)}")
                chaves = ["eua", "estados unidos", "washington", "rússia", "russia", "putin", "kremlin"]
                relevantes = []
                for c in lista:
                    blob = (c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")
                    L = blob.lower()
                    if any(k in L for k in chaves):
                        relevantes.append({
                            "id": c["id"],
                            "titulo": c.get("titulo_final"),
                            "resumo": c.get("resumo_final"),
                            "tag": c.get("tag"),
                        })
                print(f"[Estagiario] Relevantes EUA–Rússia: {len(relevantes)}")
                if not relevantes:
                    return AgentAnswer(True, f"Nenhum impacto {alvo.split('_')[0]} EUA–Rússia encontrado hoje.")
                llm_txt = self._llm_answer(question, relevantes)
                if llm_txt:
                    return AgentAnswer(True, llm_txt, {"itens": relevantes[:10]})
                bullets = [f"- {it['titulo']}: {it['resumo']}" for it in relevantes[:8]]
                return AgentAnswer(True, f"Principais impactos ({alvo.split('_')[0]}) EUA–Rússia:\n" + "\n".join(bullets))

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
                detalhes = self._fetch_details_for(db, top_ids, limit=6)
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
                    })
                # Síntese LLM em Markdown
                base_para_sintese = retrieved if retrieved else [c for c in candidatos if (c.get("id") in top_ids)][:10]
                llm_txt = self._llm_answer(question, base_para_sintese)
                if llm_txt:
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
                        "fontes": []
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


