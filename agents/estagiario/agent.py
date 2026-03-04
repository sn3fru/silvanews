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
import time
# Evite imports locais dentro de blocos; import global seguro para update de prioridade
from backend.crud import update_cluster_priority

try:
    # Imports relativos ao backend já existente
    from backend.database import SessionLocal
    from backend.crud import (
        get_clusters_for_feed_by_date,
        get_cluster_details_by_id,
        get_metricas_by_date,
        list_feedback,
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
                self.model = genai.GenerativeModel('gemini-2.5-flash')
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
        # Controle simples de iterações por hora (LLM refinamentos)
        self._iter_timestamps: List[float] = []
        self._iter_limit_per_hour: int = 10

    def _catalogo_tags(self, db) -> List[str]:
        """Retorna as tags canônicas a partir do banco; fallback para self.tags_permitidas."""
        try:
            from backend.crud import get_prompts_compilados
            comp = get_prompts_compilados(db)
            tags_payload = comp.get('tags') or {}
            if isinstance(tags_payload, dict) and tags_payload:
                return list(tags_payload.keys())
        except Exception:
            pass
        return self.tags_permitidas or []

    def _normalize_str(self, s: str) -> str:
        import unicodedata, re
        s = s or ""
        s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
        s = s.lower()
        s = re.sub(r"[^\w\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _extract_keywords_simple(self, text: str) -> List[str]:
        import re
        t = (text or '').lower()
        # remove pontuação simples
        t = re.sub(r"[^\w\sçáéíóúãõâêîôûàèìòù]", " ", t)
        tokens = [w for w in t.split() if len(w) >= 3]
        stops = set(["das","dos","de","da","do","para","por","com","uma","umas","noticias","notícia","noticia","hoje","essa","dessa","sobre","que","nas","nos","na","no","pegue","troque","tag"]) 
        return [w for w in tokens if w not in stops][:8]

    def _within_iteration_budget(self) -> bool:
        now = time.time()
        # remove eventos mais antigos que 1h
        self._iter_timestamps = [t for t in self._iter_timestamps if now - t < 3600]
        return len(self._iter_timestamps) < self._iter_limit_per_hour

    def _consume_iteration(self) -> None:
        self._iter_timestamps.append(time.time())

    def _llm_choose_tag_from_phrase(self, phrase: str, catalogo_tags: List[str]) -> Optional[str]:
        if not self.model:
            return None
        try:
            instr = (
                "Escolha UMA única TAG da lista a seguir que melhor descreva a frase. "
                "Responda APENAS com JSON {\"tag\": \"<nome exato>\"}.\n\n"
                f"Frase: {phrase}\n"
                f"Tags: {catalogo_tags}\n"
            )
            print("[Estagiario] LLM choose_tag_from_phrase: solicitando JSON...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 128})
            raw = (resp.text or '').strip()
            print(f"[Estagiario] LLM choose_tag_from_phrase (raw): {raw[:400]}")
            import json, re
            if raw.startswith('```'):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            data = {}
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            tag = data.get('tag') if isinstance(data, dict) else None
            if tag and any(tag.lower() == t.lower() for t in catalogo_tags):
                for t in catalogo_tags:
                    if tag.lower() == t.lower():
                        return t
            return None
        except Exception as e:
            print(f"[Estagiario] Falha LLM choose_tag_from_phrase: {e}")
            return None

    def _resolve_tag_canonically(self, db, question: str, cluster_id: int, default_guess: Optional[str]) -> Optional[str]:
        catalogo = self._catalogo_tags(db)
        tentativa = self._extract_target_tag(question, question)
        norm = self._normalize_str(tentativa) if tentativa else ''
        if norm in ['juridico e falencia','juridico e falencias','juridico falencia','juridico falencias','jurídico e falência','jurídico e falências']:
            tentativa = 'Jurídico, Falências e Regulatório'
        # 1) candidato explícito
        if tentativa and any(tentativa.lower() == t.lower() for t in catalogo):
            for t in catalogo:
                if tentativa.lower() == t.lower():
                    print(f"[Estagiario] Resolve tag: candidato explícito '{t}'")
                    return t
        # 2) default_guess
        if default_guess and any(default_guess.lower() == t.lower() for t in catalogo):
            for t in catalogo:
                if default_guess.lower() == t.lower():
                    print(f"[Estagiario] Resolve tag: default_guess '{t}'")
                    return t
        # 3) LLM contexto cluster
        if self._within_iteration_budget():
            self._consume_iteration()
            tctx = self._llm_choose_tag(db, cluster_id)
            if tctx:
                print(f"[Estagiario] Resolve tag: LLM contexto → '{tctx}'")
                return tctx
        # 4) LLM frase
        if self._within_iteration_budget():
            self._consume_iteration()
            tphrase = self._llm_choose_tag_from_phrase(question, catalogo)
            if tphrase:
                print(f"[Estagiario] Resolve tag: LLM frase → '{tphrase}'")
                return tphrase
        print("[Estagiario] Resolve tag: falhou em todas as tentativas")
        return None

    def _resolve_priority(self, db, question: str, cluster_id: int, default_guess: Optional[str]) -> Optional[str]:
        pr = self._extract_target_priority(question)
        if pr in self.prioridades_permitidas:
            print(f"[Estagiario] Resolve prio: explícita '{pr}'")
            return pr
        if default_guess in self.prioridades_permitidas:
            print(f"[Estagiario] Resolve prio: default_guess '{default_guess}'")
            return default_guess
        if self._within_iteration_budget():
            self._consume_iteration()
            pctx = self._llm_choose_priority(db, cluster_id)
            if pctx in self.prioridades_permitidas:
                print(f"[Estagiario] Resolve prio: LLM contexto → '{pctx}'")
                return pctx
        # LLM por frase
        if self._within_iteration_budget() and self.model:
            self._consume_iteration()
            try:
                instr = (
                    "Escolha a PRIORIDADE (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO, IRRELEVANTE) que melhor corresponde à frase. "
                    "Responda APENAS com JSON {\"prioridade\": \"<nivel>\"}.\n\n"
                    f"Frase: {question}\n"
                )
                print("[Estagiario] LLM choose_priority_from_phrase: solicitando JSON...")
                resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 128})
                raw = (resp.text or '').strip()
                print(f"[Estagiario] LLM choose_priority_from_phrase (raw): {raw[:400]}")
                import json, re
                if raw.startswith('```'):
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
                data = {}
                try:
                    data = json.loads(raw)
                except Exception:
                    m = re.search(r"\{[\s\S]*\}", raw)
                    data = json.loads(m.group(0)) if m else {}
                p = data.get('prioridade') if isinstance(data, dict) else None
                if p in self.prioridades_permitidas:
                    print(f"[Estagiario] Resolve prio: LLM frase → '{p}'")
                    return p
            except Exception as e:
                print(f"[Estagiario] Falha LLM choose_priority_from_phrase: {e}")
        print("[Estagiario] Resolve prio: falhou em todas as tentativas")
        return None

    def _llm_pick_best_by_title(self, titulo_alvo: str, candidatos: List[Dict[str, Any]]) -> List[int]:
        """Pede ao LLM para escolher o(s) melhor(es) candidatos por título. Retorna lista de IDs (pode ser 1)."""
        if not self.model or not candidatos:
            return []
        try:
            instr = (
                "Escolha o MELHOR MATCH pelo título alvo. Responda APENAS com JSON.\n"
                "Formato preferido: {\"ids\": [<id1>, <id2>]} ou {\"id\": <id>}\n\n"
                f"Título alvo: {titulo_alvo}\n"
                f"Candidatos: {[{'id': c.get('id'), 'titulo': c.get('titulo') or c.get('titulo_final')} for c in candidatos]}\n"
            )
            print("[Estagiario] LLM pick-best-candidate: solicitando JSON...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 128})
            raw = (resp.text or '').strip()
            print(f"[Estagiario] LLM pick-best-candidate (raw): {raw[:400]}")
            import json, re
            if raw.startswith('```'):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            ids: List[int] = []
            if isinstance(data, dict):
                if 'ids' in data and isinstance(data['ids'], list):
                    for x in data['ids']:
                        try:
                            ids.append(int(x))
                        except Exception:
                            pass
                elif 'id' in data:
                    try:
                        ids.append(int(data['id']))
                    except Exception:
                        pass
            # filtra por candidatos válidos
            cand_ids = set([c.get('id') for c in candidatos])
            ids = [i for i in ids if i in cand_ids]
            if not ids and candidatos:
                ids = [candidatos[0].get('id')]
            return ids
        except Exception as e:
            print(f"[Estagiario] Falha LLM pick-best: {e}")
            return []

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

    def _llm_answer(self, question: str, retrieved: List[Dict[str, Any]], context_prompt: str = "") -> Optional[str]:
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
            
            # Adiciona contexto da conversa se disponível
            context_instruction = ""
            if context_prompt:
                context_instruction = (
                    "\n\nIMPORTANTE: Mantenha o contexto da conversa anterior. "
                    "Se a pergunta se referir a algo mencionado antes, use essa informação. "
                    "Se for uma continuação ou esclarecimento, responda de forma coerente com o que já foi discutido.\n"
                    f"{context_prompt}"
                )
                print(f"[Estagiario] Contexto incluído no prompt: {len(context_instruction)} caracteres")
            else:
                print("[Estagiario] Sem contexto para incluir no prompt")
            
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
                f"{context_instruction}"
                "Pergunta do usuário: " + question + "\n"
            )
            print(f"[Estagiario] Prompt final: {len(prompt)} caracteres")
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

    def _llm_generate_search_spec(self, question: str) -> Optional[Dict[str, Any]]:
        """Pede ao LLM um plano de busca (prioridades, tags canônicas e keywords) em JSON estrito."""
        if not self.model:
            return None
        try:
            # Constrói catálogo de tags para orientar a escolha canônica
            catalogo_tags = self.tags_permitidas or []
            instr = (
                "Você é um agente de planejamento. Gere um ESPEC JSON ESTRITO com as chaves: "
                "priorities (array com valores entre 'P1_CRITICO','P2_ESTRATEGICO','P3_MONITORAMENTO' ou vazio), "
                "tags (array com nomes EXATOS da lista fornecida), keywords (array de até 8 termos curtos em pt-br).\n"
                "Regra: use apenas tags da lista permitida. Não explique, responda somente JSON.\n\n"
                f"Pergunta: {question}\n"
                f"Tags permitidas: {catalogo_tags}\n"
            )
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.2, 'max_output_tokens': 256})
            raw = (resp.text or "").strip()
            import json, re
            # Remove cercas ```json ... ``` se vierem
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            # Fallback: extrai primeiro objeto JSON
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            # Sanitiza
            out: Dict[str, Any] = {
                'priorities': [p for p in (data.get('priorities') or []) if p in self.prioridades_permitidas],
                'tags': [t for t in (data.get('tags') or []) if any(t.lower() == c.lower() for c in catalogo_tags)],
                'keywords': [k for k in (data.get('keywords') or []) if isinstance(k, str)][:8],
            }
            return out
        except Exception as e:
            print(f"[Estagiario] Falha no plano de busca LLM: {e}")
            return None

    def _llm_understand_edit(self, question: str) -> Optional[Dict[str, Any]]:
        """Usa LLM para entender edição solicitada e normalizar para o catálogo de tags/prioridades."""
        if not self.model:
            return None
        try:
            catalogo_tags = self.tags_permitidas or []
            instr = (
                "Você é um agente de edição. Converta a solicitação abaixo em JSON ESTRITO com as chaves possíveis: "
                "operation ('update_tag'|'update_priority'|'merge'), cluster_id (int|null), cluster_title (string|null), "
                "new_tag (string|null), new_priority ('P1_CRITICO'|'P2_ESTRATEGICO'|'P3_MONITORAMENTO'|'IRRELEVANTE'|null). "
                "Se new_tag for pedida, ESCOLHA EXATAMENTE um nome da lista de tags permitidas. Não explique.\n\n"
                f"Solicitação: {question}\n"
                f"Tags permitidas: {catalogo_tags}\n"
            )
            print("[Estagiario] LLM understand_edit: solicitando JSON...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 256})
            raw = (resp.text or "").strip()
            print(f"[Estagiario] LLM understand_edit (raw): {raw[:400]}")
            import json, re
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            # Valida campos básicos
            op = data.get('operation')
            if op not in ('update_tag', 'update_priority', 'merge'):
                return None
            # Normaliza prioridade
            pr = data.get('new_priority')
            if pr and pr not in self.prioridades_permitidas:
                pr = None
            # Normaliza tag contra catálogo
            nt = data.get('new_tag')
            if nt and not any(nt.lower() == c.lower() for c in catalogo_tags):
                nt = None
            return {
                'operation': op,
                'cluster_id': data.get('cluster_id'),
                'cluster_title': data.get('cluster_title'),
                'new_tag': nt,
                'new_priority': pr,
            }
        except Exception as e:
            print(f"[Estagiario] Falha no entendimento de edição LLM: {e}")
            return None

    def _llm_choose_tag(self, db, cluster_id: int) -> Optional[str]:
        """Decide a TAG correta via LLM com base no catálogo do banco e no contexto do cluster."""
        if not self.model:
            return None
        try:
            # Carrega catálogo de tags canônicas
            catalogo_tags = self.tags_permitidas or []
            if not catalogo_tags:
                return None
            # Carrega contexto do cluster
            try:
                from backend.crud import get_cluster_details_by_id
                ctx = get_cluster_details_by_id(db, cluster_id) or {}
            except Exception:
                ctx = {}
            titulo = ctx.get('titulo_final') or ctx.get('titulo') or ''
            resumo = ctx.get('resumo_final') or ctx.get('resumo') or ''
            artigos = ctx.get('artigos') or []
            artigos_titulos = [a.get('titulo') for a in artigos[:5] if a.get('titulo')]
            instr = (
                "Classifique o cluster abaixo em UMA única TAG, escolhendo EXATAMENTE um nome da lista de tags permitidas. "
                "Responda APENAS com JSON no formato {\"tag\": \"<nome exato>\"}. Não explique.\n\n"
                f"Tags permitidas: {catalogo_tags}\n"
                f"Titulo: {titulo}\n"
                f"Resumo: {resumo}\n"
                f"Artigos (títulos): {artigos_titulos}\n"
            )
            print("[Estagiario] LLM choose_tag: solicitando JSON...")
            print("[Estagiario] LLM choose_priority: solicitando JSON...")
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 128})
            raw = (resp.text or '').strip()
            print(f"[Estagiario] LLM choose_priority (raw): {raw[:400]}")
            print(f"[Estagiario] LLM choose_tag (raw): {raw[:400]}")
            import json, re
            if raw.startswith('```'):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            tag = data.get('tag') if isinstance(data, dict) else None
            if tag and any(tag.lower() == t.lower() for t in catalogo_tags):
                # Normaliza para o nome do catálogo
                for t in catalogo_tags:
                    if tag.lower() == t.lower():
                        return t
            return None
        except Exception as e:
            print(f"[Estagiario] Falha no LLM escolha de tag: {e}")
            return None

    def _fallback_understand_edit(self, question: str) -> Optional[Dict[str, Any]]:
        """Fallback leve e seguro quando o LLM não retorna JSON: extrai intenção básica.
        - Suporta: alterar tag por título parcial do enunciado (após dois-pontos) e mapear tag destino por aliases.
        """
        qlow = (question or "").strip()
        if not qlow:
            return None
        qlow_norm = qlow.lower()
        # Extrai título: primeiro procura entre aspas, senão tenta após o último ':'
        import re
        title = None
        m = re.search(r'["\']([^"\']{5,200})["\']', qlow)
        if m:
            title = m.group(1).strip()
        if not title and ':' in qlow:
            title = qlow.split(':')[-1].strip()
        # Determina operação/tag
        if 'tag' in qlow_norm or 'categoria' in qlow_norm or 'classificada' in qlow_norm:
            # Mapeia para catálogo
            destino = None
            # Sinais fortes de Dívida Ativa
            if any(k in qlow_norm for k in ['divida ativa', 'dívida ativa', 'cda']):
                for t in self.tags_permitidas:
                    if 'dívida ativa' in t.lower() or 'divida ativa' in t.lower():
                        destino = t
                        break
            # Busca match direto por nome de tag na frase
            if not destino:
                for t in self.tags_permitidas:
                    if t.lower() in qlow_norm:
                        destino = t
                        break
            if destino and title:
                return {
                    'operation': 'update_tag',
                    'cluster_id': None,
                    'cluster_title': title,
                    'new_tag': destino,
                    'new_priority': None,
                }
        return None
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

    def _fetch_feedback_likes(self, db, start_date: datetime.date, end_date: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
        """Busca artigos com feedback positivo (likes) em um intervalo de datas."""
        try:
            from sqlalchemy import func, and_
            from backend.database import ArtigoBruto, FeedbackNoticia
            
            query = db.query(
                ArtigoBruto.id,
                ArtigoBruto.titulo_extraido,
                ArtigoBruto.jornal,
                ArtigoBruto.created_at,
                ClusterEvento.titulo_cluster,
                ClusterEvento.id.label('cluster_id'),
                FeedbackNoticia.created_at.label('feedback_date')
            ).join(
                FeedbackNoticia, ArtigoBruto.id == FeedbackNoticia.artigo_id
            ).outerjoin(
                ClusterEvento, ArtigoBruto.cluster_id == ClusterEvento.id
            ).filter(
                FeedbackNoticia.feedback == 'like'
            )
            
            # Adiciona filtro de data apenas se end_date não for None (sem filtro de data)
            if end_date is not None:
                if end_date == start_date:
                    query = query.filter(func.date(ArtigoBruto.created_at) == start_date)
                else:
                    query = query.filter(
                        and_(
                            func.date(ArtigoBruto.created_at) >= start_date,
                            func.date(ArtigoBruto.created_at) <= end_date
                        )
                    )
            else:
                # Sem filtro de data - busca tudo desde o start_date
                query = query.filter(func.date(ArtigoBruto.created_at) >= start_date)
            
            results = query.distinct().order_by(FeedbackNoticia.created_at.desc()).all()
            
            return [
                {
                    "id": r.id,
                    "titulo_extraido": r.titulo_extraido,
                    "jornal": r.jornal,
                    "titulo_cluster": r.titulo_cluster,
                    "cluster_id": r.cluster_id,
                    "created_at": r.created_at.strftime('%Y-%m-%d') if r.created_at else None,
                    "feedback_date": r.feedback_date.strftime('%Y-%m-%d %H:%M') if r.feedback_date else None
                }
                for r in results
            ]
        except Exception as e:
            print(f"[Estagiario] Erro fetch_feedback_likes: {e}")
            return []

    def _fetch_feedback_dislikes(self, db, start_date: datetime.date, end_date: Optional[datetime.date] = None) -> List[Dict[str, Any]]:
        """Busca artigos com feedback negativo (dislikes) em um intervalo de datas."""
        try:
            from sqlalchemy import func, and_
            from backend.database import ArtigoBruto, FeedbackNoticia
            
            query = db.query(
                ArtigoBruto.id,
                ArtigoBruto.titulo_extraido,
                ArtigoBruto.jornal,
                ArtigoBruto.created_at,
                ClusterEvento.titulo_cluster,
                ClusterEvento.id.label('cluster_id'),
                FeedbackNoticia.created_at.label('feedback_date')
            ).join(
                FeedbackNoticia, ArtigoBruto.id == FeedbackNoticia.artigo_id
            ).outerjoin(
                ClusterEvento, ArtigoBruto.cluster_id == ClusterEvento.id
            ).filter(
                FeedbackNoticia.feedback == 'dislike'
            )
            
            # Adiciona filtro de data apenas se end_date não for None (sem filtro de data)
            if end_date is not None:
                if end_date == start_date:
                    query = query.filter(func.date(ArtigoBruto.created_at) == start_date)
                else:
                    query = query.filter(
                        and_(
                            func.date(ArtigoBruto.created_at) >= start_date,
                            func.date(ArtigoBruto.created_at) <= end_date
                        )
                    )
            else:
                # Sem filtro de data - busca tudo desde o start_date
                query = query.filter(func.date(ArtigoBruto.created_at) >= start_date)
            
            results = query.distinct().order_by(FeedbackNoticia.created_at.desc()).all()
            
            return [
                {
                    "id": r.id,
                    "titulo_extraido": r.titulo_extraido,
                    "jornal": r.jornal,
                    "titulo_cluster": r.titulo_cluster,
                    "cluster_id": r.cluster_id,
                    "created_at": r.created_at.strftime('%Y-%m-%d') if r.created_at else None,
                    "feedback_date": r.feedback_date.strftime('%Y-%m-%d %H:%M') if r.feedback_date else None
                }
                for r in results
            ]
        except Exception as e:
            print(f"[Estagiario] Erro fetch_feedback_dislikes: {e}")
            return []

    def _count_feedback(self, db, start_date: datetime.date, end_date: Optional[datetime.date] = None) -> Dict[str, int]:
        """Conta feedback por tipo (likes/dislikes) em um intervalo de datas."""
        try:
            from sqlalchemy import func, and_
            from backend.database import ArtigoBruto, FeedbackNoticia
            
            query = db.query(
                FeedbackNoticia.feedback,
                func.count(FeedbackNoticia.id).label('total')
            ).join(
                ArtigoBruto, FeedbackNoticia.artigo_id == ArtigoBruto.id
            )
            
            # Adiciona filtro de data apenas se end_date não for None (sem filtro de data)
            if end_date is not None:
                if end_date == start_date:
                    query = query.filter(func.date(ArtigoBruto.created_at) == start_date)
                else:
                    query = query.filter(
                        and_(
                            func.date(ArtigoBruto.created_at) >= start_date,
                            func.date(ArtigoBruto.created_at) <= end_date
                        )
                    )
            else:
                # Sem filtro de data - busca tudo desde o start_date
                query = query.filter(func.date(ArtigoBruto.created_at) >= start_date)
            
            results = query.group_by(FeedbackNoticia.feedback).all()
            
            counts = {"likes": 0, "dislikes": 0}
            for r in results:
                if r.feedback == 'like':
                    counts["likes"] = r.total
                elif r.feedback == 'dislike':
                    counts["dislikes"] = r.total
            
            return counts
        except Exception as e:
            print(f"[Estagiario] Erro count_feedback: {e}")
            return {"likes": 0, "dislikes": 0}

    def _classify_intent(self, question: str) -> dict:
        """
        Primeira camada: LLM classifica a intenção da pergunta do usuário.
        Retorna um dicionário com a funcionalidade identificada e parâmetros.
        """
        prompt = f"""Você é um classificador de intenção para um agente de notícias.

FUNCIONALIDADES DISPONÍVEIS:
1. **CONSULTA_FEEDBACK_LIKES**: Buscar notícias que receberam feedback positivo (likes)
2. **CONSULTA_FEEDBACK_DISLIKES**: Buscar notícias que receberam feedback negativo (dislikes)  
3. **CONSULTA_FEEDBACK_GERAL**: Buscar todas as notícias com qualquer tipo de feedback (likes + dislikes)
4. **CONTAGEM_FEEDBACK**: Contar quantidades de likes/dislikes
5. **EDICAO_TAG**: Alterar/atualizar tag de uma notícia específica
6. **EDICAO_PRIORIDADE**: Alterar/atualizar prioridade de uma notícia
7. **BUSCA_NOTICIAS**: Buscar notícias por termo, título, conteúdo
8. **RESUMO_NOTICIAS**: Resumir/sintetizar notícias encontradas
9. **CONSULTA_OFERTAS**: Buscar ofertas públicas de ações
10. **ANALISE_GEOPOLITICA**: Análise de impactos geopolíticos (EUA-Rússia, etc.)
11. **CONSULTA_PRIORIDADES**: Listar notícias por nível de prioridade
12. **CONSULTA_GERAL**: Pergunta genérica que precisa de busca e análise

PERGUNTA DO USUÁRIO: "{question}"

Analise a pergunta e retorne um JSON com:
{{
  "funcionalidade": "NOME_DA_FUNCIONALIDADE",
  "confianca": 0.95,
  "parametros": {{
    "periodo": "hoje|ultima_semana|ultimo_mes|sem_filtro",
    "tipo_feedback": "like|dislike|ambos",
    "termo_busca": "palavra ou frase a buscar",
    "prioridade": "P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO",
    "acao": "listar|contar|alterar|buscar"
  }}
}}

IMPORTANTE: 
- Se mencionar "like" E "dislike" juntos = CONSULTA_FEEDBACK_GERAL
- Se só "like" ou "feedback positivo" = CONSULTA_FEEDBACK_LIKES  
- Se só "dislike" ou "feedback negativo" = CONSULTA_FEEDBACK_DISLIKES
- Se "quantos/quantas" + feedback = CONTAGEM_FEEDBACK
- Se "altere/mude/atualize" = EDICAO_TAG ou EDICAO_PRIORIDADE
- Se buscar por termo/palavra = BUSCA_NOTICIAS
- Palavras como "classificadas", "com feedback" indicam CONSULTA, não EDIÇÃO
"""

        try:
            import json
            response = self.llm.invoke(prompt)
            result_text = response.content.strip()
            
            # Remove markdown se houver
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].strip()
            
            result = json.loads(result_text)
            return result
            
        except Exception as e:
            print(f"[Estagiario] Erro na classificação de intenção: {e}")
            # Fallback para classificação simples
            return {
                "funcionalidade": "CONSULTA_GERAL",
                "confianca": 0.5,
                "parametros": {}
            }

    def _route_by_intent(self, intent_result: dict, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """
        Roteamento baseado na classificação de intenção do LLM.
        """
        funcionalidade = intent_result.get("funcionalidade", "CONSULTA_GERAL")
        parametros = intent_result.get("parametros", {})
        
        print(f"[Estagiario] Roteando para: {funcionalidade}")
        
        # Extração de período de tempo
        start_date, end_date = self._extract_time_period(question, target_date)
        
        if funcionalidade == "CONSULTA_FEEDBACK_LIKES":
            return self._handle_feedback_likes(db, start_date, end_date)
            
        elif funcionalidade == "CONSULTA_FEEDBACK_DISLIKES":
            return self._handle_feedback_dislikes(db, start_date, end_date)
            
        elif funcionalidade == "CONSULTA_FEEDBACK_GERAL":
            return self._handle_feedback_general(db, start_date, end_date)
            
        elif funcionalidade == "CONTAGEM_FEEDBACK":
            return self._handle_feedback_count(db, start_date, end_date)
            
        elif funcionalidade in ["EDICAO_TAG", "EDICAO_PRIORIDADE"]:
            return self._handle_edit_operation(question, db, target_date)
            
        elif funcionalidade == "BUSCA_NOTICIAS":
            return self._handle_news_search(question, db, target_date)
            
        elif funcionalidade == "CONSULTA_OFERTAS":
            return self._handle_ofertas_search(question, db, target_date)
            
        elif funcionalidade == "ANALISE_GEOPOLITICA":
            return self._handle_geopolitical_analysis(question, db, target_date)
            
        elif funcionalidade == "CONSULTA_PRIORIDADES":
            return self._handle_priority_query(question, db, target_date)
            
        else:  # CONSULTA_GERAL ou fallback
            return self._handle_general_query(question, db, target_date)

    # ====== HANDLERS ESPECÍFICOS PARA CADA FUNCIONALIDADE ======
    
    def _handle_feedback_likes(self, db, start_date: datetime.date, end_date: Optional[datetime.date]) -> AgentAnswer:
        """Handler para consultas de feedback positivo (likes)"""
        print("[Estagiario] Caso: notícias com feedback positivo")
        likes = self._fetch_feedback_likes(db, start_date, end_date)
        
        if not likes:
            if end_date is None:
                period_str = "TODO O HISTÓRICO"
            else:
                period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
            return AgentAnswer(True, f"Nenhuma notícia com feedback positivo encontrada no período {period_str}.")
        
        # Monta resposta em Markdown
        if end_date is None:
            period_str = "TODO O HISTÓRICO"
        else:
            period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        texto = f"## Notícias com Reforço Positivo (Likes) - {period_str}\n\n"
        texto += f"**Total de notícias com likes: {len(likes)}**\n\n"
        
        for i, item in enumerate(likes[:30], 1):
            cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
            jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
            date_info = f" [{item['created_at']}]" if item['created_at'] else ""
            feedback_info = f" (Feedback: {item['feedback_date']})" if item['feedback_date'] else ""
            texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}{feedback_info}\n"
        
        if len(likes) > 30:
            texto += f"\n... e mais {len(likes) - 30} notícias com likes.\n"
            
        texto += "\n### Análise\n"
        texto += "Estas notícias receberam feedback positivo dos usuários. "
        texto += "Padrões identificados podem ser usados para melhorar a qualidade da classificação e resumos.\n"
        
        return AgentAnswer(True, texto, {"likes": likes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

    def _handle_feedback_dislikes(self, db, start_date: datetime.date, end_date: Optional[datetime.date]) -> AgentAnswer:
        """Handler para consultas de feedback negativo (dislikes)"""
        print("[Estagiario] Caso: notícias com feedback negativo")
        dislikes = self._fetch_feedback_dislikes(db, start_date, end_date)
        
        if not dislikes:
            if end_date is None:
                period_str = "TODO O HISTÓRICO"
            else:
                period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
            return AgentAnswer(True, f"Nenhuma notícia com feedback negativo encontrada no período {period_str}.")
        
        # Monta resposta em Markdown
        if end_date is None:
            period_str = "TODO O HISTÓRICO"
        else:
            period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        texto = f"## Notícias com Reforço Negativo (Dislikes) - {period_str}\n\n"
        texto += f"**Total de notícias com dislikes: {len(dislikes)}**\n\n"
        
        for i, item in enumerate(dislikes[:30], 1):
            cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
            jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
            date_info = f" [{item['created_at']}]" if item['created_at'] else ""
            feedback_info = f" (Feedback: {item['feedback_date']})" if item['feedback_date'] else ""
            texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}{feedback_info}\n"
        
        if len(dislikes) > 30:
            texto += f"\n... e mais {len(dislikes) - 30} notícias com dislikes.\n"
            
        texto += "\n### Análise\n"
        texto += "Estas notícias receberam feedback negativo dos usuários. "
        texto += "Podem indicar problemas na classificação, resumos inadequados ou conteúdo irrelevante.\n"
        
        return AgentAnswer(True, texto, {"dislikes": dislikes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

    def _handle_feedback_general(self, db, start_date: datetime.date, end_date: Optional[datetime.date]) -> AgentAnswer:
        """Handler para consultas gerais de feedback (likes + dislikes)"""
        print("[Estagiario] Caso: consulta geral de feedback (likes + dislikes)")
        
        # Busca ambos
        likes = self._fetch_feedback_likes(db, start_date, end_date)
        dislikes = self._fetch_feedback_dislikes(db, start_date, end_date)
        
        if not likes and not dislikes:
            if end_date is None:
                period_str = "TODO O HISTÓRICO"
            else:
                period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
            return AgentAnswer(True, f"Nenhuma notícia com feedback encontrada no período {period_str}.")
        
        # Monta resposta combinada
        if end_date is None:
            period_str = "TODO O HISTÓRICO"
        else:
            period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        
        texto = f"## Notícias com Feedback (Likes + Dislikes) - {period_str}\n\n"
        texto += f"**Total: {len(likes)} likes + {len(dislikes)} dislikes = {len(likes) + len(dislikes)} notícias**\n\n"
        
        if likes:
            texto += f"### ✅ Notícias com Likes ({len(likes)})\n\n"
            for i, item in enumerate(likes[:15], 1):
                cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}\n"
            if len(likes) > 15:
                texto += f"... e mais {len(likes) - 15} notícias com likes.\n"
            texto += "\n"
        
        if dislikes:
            texto += f"### ❌ Notícias com Dislikes ({len(dislikes)})\n\n"
            for i, item in enumerate(dislikes[:15], 1):
                cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}\n"
            if len(dislikes) > 15:
                texto += f"... e mais {len(dislikes) - 15} notícias com dislikes.\n"
        
        return AgentAnswer(True, texto, {"likes": likes, "dislikes": dislikes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

    def _handle_feedback_count(self, db, start_date: datetime.date, end_date: Optional[datetime.date]) -> AgentAnswer:
        """Handler para contagem de feedback"""
        print("[Estagiario] Caso: contagem de feedback")
        counts = self._count_feedback(db, start_date, end_date)
        
        if end_date is None:
            period_str = "TODO O HISTÓRICO"
        else:
            period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
        texto = f"## Resumo de Feedback - {period_str}\n\n"
        texto += f"- **Likes (reforço positivo):** {counts['likes']}\n"
        texto += f"- **Dislikes (reforço negativo):** {counts['dislikes']}\n"
        total = counts['likes'] + counts['dislikes']
        if total > 0:
            pct_positivo = (counts['likes'] / total) * 100
            texto += f"- **Total de feedback:** {total}\n"
            texto += f"- **Taxa de aprovação:** {pct_positivo:.1f}%\n"
        else:
            texto += "- **Total de feedback:** 0\n"
        
        counts["period"] = {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}
        return AgentAnswer(True, texto, counts)

    def _handle_edit_operation(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para operações de edição (delegando ao código legado)"""
        print("[Estagiario] Delegando para código legado de edição...")
        # Delega para o sistema existente (abaixo será chamado o fallback)
        return self._fallback_to_legacy_system(question, db, target_date)

    def _handle_news_search(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para busca de notícias"""
        print("[Estagiario] Delegando para busca de notícias...")
        return self._fallback_to_legacy_system(question, db, target_date)

    def _handle_ofertas_search(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para busca de ofertas"""
        print("[Estagiario] Delegando para busca de ofertas...")
        return self._fallback_to_legacy_system(question, db, target_date)

    def _handle_geopolitical_analysis(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para análise geopolítica"""
        print("[Estagiario] Delegando para análise geopolítica...")
        return self._fallback_to_legacy_system(question, db, target_date)

    def _handle_priority_query(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para consultas por prioridade"""
        print("[Estagiario] Delegando para consultas por prioridade...")
        return self._fallback_to_legacy_system(question, db, target_date)

    def _handle_general_query(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Handler para consultas gerais"""
        print("[Estagiario] Delegando para consulta geral...")
        return self._fallback_to_legacy_system(question, db, target_date)

    def _fallback_to_legacy_system(self, question: str, db, target_date: datetime.date) -> AgentAnswer:
        """Fallback para o sistema de heurísticas legado"""
        print("[Estagiario] Usando sistema legado como fallback...")
        # Para o fallback, vamos direto para busca básica
        q = question.lower().strip()
        
        # Busca simples por termo
        try:
            clusters = self._fetch_clusters(db, target_date)
            if not clusters:
                return AgentAnswer(True, "Nenhuma notícia encontrada para hoje.")
            
            # LLM para responder com base nos clusters encontrados
            llm_txt = self._llm_answer(question, clusters[:20], "")
            if llm_txt:
                return AgentAnswer(True, llm_txt, {"clusters": clusters[:10]})
            
            return AgentAnswer(True, f"Encontradas {len(clusters)} notícias para análise.", {"clusters": clusters[:10]})
            
        except Exception as e:
            print(f"[Estagiario] Erro no fallback: {e}")
            return AgentAnswer(False, "Erro ao processar a consulta.")

    def _extract_time_period(self, question: str, default_date: datetime.date) -> tuple[datetime.date, Optional[datetime.date]]:
        """Extrai período de tempo da pergunta ou retorna data padrão. Retorna (start_date, end_date) onde None indica sem filtro."""
        import re
        from datetime import timedelta
        
        q = question.lower().strip()
        today = default_date
        
        # Detecta "sem filtro", "tudo", "todos", "todas", "histórico completo"
        if any(phrase in q for phrase in [
            "sem filtro de data", "sem filtro", "traga tudo", "tudo", "todos", "todas",
            "histórico completo", "historico completo", "todo o histórico", "todo o historico",
            "completo", "desde sempre", "sem limite de data"
        ]):
            print(f"[Estagiario] Período extraído: SEM FILTRO DE DATA (todos os registros)")
            return datetime.date(2020, 1, 1), None  # start_date muito antiga, end_date = None indica sem limite
        
        # Detecta "última semana" / "ultimos 7 dias"
        if ("última semana" in q or "ultima semana" in q or "últimos 7 dias" in q or 
            "ultimos 7 dias" in q or "last week" in q or "past week" in q):
            end_date = today
            start_date = today - timedelta(days=7)
            print(f"[Estagiario] Período extraído: última semana ({start_date} a {end_date})")
            return start_date, end_date
            
        # Detecta "últimos X dias"
        match = re.search(r"últimos?\s+(\d+)\s+dias?|ultimos?\s+(\d+)\s+dias?|last\s+(\d+)\s+days?", q)
        if match:
            days = int(match.group(1) or match.group(2) or match.group(3))
            end_date = today
            start_date = today - timedelta(days=days)
            print(f"[Estagiario] Período extraído: últimos {days} dias ({start_date} a {end_date})")
            return start_date, end_date
            
        # Detecta "último mês" / "últimos 30 dias"
        if ("último mês" in q or "ultimo mes" in q or "últimos 30 dias" in q or 
            "ultimos 30 dias" in q or "last month" in q or "past month" in q):
            end_date = today
            start_date = today - timedelta(days=30)
            print(f"[Estagiario] Período extraído: último mês ({start_date} a {end_date})")
            return start_date, end_date
            
        # Detecta "ontem"
        if ("ontem" in q or "yesterday" in q):
            yesterday = today - timedelta(days=1)
            print(f"[Estagiario] Período extraído: ontem ({yesterday})")
            return yesterday, yesterday
            
        # Detecta "esta semana" / "semana atual"
        if ("esta semana" in q or "semana atual" in q or "this week" in q or "current week" in q):
            # Encontra segunda-feira da semana atual
            days_since_monday = today.weekday()
            start_date = today - timedelta(days=days_since_monday)
            end_date = today
            print(f"[Estagiario] Período extraído: esta semana ({start_date} a {end_date})")
            return start_date, end_date
            
        # Default: apenas hoje
        print(f"[Estagiario] Período padrão: hoje ({today})")
        return today, today

    def _handle_edit_command(self, db, question: str, q: str, target_date: datetime.date) -> AgentAnswer:
        """
        Processa comandos de edição com lógica inteligente:
        1. Identifica o que alterar (tag/prioridade)
        2. Encontra o cluster por ID ou título parcial
        3. Executa a alteração
        """
        import re
        
        # ETAPA 1: Detecta comandos diretos com ID de cluster
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
        m = re.search(r"tag.*cluster\s+(\d+)\s+para\s+([\wãáàâêíçõéú\s-]+)", q)
        if m:
            cluster_id = int(m.group(1))
            tag = m.group(2).strip()
            return self._update_cluster_tag(db, cluster_id, tag, question)

        # merge: "merge o cluster 111 no 222"
        m = re.search(r"merge.*cluster\s+(\d+)\s+no\s+(\d+)", q)
        if m:
            origem = int(m.group(1))
            destino = int(m.group(2))
            if origem == destino:
                return AgentAnswer(False, "IDs de origem e destino iguais.")
            from backend.crud import merge_clusters
            res = merge_clusters(db, destino_id=destino, fontes_ids=[origem], motivo=f"Estagiario: merge solicitado '{question}'")
            return AgentAnswer(True, f"✅ Merge efetuado. Artigos movidos: {res.get('artigos_movidos',0)}; Clusters encerrados: {res.get('clusters_descartados',0)}.")

        # ETAPA 2: Comandos inteligentes com busca por título
        # Extrai trecho do título mencionado
        titulo_patterns = [
            r'noticia.*?["\'](.*?)["\'"]',
            r'noticia.*?:\s*["\'](.*?)["\'"]',
            r'essa noticia.*?["\'](.*?)["\'"]',
            r'noticia.*?de hoje.*?["\'](.*?)["\'"]',
            r'["\'](.*?)["\']\s*foi classificada',
            r'["\'](.*?)["\']\s*está.*tag',
        ]
        
        titulo_encontrado = None
        for pattern in titulo_patterns:
            m = re.search(pattern, question, re.IGNORECASE)
            if m:
                titulo_encontrado = m.group(1).strip()
                break
        
        # Se não encontrou título entre aspas, tenta extrair de forma mais flexível
        if not titulo_encontrado:
            # Procura por padrões como "noticia de hoje: texto" ou "essa noticia texto"
            flexible_patterns = [
                r'noticia.*?de hoje\s*:\s*(.{10,80}?)\s*(?:foi|está|mude|altere|corrija)',
                r'essa noticia.*?:\s*(.{10,80}?)\s*(?:foi|está|mude|altere|corrija)',
                r'noticia.*?:\s*(.{10,80}?)\s*(?:foi|está|mude|altere|corrija)',
            ]
            for pattern in flexible_patterns:
                m = re.search(pattern, question, re.IGNORECASE)
                if m:
                    titulo_encontrado = m.group(1).strip()
                    break
        
        if not titulo_encontrado:
            return AgentAnswer(False, "❌ Não consegui identificar qual notícia alterar. Use aspas no título ou o ID do cluster.\nExemplos:\n- 'mude a tag da notícia \"Título da notícia\" para Dívida Ativa'\n- 'atualize prioridade do cluster 123 para p2'")

        print(f"[Estagiario] Título extraído: '{titulo_encontrado}'")

        # ETAPA 3: Busca clusters por título parcial
        clusters_candidatos = self._find_clusters_by_partial_title(db, titulo_encontrado, target_date)
        if not clusters_candidatos:
            return AgentAnswer(False, f"❌ Nenhuma notícia encontrada com título similar a: '{titulo_encontrado}'")
        
        if len(clusters_candidatos) > 1:
            # Múltiplos candidatos: lista para o usuário escolher
            lista_opcoes = []
            for i, c in enumerate(clusters_candidatos[:5], 1):
                lista_opcoes.append(f"{i}. [ID {c['id']}] {c['titulo']} (Tag: {c['tag']}, Prioridade: {c['prioridade']})")
            
            return AgentAnswer(False, f"❌ Encontrei {len(clusters_candidatos)} notícias similares. Seja mais específico ou use o ID:\n\n" + "\n".join(lista_opcoes))
        
        # ETAPA 4: Cluster único encontrado - executa alteração
        cluster = clusters_candidatos[0]
        cluster_id = cluster['id']
        
        # Detecta o tipo de alteração desejada
        if any(word in q for word in ["tag", "categoria", "classificada", "classificar"]):
            # Alteração de TAG
            nova_tag = self._extract_target_tag(question, q)
            if not nova_tag:
                print("[Estagiario] Edit: tag não encontrada na frase, pedindo LLM para escolher a tag canônica...")
                nova_tag = self._llm_choose_tag(db, cluster_id)
                if not nova_tag:
                    return AgentAnswer(False, f"❌ Não consegui identificar para qual tag alterar. Notícia encontrada: [ID {cluster_id}] {cluster['titulo']}")
            return self._update_cluster_tag(db, cluster_id, nova_tag, question, cluster['titulo'])
            
        elif any(word in q for word in ["prioridade", "p1", "p2", "p3"]):
            # Alteração de PRIORIDADE
            nova_prioridade = self._extract_target_priority(q)
            if not nova_prioridade:
                print("[Estagiario] Edit: prioridade não encontrada na frase, pedindo LLM para escolher...")
                nova_prioridade = self._llm_choose_priority(db, cluster_id)
                if not nova_prioridade:
                    return AgentAnswer(False, f"❌ Não consegui identificar para qual prioridade alterar. Notícia encontrada: [ID {cluster_id}] {cluster['titulo']}")
            ok = update_cluster_priority(db, cluster_id, nova_prioridade, motivo=f"Estagiario: ajuste solicitado '{question}'")
            if ok:
                return AgentAnswer(True, f"✅ Prioridade atualizada para {nova_prioridade}!\n\n📰 Notícia: [ID {cluster_id}] {cluster['titulo']}")
            else:
                return AgentAnswer(False, f"❌ Falha ao atualizar prioridade da notícia [ID {cluster_id}] {cluster['titulo']}")
        
        return AgentAnswer(False, f"❌ Comando de edição não reconhecido. Notícia encontrada: [ID {cluster_id}] {cluster['titulo']}\n\nEspecifique se quer alterar 'tag' ou 'prioridade'.")

    def _find_clusters_by_partial_title(self, db, titulo_busca: str, target_date: datetime.date, limit: int = 5) -> List[Dict[str, Any]]:
        """Busca clusters por título parcial usando LIKE."""
        try:
            from sqlalchemy import func, and_
            # Normaliza busca
            titulo_busca_norm = titulo_busca.lower().strip()
            
            clusters = db.query(ClusterEvento).filter(
                and_(
                    func.date(ClusterEvento.created_at) == target_date,
                    ClusterEvento.status == 'ativo',
                    func.lower(ClusterEvento.titulo_cluster).like(f'%{titulo_busca_norm}%')
                )
            ).limit(limit).all()
            
            resultado = []
            for c in clusters:
                resultado.append({
                    'id': c.id,
                    'titulo': c.titulo_cluster,
                    'tag': c.tag,
                    'prioridade': c.prioridade
                })
            
            print(f"[Estagiario] Busca por '{titulo_busca}' encontrou {len(resultado)} clusters")
            return resultado
            
        except Exception as e:
            print(f"[Estagiario] Erro na busca por título: {e}")
            return []

    def _extract_target_tag(self, question: str, q: str) -> Optional[str]:
        """Extrai a tag de destino da pergunta."""
        # Mapeia termos comuns para tags canônicas
        tag_aliases = {
            "divida ativa": "Dívida Ativa e Créditos Públicos",
            "dívida ativa": "Dívida Ativa e Créditos Públicos", 
            "creditos publicos": "Dívida Ativa e Créditos Públicos",
            "créditos públicos": "Dívida Ativa e Créditos Públicos",
            "cda": "Dívida Ativa e Créditos Públicos",
            "m&a": "M&A e Transações Corporativas",
            "ma": "M&A e Transações Corporativas",
            "transacoes": "M&A e Transações Corporativas",
            "transações": "M&A e Transações Corporativas",
            "juridico": "Jurídico, Falências e Regulatório",
            "jurídico": "Jurídico, Falências e Regulatório",
            "falencias": "Jurídico, Falências e Regulatório",
            "falências": "Jurídico, Falências e Regulatório",
            "regulatorio": "Jurídico, Falências e Regulatório",
            "regulatório": "Jurídico, Falências e Regulatório",
            "mercado de capitais": "Mercado de Capitais e Ofertas Públicas",
            "ofertas publicas": "Mercado de Capitais e Ofertas Públicas",
            "ofertas públicas": "Mercado de Capitais e Ofertas Públicas",
            "internacional": "Política Econômica e Internacional",
            "politica economica": "Política Econômica e Internacional",
            "política econômica": "Política Econômica e Internacional",
            "tecnologia": "Tecnologia e Setores Estratégicos",
            "setores estrategicos": "Tecnologia e Setores Estratégicos",
            "setores estratégicos": "Tecnologia e Setores Estratégicos",
            "distressed": "Distressed Assets e NPLs",
            "npls": "Distressed Assets e NPLs"
        }
        
        # Busca por padrões de destino
        import re
        # 1) Após "para" com aspas (aceita curvas)
        m = re.search(r'para\s*["\'“”]([^"\'“”]+)["\'“”]', q, re.IGNORECASE)
        if m:
            tag_candidata = m.group(1).strip()
            low = tag_candidata.lower()
            if low in tag_aliases:
                return tag_aliases[low]
            return tag_candidata
        # 2) Último bloco entre aspas pode ser a TAG
        quoted = re.findall(r'["\'“”]([^"\'“”]+)["\'“”]', question)
        if quoted:
            possivel = quoted[-1].strip()
            return possivel
        # 3) Padrões sem aspas
        m = re.search(r'(?:mude|altere|troque).*?para\s+(.+)$', q, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        
        return None

    def _extract_target_priority(self, q: str) -> Optional[str]:
        """Extrai a prioridade de destino da pergunta."""
        import re
        patterns = [
            r'para\s+(p1|p2|p3|irrelevante)',
            r'prioridade\s+(p1|p2|p3|irrelevante)',
            r'(p1|p2|p3|irrelevante)'
        ]
        
        for pattern in patterns:
            m = re.search(pattern, q, re.IGNORECASE)
            if m:
                alvo = m.group(1).upper()
                mapa = {"P1": "P1_CRITICO", "P2": "P2_ESTRATEGICO", "P3": "P3_MONITORAMENTO", "IRRELEVANTE": "IRRELEVANTE"}
                return mapa.get(alvo)
        
        return None

    def _llm_choose_priority(self, db, cluster_id: int) -> Optional[str]:
        """Decide a PRIORIDADE via LLM (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO, IRRELEVANTE)."""
        if not self.model:
            return None
        try:
            niveis = self.prioridades_permitidas
            from backend.crud import get_cluster_details_by_id
            ctx = get_cluster_details_by_id(db, cluster_id) or {}
            titulo = ctx.get('titulo_final') or ctx.get('titulo') or ''
            resumo = ctx.get('resumo_final') or ctx.get('resumo') or ''
            instr = (
                "Classifique a PRIORIDADE do cluster em UMA das seguintes: 'P1_CRITICO','P2_ESTRATEGICO','P3_MONITORAMENTO','IRRELEVANTE'. "
                "Responda APENAS com JSON no formato {\"prioridade\": \"<nivel>\"}. Não explique.\n\n"
                f"Titulo: {titulo}\n"
                f"Resumo: {resumo}\n"
            )
            resp = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 128})
            raw = (resp.text or '').strip()
            import json, re
            if raw.startswith('```'):
                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
            try:
                data = json.loads(raw)
            except Exception:
                m = re.search(r"\{[\s\S]*\}", raw)
                data = json.loads(m.group(0)) if m else {}
            pr = data.get('prioridade') if isinstance(data, dict) else None
            if pr in niveis:
                return pr
            return None
        except Exception as e:
            print(f"[Estagiario] Falha no LLM escolha de prioridade: {e}")
            return None

    def _update_cluster_tag(self, db, cluster_id: int, nova_tag: str, question: str, titulo_cluster: str = None) -> AgentAnswer:
        """Atualiza tag de um cluster com validação."""
        # Valida contra catálogo
        tag_valida = None
        catalogo = self._catalogo_tags(db)
        for tag_oficial in catalogo:
            if nova_tag.lower() == tag_oficial.lower():
                tag_valida = tag_oficial
                break
        
        if not tag_valida:
            # Busca match parcial
            for tag_oficial in catalogo:
                if nova_tag.lower() in tag_oficial.lower() or tag_oficial.lower() in nova_tag.lower():
                    tag_valida = tag_oficial
                    break
        
        if not tag_valida:
            tags_disponiveis = "', '".join(catalogo)
            return AgentAnswer(False, f"❌ Tag '{nova_tag}' não reconhecida.\n\nTags disponíveis: '{tags_disponiveis}'")
        
        from backend.crud import update_cluster_tags
        ok = update_cluster_tags(db, cluster_id, [tag_valida], motivo=f"Estagiario: ajuste solicitado '{question}'")
        
        if ok:
            cluster_info = f"[ID {cluster_id}]" + (f" {titulo_cluster}" if titulo_cluster else "")
            return AgentAnswer(True, f"✅ Tag atualizada para '{tag_valida}'!\n\n📰 Notícia: {cluster_info}")
        else:
            return AgentAnswer(False, f"❌ Falha ao atualizar tag da notícia [ID {cluster_id}]")

    def answer_with_context(self, question: str, chat_history: List[Dict[str, Any]], date_str: Optional[str] = None) -> AgentAnswer:
        """
        Responde perguntas mantendo o contexto da conversa anterior.
        """
        print("[Estagiario] ================= INÍCIO COM CONTEXTO =================")
        print(f"[Estagiario] Pergunta: {question}")
        print(f"[Estagiario] Histórico: {len(chat_history)} mensagens")
        
        # Formata o histórico para o LLM
        context_prompt = ""
        if chat_history and len(chat_history) > 1:  # Mais de 1 porque a última é a pergunta atual
            context_prompt = "\n\n### Histórico da Conversa:\n"
            for i, msg in enumerate(chat_history[:-1]):  # Exclui a última mensagem (pergunta atual)
                role = "Usuário" if msg.get('role') == 'user' else "Assistente"
                content = msg.get('content', '')
                context_prompt += f"{role}: {content}\n"
                print(f"[Estagiario] Contexto: {role}: {content[:100]}...")
            context_prompt += "\n### Pergunta Atual:\n"
            print(f"[Estagiario] Contexto final: {len(context_prompt)} caracteres")
        else:
            print("[Estagiario] Sem histórico para incluir no contexto")
        
        # Chama a função original com contexto adicional
        return self.answer(question, date_str, context_prompt)
    
    def answer(self, question: str, date_str: Optional[str] = None, context_prompt: str = "") -> AgentAnswer:
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

            # Roteamento ADMIN (CONSULTA DE TAGS): perguntas como "quais são as tags disponíveis" vão direto ao banco
            if (any(k in q for k in ["tag", "tags"]) and any(k in q for k in ["disponiveis", "disponíveis", "lista", "listagem", "todas"])) or (
                any(k in q for k in ["tag", "tags"]) and any(k in q for k in ["exemplo", "exemplos"]) and ("banco" in q or "catálogo" in q or "catalogo" in q or "disponiveis" in q or "disponíveis" in q or "site" in q or "tabela" in q)
            ):
                try:
                    from backend.crud import get_prompts_compilados
                    comp = get_prompts_compilados(db)
                    tags_payload = comp.get("tags") or {}
                    # Normaliza em linhas (nome, descricao, exemplos)
                    rows = []
                    if isinstance(tags_payload, dict):
                        for nome, meta in tags_payload.items():
                            try:
                                desc = (meta.get("descricao") or "").strip()
                                exemplos = meta.get("exemplos") or []
                            except AttributeError:
                                desc = ""
                                exemplos = []
                            rows.append((nome, desc, exemplos))
                    elif isinstance(tags_payload, list):
                        for t in tags_payload:
                            if isinstance(t, dict):
                                nome = t.get("nome") or t.get("tag") or "(sem nome)"
                                desc = (t.get("descricao") or "").strip()
                                exemplos = t.get("exemplos") or []
                                rows.append((nome, desc, exemplos))
                    if not rows:
                        return AgentAnswer(True, "Nenhuma tag configurada no banco.")
                    # Renderiza em Markdown (tabela)
                    def esc(s: str) -> str:
                        return str(s).replace("|", "\\|")
                    linhas = [
                        "### Tags (catálogo do banco)",
                        "",
                        "| Tag | Descrição | Exemplos |",
                        "|---|---|---|",
                    ]
                    for nome, desc, exemplos in rows:
                        ex_list = exemplos if isinstance(exemplos, list) else []
                        exemplos_txt = "; ".join([str(e) for e in ex_list[:8]])
                        linhas.append(f"| {esc(nome)} | {esc(desc)} | {esc(exemplos_txt)} |")
                    return AgentAnswer(True, "\n".join(linhas), {"tags": tags_payload})
                except Exception as e:
                    print(f"[Estagiario] Falha ao consultar tags do banco: {e}")
                    return AgentAnswer(False, "Falha ao consultar tags do banco.")

            if ("prioridade" in q or "prioridades" in q) and ("exemplo" in q or "exemplos" in q or "itens" in q):
                try:
                    from backend.crud import get_prompts_compilados
                    comp = get_prompts_compilados(db)
                    p1 = comp.get("p1", [])
                    p2 = comp.get("p2", [])
                    p3 = comp.get("p3", [])
                    linhas = ["### Prioridades (catalogo do banco)"]
                    def render(nivel: str, itens):
                        linhas.append(f"- **{nivel}**:")
                        if itens:
                            for it in itens[:20]:
                                linhas.append(f"  - {it}")
                        else:
                            linhas.append("  - (sem itens)")
                    render("P1_CRITICO", p1)
                    render("P2_ESTRATEGICO", p2)
                    render("P3_MONITORAMENTO", p3)
                    return AgentAnswer(True, "\n".join(linhas), {"p1": p1, "p2": p2, "p3": p3})
                except Exception as e:
                    print(f"[Estagiario] Falha ao consultar prioridades do banco: {e}")
                    return AgentAnswer(False, "Falha ao consultar prioridades do banco.")

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

            # ====== NOVA ARQUITETURA: CLASSIFICAÇÃO DE INTENÇÃO VIA LLM ======
            print("[Estagiario] Classificando intenção da pergunta via LLM...")
            intent_result = self._classify_intent(question)
            print(f"[Estagiario] Intenção detectada: {intent_result}")
            
            # Roteamento baseado na classificação LLM
            return self._route_by_intent(intent_result, question, db, target_date)

            # ====== CÓDIGO LEGADO (MANTIDO COMO FALLBACK) ======
            # PRIORIDADE 1: Casos de Feedback - detectar ANTES de comandos de edição
            # Primeiro, detecta especificamente dislikes para evitar conflito com "like" em "dislike"
            is_dislike_query = ("reforço negativo" in q or "reforco negativo" in q or 
                               "dislikes" in q or "dislike" in q or "feedback negativo" in q)
            is_like_query = ("reforço positivo" in q or "reforco positivo" in q or 
                            "likes" in q or ("like" in q and "dislike" not in q) or "feedback positivo" in q)
            
            # Caso 2.2: notícias com feedback negativo (dislikes) - processar primeiro para evitar conflitos
            if is_dislike_query and ("notícias" in q or "noticias" in q or "títulos" in q or "titulos" in q):
                print("[Estagiario] Caso: notícias com feedback negativo")
                start_date, end_date = self._extract_time_period(question, target_date)
                dislikes = self._fetch_feedback_dislikes(db, start_date, end_date)
                
                if not dislikes:
                    if end_date is None:
                        period_str = "TODO O HISTÓRICO"
                    else:
                        period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                    return AgentAnswer(True, f"Nenhuma notícia com feedback negativo encontrada no período {period_str}.")
                
                # Monta resposta em Markdown
                if end_date is None:
                    period_str = "TODO O HISTÓRICO"
                else:
                    period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                texto = f"## Notícias com Reforço Negativo (Dislikes) - {period_str}\n\n"
                texto += f"**Total de notícias com dislikes: {len(dislikes)}**\n\n"
                
                for i, item in enumerate(dislikes[:30], 1):  # Aumenta limite para períodos maiores
                    cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                    jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                    date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                    feedback_info = f" (Feedback: {item['feedback_date']})" if item['feedback_date'] else ""
                    texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}{feedback_info}\n"
                
                if len(dislikes) > 30:
                    texto += f"\n... e mais {len(dislikes) - 30} notícias com dislikes.\n"
                    
                texto += "\n### Análise\n"
                texto += "Estas notícias receberam feedback negativo dos usuários. "
                texto += "Podem indicar problemas na classificação, resumos inadequados ou conteúdo irrelevante.\n"
                
                return AgentAnswer(True, texto, {"dislikes": dislikes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

            # Caso 2.1: notícias com feedback positivo (likes)
            if is_like_query and ("notícias" in q or "noticias" in q or "títulos" in q or "titulos" in q):
                print("[Estagiario] Caso: notícias com feedback positivo")
                start_date, end_date = self._extract_time_period(question, target_date)
                likes = self._fetch_feedback_likes(db, start_date, end_date)
                
                if not likes:
                    if end_date is None:
                        period_str = "TODO O HISTÓRICO"
                    else:
                        period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                    return AgentAnswer(True, f"Nenhuma notícia com feedback positivo encontrada no período {period_str}.")
                
                # Monta resposta em Markdown
                if end_date is None:
                    period_str = "TODO O HISTÓRICO"
                else:
                    period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                texto = f"## Notícias com Reforço Positivo (Likes) - {period_str}\n\n"
                texto += f"**Total de notícias com likes: {len(likes)}**\n\n"
                
                for i, item in enumerate(likes[:30], 1):  # Aumenta limite para períodos maiores
                    cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                    jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                    date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                    feedback_info = f" (Feedback: {item['feedback_date']})" if item['feedback_date'] else ""
                    texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}{feedback_info}\n"
                
                if len(likes) > 30:
                    texto += f"\n... e mais {len(likes) - 30} notícias com likes.\n"
                    
                texto += "\n### Análise\n"
                texto += "Estas notícias receberam feedback positivo dos usuários. "
                texto += "Padrões identificados podem ser usados para melhorar a qualidade da classificação e resumos.\n"
                
                return AgentAnswer(True, texto, {"likes": likes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

            # Caso 2.3: consulta geral de feedback (like E dislike juntos)
            if (("like" in q and "dislike" in q) or "feedback" in q) and ("notícias" in q or "noticias" in q or "títulos" in q or "titulos" in q or "classificadas" in q):
                print("[Estagiario] Caso: consulta geral de feedback (likes + dislikes)")
                start_date, end_date = self._extract_time_period(question, target_date)
                
                # Busca ambos
                likes = self._fetch_feedback_likes(db, start_date, end_date)
                dislikes = self._fetch_feedback_dislikes(db, start_date, end_date)
                
                if not likes and not dislikes:
                    if end_date is None:
                        period_str = "TODO O HISTÓRICO"
                    else:
                        period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                    return AgentAnswer(True, f"Nenhuma notícia com feedback encontrada no período {period_str}.")
                
                # Monta resposta combinada
                if end_date is None:
                    period_str = "TODO O HISTÓRICO"
                else:
                    period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                
                texto = f"## Notícias com Feedback (Likes + Dislikes) - {period_str}\n\n"
                texto += f"**Total: {len(likes)} likes + {len(dislikes)} dislikes = {len(likes) + len(dislikes)} notícias**\n\n"
                
                if likes:
                    texto += f"### ✅ Notícias com Likes ({len(likes)})\n\n"
                    for i, item in enumerate(likes[:15], 1):
                        cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                        jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                        date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                        texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}\n"
                    if len(likes) > 15:
                        texto += f"... e mais {len(likes) - 15} notícias com likes.\n"
                    texto += "\n"
                
                if dislikes:
                    texto += f"### ❌ Notícias com Dislikes ({len(dislikes)})\n\n"
                    for i, item in enumerate(dislikes[:15], 1):
                        cluster_info = f" (Cluster: {item['cluster_id']} - {item['titulo_cluster']})" if item['cluster_id'] else ""
                        jornal_info = f" - {item['jornal']}" if item['jornal'] else ""
                        date_info = f" [{item['created_at']}]" if item['created_at'] else ""
                        texto += f"{i}. [{item['id']}] {item['titulo_extraido']}{jornal_info}{date_info}{cluster_info}\n"
                    if len(dislikes) > 15:
                        texto += f"... e mais {len(dislikes) - 15} notícias com dislikes.\n"
                
                return AgentAnswer(True, texto, {"likes": likes, "dislikes": dislikes, "period": {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}})

            # Caso 2.4: contagem de feedback
            if ("quantos" in q or "quantas" in q) and ("likes" in q or "dislikes" in q or "feedback" in q):
                print("[Estagiario] Caso: contagem de feedback")
                start_date, end_date = self._extract_time_period(question, target_date)
                counts = self._count_feedback(db, start_date, end_date)
                
                if end_date is None:
                    period_str = "TODO O HISTÓRICO"
                else:
                    period_str = f"{start_date.strftime('%d/%m/%Y')}" if start_date == end_date else f"{start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}"
                texto = f"## Resumo de Feedback - {period_str}\n\n"
                texto += f"- **Likes (reforço positivo):** {counts['likes']}\n"
                texto += f"- **Dislikes (reforço negativo):** {counts['dislikes']}\n"
                total = counts['likes'] + counts['dislikes']
                if total > 0:
                    pct_positivo = (counts['likes'] / total) * 100
                    texto += f"- **Total de feedback:** {total}\n"
                    texto += f"- **Taxa de aprovação:** {pct_positivo:.1f}%\n"
                else:
                    texto += "- **Total de feedback:** 0\n"
                
                counts["period"] = {"start": start_date.isoformat(), "end": end_date.isoformat() if end_date else None}
                return AgentAnswer(True, texto, counts)

            # PRIORIDADE 2: Detecta comandos de edição/alteração (APÓS verificação de feedback)
            edit_triggers = ["atualize", "troque", "mude", "altere", "corrija", "modifique", "merge", "unir", "unifica", "foi classificada", "tag errada", "prioridade errada"]
            is_edit_command = any(trigger in q for trigger in edit_triggers)
            
            # SAFEGUARD: Se a pergunta contém termos de consulta/busca, NÃO é comando de edição
            query_indicators = ["quais", "quantas", "quantos", "mostre", "liste", "busque", "encontre", "procure", "veja", "ver", "consulte"]
            is_query = any(indicator in q for indicator in query_indicators)
            
            if is_edit_command and not is_query:
                print("[Estagiario] Detectado: comando de edição/alteração")
                # Primeiro tenta entender via LLM a operação desejada (camada agentica)
                spec = self._llm_understand_edit(question)
                if not spec:
                    # Fallback robusto quando LLM não devolve JSON válido
                    spec = self._fallback_understand_edit(question)
                if not spec:
                    # Nova estratégia: extrair possíveis entidades (título não fornecido) a partir de keywords e deixar o LLM escolher direto
                    kws = self._extract_keywords_simple(question)
                    print(f"[Estagiario] Edit: nenhum spec; tentando keywords={kws}")
                    universo = self._fetch_clusters(db, target_date, priority=None)
                    candidatos = []
                    for it in universo:
                        blob = ((it.get('titulo_final') or '') + '\n' + (it.get('resumo_final') or '')).lower()
                        if all(k in blob for k in kws):
                            candidatos.append({'id': it.get('id'), 'titulo': it.get('titulo_final')})
                    if candidatos:
                        ids = self._llm_pick_best_by_title(" ".join(kws), candidatos)
                        if ids:
                            # Assume update_tag se 'tag' na pergunta, senão update_priority se 'p1/p2/p3/prioridade'
                            op_guess = 'update_tag' if 'tag' in q or 'categoria' in q else ('update_priority' if any(x in q for x in ['p1','p2','p3','prioridade']) else 'update_tag')
                            spec = {'operation': op_guess, 'cluster_id': ids[0], 'cluster_title': None, 'new_tag': None, 'new_priority': None}
                if spec:
                    # Se veio cluster_id, tenta aplicar direto; senão, usa cluster_title parcial para buscar
                    op = spec.get('operation')
                    cid = spec.get('cluster_id')
                    ctitle = spec.get('cluster_title')
                    new_tag = spec.get('new_tag')
                    new_pr = spec.get('new_priority')
                    cand: List[Dict[str, Any]] = []
                    apply_all = ('todas' in q) or ('todos' in q)
                    if cid:
                        if op == 'update_tag':
                            # Resolve tag com múltiplas tentativas (explícita → contexto → frase), respeitando budget de iterações
                            tag_escolhida = self._resolve_tag_canonically(db, question, int(cid), new_tag)
                            if not tag_escolhida:
                                return AgentAnswer(False, f"❌ Não consegui determinar a tag correta para o cluster [ID {cid}].")
                            return self._update_cluster_tag(db, int(cid), tag_escolhida, question)
                        if op == 'update_priority':
                            pr_escolhida = self._resolve_priority(db, question, int(cid), new_pr)
                            if not pr_escolhida:
                                return AgentAnswer(False, f"❌ Não consegui determinar a prioridade correta para o cluster [ID {cid}].")
                            ok = update_cluster_priority(db, int(cid), pr_escolhida, motivo=f"Estagiario: ajuste solicitado '{question}'")
                            return AgentAnswer(bool(ok), (f"✅ Prioridade atualizada para {pr_escolhida}." if ok else "Falha ao atualizar prioridade."))
                    # Sem ID: tenta busca por título parcial ou por keywords/LLM search spec
                    if ctitle:
                        cand = self._find_clusters_by_partial_title(db, ctitle, target_date)
                        if not cand:
                            # Tenta buscar por palavras-chave do ctitle
                            filtros = self._llm_generate_search_spec(ctitle)
                            kws = (filtros.get('keywords') if filtros else None) or self._extract_keywords_simple(ctitle)
                            prios = (filtros.get('priorities') if filtros else []) if filtros else []
                            tgs = (filtros.get('tags') if filtros else []) if filtros else []
                            print(f"[Estagiario] Busca por LLM-spec: prios={prios} tags={tgs} keywords={kws}")
                            universo: List[Dict[str, Any]] = []
                            if prios:
                                for p in prios:
                                    universo.extend(self._fetch_clusters(db, target_date, priority=p))
                            else:
                                universo = self._fetch_clusters(db, target_date, priority=None)
                            # Filtra por tags se houver
                            if tgs:
                                tgset = set([t.lower() for t in tgs])
                                universo = [u for u in universo if (u.get('tag') or '').lower() in tgset]
                            # Candidatos por keywords (qualquer match)
                            candidatos = []
                            for it in universo:
                                blob = ((it.get('titulo_final') or '') + '\n' + (it.get('resumo_final') or '')).lower()
                                if any(k.lower() in blob for k in kws):
                                    candidatos.append({'id': it.get('id'), 'titulo': it.get('titulo_final')})
                            print(f"[Estagiario] Candidatos por keywords: {len(candidatos)}")
                            if candidatos:
                                ids = self._llm_pick_best_by_title(ctitle, candidatos)
                                if ids:
                                    cand = [{'id': i, 'titulo': next((c['titulo'] for c in candidatos if c['id']==i), '')} for i in ids]
                            if not cand:
                                return AgentAnswer(False, f"❌ Não encontrei notícia com título similar a: '{ctitle}'")
                    else:
                        # Sem título nem ID: pede SPEC ao LLM e monta busca dinâmica
                        filtros = self._llm_generate_search_spec(question)
                        kws = (filtros.get('keywords') if filtros else None) or self._extract_keywords_simple(question)
                        prios = (filtros.get('priorities') if filtros else []) if filtros else []
                        tgs = (filtros.get('tags') if filtros else []) if filtros else []
                        print(f"[Estagiario] Edit: sem título; buscando por prios={prios} tags={tgs} keywords={kws}")
                        universo: List[Dict[str, Any]] = []
                        if prios:
                            for p in prios:
                                universo.extend(self._fetch_clusters(db, target_date, priority=p))
                        else:
                            universo = self._fetch_clusters(db, target_date, priority=None)
                        if tgs:
                            tgset = set([t.lower() for t in tgs])
                            universo = [u for u in universo if (u.get('tag') or '').lower() in tgset]
                        candidatos = []
                        for it in universo:
                            blob = ((it.get('titulo_final') or '') + '\n' + (it.get('resumo_final') or '')).lower()
                            if any(k.lower() in blob for k in kws):
                                candidatos.append({'id': it.get('id'), 'titulo': it.get('titulo_final')})
                        print(f"[Estagiario] Candidatos por keywords (sem título): {len(candidatos)}")
                        if candidatos:
                            ids = self._llm_pick_best_by_title(' '.join(kws), candidatos)
                            if ids:
                                cand = [{'id': i, 'titulo': next((c['titulo'] for c in candidatos if c['id']==i), '')} for i in ids]
                        if not cand:
                            return AgentAnswer(False, "❌ Não consegui localizar a notícia a partir da descrição. Tente incluir um trecho do título entre aspas.")
                        if len(cand) > 1 and self.model:
                            # Usa LLM para escolher o melhor candidato com base no título solicitado
                            instr = (
                                "Escolha o MELHOR MATCH pelo título solicitado. Responda APENAS com JSON do tipo {\"id\": <id>}\n\n"
                                f"Título alvo: {ctitle}\n"
                                f"Candidatos: {[{'id': c['id'], 'titulo': c['titulo']} for c in cand]}\n"
                            )
                            print("[Estagiario] LLM pick-best-candidate: solicitando JSON...")
                            r = self.model.generate_content(instr, generation_config={'temperature': 0.1, 'max_output_tokens': 64})
                            raw = (r.text or '').strip()
                            print(f"[Estagiario] LLM pick-best-candidate (raw): {raw[:300]}")
                            import json, re
                            if raw.startswith('```'):
                                raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
                            escolha_id = None
                            escolha_ids: List[int] = []
                            try:
                                data = json.loads(raw)
                                if isinstance(data.get('ids'), list):
                                    for x in data.get('ids'):
                                        try:
                                            escolha_ids.append(int(x))
                                        except Exception:
                                            pass
                                escolha_id = int(data.get('id')) if isinstance(data.get('id'), (int, str)) else None
                            except Exception:
                                m = re.search(r"\d+", raw)
                                escolha_id = int(m.group(0)) if m else None
                            if apply_all and escolha_ids:
                                keep = set([i for i in escolha_ids if any(c['id']==i for c in cand)])
                                if keep:
                                    cand = [c for c in cand if c['id'] in keep]
                            elif escolha_id and any(c['id'] == escolha_id for c in cand):
                                cand = [c for c in cand if c['id'] == escolha_id]
                            else:
                                cand = [cand[0]]
                        # prossegue com único
                        targets = cand if apply_all and len(cand) > 1 else [cand[0]]
                        print("[Estagiario] Edit: alvos escolhidos:", 
                              ", ".join([f"[ID {t['id']}] {t.get('titulo')}" for t in targets]))
                        if op == 'update_tag':
                            aplicados = []
                            for t in targets:
                                tag_escolhida = self._resolve_tag_canonically(db, question, t['id'], new_tag)
                                if not tag_escolhida:
                                    continue
                                res = self._update_cluster_tag(db, t['id'], tag_escolhida, question, t.get('titulo'))
                                try:
                                    det = get_cluster_details_by_id(db, t['id'])
                                    print(f"[Estagiario] DB confirm tag: [ID {t['id']}] tag={det.get('tag')} prio={det.get('prioridade')}")
                                except Exception:
                                    pass
                                if res and res.ok:
                                    aplicados.append((t['id'], t.get('titulo'), tag_escolhida))
                            if aplicados:
                                linhas = [f"✅ Tag '{tg}' aplicada em [ID {cid}] {ttl}" for cid, ttl, tg in aplicados]
                                return AgentAnswer(True, "\n".join(linhas))
                            return AgentAnswer(False, "❌ Não foi possível aplicar a tag nos alvos escolhidos.")
                        if op == 'update_priority':
                            aplicados = []
                            for t in targets:
                                pr_escolhida = self._resolve_priority(db, question, t['id'], new_pr)
                                if not pr_escolhida:
                                    continue
                                ok = update_cluster_priority(db, t['id'], pr_escolhida, motivo=f"Estagiario: ajuste solicitado '{question}'")
                                try:
                                    det = get_cluster_details_by_id(db, t['id'])
                                    print(f"[Estagiario] DB confirm prio: [ID {t['id']}] tag={det.get('tag')} prio={det.get('prioridade')}")
                                except Exception:
                                    pass
                                if ok:
                                    aplicados.append((t['id'], t.get('titulo'), pr_escolhida))
                            if aplicados:
                                linhas = [f"✅ Prioridade '{pr}' aplicada em [ID {cid}] {ttl}" for cid, ttl, pr in aplicados]
                                return AgentAnswer(True, "\n".join(linhas))
                            return AgentAnswer(False, "❌ Não foi possível aplicar a prioridade nos alvos escolhidos.")
                    # Se LLM entendeu 'merge', manter fluxo manual por segurança
                # Fallback: heurística atual
                return self._handle_edit_command(db, question, q, target_date)

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
                llm_txt = self._llm_answer(question, achados, context_prompt)
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
                llm_txt = self._llm_answer(question, retrieved if retrieved else selecionados, context_prompt)
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
                print("[Estagiario] Caso: busca genérica (plano via LLM → execução)")
                # Pede ao LLM um plano de busca (prioridades/tags/keywords) e usa como primeira camada
                filtros = self._llm_generate_search_spec(question) or self._infer_filters(q)
                # Coleta priorizada por prioridades inferidas ou ALL
                candidatos: List[Dict[str, Any]] = []
                if filtros.get("priorities"):
                    for p in filtros.get("priorities"):
                        candidatos.extend(self._fetch_clusters(db, target_date, priority=p))
                else:
                    candidatos = self._fetch_clusters(db, target_date, priority=None)
                print(f"[Estagiario] Candidatos (pré-tag): {len(candidatos)}")
                # Filtra por tags inferidas (se houver)
                if filtros.get("tags"):
                    tgset = set([t.lower() for t in filtros.get("tags")])
                    candidatos = [c for c in candidatos if (c.get("tag") or '').lower() in tgset]
                print(f"[Estagiario] Após filtro de tags: {len(candidatos)}")
                # Opcional: filtragem leve por keyword (evita perder muito recall)
                if filtros.get("keywords") and len(candidatos) > 160:
                    def contains_kw(c):
                        L = ((c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")).lower()
                        return any(k.lower() in L for k in filtros.get("keywords"))
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
                llm_txt = self._llm_answer(question, base_para_sintese, context_prompt)
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


