"""
Script de Backfill para o Grafo de Conhecimento (v2.0).

Le artigos dos ultimos N dias e extrai entidades para popular
as tabelas graph_entities e graph_edges. Sem isso, o sistema
comeca "amnesico" (sem memoria temporal).

Uso:
    conda activate pymc2
    python scripts/backfill_graph.py --days 90 --limit 5000 --batch 50

Opcoes:
    --days N     Ultimos N dias para processar (default: 90)
    --limit N    Maximo de artigos a processar (default: 5000)
    --batch N    Tamanho do lote por chamada LLM (default: 20)
    --dry-run    Apenas mostra quantos artigos seriam processados
"""

import sys
import os
import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Adiciona o diretorio pai ao path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# Carrega .env antes de qualquer import do backend
from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / "backend" / ".env")

from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
from backend.agents.graph_crud import (
    get_or_create_entity,
    create_edge,
    link_artigo_to_entities,
    get_entity_stats,
)
from backend.utils import extrair_json_da_resposta, get_gemini_model
from backend.processing import gerar_embedding_v2

# Prompt para extracao de entidades em lote
PROMPT_BATCH_ENTITY_EXTRACTION = """Voce e um especialista em NER (Named Entity Recognition) para o mercado financeiro brasileiro.

Para CADA artigo abaixo, extraia as entidades principais (pessoas, empresas, orgaos governamentais, eventos e conceitos).

ARTIGOS:
{artigos_json}

REGRAS:
1. Extraia apenas entidades CONCRETAS e NOMEADAS
2. Para cada artigo, indique o artigo_id e as entidades encontradas
3. Tipos validos: PERSON | ORG | GOV | EVENT | CONCEPT
4. Roles: PROTAGONIST | TARGET | MENTIONED
5. Maximo 10 entidades por artigo

Responda APENAS com JSON valido:
```json
{{
  "results": [
    {{
      "artigo_id": 123,
      "entities": [
        {{
          "name": "Petrobras",
          "type": "ORG",
          "role": "PROTAGONIST",
          "sentiment": 0.5,
          "context": "trecho curto"
        }}
      ]
    }}
  ]
}}
```"""


def get_artigos_para_backfill(db, days: int, limit: int):
    """Busca artigos dos ultimos N dias que ainda nao tem entidades no grafo."""
    from backend.database import GraphEdge
    from sqlalchemy import func, select
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Subquery: artigos que ja tem edges (usando select() para evitar SAWarning)
    artigos_com_edges = (
        select(GraphEdge.artigo_id)
        .distinct()
        .scalar_subquery()
    )
    
    # Busca artigos sem edges, dos ultimos N dias
    artigos = (
        db.query(ArtigoBruto)
        .filter(
            ArtigoBruto.created_at >= cutoff,
            ArtigoBruto.status.in_(['processado', 'pronto_agrupar']),
            ~ArtigoBruto.id.in_(artigos_com_edges),
        )
        .order_by(ArtigoBruto.created_at.desc())
        .limit(limit)
        .all()
    )
    
    return artigos


def process_batch_with_llm(artigos_batch, model):
    """Processa um lote de artigos com LLM para extrair entidades."""
    artigos_json = []
    for artigo in artigos_batch:
        titulo = artigo.titulo_extraido or ""
        texto = (artigo.texto_bruto or "")[:800]  # Compacto para caber mais no batch
        artigos_json.append({
            "artigo_id": artigo.id,
            "titulo": titulo,
            "texto": texto,
        })
    
    prompt = PROMPT_BATCH_ENTITY_EXTRACTION.format(
        artigos_json=json.dumps(artigos_json, ensure_ascii=False, indent=2)
    )
    
    try:
        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.2,
                'max_output_tokens': 65536,  # Maximo para nao truncar JSONs grandes
            }
        )
        
        resultado = extrair_json_da_resposta(response.text)
        if resultado and isinstance(resultado, dict):
            return resultado.get("results", [])
        
        # Se falhou o parse e o lote e grande, tenta dividir ao meio (recursivo)
        if len(artigos_batch) > 5:
            print(f"    JSON truncado ({len(artigos_batch)} artigos). Dividindo lote ao meio...")
            meio = len(artigos_batch) // 2
            r1 = process_batch_with_llm(artigos_batch[:meio], model)
            r2 = process_batch_with_llm(artigos_batch[meio:], model)
            return r1 + r2
        
        return []
    except Exception as e:
        print(f"  ERRO no LLM: {e}")
        # Retry com lote menor em caso de erro
        if len(artigos_batch) > 5:
            print(f"    Retry com lote menor ({len(artigos_batch) // 2} artigos)...")
            meio = len(artigos_batch) // 2
            r1 = process_batch_with_llm(artigos_batch[:meio], model)
            r2 = process_batch_with_llm(artigos_batch[meio:], model)
            return r1 + r2
        return []


