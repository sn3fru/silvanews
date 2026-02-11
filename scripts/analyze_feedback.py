"""
Analisa padroes de feedback (like/dislike) e gera REGRAS_APRENDIDAS
para injecao conservadora nos prompts do pipeline.

Uso:
    conda activate pymc2
    python scripts/analyze_feedback.py
    python scripts/analyze_feedback.py --days 90 --min-samples 5 --save

Opcoes:
    --days N        Ultimos N dias de feedback (default: 90)
    --min-samples N Minimo de amostras para considerar padrao (default: 5)
    --save          Salva regras no banco (tabela prompt_configs) para injecao
    --dry-run       Apenas mostra analise sem salvar
"""

import sys
import os
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter, defaultdict

# Setup path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / "backend" / ".env")

from backend.database import SessionLocal, FeedbackNoticia, ArtigoBruto, ClusterEvento


def collect_feedback(db, days: int):
    """Coleta feedback dos ultimos N dias com contexto."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    feedbacks = (
        db.query(FeedbackNoticia)
        .filter(FeedbackNoticia.created_at >= cutoff)
        .order_by(FeedbackNoticia.created_at.desc())
        .all()
    )
    
    enriched = []
    for fb in feedbacks:
        meta = fb.metadados or {}
        
        # Se metadados esta vazio (feedback antigo), tenta enriquecer retroativamente
        if not meta.get("tag"):
            artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == fb.artigo_id).first()
            if artigo:
                meta["tag"] = artigo.tag
                meta["prioridade"] = artigo.prioridade
                meta["titulo"] = artigo.titulo_extraido or ""
                meta["cluster_id"] = artigo.cluster_id
                meta["tipo_fonte"] = artigo.tipo_fonte
                if artigo.cluster_id:
                    cluster = db.query(ClusterEvento).filter(ClusterEvento.id == artigo.cluster_id).first()
                    if cluster:
                        meta["titulo_cluster"] = cluster.titulo_cluster or ""
        
        enriched.append({
            "id": fb.id,
            "artigo_id": fb.artigo_id,
            "feedback": fb.feedback,
            "created_at": fb.created_at.isoformat(),
            "tag": meta.get("tag", "DESCONHECIDO"),
            "prioridade": meta.get("prioridade", "DESCONHECIDO"),
            "titulo": meta.get("titulo", ""),
            "titulo_cluster": meta.get("titulo_cluster", ""),
            "cluster_id": meta.get("cluster_id"),
            "tipo_fonte": meta.get("tipo_fonte", ""),
            "entidades": meta.get("entidades", []),
        })
    
    return enriched


def analyze_patterns(feedbacks, min_samples: int = 5):
    """Descobre padroes nos feedbacks."""
    
    # Contagens por tag
    tag_feedback = defaultdict(lambda: {"like": 0, "dislike": 0})
    for fb in feedbacks:
        tag_feedback[fb["tag"]][fb["feedback"]] += 1
    
    # Contagens por prioridade
    prio_feedback = defaultdict(lambda: {"like": 0, "dislike": 0})
    for fb in feedbacks:
        prio_feedback[fb["prioridade"]][fb["feedback"]] += 1
    
    # Contagens por entidade
    entity_feedback = defaultdict(lambda: {"like": 0, "dislike": 0, "type": ""})
    for fb in feedbacks:
        for ent in fb.get("entidades", []):
            key = ent.get("name", "")
            if key:
                entity_feedback[key][fb["feedback"]] += 1
                entity_feedback[key]["type"] = ent.get("type", "")
    
    # Palavras-chave em titulos de dislikes
    dislike_words = Counter()
    like_words = Counter()
    stopwords = {"de", "da", "do", "dos", "das", "e", "em", "o", "a", "os", "as", "um", "uma",
                 "para", "com", "por", "no", "na", "nos", "nas", "ao", "se", "que", "como",
                 "mais", "entre", "sobre", "sua", "seu", "ser", "ter", "foi", "sao", "tem"}
    
    for fb in feedbacks:
        titulo = (fb.get("titulo_cluster") or fb.get("titulo") or "").lower()
        words = [w.strip(".,;:!?()[]{}\"'") for w in titulo.split() if len(w) > 3 and w.lower() not in stopwords]
        if fb["feedback"] == "dislike":
            dislike_words.update(words)
        else:
            like_words.update(words)
    
    # Monta analise
    analysis = {
        "total_feedbacks": len(feedbacks),
        "total_likes": sum(1 for f in feedbacks if f["feedback"] == "like"),
        "total_dislikes": sum(1 for f in feedbacks if f["feedback"] == "dislike"),
        "patterns": {
            "tags_with_high_dislike": [],
            "priorities_overclassified": [],
            "entities_disliked": [],
            "keywords_disliked": [],
            "keywords_liked": [],
        },
    }
    
    # Tags com alto dislike rate
    for tag, counts in tag_feedback.items():
        total = counts["like"] + counts["dislike"]
        if total >= min_samples:
            dislike_rate = counts["dislike"] / total
            if dislike_rate >= 0.5:
                analysis["patterns"]["tags_with_high_dislike"].append({
                    "tag": tag,
                    "dislike_rate": round(dislike_rate * 100),
                    "total": total,
                    "dislikes": counts["dislike"],
                })
    
    analysis["patterns"]["tags_with_high_dislike"].sort(
        key=lambda x: x["dislike_rate"], reverse=True
    )
    
    # Prioridades over-classificadas (P1/P2 com muitos dislikes)
    for prio, counts in prio_feedback.items():
        total = counts["like"] + counts["dislike"]
        if total >= min_samples and prio in ("P1_CRITICO", "P2_ESTRATEGICO"):
            dislike_rate = counts["dislike"] / total
            if dislike_rate >= 0.3:
                analysis["patterns"]["priorities_overclassified"].append({
                    "prioridade": prio,
                    "dislike_rate": round(dislike_rate * 100),
                    "total": total,
                    "dislikes": counts["dislike"],
                })
    
    # Entidades frequentemente disliked
    for name, counts in entity_feedback.items():
        total = counts["like"] + counts["dislike"]
        if total >= min_samples:
            dislike_rate = counts["dislike"] / total
            if dislike_rate >= 0.6:
                analysis["patterns"]["entities_disliked"].append({
                    "entity": name,
                    "type": counts["type"],
                    "dislike_rate": round(dislike_rate * 100),
                    "total": total,
                })
    
    analysis["patterns"]["entities_disliked"].sort(
        key=lambda x: x["dislike_rate"], reverse=True
    )
    
    # Top keywords
    analysis["patterns"]["keywords_disliked"] = [
        {"word": w, "count": c} for w, c in dislike_words.most_common(15)
        if c >= 3
    ]
    analysis["patterns"]["keywords_liked"] = [
        {"word": w, "count": c} for w, c in like_words.most_common(10)
        if c >= 3
    ]
    
    return analysis


def generate_rules(analysis):
    """Gera texto REGRAS_APRENDIDAS para injecao nos prompts."""
    rules = []
    
    # Regras de tags
    for tag_info in analysis["patterns"]["tags_with_high_dislike"]:
        rules.append(
            f"- Noticias com tag '{tag_info['tag']}' tem {tag_info['dislike_rate']}% de rejeicao "
            f"pelos analistas ({tag_info['dislikes']}/{tag_info['total']} amostras). "
            f"Considere rebaixar prioridade ou classificar como IRRELEVANTE."
        )
    
    # Regras de prioridade
    for prio_info in analysis["patterns"]["priorities_overclassified"]:
        rules.append(
            f"- Noticias classificadas como '{prio_info['prioridade']}' tem {prio_info['dislike_rate']}% de rejeicao. "
            f"Seja mais rigoroso ao atribuir esta prioridade."
        )
    
    # Regras de entidades
    for ent_info in analysis["patterns"]["entities_disliked"][:5]:
        rules.append(
            f"- Noticias sobre '{ent_info['entity']}' ({ent_info['type']}) tem {ent_info['dislike_rate']}% de rejeicao. "
            f"Provavelmente irrelevante para Special Situations."
        )
    
    # Regras fixas (domain knowledge)
    rules.append("- Deals e operacoes abaixo de R$10 milhoes sao P3_MONITORAMENTO no maximo.")
    rules.append("- Noticias sobre celebridades, entretenimento, esportes e fofoca sao IRRELEVANTES.")
    rules.append("- Clima e meteorologia sao IRRELEVANTES exceto se afetar commodities ou logistica.")
    
    if not rules:
        return ""
    
    header = (
        "REGRAS APRENDIDAS DO FEEDBACK DOS ANALISTAS DA MESA DE SPECIAL SITUATIONS:\n"
        "(Baseado em historico de likes/dislikes dos ultimos 90 dias)\n\n"
    )
    
    return header + "\n".join(rules)


def print_report(analysis, rules_text):
    """Imprime relatorio formatado."""
    print("=" * 70)
    print("ANALISE DE FEEDBACK - PADROES DESCOBERTOS")
    print("=" * 70)
    print(f"  Total feedbacks: {analysis['total_feedbacks']}")
    print(f"  Likes: {analysis['total_likes']}")
    print(f"  Dislikes: {analysis['total_dislikes']}")
    
    if analysis["patterns"]["tags_with_high_dislike"]:
        print(f"\n  TAGS COM ALTO DISLIKE:")
        for t in analysis["patterns"]["tags_with_high_dislike"]:
            print(f"    {t['tag']}: {t['dislike_rate']}% dislike ({t['total']} amostras)")
    
    if analysis["patterns"]["priorities_overclassified"]:
        print(f"\n  PRIORIDADES OVER-CLASSIFICADAS:")
        for p in analysis["patterns"]["priorities_overclassified"]:
            print(f"    {p['prioridade']}: {p['dislike_rate']}% dislike ({p['total']} amostras)")
    
    if analysis["patterns"]["entities_disliked"]:
        print(f"\n  ENTIDADES REJEITADAS:")
        for e in analysis["patterns"]["entities_disliked"][:10]:
            print(f"    {e['entity']} ({e['type']}): {e['dislike_rate']}% dislike ({e['total']} amostras)")
    
    if analysis["patterns"]["keywords_disliked"]:
        print(f"\n  PALAVRAS-CHAVE EM DISLIKES:")
        for k in analysis["patterns"]["keywords_disliked"][:10]:
            print(f"    '{k['word']}': {k['count']}x")
    
    print(f"\n{'='*70}")
    print("REGRAS GERADAS PARA INJECAO NOS PROMPTS:")
    print("=" * 70)
    if rules_text:
        print(rules_text)
    else:
        print("  Nenhuma regra gerada (feedback insuficiente)")
    print("=" * 70)


def save_rules(db, rules_text, analysis):
    """Salva regras no banco para uso pelo pipeline."""
    try:
        from backend.database import Base
        from sqlalchemy import text
        
        # Salva como configuracao
        db.execute(text("""
            INSERT INTO prompt_configs (chave, valor, descricao, updated_at)
            VALUES (:chave, :valor, :descricao, NOW())
            ON CONFLICT (chave) DO UPDATE
            SET valor = :valor, descricao = :descricao, updated_at = NOW()
        """), {
            "chave": "FEEDBACK_RULES",
            "valor": rules_text,
            "descricao": json.dumps(analysis, ensure_ascii=False, default=str),
        })
        db.commit()
        print("\n  Regras salvas na tabela prompt_configs (chave: FEEDBACK_RULES)")
    except Exception as e:
        # Fallback: salva como arquivo
        rules_file = PROJECT_DIR / "backend" / "feedback_rules.txt"
        rules_file.write_text(rules_text, encoding="utf-8")
        print(f"\n  Tabela prompt_configs indisponivel ({e})")
        print(f"  Regras salvas em: {rules_file}")


def main():
    parser = argparse.ArgumentParser(description="Analise de Feedback para Prompt Optimization")
    parser.add_argument("--days", type=int, default=90, help="Ultimos N dias")
    parser.add_argument("--min-samples", type=int, default=5, help="Minimo de amostras")
    parser.add_argument("--save", action="store_true", help="Salva regras no banco/arquivo")
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        # 1. Coleta
        print(f"\n[1/3] Coletando feedback dos ultimos {args.days} dias...")
        feedbacks = collect_feedback(db, args.days)
        print(f"  {len(feedbacks)} feedbacks encontrados")
        
        if not feedbacks:
            print("  Nenhum feedback encontrado. Nada a analisar.")
            return
        
        # 2. Analise
        print(f"\n[2/3] Analisando padroes (min {args.min_samples} amostras)...")
        analysis = analyze_patterns(feedbacks, args.min_samples)
        
        # 3. Gera regras
        print(f"\n[3/3] Gerando regras...")
        rules_text = generate_rules(analysis)
        
        # Report
        print_report(analysis, rules_text)
        
        # Salva
        if args.save and rules_text:
            save_rules(db, rules_text, analysis)
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
