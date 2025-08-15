from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date

try:
    from backend.database import SessionLocal
    from backend.crud import (
        get_clusters_for_feed_by_date,
        get_cluster_details_by_id,
        update_cluster_priority as crud_update_cluster_priority,
    )
    from backend.utils import get_date_brasil
except Exception:
    SessionLocal = None  # type: ignore


class QueryClustersInput(BaseModel):
    data: Optional[date] = Field(default=None, description="Data no formato YYYY-MM-DD. Padrão: hoje.")
    prioridade: Optional[str] = Field(None, description="'P1_CRITICO' | 'P2_ESTRATEGICO' | 'P3_MONITORAMENTO' | None")
    palavras_chave: Optional[List[str]] = Field(None, description="Busca em título/resumo (case-insensitive)")
    limite: int = Field(50, description="Máximo de clusters")


class GetClusterDetailsInput(BaseModel):
    cluster_id: int


class UpdateClusterPriorityInput(BaseModel):
    cluster_id: int
    nova_prioridade: str


def _open_db():
    if SessionLocal is None:
        raise RuntimeError("Backend indisponível")
    return SessionLocal()


def query_clusters(params: QueryClustersInput) -> List[Dict[str, Any]]:
    db = _open_db()
    try:
        d = params.data or get_date_brasil()
        # paginação simples até atingir limite
        page, acc = 1, []
        while len(acc) < params.limite:
            resp = get_clusters_for_feed_by_date(db, d, page=page, page_size=min(100, params.limite - len(acc)), load_full_text=False, priority=params.prioridade)
            clusters = resp.get("clusters", [])
            if params.palavras_chave:
                kws = [k.lower() for k in params.palavras_chave]
                fil = []
                for c in clusters:
                    blob = ((c.get("titulo_final") or "") + "\n" + (c.get("resumo_final") or "")).lower()
                    if any(k in blob for k in kws):
                        fil.append(c)
                clusters = fil
            acc.extend(clusters)
            if not resp.get("paginacao", {}).get("tem_proxima"):
                break
            page += 1
        return acc[: params.limite]
    finally:
        try:
            db.close()
        except Exception:
            pass


def get_cluster_details(params: GetClusterDetailsInput) -> Dict[str, Any]:
    db = _open_db()
    try:
        det = get_cluster_details_by_id(db, params.cluster_id)
        return det or {}
    finally:
        try:
            db.close()
        except Exception:
            pass


def update_cluster_priority(params: UpdateClusterPriorityInput) -> Dict[str, Any]:
    db = _open_db()
    try:
        permitido = {"P1_CRITICO", "P2_ESTRATEGICO", "P3_MONITORAMENTO", "IRRELEVANTE"}
        if params.nova_prioridade not in permitido:
            return {"ok": False, "error": "Prioridade não permitida"}
        ok = crud_update_cluster_priority(db, params.cluster_id, params.nova_prioridade, motivo="Estagiario (tool)")
        return {"ok": bool(ok)}
    finally:
        try:
            db.close()
        except Exception:
            pass