def process_batch_heuristic(artigos_batch):
    """
    Extracao heuristica de entidades (sem LLM).
    Usa regex para identificar nomes proprios e empresas conhecidas.
    """
    import re
    
    # Empresas frequentes no mercado BR
    KNOWN_COMPANIES = {
        "petrobras", "vale", "itau", "bradesco", "btg pactual", "americanas",
        "oi", "gol", "azul", "latam", "jbs", "ambev", "eletrobras", "sabesp",
        "magazine luiza", "via varejo", "renner", "marfrig", "minerva",
        "suzano", "klabin", "cemig", "copel", "equatorial", "neoenergia",
        "hapvida", "rede d'or", "fleury", "dasa", "embraer", "weg",
        "localiza", "movida", "cosan", "rumo", "raizen",
    }
    
    KNOWN_ORGS = {
        "banco central", "bacen", "cvm", "carf", "stf", "stj",
        "pgfn", "receita federal", "bndes", "cade", "anatel", "aneel",
        "copom", "tesouro nacional", "b3",
    }
    
    results = []
    
    for artigo in artigos_batch:
        texto = f"{artigo.titulo_extraido or ''} {(artigo.texto_bruto or '')[:2000]}".lower()
        entities = []
        
        # Busca empresas conhecidas
        for company in KNOWN_COMPANIES:
            if company in texto:
                entities.append({
                    "name": company.title(),
                    "type": "ORG",
                    "role": "MENTIONED",
                    "sentiment": 0.0,
                    "context": "",
                    "confidence": 0.7,
                })
        
        # Busca orgaos governamentais
        for org in KNOWN_ORGS:
            if org in texto:
                entities.append({
                    "name": org.upper() if len(org) <= 5 else org.title(),
                    "type": "GOV",
                    "role": "MENTIONED",
                    "sentiment": 0.0,
                    "context": "",
                    "confidence": 0.7,
                })
        
        if entities:
            results.append({
                "artigo_id": artigo.id,
                "entities": entities[:10],
            })
    
    return results


def run_backfill(days: int = 90, limit: int = 5000, batch_size: int = 20, dry_run: bool = False):
    """Executa o backfill do grafo."""
    print("=" * 60)
    print("BACKFILL DO GRAFO DE CONHECIMENTO (v2.0)")
    print("=" * 60)
    print(f"  Dias: {days}")
    print(f"  Limite: {limit}")
    print(f"  Batch: {batch_size}")
    print(f"  Modo: {'DRY RUN' if dry_run else 'PRODUCAO'}")
    
    db = SessionLocal()
    
    try:
        # 1. Busca artigos para processar
        print(f"\n[1/4] Buscando artigos dos ultimos {days} dias...")
        artigos = get_artigos_para_backfill(db, days, limit)
        print(f"  Encontrados: {len(artigos)} artigos sem entidades no grafo")
        
        if dry_run:
            print("\n[DRY RUN] Nenhuma alteracao feita.")
            stats = get_entity_stats(db)
            print(f"\n  Stats atuais do grafo:")
            print(f"    Entidades: {stats['total_entities']}")
            print(f"    Arestas: {stats['total_edges']}")
            return
        
        # 2. Tenta usar LLM, fallback para heuristicas
        print(f"\n[2/5] Preparando extracao de entidades...")
        try:
            model = get_gemini_model()
            use_llm = True
        except (ValueError, Exception) as e:
            print(f"  AVISO: {e}")
            model = None
            use_llm = False
        
        if use_llm:
            print("  Usando Gemini para NER (alta qualidade)")
        else:
            print("  Gemini indisponivel, usando heuristicas (qualidade basica)")
        
        # 3. Processa em batches: NER
        total_entities = 0
        total_edges = 0
        
        if not artigos:
            print("\n[3/5] NER: Todos artigos ja tem entidades no grafo. Pulando.")
        else:
            print(f"\n[3/5] Processando {len(artigos)} artigos em lotes de {batch_size}...")
        
        for i in range(0, len(artigos), batch_size):
            batch = artigos[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(artigos) + batch_size - 1) // batch_size
            
            print(f"\n  Lote {batch_num}/{total_batches} ({len(batch)} artigos)...")
            
            if use_llm:
                results = process_batch_with_llm(batch, model)
                time.sleep(1)  # Rate limit
            else:
                results = process_batch_heuristic(batch)
            
            # Persiste no grafo
            for result in results:
                artigo_id = result.get("artigo_id")
                entities = result.get("entities", [])
                
                if artigo_id and entities:
                    edges = link_artigo_to_entities(db, artigo_id, entities)
                    total_entities += len(set(e.entity_id for e in edges))
                    total_edges += len(edges)
            
            print(f"    OK - {len(results)} artigos com entidades extraidas")
        
        # 4. Gera embeddings v2 (Gemini 768d) em paralelo
        #    Busca TODOS artigos recentes sem embedding (nao apenas os sem edges)
        print(f"\n[4/5] Gerando embeddings v2 (Gemini 768d) em paralelo...")
        cutoff_emb = datetime.utcnow() - timedelta(days=days)
        artigos_sem_embedding = (
            db.query(ArtigoBruto)
            .filter(
                ArtigoBruto.created_at >= cutoff_emb,
                ArtigoBruto.embedding_v2.is_(None),
                ArtigoBruto.status.in_(['processado', 'pronto_agrupar']),
            )
            .order_by(ArtigoBruto.created_at.desc())
            .limit(limit)
            .all()
        )
        print(f"  {len(artigos_sem_embedding)} artigos sem embedding v2 encontrados")
        total_embeddings = 0
        
        def _gen_emb(artigo):
            """Gera embedding para um artigo (thread-safe, sem DB write)."""
            texto = f"{artigo.titulo_extraido or ''}\n{(artigo.texto_bruto or '')[:6000]}"
            return (artigo.id, gerar_embedding_v2(texto))
        
        WORKERS = 5  # 5 threads paralelas para I/O bound
        batch_commit = 50
        
        for chunk_start in range(0, len(artigos_sem_embedding), batch_commit):
            chunk = artigos_sem_embedding[chunk_start:chunk_start + batch_commit]
            artigo_map = {a.id: a for a in chunk}
            
            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = {executor.submit(_gen_emb, a): a.id for a in chunk}
                for future in as_completed(futures):
                    try:
                        aid, emb = future.result()
                        if emb and aid in artigo_map:
                            artigo_map[aid].embedding_v2 = emb
                            total_embeddings += 1
                    except Exception:
                        pass
            
            db.commit()
            done = min(chunk_start + batch_commit, len(artigos_sem_embedding))
            print(f"    {done}/{len(artigos_sem_embedding)} embeddings gerados...")
        
        print(f"  OK - {total_embeddings} embeddings v2 gerados")
        
        # 5. Estatisticas finais
        print(f"\n[5/5] Estatisticas finais do grafo...")
        stats = get_entity_stats(db)
        print(f"  Total entidades: {stats['total_entities']}")
        print(f"  Total arestas: {stats['total_edges']}")
        print(f"  Entidades por tipo: {stats['entities_by_type']}")
        print(f"  Arestas por relacao: {stats['edges_by_relation']}")
        
        print(f"\n  Backfill: +{total_edges} arestas criadas nesta execucao")
        
    except Exception as e:
        print(f"\nERRO: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
    
    print(f"\n{'='*60}")
    print("BACKFILL CONCLUIDO")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill do Grafo de Conhecimento")
    parser.add_argument("--days", type=int, default=90, help="Ultimos N dias")
    parser.add_argument("--limit", type=int, default=5000, help="Maximo de artigos")
    parser.add_argument("--batch", type=int, default=20, help="Tamanho do lote (default: 20)")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra quantos artigos")
    
    args = parser.parse_args()
    run_backfill(
        days=args.days,
        limit=args.limit,
        batch_size=args.batch,
        dry_run=args.dry_run,
    )
