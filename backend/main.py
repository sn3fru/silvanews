"""
Endpoints da API para o frontend e integrações.
"""

import os
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path  # Modernização: usar pathlib para caminhos
from dotenv import load_dotenv
import time # Adicionado para tracking de progresso
import asyncio # Adicionado para delays assíncronos

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import google.generativeai as genai

# Carrega variáveis de ambiente do arquivo .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Arquivo .env carregado: {env_file}")
else:
    print(f"⚠️ Arquivo .env não encontrado: {env_file}")

try:
    from .database import get_db, init_database, ArtigoBruto, ClusterEvento, SinteseExecutiva
    from .models import ProcessarArtigoRequest, StatusResponse, ArtigoBrutoCreate, ChatRequest, ChatResponse, ClusterUpdateRequest
    from .crud import (
        get_artigos_pendentes, get_metricas_today, get_sintese_today,
        get_clusters_for_feed, get_cluster_by_id, get_artigos_by_cluster,
        create_artigo_bruto, get_artigo_by_hash, get_artigo_by_id, create_log, get_database_stats,
        get_metricas_by_date, get_sintese_by_date, get_clusters_for_feed_by_date,
        get_cluster_details_by_id, get_or_create_chat_session, add_chat_message, get_chat_messages_by_session,
        get_chat_session_by_cluster, update_cluster_priority, update_cluster_tags,
        get_cluster_alteracoes, get_all_cluster_alteracoes,
        get_artigos_processados_hoje, get_clusters_existentes_hoje, get_cluster_com_artigos,
        associate_artigo_to_existing_cluster, create_cluster_for_artigo,
        agg_noticias_por_dia, agg_noticias_por_fonte, agg_noticias_por_autor,
        create_feedback, list_feedback, mark_feedback_processed
    )
    from .processing import processar_artigo_pipeline, gerar_resumo_cluster, inicializar_processamento
    from .utils import gerar_hash_unico, formatar_timestamp_relativo, get_date_brasil, parse_date_brasil
except ImportError:
    # Fallback para import absoluto quando executado fora do pacote
    from backend.database import get_db, init_database, ArtigoBruto, ClusterEvento, SinteseExecutiva
    from backend.models import ProcessarArtigoRequest, StatusResponse, ArtigoBrutoCreate, ChatRequest, ChatResponse, ClusterUpdateRequest
    from backend.crud import (
        get_artigos_pendentes, get_metricas_today, get_sintese_today,
        get_clusters_for_feed, get_cluster_by_id, get_artigos_by_cluster,
        create_artigo_bruto, get_artigo_by_hash, get_artigo_by_id, create_log, get_database_stats,
        get_metricas_by_date, get_sintese_by_date, get_clusters_for_feed_by_date,
        get_cluster_details_by_id, get_or_create_chat_session, add_chat_message, get_chat_messages_by_session,
        get_chat_session_by_cluster, update_cluster_priority, update_cluster_tags,
        get_cluster_alteracoes, get_all_cluster_alteracoes,
        get_artigos_processados_hoje, get_clusters_existentes_hoje, get_cluster_com_artigos,
        associate_artigo_to_existing_cluster, create_cluster_for_artigo
    )
    from backend.processing import processar_artigo_pipeline, gerar_resumo_cluster, inicializar_processamento
    from backend.utils import gerar_hash_unico, formatar_timestamp_relativo, get_date_brasil, parse_date_brasil


# ==============================================================================
# CONFIGURAÇÃO DE CAMINHOS E INICIALIZAÇÃO
# ==============================================================================

# Usando pathlib para uma definição de caminhos mais clara e robusta
BACKEND_DIR = Path(__file__).parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação."""
    # Startup
    print("🚀 Iniciando SILVA NEWS API...")
    
    # Inicializa banco de dados
    init_database()
    
    # Inicializa processamento
    if not inicializar_processamento():
        print("⚠️ Aviso: Processamento não inicializado completamente")
    
    print("✅ SILVA NEWS API iniciada com sucesso!")
    
    yield
    
    # Shutdown
    print("🛑 Finalizando SILVA NEWS API...")


# Criação da aplicação FastAPI
app = FastAPI(
    title="SILVA NEWS API",
    description="API para processamento e análise de notícias em tempo real",
    version="1.0.0",
    lifespan=lifespan
)

# Configuração CORS para desenvolvimento
# ATENÇÃO: Em produção, restrinja para domínios específicos!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especificar domínios
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# SERVIR FRONTEND E ENDPOINTS PRINCIPAIS
# ==============================================================================

# SOLUÇÃO: Montar o diretório do frontend. Mantemos /frontend por compatibilidade,
# e servimos também na raiz / para não exibir o sufixo na URL.
if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True, check_dir=True), name="frontend")

@app.get("/")
async def serve_root_index():
    """Serve o index.html do frontend na raiz sem redirecionar para /frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return RedirectResponse(url="/frontend")
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), status_code=200)

# Removido catch-all para não interferir nas rotas /api





@app.get("/api/feed")
async def get_feed(
    data: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    load_full_text: bool = False,
    priority: Optional[str] = None,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Endpoint principal para o frontend com paginação e carregamento lazy.
    Retorna métricas e lista de clusters paginada.
    
    Args:
        data: Data no formato YYYY-MM-DD (opcional, padrão: hoje)
        page: Número da página (começa em 1)
        page_size: Tamanho da página (padrão: 20)
        load_full_text: Se True, carrega texto completo. Se False, apenas título e resumo
        priority: Filtro opcional por prioridade (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO)
        db: Sessão do banco de dados
    """
    try:
        # Converte string de data para objeto date
        target_date = None
        if data:
            try:
                target_date = datetime.strptime(data, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
        else:
            target_date = get_date_brasil()
        
        # Valida parâmetros de paginação
        if page < 1:
            raise HTTPException(status_code=400, detail="Página deve ser maior que 0")
        if page_size < 1 or page_size > 100:
            raise HTTPException(status_code=400, detail="Tamanho da página deve estar entre 1 e 100")
        
        # Busca métricas da data específica
        metricas = get_metricas_by_date(db, target_date)
        
        # Busca síntese da data específica
        sintese = get_sintese_by_date(db, target_date)
        
        # Busca clusters da data específica com paginação
        resultado_clusters = get_clusters_for_feed_by_date(
            db, target_date, page=page, page_size=page_size, load_full_text=load_full_text, priority=priority
        )
        
        # Se não há dados reais, retorna dados vazios
        if not resultado_clusters["clusters"]:
            return {
                "metricas": {
                    "total_noticias_coletadas": 0,
                    "total_eventos_unicos": 0,
                    "total_analises_criticas": 0,
                    "total_em_monitoramento": 0
                },
                "sintese": None,
                "feed": [],
                "paginacao": {
                    "pagina_atual": page,
                    "total_paginas": 0,
                    "total_registros": 0,
                    "tem_proxima": False
                },
                "data_consulta": target_date.isoformat()
            }
        
        return {
            "metricas": metricas,
            "sintese": sintese,
            "feed": resultado_clusters["clusters"],
            "paginacao": resultado_clusters["paginacao"],
            "data_consulta": target_date.isoformat()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /api/feed: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/cluster/{cluster_id}")
async def get_cluster_details(
    cluster_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Endpoint para buscar detalhes completos de um cluster específico.
    Usado para carregamento lazy quando o usuário clica em uma notícia.
    
    Args:
        cluster_id: ID do cluster
        db: Sessão do banco de dados
    """
    try:
        cluster_details = get_cluster_details_by_id(db, cluster_id)
        
        if not cluster_details:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        return cluster_details
    
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /api/cluster/{cluster_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS INTERNOS (PARA COLETORES)
# ==============================================================================

@app.post("/internal/processar-artigo")
async def processar_artigo_endpoint(
    request: ProcessarArtigoRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint interno para processar um artigo.
    Usado pelos coletores para enviar artigos para processamento.
    """
    try:
        # Verifica se o artigo existe
        artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == request.id_artigo).first()
        if not artigo:
            raise HTTPException(status_code=404, detail="Artigo não encontrado")
        
        # Adiciona tarefa em background
        background_tasks.add_task(processar_artigo_background, request.id_artigo)
        
        create_log(db, "INFO", "api", 
                  f"Artigo {request.id_artigo} adicionado à fila de processamento")
        
        return StatusResponse(
            status="aceito",
            message=f"Artigo {request.id_artigo} adicionado à fila de processamento",
            data={"id_artigo": request.id_artigo}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /internal/processar-artigo: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/internal/novo-artigo")
async def criar_novo_artigo(
    artigo_data: ArtigoBrutoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para coletores criarem novos artigos.
    """
    try:
        # Verifica se já existe um artigo com o mesmo hash
        artigo_existente = get_artigo_by_hash(db, artigo_data.hash_unico)
        if artigo_existente:
            return StatusResponse(
                status="duplicado",
                message="Artigo já existe no sistema",
                data={"id_artigo": artigo_existente.id}
            )
        
        # Cria novo artigo (apenas carga bruta; processamento é etapa posterior)
        novo_artigo = create_artigo_bruto(db, artigo_data)
        
        create_log(db, "INFO", "api", 
                  f"Novo artigo criado: {novo_artigo.id}",
                  {"fonte": artigo_data.fonte_coleta})
        
        return StatusResponse(
            status="criado",
            message=f"Artigo criado com sucesso (processamento pendente)",
            data={"id_artigo": novo_artigo.id}
        )
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /internal/novo-artigo: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS DE ADMINISTRAÇÃO
# ==============================================================================

@app.get("/admin/stats")
async def get_admin_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Endpoint para estatísticas administrativas.
    """
    try:
        stats = get_database_stats(db)
        
        # Busca artigos pendentes
        artigos_pendentes = get_artigos_pendentes(db, limite=10)
        
        return {
            "database_stats": stats,
            "artigos_pendentes": len(artigos_pendentes),
            "sistema_status": "funcionando",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/stats: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS DE BI (DASHBOARDS SIMPLES)
# ==============================================================================

@app.get("/api/bi/series-por-dia")
async def bi_series_por_dia(dias: int = 30, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        series = agg_noticias_por_dia(db, dias=dias)
        return {"series": series}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/series-por-dia: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/bi/noticias-por-fonte")
async def bi_noticias_por_fonte(limit: int = 20, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        data = agg_noticias_por_fonte(db, limit=limit)
        return {"itens": data}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/noticias-por-fonte: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/bi/noticias-por-autor")
async def bi_noticias_por_autor(limit: int = 20, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        data = agg_noticias_por_autor(db, limit=limit)
        return {"itens": data}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/noticias-por-autor: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS DE FEEDBACK
# ==============================================================================

@app.post("/api/feedback")
async def post_feedback(artigo_id: int, feedback: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if feedback not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback deve ser 'like' ou 'dislike'")
    try:
        fb_id = create_feedback(db, artigo_id, feedback)
        return {"status": "ok", "id": fb_id}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em POST /api/feedback: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/feedback")
async def get_feedback(processed: Optional[bool] = None, limit: int = 100, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        itens = list_feedback(db, processed=processed, limit=limit)
        # Serialização simples
        data = [
            {
                "id": it.id,
                "artigo_id": it.artigo_id,
                "feedback": it.feedback,
                "processed": it.processed,
                "created_at": it.created_at.isoformat()
            }
            for it in itens
        ]
        return {"itens": data}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em GET /api/feedback: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/api/feedback/{feedback_id}/process")
async def process_feedback(feedback_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = mark_feedback_processed(db, feedback_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Feedback não encontrado")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em POST /api/feedback/{{id}}/process: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/admin/processar-pendentes")
async def processar_artigos_pendentes(
    background_tasks: BackgroundTasks,
    limite: int = 50,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para processar artigos pendentes manualmente.
    """
    try:
        artigos_pendentes = get_artigos_pendentes(db, limite=limite)
        
        if not artigos_pendentes:
            return StatusResponse(
                status="vazio",
                message="Não há artigos pendentes para processar"
            )
        
        # Adiciona todos para processamento em background
        for artigo in artigos_pendentes:
            background_tasks.add_task(processar_artigo_background, artigo.id)
        
        create_log(db, "INFO", "api", 
                  f"Iniciado processamento de {len(artigos_pendentes)} artigos pendentes")
        
        return StatusResponse(
            status="iniciado",
            message=f"Processamento de {len(artigos_pendentes)} artigos iniciado",
            data={"total_artigos": len(artigos_pendentes)}
        )
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/processar-pendentes: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/admin/gerar-resumo/{cluster_id}")
async def gerar_resumo_cluster_endpoint(
    cluster_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para gerar/atualizar resumo de um cluster específico.
    """
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        # Adiciona tarefa em background
        background_tasks.add_task(gerar_resumo_background, cluster_id)
        
        return StatusResponse(
            status="iniciado",
            message=f"Geração de resumo do cluster {cluster_id} iniciada",
            data={"cluster_id": cluster_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/gerar-resumo/{cluster_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# Alias de rota para manter consistência com demais endpoints /api/admin
@app.post("/admin/carregar-arquivos")
@app.post("/api/admin/carregar-arquivos")
async def carregar_arquivos_endpoint(
    background_tasks: BackgroundTasks,
    diretorio: str = "../pdfs",
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para carregar notícias a partir de arquivos PDFs e JSONs.
    """
    try:
        # Resolve caminho absoluto com base no PROJECT_ROOT para alinhar com o CLI (../pdfs)
        from pathlib import Path
        dir_path = Path(diretorio)
        if not dir_path.is_absolute():
            dir_path = (PROJECT_ROOT / dir_path).resolve()

        # Adiciona tarefa em background, garantindo o mesmo efeito de --direct
        background_tasks.add_task(carregar_arquivos_background, str(dir_path))

        create_log(db, "INFO", "api", 
                  f"Iniciado carregamento de arquivos do diretório: {dir_path}")

        return StatusResponse(
            status="iniciado",
            message=f"Carregamento de arquivos iniciado",
            data={"diretorio": str(dir_path)}
        )
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/carregar-arquivos: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# Variáveis globais para tracking de progresso
upload_progress = {}
processing_state = {}

@app.post("/api/admin/upload-file")
async def upload_file_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para upload de arquivos PDF ou JSON.
    """
    try:
        # Verifica tipo de arquivo
        if not file.filename:
            raise HTTPException(status_code=400, detail="Nome do arquivo não fornecido")
        
        file_ext = file.filename.lower().split('.')[-1]
        if file_ext not in ['pdf', 'json']:
            raise HTTPException(status_code=400, detail="Apenas arquivos PDF e JSON são suportados")
        
        # Inicializa progresso para este arquivo
        file_id = f"{file.filename}_{int(time.time())}"
        upload_progress[file_id] = {
            "filename": file.filename,
            "status": "uploading",
            "current_article": 0,
            "total_articles": 0,
            "message": "Iniciando upload...",
            "start_time": time.time()
        }
        
        # Cria diretório temporário se não existir
        temp_dir = PROJECT_ROOT / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        
        # Salva arquivo temporariamente
        file_path = temp_dir / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Atualiza status para processamento
        upload_progress[file_id]["status"] = "processing"
        upload_progress[file_id]["message"] = "Processando arquivo..."
        
        # Processa arquivo com tracking de progresso
        artigos_processados = await processar_arquivo_upload_com_progresso(file_path, file_ext, db, file_id)
        
        # Remove arquivo temporário
        file_path.unlink()
        
        # Finaliza progresso
        upload_progress[file_id]["status"] = "completed"
        upload_progress[file_id]["message"] = "Processamento concluído"
        upload_progress[file_id]["current_article"] = artigos_processados
        upload_progress[file_id]["total_articles"] = artigos_processados
        
        create_log(db, "INFO", "api", 
                  f"Arquivo {file.filename} processado com sucesso. {artigos_processados} artigos criados.")
        
        return StatusResponse(
            status="sucesso",
            message=f"Arquivo {file.filename} processado com sucesso",
            data={"artigos_processados": artigos_processados, "file_id": file_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        if file_id in upload_progress:
            upload_progress[file_id]["status"] = "error"
            upload_progress[file_id]["message"] = f"Erro: {str(e)}"
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/upload-file: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/api/admin/process-articles")
async def process_articles_endpoint(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para processar artigos pendentes (equivalente ao process_articles.py).
    """
    try:
        # Inicializa estado de processamento global
        global processing_state
        try:
            total_pendentes = len(get_artigos_pendentes(db, limite=100000))
        except Exception:
            total_pendentes = 0
        processing_state = {
            "status": "processing",
            "total": total_pendentes,
            "processed": 0,
            "start_time": time.time(),
            "message": "Iniciando processamento de artigos pendentes..."
        }

        # Adiciona tarefa em background usando o script oficial process_articles.py
        background_tasks.add_task(processar_artigos_via_script)
        
        create_log(db, "INFO", "api", "Iniciado processamento de artigos pendentes")
        
        return StatusResponse(
            status="iniciado",
            message="Processamento de artigos iniciado",
            data={}
        )
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/process-articles: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/admin/upload-progress/{file_id}")
async def upload_progress_endpoint(file_id: str) -> Dict[str, Any]:
    """
    Endpoint para verificar progresso do upload de arquivo.
    """
    try:
        if file_id not in upload_progress:
            raise HTTPException(status_code=404, detail="File ID não encontrado")
        
        progress = upload_progress[file_id]
        
        # Calcula tempo decorrido
        elapsed_time = time.time() - progress.get("start_time", time.time())
        
        return {
            "file_id": file_id,
            "filename": progress.get("filename", ""),
            "status": progress.get("status", "unknown"),
            "current_article": progress.get("current_article", 0),
            "total_articles": progress.get("total_articles", 0),
            "message": progress.get("message", ""),
            "elapsed_time": round(elapsed_time, 2)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/admin/processing-status")
async def processing_status_endpoint(db: Session = Depends(get_db)) -> StatusResponse:
    """
    Endpoint para verificar status do processamento.
    """
    try:
        global processing_state
        # Se não houver state, inferimos via pendentes (compatibilidade)
        if 'processing_state' not in globals() or not processing_state:
            artigos_pendentes = get_artigos_pendentes(db, limite=1)
            if not artigos_pendentes:
                return StatusResponse(status="completed", message="Não há artigos pendentes para processar", data={})
            return StatusResponse(status="processing", message="Processando...", data={})

        # Calcula métricas
        elapsed = time.time() - processing_state.get("start_time", time.time())
        processed = processing_state.get("processed", 0)
        total = processing_state.get("total", 0)
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = max(total - processed, 0)
        eta_seconds = (remaining / rate) if rate > 0 else None

        data = {
            "processed": processed,
            "total": total,
            "elapsed_seconds": round(elapsed, 2),
            "eta_seconds": round(eta_seconds, 2) if eta_seconds is not None else None
        }
        return StatusResponse(status=processing_state.get("status", "processing"), message=processing_state.get("message", "Processando..."), data=data)
    
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /admin/processing-status: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# FUNÇÕES DE BACKGROUND TASKS
# ==============================================================================

async def processar_artigo_background(id_artigo: int):
    """Processa um artigo em background."""
    try:
        from .database import SessionLocal
    except ImportError:
        from database import SessionLocal
    
    db = SessionLocal()
    try:
        # Configura cliente Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            create_log(db, "ERROR", "background", "GEMINI_API_KEY não configurada")
            return
        
        genai.configure(api_key=api_key)
        client = genai
        
        # Processa o artigo
        sucesso = processar_artigo_pipeline(db, id_artigo, client)
        
        if sucesso:
            create_log(db, "INFO", "background", 
                      f"Artigo {id_artigo} processado com sucesso")
        else:
            create_log(db, "ERROR", "background", 
                      f"Falha no processamento do artigo {id_artigo}")
    
    except Exception as e:
        create_log(db, "ERROR", "background", 
                  f"Erro no processamento background do artigo {id_artigo}: {e}")
    finally:
        db.close()


async def gerar_resumo_background(cluster_id: int):
    """Gera resumo de um cluster em background."""
    try:
        from .database import SessionLocal
    except ImportError:
        from database import SessionLocal
    
    db = SessionLocal()
    try:
        # Configura cliente Gemini
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            create_log(db, "ERROR", "background", "GEMINI_API_KEY não configurada")
            return
        
        genai.configure(api_key=api_key)
        client = genai
        
        # Gera o resumo
        sucesso = gerar_resumo_cluster(db, cluster_id, client)
        
        if sucesso:
            create_log(db, "INFO", "background", 
                      f"Resumo do cluster {cluster_id} gerado com sucesso")
        else:
            create_log(db, "ERROR", "background", 
                      f"Falha na geração do resumo do cluster {cluster_id}")
    
    except Exception as e:
        create_log(db, "ERROR", "background", 
                  f"Erro na geração de resumo background do cluster {cluster_id}: {e}")
    finally:
        db.close()


async def carregar_arquivos_background(diretorio: str):
    """Carrega arquivos em background."""
    try:
        from .database import SessionLocal
        from .collectors.file_loader import FileLoader
    except ImportError:
        # Fallback para import absoluto quando executado diretamente
        from database import SessionLocal
        from collectors.file_loader import FileLoader
    
    db = SessionLocal()
    try:
        # Alinha ambiente e cliente Gemini como no load_news.py
        import os
        from pathlib import Path
        try:
            from dotenv import load_dotenv  # type: ignore
            backend_dir = Path(__file__).resolve().parent
            env_path = backend_dir / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
        except Exception:
            pass

        client = None
        try:
            from google import genai as genai_new  # type: ignore
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                client = genai_new.Client(api_key=api_key)
        except Exception:
            client = None

        # Cria instância do carregador com cliente (quando disponível)
        loader = FileLoader(files_directory=diretorio, client=client)
        
        # Processa arquivos diretamente no banco
        stats = loader.processar_diretorio(usar_api=False)
        
        create_log(db, "INFO", "background", 
                  f"Carregamento de arquivos finalizado",
                  {"arquivos_processados": stats["arquivos_processados"], 
                   "artigos_criados": stats["artigos_criados"]})
        
    except Exception as e:
        create_log(db, "ERROR", "background", 
                  f"Erro no carregamento de arquivos: {e}")
    finally:
        db.close()


async def processar_arquivo_upload_com_progresso(file_path: Path, file_ext: str, db: Session, file_id: str) -> int:
    """
    Processa arquivo de upload com progresso em tempo real.
    """
    try:
        from backend.collectors.file_loader import FileLoader
        # Carrega .env do backend (alinha com load_news.py)
        try:
            from dotenv import load_dotenv  # type: ignore
            backend_dir = Path(__file__).resolve().parent
            env_path = backend_dir / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
        except Exception:
            pass
        
        if file_ext.lower() == 'json':
            # Processa JSON
            upload_progress[file_id]["status"] = "processing"
            upload_progress[file_id]["message"] = "Processando conteúdo JSON..."
            
            # Carrega todos os artigos do JSON
            # Instancia o FileLoader apontando para a pasta do arquivo enviado
            loader = FileLoader(files_directory=str(file_path.parent))
            artigos = loader.processar_json_dump(file_path)
            total_artigos = len(artigos)
            upload_progress[file_id]["total_articles"] = total_artigos
            
            upload_progress[file_id]["status"] = "database"
            upload_progress[file_id]["message"] = "Salvando artigos no banco de dados..."
            
            # Processa cada artigo individualmente
            for i, artigo in enumerate(artigos, 1):
                upload_progress[file_id]["current_article"] = i
                upload_progress[file_id]["message"] = f"Enviando artigo {i}/{total_artigos}..."
                
                # Envia artigo para o banco
                print(f"🔍 DEBUG: Enviando artigo {i}/{total_artigos} para o banco...")
                sucesso = loader.enviar_artigo_direto_db(artigo)
                if not sucesso:
                    print(f"🔍 DEBUG: ERRO ao enviar artigo {i} para o banco")
                else:
                    print(f"🔍 DEBUG: Artigo {i} enviado com sucesso para o banco")
                
                # Pequena pausa para efeito visual
                await asyncio.sleep(0.02)
            
            upload_progress[file_id]["status"] = "completed"
            upload_progress[file_id]["message"] = f"SUCESSO: {total_artigos}/{total_artigos} artigos processados"
            return total_artigos
            
        elif file_ext.lower() == 'pdf':
            # Processa PDF
            upload_progress[file_id]["status"] = "processing"
            upload_progress[file_id]["message"] = "Processando conteúdo PDF..."
            
            # Tenta processar com Gemini primeiro
            try:
                # Inicializa cliente Gemini (novo SDK) como no load_news
                client = None
                try:
                    from google import genai as genai_new
                    api_key = os.getenv("GEMINI_API_KEY")
                    if api_key:
                        client = genai_new.Client(api_key=api_key)
                except Exception:
                    client = None

                # Instancia o FileLoader apontando para a pasta do arquivo enviado
                loader = FileLoader(files_directory=str(file_path.parent), client=client)
                artigos = loader.processar_pdf(file_path)
                total_artigos = len(artigos)
                upload_progress[file_id]["total_articles"] = total_artigos
                
                upload_progress[file_id]["status"] = "database"
                upload_progress[file_id]["message"] = "Salvando artigos no banco de dados..."
                
                # Processa cada artigo individualmente
                for i, artigo in enumerate(artigos, 1):
                    upload_progress[file_id]["current_article"] = i
                    upload_progress[file_id]["message"] = f"Enviando artigo {i}/{total_artigos}..."
                    
                    # Envia artigo para o banco
                    loader.enviar_artigo_direto_db(artigo)
                    
                    # Pequena pausa para efeito visual
                    await asyncio.sleep(0.02)
                
                upload_progress[file_id]["status"] = "completed"
                upload_progress[file_id]["message"] = f"SUCESSO: {total_artigos}/{total_artigos} artigos processados"
                return total_artigos
                
            except Exception as e:
                # Fallback para processamento básico
                upload_progress[file_id]["message"] = f"Fallback: processando PDF com método básico..."
                
                # Instancia o FileLoader apontando para a pasta do arquivo enviado
                loader = FileLoader(files_directory=str(file_path.parent))
                artigos = loader.processar_pdf(file_path)
                total_artigos = len(artigos)
                upload_progress[file_id]["total_articles"] = total_artigos
                
                upload_progress[file_id]["status"] = "database"
                upload_progress[file_id]["message"] = "Salvando artigos no banco de dados..."
                
                # Processa cada artigo individualmente
                for i, artigo in enumerate(artigos, 1):
                    upload_progress[file_id]["current_article"] = i
                    upload_progress[file_id]["message"] = f"Enviando artigo {i}/{total_artigos}..."
                    
                    # Envia artigo para o banco
                    loader.enviar_artigo_direto_db(artigo)
                    
                    # Pequena pausa para efeito visual
                    await asyncio.sleep(0.02)
                
                upload_progress[file_id]["status"] = "completed"
                upload_progress[file_id]["message"] = f"SUCESSO: {total_artigos}/{total_artigos} artigos processados (fallback)"
                return total_artigos
        
        else:
            upload_progress[file_id]["status"] = "error"
            upload_progress[file_id]["message"] = f"Formato de arquivo não suportado: {file_ext}"
            return 0
            
    except Exception as e:
        upload_progress[file_id]["status"] = "error"
        upload_progress[file_id]["message"] = f"Erro ao processar arquivo: {str(e)}"
        return 0


async def agrupar_noticias_original(db: Session, artigos_novos: List) -> bool:
    """
    Realiza agrupamento original (do process_articles.py) para artigos novos.
    Usado quando não há clusters existentes no dia.
    """
    try:
        from backend.prompts import PROMPT_AGRUPAMENTO_V1
        from backend.crud import create_cluster, associate_artigo_to_cluster, create_log
        from backend.utils import get_gemini_model
        import json
        
        if not artigos_novos:
            create_log(db, "INFO", "original_clustering", "Nenhum artigo para agrupar")
            return True
        
        create_log(db, "INFO", "original_clustering", f"Iniciando agrupamento original para {len(artigos_novos)} artigos")
        print(f"🔍 DEBUG: Iniciando agrupamento original para {len(artigos_novos)} artigos")
        
        # Prepara dados para o prompt de agrupamento original
        noticias_para_agrupar = []
        for i, artigo in enumerate(artigos_novos):
            noticia_data = {
                "id": i,
                "titulo": artigo.titulo_extraido or "Sem título",
                "jornal": artigo.jornal or "Fonte desconhecida",
                "trecho": (artigo.texto_processado[:300] + "...") if len(artigo.texto_processado or "") > 300 else (artigo.texto_processado or "")
            }
            noticias_para_agrupar.append(noticia_data)
        
        # Mapeamento de ID para artigo original
        mapa_id_para_artigo = {i: artigo for i, artigo in enumerate(artigos_novos)}
        
        # Monta o prompt completo
        prompt_completo = PROMPT_AGRUPAMENTO_V1 + "\n\nNOTÍCIAS PARA AGRUPAR:\n" + json.dumps(noticias_para_agrupar, indent=2, ensure_ascii=False)
        
        create_log(db, "INFO", "original_clustering", f"Enviando {len(noticias_para_agrupar)} notícias para agrupamento via prompt...")
        print(f"🔍 DEBUG: Enviando {len(noticias_para_agrupar)} notícias para agrupamento original via prompt...")
        
        # Chama a API para agrupamento
        client = get_gemini_model()
        response = client.generate_content(
            prompt_completo,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 4096
            }
        )
        
        if not response.text:
            create_log(db, "ERROR", "original_clustering", "API retornou resposta vazia para agrupamento")
            return False
        
        # Extrai JSON da resposta
        try:
            # Remove possíveis marcadores de código
            texto_limpo = response.text.strip()
            if "```json" in texto_limpo:
                texto_limpo = texto_limpo.split("```json")[1].split("```")[0].strip()
            elif "```" in texto_limpo:
                texto_limpo = texto_limpo.split("```")[1].strip()
            
            grupos_brutos = json.loads(texto_limpo)
        except Exception as e:
            create_log(db, "ERROR", "original_clustering", f"Erro ao extrair JSON da resposta: {e}")
            return False
        
        if not isinstance(grupos_brutos, list):
            create_log(db, "ERROR", "original_clustering", "Resposta de agrupamento inválida")
            return False
        
        create_log(db, "INFO", "original_clustering", f"SUCESSO: {len(grupos_brutos)} grupos criados pelo prompt")
        
        # Processa cada grupo e cria clusters
        clusters_criados = 0
        artigos_agrupados = 0
        
        for i, grupo_data in enumerate(grupos_brutos, 1):
            try:
                tema_principal = grupo_data.get("tema_principal", f"Grupo {i}")
                ids_originais = grupo_data.get("ids_originais", [])
                
                if not ids_originais:
                    continue
                
                # Coleta artigos do grupo
                artigos_grupo = []
                for id_original in ids_originais:
                    artigo = mapa_id_para_artigo.get(id_original)
                    if artigo:
                        artigos_grupo.append(artigo)
                
                if not artigos_grupo:
                    continue
                
                # Determina prioridade do grupo (maior prioridade vence)
                prioridades = [artigo.prioridade for artigo in artigos_grupo if artigo.prioridade]
                prioridade_grupo = "P3_MONITORAMENTO"
                if "P1_CRITICO" in prioridades:
                    prioridade_grupo = "P1_CRITICO"
                elif "P2_ESTRATEGICO" in prioridades:
                    prioridade_grupo = "P2_ESTRATEGICO"
                
                # Determina tag do grupo (mais frequente) com fallback válido
                tags = [artigo.tag for artigo in artigos_grupo if artigo.tag]
                if tags:
                    from collections import Counter
                    tag_counts = Counter(tags)
                    tag_grupo = tag_counts.most_common(1)[0][0]
                else:
                    # Se não houver tags, classifica como IRRELEVANTE para evitar criação de tags novas
                    tag_grupo = 'IRRELEVANTE'
                
                # Calcula embedding médio do grupo
                embeddings = []
                for artigo in artigos_grupo:
                    if artigo.embedding:
                        embeddings.append(artigo.embedding)
                
                embedding_medio = None
                if embeddings:
                    import numpy as np
                    # Converte bytes para numpy array
                    embeddings_np = []
                    for emb in embeddings:
                        if isinstance(emb, bytes):
                            embeddings_np.append(np.frombuffer(emb, dtype=np.float32))
                        else:
                            embeddings_np.append(emb)
                    
                    if embeddings_np:
                        embedding_medio = np.mean(embeddings_np, axis=0).tobytes()
                
                # Cria cluster
                from backend.models import ClusterEventoCreate
                cluster_data = ClusterEventoCreate(
                    titulo_cluster=tema_principal,
                    resumo_cluster=None,  # Será preenchido posteriormente
                    tag=tag_grupo,
                    prioridade=prioridade_grupo,
                    embedding_medio=embedding_medio
                )
                
                cluster = create_cluster(db, cluster_data)
                clusters_criados += 1
                
                # Associa artigos ao cluster
                for artigo in artigos_grupo:
                    if associate_artigo_to_cluster(db, artigo.id, cluster.id):
                        artigos_agrupados += 1
                
                create_log(db, "INFO", "original_clustering", 
                          f"CLUSTER {i}: '{tema_principal}' - {len(artigos_grupo)} artigos - {prioridade_grupo}")
                
            except Exception as e:
                create_log(db, "ERROR", "original_clustering", f"Falha ao processar grupo {i}: {e}")
                continue
        
        create_log(db, "INFO", "original_clustering", 
                  f"AGRUPAMENTO ORIGINAL CONCLUIDO: {clusters_criados} clusters criados, {artigos_agrupados} artigos agrupados")
        return True
        
    except Exception as e:
        create_log(db, "ERROR", "original_clustering", f"Erro no agrupamento original: {e}")
        return False


async def agrupar_noticias_incremental(db: Session) -> bool:
    """
    Realiza agrupamento incremental de notícias.
    Pega artigos processados hoje que não foram associados a clusters
    e os classifica em relação aos clusters existentes do mesmo dia.
    """
    try:
        from backend.prompts import PROMPT_AGRUPAMENTO_INCREMENTAL_V2
        from backend.crud import (
            get_artigos_processados_hoje, get_clusters_existentes_hoje,
            get_artigos_by_cluster, associate_artigo_to_existing_cluster,
            create_cluster_for_artigo, create_log
        )
        from backend.utils import get_gemini_model
        import json
        
        # Busca artigos processados hoje que não foram associados a clusters
        artigos_novos = get_artigos_processados_hoje(db)
        
        if not artigos_novos:
            create_log(db, "INFO", "incremental_clustering", "Nenhum artigo novo para agrupamento incremental")
            return True
        
        # Busca clusters existentes de hoje
        clusters_existentes = get_clusters_existentes_hoje(db)
        
        create_log(db, "INFO", "incremental_clustering", 
                  f"Iniciando agrupamento incremental: {len(artigos_novos)} artigos novos, {len(clusters_existentes)} clusters existentes")
        
        print(f"🔍 DEBUG: {len(artigos_novos)} artigos novos encontrados")
        print(f"🔍 DEBUG: {len(clusters_existentes)} clusters existentes encontrados")
        
        # Debug: mostra alguns exemplos
        if artigos_novos:
            print(f"🔍 DEBUG: Exemplos de artigos novos:")
            for i, artigo in enumerate(artigos_novos[:3], 1):
                titulo = artigo.titulo_extraido or artigo.texto_bruto[:50]
                print(f"   {i}. ID {artigo.id}: {titulo}...")
        
        if clusters_existentes:
            print(f"🔍 DEBUG: Exemplos de clusters existentes:")
            for i, cluster in enumerate(clusters_existentes[:3], 1):
                print(f"   {i}. ID {cluster.id}: {cluster.titulo_cluster}")
        
        # Se não há clusters existentes, usa o algoritmo original de agrupamento
        if not clusters_existentes:
            create_log(db, "INFO", "incremental_clustering", "Nenhum cluster existente encontrado, usando algoritmo original de agrupamento")
            
            # Usa o algoritmo original do process_articles.py
            sucesso_agrupamento_original = await agrupar_noticias_original(db, artigos_novos)
            
            if sucesso_agrupamento_original:
                create_log(db, "INFO", "incremental_clustering", f"Agrupamento original concluído para {len(artigos_novos)} artigos")
                return True
            else:
                create_log(db, "ERROR", "incremental_clustering", "Falha no agrupamento original")
                return False
        
                # Prepara dados para o prompt (apenas títulos e IDs)
        print(f"🔍 DEBUG: Preparando dados para o prompt LLM...")
        
        novas_noticias = []
        for artigo in artigos_novos:
            noticia_data = {
                "id": artigo.id,  # ID real do banco
                "titulo": artigo.titulo_extraido or "Sem título"
            }
            novas_noticias.append(noticia_data)

        clusters_existentes_data = []
        for cluster in clusters_existentes:
            artigos_cluster = get_artigos_by_cluster(db, cluster.id)
            titulos = [
                a.titulo_extraido or (a.texto_processado[:80] + "...") if (a.texto_processado or "") else "Sem título"
                for a in artigos_cluster
            ]
            # Limita quantidade de títulos para evitar payload excessivo
            titulos = titulos[:30]
            cluster_data = {
                "cluster_id": cluster.id,
                "tema_principal": cluster.titulo_cluster,
                "titulos_internos": titulos
            }
            clusters_existentes_data.append(cluster_data)
        
        print(f"🔍 DEBUG: {len(novas_noticias)} notícias preparadas para o prompt")
        print(f"🔍 DEBUG: {len(clusters_existentes_data)} clusters preparados para o prompt")
        
        # Mapeamento de ID para artigo original
        mapa_id_para_artigo = {artigo.id: artigo for artigo in artigos_novos}
        
        # Monta o prompt completo
        print(f"🔍 DEBUG: Montando prompt completo para o LLM...")
        
        prompt_completo = PROMPT_AGRUPAMENTO_INCREMENTAL_V2.format(
            NOVAS_NOTICIAS=json.dumps(novas_noticias, indent=2, ensure_ascii=False),
            CLUSTERS_EXISTENTES=json.dumps(clusters_existentes_data, indent=2, ensure_ascii=False)
        )
        
        print(f"🔍 DEBUG: Prompt montado com sucesso")
        print(f"🔍 DEBUG: Tamanho do prompt: {len(prompt_completo)} caracteres")
        
        create_log(db, "INFO", "incremental_clustering", 
                  f"Enviando {len(novas_noticias)} notícias novas para análise incremental")
        
        # Chama a API para agrupamento incremental
        print(f"🔍 DEBUG: Chamando API Gemini para agrupamento incremental...")
        
        client = get_gemini_model()
        response = client.generate_content(
            prompt_completo,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_output_tokens': 4096
            }
        )
        
        print(f"🔍 DEBUG: Resposta da API Gemini recebida")
        print(f"🔍 DEBUG: Tamanho da resposta: {len(response.text) if response.text else 0} caracteres")
        
        if not response.text:
            create_log(db, "ERROR", "incremental_clustering", "API retornou resposta vazia para agrupamento incremental")
            return False
        
        # Extrai JSON da resposta
        try:
            # Remove possíveis marcadores de código
            texto_limpo = response.text.strip()
            if "```json" in texto_limpo:
                texto_limpo = texto_limpo.split("```json")[1].split("```")[0].strip()
            elif "```" in texto_limpo:
                texto_limpo = texto_limpo.split("```")[1].strip()
            
            classificacoes = json.loads(texto_limpo)
        except Exception as e:
            create_log(db, "ERROR", "incremental_clustering", f"Erro ao extrair JSON da resposta: {e}")
            return False
        
        if not isinstance(classificacoes, list):
            create_log(db, "ERROR", "incremental_clustering", "Resposta de agrupamento incremental inválida")
            return False
        
        # Processa cada classificação
        anexacoes = 0
        novos_clusters = 0
        
        for classificacao in classificacoes:
            try:
                tipo = classificacao.get("tipo")
                noticia_id = classificacao.get("noticia_id")
                
                if noticia_id not in mapa_id_para_artigo:
                    continue
                
                artigo = mapa_id_para_artigo[noticia_id]
                
                if tipo == "anexar":
                    cluster_id_existente = classificacao.get("cluster_id_existente")
                    
                    # Verifica se o cluster existe
                    cluster_existente = next((c for c in clusters_existentes if c.id == cluster_id_existente), None)
                    if cluster_existente:
                        if associate_artigo_to_existing_cluster(db, artigo.id, cluster_existente.id):
                            anexacoes += 1
                            create_log(db, "INFO", "incremental_clustering", 
                                     f"Artigo {artigo.id} anexado ao cluster {cluster_existente.id}")
                
                elif tipo == "novo_cluster":
                    tema_principal = classificacao.get("tema_principal", f"Cluster para artigo {artigo.id}")
                    
                    novo_cluster = create_cluster_for_artigo(db, artigo, tema_principal)
                    novos_clusters += 1
                    create_log(db, "INFO", "incremental_clustering", 
                             f"Novo cluster {novo_cluster.id} criado para artigo {artigo.id}")
                
            except Exception as e:
                create_log(db, "ERROR", "incremental_clustering", f"Erro ao processar classificação: {e}")
                continue
        
        create_log(db, "INFO", "incremental_clustering", 
                  f"Agrupamento incremental concluído: {anexacoes} anexações, {novos_clusters} novos clusters")
        return True
        
    except Exception as e:
        create_log(db, "ERROR", "incremental_clustering", f"Erro no agrupamento incremental: {e}")
        return False


async def processar_artigos_background(db: Session):
    """
    Processa artigos pendentes em background com agrupamento incremental.
    Equivalente ao process_articles.py mas com clustering incremental.
    """
    try:
        # Importa funções necessárias
        from backend.processing import processar_artigo_pipeline, gerar_resumo_cluster
        from backend.crud import get_artigos_pendentes, update_artigo_status, get_clusters_existentes_hoje
        try:
            from .utils import get_gemini_model
        except ImportError:
            from utils import get_gemini_model
        
        # ETAPA 1: Processa artigos pendentes em lotes
        print(f"🔍 DEBUG: Iniciando processamento de artigos pendentes...")
        
        # Processa em lotes de 10 artigos por vez
        lote_size = 10
        total_processados = 0
        
        while True:
            artigos_pendentes = get_artigos_pendentes(db, limite=lote_size)
            
            if not artigos_pendentes:
                if total_processados == 0:
                    create_log(db, "INFO", "background", "Nenhum artigo pendente para processar")
                    print(f"🔍 DEBUG: Nenhum artigo pendente encontrado")
                else:
                    create_log(db, "INFO", "background", f"ETAPA 1 concluída: {total_processados} artigos processados")
                    print(f"🔍 DEBUG: ETAPA 1 concluída - {total_processados} artigos processados")
                break
            
            if total_processados == 0:
                create_log(db, "INFO", "background", f"ETAPA 1: Iniciando processamento em lotes de {lote_size}")
                print(f"🔍 DEBUG: Processando em lotes de {lote_size} artigos")
            
            print(f"🔍 DEBUG: Processando lote de {len(artigos_pendentes)} artigos...")
            # Atualiza total se não setado
            try:
                if processing_state.get("total", 0) < total_processados + len(artigos_pendentes):
                    processing_state["total"] = total_processados + len(artigos_pendentes)
            except Exception:
                pass
            
            # Processa cada artigo do lote
            for artigo in artigos_pendentes:
                try:
                    # Atualiza status para processando
                    update_artigo_status(db, artigo.id, "processando")
                    
                    # Processa artigo
                    client = get_gemini_model()
                    sucesso = processar_artigo_pipeline(db, artigo.id, client)
                    
                    if sucesso:
                        update_artigo_status(db, artigo.id, "processado")
                        total_processados += 1
                        print(f"🔍 DEBUG: Artigo {artigo.id} processado com sucesso ({total_processados} total)")
                        # Atualiza progresso global
                        try:
                            processing_state["processed"] = total_processados
                            processing_state["message"] = f"Processando artigos... {total_processados}/{processing_state.get('total', 0)}"
                        except Exception:
                            pass
                    else:
                        update_artigo_status(db, artigo.id, "erro")
                        create_log(db, "ERROR", "background", f"Erro ao processar artigo {artigo.id}")
                        print(f"🔍 DEBUG: Erro ao processar artigo {artigo.id}")
                        
                except Exception as e:
                    # Garante rollback e marca erro com segurança
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    try:
                        update_artigo_status(db, artigo.id, "erro")
                    except Exception:
                        pass
                    try:
                        create_log(db, "ERROR", "background", f"Erro ao processar artigo {artigo.id}: {e}")
                    except Exception:
                        pass
                    print(f"🔍 DEBUG: Exceção ao processar artigo {artigo.id}: {e}")
            
            # Commit do lote
            db.commit()
            print(f"🔍 DEBUG: Lote processado e commitado")
        
        # ETAPA 2: Agrupamento incremental
        print(f"🔍 DEBUG: Iniciando ETAPA 2 - Agrupamento incremental")
        create_log(db, "INFO", "background", "ETAPA 2: Iniciando agrupamento incremental")
        
        sucesso_agrupamento = await agrupar_noticias_incremental(db)
        
        if sucesso_agrupamento:
            create_log(db, "INFO", "background", "ETAPA 2 concluída: Agrupamento incremental realizado com sucesso")
            print(f"🔍 DEBUG: ETAPA 2 concluída com sucesso")
        else:
            create_log(db, "ERROR", "background", "ETAPA 2 falhou: Erro no agrupamento incremental")
            print(f"🔍 DEBUG: ETAPA 2 falhou")

        # ETAPA 3: Geração de resumos para clusters do dia sem resumo
        try:
            client = get_gemini_model()
            clusters_hoje = get_clusters_existentes_hoje(db)
            gerados = 0
            for c in clusters_hoje:
                if not getattr(c, 'resumo_cluster', None):
                    ok = gerar_resumo_cluster(db, c.id, client)
                    if ok:
                        gerados += 1
            create_log(db, "INFO", "background", f"ETAPA 3: Resumos gerados: {gerados}")
        except Exception as e:
            create_log(db, "ERROR", "background", f"Falha ao gerar resumos: {e}")
        
        create_log(db, "INFO", "background", "Processamento completo finalizado")
        print(f"🔍 DEBUG: Processamento completo finalizado")
        try:
            processing_state["status"] = "completed"
            processing_state["message"] = f"Processamento concluído: {total_processados} artigos"
        except Exception:
            pass
        
    except Exception as e:
        create_log(db, "ERROR", "background", f"Erro no processamento de artigos: {e}")
        print(f"🔍 DEBUG: Erro geral no processamento: {e}")
        try:
            processing_state["status"] = "error"
            processing_state["message"] = f"Erro no processamento: {e}"
        except Exception:
            pass
    finally:
        db.close()


async def processar_artigos_via_script():
    """Wrapper para executar o pipeline oficial do script process_articles.py."""
    try:
        # Atualiza mensagem de status
        try:
            processing_state["message"] = "Executando pipeline do process_articles.py..."
        except Exception:
            pass

        # Importa módulo por caminho absoluto
        import importlib.util
        script_path = PROJECT_ROOT / "process_articles.py"
        spec = importlib.util.spec_from_file_location("process_articles", script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        # Executa função principal do pipeline
        sucesso = module.processar_artigos_pendentes(limite=999)

        # Atualiza status final
        try:
            processing_state["status"] = "completed" if sucesso else "error"
            processing_state["message"] = "Processamento concluído com sucesso" if sucesso else "Falha no processamento"
        except Exception:
            pass
    except Exception as e:
        try:
            processing_state["status"] = "error"
            processing_state["message"] = f"Erro: {e}"
        except Exception:
            pass


# ==============================================================================
# ENDPOINT DE SAÚDE
# ==============================================================================

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Endpoint de verificação de saúde do sistema."""
    try:
        # Testa conexão com banco
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        
        # Verifica configurações essenciais
        gemini_key = os.getenv("GEMINI_API_KEY")
        database_url = os.getenv("DATABASE_URL")
        
        status = {
            "status": "healthy",
            "database": "connected",
            "gemini_api": "configured" if gemini_key else "not_configured",
            "database_url": "configured" if database_url else "not_configured",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return status
    
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


# ==============================================================================
# ENDPOINTS DE SETTINGS (CRUD COMPLETO)
# ==============================================================================

@app.get("/api/settings/artigos")
async def get_artigos_settings(
    page: int = 1,
    limit: int = 20,
    status: Optional[str] = None,
    id: Optional[int] = None,
    titulo: Optional[str] = None,
    jornal: Optional[str] = None,
    tag: Optional[str] = None,
    prioridade: Optional[str] = None,
    date: Optional[str] = None,  # YYYY-MM-DD
    sort_by: Optional[str] = 'created_at',
    sort_dir: Optional[str] = 'desc',
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Lista artigos para o painel de settings com filtros e ordenação."""
    try:
        offset = (page - 1) * limit
        
        # Query base
        query = db.query(ArtigoBruto)
        
        # Filtros
        if status:
            query = query.filter(ArtigoBruto.status == status)
        if id is not None:
            query = query.filter(ArtigoBruto.id == id)
        if titulo:
            from sqlalchemy import or_
            like = f"%{titulo}%"
            query = query.filter(or_(ArtigoBruto.titulo_extraido.ilike(like), ArtigoBruto.texto_bruto.ilike(like)))
        if jornal:
            query = query.filter(ArtigoBruto.jornal.ilike(f"%{jornal}%"))
        if prioridade:
            query = query.filter(ArtigoBruto.prioridade == prioridade)
        if tag:
            if tag == 'Outras':
                # Tags válidas definidas nos prompts
                try:
                    from .prompts import TAGS_SPECIAL_SITUATIONS
                except Exception:
                    from backend.prompts import TAGS_SPECIAL_SITUATIONS  # fallback
                valid_tags = list(TAGS_SPECIAL_SITUATIONS.keys())
                query = query.filter((ArtigoBruto.tag.is_(None)) | (ArtigoBruto.tag == '') | (~ArtigoBruto.tag.in_(valid_tags)))
            else:
                query = query.filter(ArtigoBruto.tag == tag)
        if date:
            # Filtra por dia específico
            from datetime import datetime, timedelta
            try:
                start = datetime.strptime(date, "%Y-%m-%d")
                end = start + timedelta(days=1)
                query = query.filter(ArtigoBruto.created_at >= start, ArtigoBruto.created_at < end)
            except Exception:
                pass
        
        # Contagem total
        total = query.count()
        
        # Ordenação
        sort_map = {
            'id': ArtigoBruto.id,
            'titulo_extraido': ArtigoBruto.titulo_extraido,
            'jornal': ArtigoBruto.jornal,
            'status': ArtigoBruto.status,
            'tag': ArtigoBruto.tag,
            'prioridade': ArtigoBruto.prioridade,
            'created_at': ArtigoBruto.created_at,
            'processed_at': ArtigoBruto.processed_at,
        }
        sort_col = sort_map.get(sort_by or 'created_at', ArtigoBruto.created_at)
        if (sort_dir or 'desc').lower() == 'asc':
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())
        
        # Paginação
        artigos = query.offset(offset).limit(limit).all()
        
        # Formata dados
        artigos_data = []
        for artigo in artigos:
            artigos_data.append({
                "id": artigo.id,
                "hash_unico": artigo.hash_unico,
                "texto_bruto": artigo.texto_bruto[:200] + "..." if len(artigo.texto_bruto) > 200 else artigo.texto_bruto,
                "url_original": artigo.url_original,
                "fonte_coleta": artigo.fonte_coleta,
                "status": artigo.status,
                "titulo_extraido": artigo.titulo_extraido,
                "jornal": artigo.jornal,
                "tag": artigo.tag,
                "prioridade": artigo.prioridade,
                "created_at": artigo.created_at.isoformat() if artigo.created_at else None,
                "processed_at": artigo.processed_at.isoformat() if artigo.processed_at else None,
                "cluster_id": artigo.cluster_id
            })
        
        return {
            "artigos": artigos_data,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao listar artigos: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/settings/artigos/{artigo_id}")
async def get_artigo_settings(artigo_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Obtém detalhes de um artigo específico."""
    try:
        artigo = get_artigo_by_id(db, artigo_id)
        if not artigo:
            raise HTTPException(status_code=404, detail="Artigo não encontrado")
        
        return {
            "id": artigo.id,
            "hash_unico": artigo.hash_unico,
            "texto_bruto": artigo.texto_bruto,
            "url_original": artigo.url_original,
            "fonte_coleta": artigo.fonte_coleta,
            "metadados": artigo.metadados,
            "status": artigo.status,
            "titulo_extraido": artigo.titulo_extraido,
            "texto_processado": artigo.texto_processado,
            "jornal": artigo.jornal,
            "autor": artigo.autor,
            "pagina": artigo.pagina,
            "data_publicacao": artigo.data_publicacao.isoformat() if artigo.data_publicacao else None,
            "categoria": artigo.categoria,
            "tag": artigo.tag,
            "prioridade": artigo.prioridade,
            "relevance_score": artigo.relevance_score,
            "relevance_reason": artigo.relevance_reason,
            "created_at": artigo.created_at.isoformat() if artigo.created_at else None,
            "processed_at": artigo.processed_at.isoformat() if artigo.processed_at else None,
            "cluster_id": artigo.cluster_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao obter artigo {artigo_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/settings/artigos/{artigo_id}")
async def update_artigo_settings(
    artigo_id: int, 
    dados: Dict[str, Any],
    db: Session = Depends(get_db)
) -> StatusResponse:
    """Atualiza um artigo."""
    try:
        artigo = get_artigo_by_id(db, artigo_id)
        if not artigo:
            raise HTTPException(status_code=404, detail="Artigo não encontrado")
        
        # Atualiza campos permitidos
        campos_permitidos = [
            'titulo_extraido', 'jornal', 'autor', 'pagina', 'categoria',
            'tag', 'prioridade', 'relevance_score', 'relevance_reason'
        ]
        
        for campo in campos_permitidos:
            if campo in dados:
                setattr(artigo, campo, dados[campo])
        
        db.commit()
        create_log(db, "INFO", "api", f"Artigo {artigo_id} atualizado via settings")
        
        return StatusResponse(
            status="success",
            message="Artigo atualizado com sucesso",
            data={"artigo_id": artigo_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao atualizar artigo {artigo_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/settings/artigos/{artigo_id}")
async def delete_artigo_settings(artigo_id: int, db: Session = Depends(get_db)) -> StatusResponse:
    """Remove um artigo."""
    try:
        artigo = get_artigo_by_id(db, artigo_id)
        if not artigo:
            raise HTTPException(status_code=404, detail="Artigo não encontrado")
        
        db.delete(artigo)
        db.commit()
        create_log(db, "INFO", "api", f"Artigo {artigo_id} removido via settings")
        
        return StatusResponse(
            status="success",
            message="Artigo removido com sucesso",
            data={"artigo_id": artigo_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao remover artigo {artigo_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/settings/clusters")
async def get_clusters_settings(
    page: int = 1,
    limit: int = 20,
    id: Optional[int] = None,
    titulo: Optional[str] = None,
    tag: Optional[str] = None,
    prioridade: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,  # YYYY-MM-DD
    total_op: Optional[str] = None,  # one of '=', '>', '>=', '<', '<='
    total_val: Optional[int] = None,
    sort_by: Optional[str] = 'created_at',
    sort_dir: Optional[str] = 'desc',
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Lista clusters para o painel de settings com filtros e ordenação."""
    try:
        offset = (page - 1) * limit
        
        # Query base
        query = db.query(ClusterEvento)
        
        # Filtros
        if id is not None:
            query = query.filter(ClusterEvento.id == id)
        if titulo:
            query = query.filter(ClusterEvento.titulo_cluster.ilike(f"%{titulo}%"))
        if prioridade:
            query = query.filter(ClusterEvento.prioridade == prioridade)
        if status:
            query = query.filter(ClusterEvento.status == status)
        if tag:
            if tag == 'Outras':
                try:
                    from .prompts import TAGS_SPECIAL_SITUATIONS
                except Exception:
                    from backend.prompts import TAGS_SPECIAL_SITUATIONS
                valid_tags = list(TAGS_SPECIAL_SITUATIONS.keys())
                query = query.filter((ClusterEvento.tag.is_(None)) | (ClusterEvento.tag == '') | (~ClusterEvento.tag.in_(valid_tags)))
            else:
                query = query.filter(ClusterEvento.tag == tag)
        if date:
            from datetime import datetime, timedelta
            try:
                start = datetime.strptime(date, "%Y-%m-%d")
                end = start + timedelta(days=1)
                query = query.filter(ClusterEvento.created_at >= start, ClusterEvento.created_at < end)
            except Exception:
                pass
        if total_val is not None and total_op in ('=','>','>=','<','<='):
            from sqlalchemy import text
            # Usa expressão simples com bind parameters seria melhor, mas aqui mapeamos manualmente
            if total_op == '=':
                query = query.filter(ClusterEvento.total_artigos == total_val)
            elif total_op == '>':
                query = query.filter(ClusterEvento.total_artigos > total_val)
            elif total_op == '>=':
                query = query.filter(ClusterEvento.total_artigos >= total_val)
            elif total_op == '<':
                query = query.filter(ClusterEvento.total_artigos < total_val)
            elif total_op == '<=':
                query = query.filter(ClusterEvento.total_artigos <= total_val)
        
        # Contagem total
        total = query.count()
        
        # Ordenação
        sort_map = {
            'id': ClusterEvento.id,
            'titulo_cluster': ClusterEvento.titulo_cluster,
            'tag': ClusterEvento.tag,
            'prioridade': ClusterEvento.prioridade,
            'status': ClusterEvento.status,
            'total_artigos': ClusterEvento.total_artigos,
            'created_at': ClusterEvento.created_at,
            'updated_at': ClusterEvento.updated_at,
        }
        sort_col = sort_map.get(sort_by or 'created_at', ClusterEvento.created_at)
        if (sort_dir or 'desc').lower() == 'asc':
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())
        
        # Paginação
        clusters = query.offset(offset).limit(limit).all()
        
        # Formata dados
        clusters_data = []
        for cluster in clusters:
            clusters_data.append({
                "id": cluster.id,
                "titulo_cluster": cluster.titulo_cluster,
                "resumo_cluster": cluster.resumo_cluster,
                "tag": cluster.tag,
                "prioridade": cluster.prioridade,
                "status": cluster.status,
                "total_artigos": cluster.total_artigos,
                "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
                "updated_at": cluster.updated_at.isoformat() if cluster.updated_at else None
            })
        
        return {
            "clusters": clusters_data,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao listar clusters: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/settings/clusters/{cluster_id}")
async def get_cluster_settings(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Obtém detalhes de um cluster específico."""
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        # Busca artigos do cluster
        artigos = get_artigos_by_cluster(db, cluster_id)
        artigos_data = []
        for artigo in artigos:
            artigos_data.append({
                "id": artigo.id,
                "titulo_extraido": artigo.titulo_extraido,
                "jornal": artigo.jornal,
                "status": artigo.status,
                "created_at": artigo.created_at.isoformat() if artigo.created_at else None
            })
        
        return {
            "id": cluster.id,
            "titulo_cluster": cluster.titulo_cluster,
            "resumo_cluster": cluster.resumo_cluster,
            "tag": cluster.tag,
            "prioridade": cluster.prioridade,
            "status": cluster.status,
            "total_artigos": cluster.total_artigos,
            "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
            "updated_at": cluster.updated_at.isoformat() if cluster.updated_at else None,
            "artigos": artigos_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao obter cluster {cluster_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/settings/clusters/{cluster_id}")
async def update_cluster_settings(
    cluster_id: int, 
    dados: Dict[str, Any],
    db: Session = Depends(get_db)
) -> StatusResponse:
    """Atualiza um cluster."""
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        # Atualiza campos permitidos
        campos_permitidos = [
            'titulo_cluster', 'resumo_cluster', 'tag', 'prioridade', 'status'
        ]
        
        for campo in campos_permitidos:
            if campo in dados:
                setattr(cluster, campo, dados[campo])
        
        db.commit()
        create_log(db, "INFO", "api", f"Cluster {cluster_id} atualizado via settings")
        
        return StatusResponse(
            status="success",
            message="Cluster atualizado com sucesso",
            data={"cluster_id": cluster_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao atualizar cluster {cluster_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/settings/clusters/{cluster_id}")
async def delete_cluster_settings(cluster_id: int, db: Session = Depends(get_db)) -> StatusResponse:
    """Remove um cluster."""
    try:
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        # Remove associações com artigos
        db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == cluster_id).update({"cluster_id": None})
        
        # Remove o cluster
        db.delete(cluster)
        db.commit()
        create_log(db, "INFO", "api", f"Cluster {cluster_id} removido via settings")
        
        return StatusResponse(
            status="success",
            message="Cluster removido com sucesso",
            data={"cluster_id": cluster_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao remover cluster {cluster_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/settings/sinteses")
async def get_sinteses_settings(
    page: int = 1, 
    limit: int = 20,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Lista sínteses executivas para o painel de settings."""
    try:
        offset = (page - 1) * limit
        
        # Query base
        query = db.query(SinteseExecutiva)
        
        # Contagem total
        total = query.count()
        
        # Paginação
        sinteses = query.order_by(SinteseExecutiva.data_sintese.desc()).offset(offset).limit(limit).all()
        
        # Formata dados
        sinteses_data = []
        for sintese in sinteses:
            sinteses_data.append({
                "id": sintese.id,
                "data_sintese": sintese.data_sintese.isoformat() if sintese.data_sintese else None,
                "texto_sintese": sintese.texto_sintese[:200] + "..." if len(sintese.texto_sintese) > 200 else sintese.texto_sintese,
                "total_noticias_coletadas": sintese.total_noticias_coletadas,
                "total_eventos_unicos": sintese.total_eventos_unicos,
                "total_analises_criticas": sintese.total_analises_criticas,
                "total_monitoramento": sintese.total_monitoramento,
                "created_at": sintese.created_at.isoformat() if sintese.created_at else None
            })
        
        return {
            "sinteses": sinteses_data,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }
        
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao listar sínteses: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/settings/sinteses/{sintese_id}")
async def get_sintese_settings(sintese_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Obtém detalhes de uma síntese específica."""
    try:
        sintese = db.query(SinteseExecutiva).filter(SinteseExecutiva.id == sintese_id).first()
        if not sintese:
            raise HTTPException(status_code=404, detail="Síntese não encontrada")
        
        return {
            "id": sintese.id,
            "data_sintese": sintese.data_sintese.isoformat() if sintese.data_sintese else None,
            "texto_sintese": sintese.texto_sintese,
            "total_noticias_coletadas": sintese.total_noticias_coletadas,
            "total_eventos_unicos": sintese.total_eventos_unicos,
            "total_analises_criticas": sintese.total_analises_criticas,
            "total_monitoramento": sintese.total_monitoramento,
            "created_at": sintese.created_at.isoformat() if sintese.created_at else None,
            "updated_at": sintese.updated_at.isoformat() if sintese.updated_at else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao obter síntese {sintese_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/settings/sinteses/{sintese_id}")
async def update_sintese_settings(
    sintese_id: int, 
    dados: Dict[str, Any],
    db: Session = Depends(get_db)
) -> StatusResponse:
    """Atualiza uma síntese."""
    try:
        sintese = db.query(SinteseExecutiva).filter(SinteseExecutiva.id == sintese_id).first()
        if not sintese:
            raise HTTPException(status_code=404, detail="Síntese não encontrada")
        
        # Atualiza campos permitidos
        if 'texto_sintese' in dados:
            sintese.texto_sintese = dados['texto_sintese']
        
        db.commit()
        create_log(db, "INFO", "api", f"Síntese {sintese_id} atualizada via settings")
        
        return StatusResponse(
            status="success",
            message="Síntese atualizada com sucesso",
            data={"sintese_id": sintese_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao atualizar síntese {sintese_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/settings/sinteses/{sintese_id}")
async def delete_sintese_settings(sintese_id: int, db: Session = Depends(get_db)) -> StatusResponse:
    """Remove uma síntese."""
    try:
        sintese = db.query(SinteseExecutiva).filter(SinteseExecutiva.id == sintese_id).first()
        if not sintese:
            raise HTTPException(status_code=404, detail="Síntese não encontrada")
        
        db.delete(sintese)
        db.commit()
        create_log(db, "INFO", "api", f"Síntese {sintese_id} removida via settings")
        
        return StatusResponse(
            status="success",
            message="Síntese removida com sucesso",
            data={"sintese_id": sintese_id}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro ao remover síntese {sintese_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# Nota: O bloco if __name__ == "__main__" foi removido pois a execução
# é controlada pelo script start_dev.py, tornando-o redundante no fluxo atual.

# ==============================================================================
# FUNÇÕES AUXILIARES
# ==============================================================================

def gerar_dados_teste() -> Dict[str, Any]:
    """
    Gera dados de teste para demonstração da funcionalidade P3.
    """
    from datetime import datetime, timedelta
    
    # Dados de teste com diferentes prioridades
    clusters_teste = [
        # P1 - Crítico
        {
            "id": 1,
            "titulo_final": "Falência da Empresa ABC - Impacto Crítico para Credores",
            "resumo_final": "A empresa ABC, com dívidas de R$ 500 milhões, declarou falência ontem. O processo afeta mais de 2.000 credores, incluindo bancos e fornecedores. A recuperação judicial foi negada pelo juiz responsável, que considerou a situação irreversível. Especialistas estimam que os credores podem perder até 80% dos valores devidos.",
            "prioridade": "P1_CRITICO",
            "tag": "Empresas Privadas",
            "tags": ["Empresas Privadas"],
            "total_artigos": 15,
            "timestamp": "2025-01-30T10:30:00"
        },
        {
            "id": 2,
            "titulo_final": "M&A Multinacional - Aquisição Hostil em Andamento",
            "resumo_final": "A multinacional XYZ iniciou processo de aquisição hostil da empresa brasileira DEF. A oferta de R$ 2 bilhões representa prêmio de 40% sobre o valor de mercado. O conselho da DEF rejeitou a proposta inicial, mas acionistas minoritários pressionam por negociação. O CADE já foi notificado sobre a operação.",
            "prioridade": "P1_CRITICO",
            "tag": "Empresas Privadas",
            "tags": ["Empresas Privadas"],
            "total_artigos": 8,
            "timestamp": "2025-01-30T09:15:00"
        },
        
        # P2 - Estratégico
        {
            "id": 3,
            "titulo_final": "Nova Regulamentação do Banco Central - Impactos Setoriais",
            "resumo_final": "O Banco Central anunciou nova regulamentação que afeta diretamente o setor financeiro. As mudanças incluem aumento do capital mínimo para bancos médios e novas regras de compliance. A implementação será gradual ao longo de 18 meses. Analistas estimam que 30% dos bancos precisarão de recapitalização.",
            "prioridade": "P2_ESTRATEGICO",
            "tag": "Economia e Tecnologia",
            "tags": ["Economia e Tecnologia"],
            "total_artigos": 12,
            "timestamp": "2025-01-30T08:45:00"
        },
        {
            "id": 4,
            "titulo_final": "Disputa Judicial - Litígio Bilionário em Andamento",
            "resumo_final": "Processo judicial envolvendo R$ 1,5 bilhão entre duas grandes empresas do setor elétrico. A disputa envolve contratos de fornecimento de energia e indenizações por quebra de acordo. O julgamento está previsto para o próximo mês no STJ.",
            "prioridade": "P2_ESTRATEGICO",
            "tag": "Judicionario",
            "tags": ["Judicionario"],
            "total_artigos": 6,
            "timestamp": "2025-01-30T07:30:00"
        },
        
        # P3 - Monitoramento (Economia e Tecnologia)
        {
            "id": 5,
            "titulo_final": "Tendências do Mercado de Criptomoedas em 2025",
            "resumo_final": "Análise das principais tendências do mercado de criptomoedas para 2025, incluindo regulamentação e adoção institucional.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Economia e Tecnologia",
            "tags": ["Economia e Tecnologia"],
            "total_artigos": 3,
            "timestamp": "2025-01-30T06:20:00"
        },
        {
            "id": 6,
            "titulo_final": "Novas Tecnologias em Fintech - Impactos no Setor Bancário",
            "resumo_final": "Revisão das inovações tecnológicas em fintechs e seus impactos na transformação digital do setor bancário tradicional.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Economia e Tecnologia",
            "tags": ["Economia e Tecnologia"],
            "total_artigos": 4,
            "timestamp": "2025-01-30T05:15:00"
        },
        {
            "id": 7,
            "titulo_final": "Mercado de Inteligência Artificial - Crescimento Sustentado",
            "resumo_final": "Análise do crescimento do mercado de IA e suas aplicações em diferentes setores da economia brasileira.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Economia e Tecnologia",
            "tags": ["Economia e Tecnologia"],
            "total_artigos": 2,
            "timestamp": "2025-01-30T04:10:00"
        },
        
        # P3 - Monitoramento (Governo e Política)
        {
            "id": 8,
            "titulo_final": "Reformas Tributárias - Discussões no Congresso",
            "resumo_final": "Acompanhamento das discussões sobre reformas tributárias em tramitação no Congresso Nacional.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Governo e Politica",
            "tags": ["Governo e Politica"],
            "total_artigos": 5,
            "timestamp": "2025-01-30T03:05:00"
        },
        {
            "id": 9,
            "titulo_final": "Políticas de Desenvolvimento Regional - Novas Iniciativas",
            "resumo_final": "Análise das novas políticas de desenvolvimento regional anunciadas pelo governo federal.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Governo e Politica",
            "tags": ["Governo e Politica"],
            "total_artigos": 3,
            "timestamp": "2025-01-30T02:00:00"
        },
        
        # P3 - Monitoramento (Judiciário)
        {
            "id": 10,
            "titulo_final": "Decisões do STF - Impactos em Direito Empresarial",
            "resumo_final": "Revisão das principais decisões do STF que afetam o direito empresarial e contratual.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Judicionario",
            "tags": ["Judicionario"],
            "total_artigos": 4,
            "timestamp": "2025-01-30T01:30:00"
        },
        {
            "id": 11,
            "titulo_final": "Jurisprudência sobre Recuperação Judicial - Tendências",
            "resumo_final": "Análise das tendências jurisprudenciais em casos de recuperação judicial nos tribunais superiores.",
            "prioridade": "P3_MONITORAMENTO",
            "tag": "Judicionario",
            "tags": ["Judicionario"],
            "total_artigos": 2,
            "timestamp": "2025-01-30T00:45:00"
        }
    ]
    
    return {
        "metricas": {
            "coletadas": 85,
            "eventos": 11,
            "p1": 2,
            "p2p3": 9
        },
        "sintese": {
            "id": 1,
            "resumo": "Hoje foram processadas 85 notícias, gerando 11 eventos únicos. Destacam-se 2 eventos críticos (P1) envolvendo falência empresarial e M&A hostil, além de 9 eventos estratégicos e de monitoramento (P2+P3) distribuídos entre regulamentação bancária, disputas judiciais e tendências setoriais.",
            "data": "2025-01-30"
        },
        "feed": clusters_teste,
        "paginacao": {
            "pagina_atual": 1,
            "tamanho_pagina": 20,
            "total_clusters": 11,
            "total_paginas": 1,
            "tem_proxima": False,
            "tem_anterior": False
        }
    }


# ==============================================================================
# ENDPOINTS PARA CHAT E ALTERAÇÕES
# ==============================================================================

@app.post("/api/chat/send")
async def send_chat_message(
    request: ChatRequest,
    db: Session = Depends(get_db)
) -> ChatResponse:
    """Envia uma mensagem para o chat de um cluster."""
    try:
        # Verifica se o cluster existe
        cluster = get_cluster_by_id(db, request.cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        # Obtém ou cria sessão de chat
        session = get_or_create_chat_session(db, request.cluster_id)
        
        # Adiciona mensagem do usuário
        add_chat_message(db, session.id, 'user', request.message)
        
        # Obtém artigos do cluster para contexto
        artigos = get_artigos_by_cluster(db, request.cluster_id)
        
        # Prepara contexto para o LLM
        fontes_originais = []
        for artigo in artigos:
            fonte = {
                'titulo': artigo.titulo_extraido or 'Título não disponível',
                'jornal': artigo.jornal or 'Fonte não identificada',
                'texto': artigo.texto_processado or artigo.texto_bruto[:500] + '...' if len(artigo.texto_bruto) > 500 else artigo.texto_bruto
            }
            fontes_originais.append(fonte)
        
        # Formata fontes para o prompt
        fontes_texto = ""
        for i, fonte in enumerate(fontes_originais, 1):
            fontes_texto += f"{i}. **{fonte['jornal']}**: {fonte['titulo']}\n"
            fontes_texto += f"   {fonte['texto'][:300]}...\n\n"
        
        # Obtém histórico de mensagens para contexto
        mensagens_anteriores = get_chat_messages_by_session(db, session.id)
        historico_conversa = ""
        
        if mensagens_anteriores:
            historico_conversa = "**CONVERSA ANTERIOR:**\n"
            for msg in mensagens_anteriores:
                role = "Usuário" if msg.role == 'user' else "Assistente"
                historico_conversa += f"{role}: {msg.content}\n"
            historico_conversa += "\n"
        
        # Prepara prompt para o LLM
        try:
            from .prompts import PROMPT_CHAT_CLUSTER_V1
        except ImportError:
            # Fallback para import absoluto quando executado diretamente
            from prompts import PROMPT_CHAT_CLUSTER_V1
        prompt = PROMPT_CHAT_CLUSTER_V1.format(
            TITULO_EVENTO=cluster.titulo_cluster,
            RESUMO_EVENTO=cluster.resumo_cluster or "Resumo não disponível",
            PRIORIDADE=cluster.prioridade,
            CATEGORIA=cluster.tag,
            TOTAL_FONTES=len(artigos),
            FONTES_ORIGINAIS=fontes_texto,
            HISTORICO_CONVERSA=historico_conversa,
            PERGUNTA_USUARIO=request.message
        )
        
        # Chama o LLM
        try:
            import google.generativeai as genai
            try:
                from .utils import get_gemini_model
            except ImportError:
                # Fallback para import absoluto quando executado diretamente
                from utils import get_gemini_model
            
            model = get_gemini_model()
            response = model.generate_content(prompt)
            resposta = response.text
        except Exception as e:
            print(f"Erro ao chamar LLM: {e}")
            resposta = "Desculpe, não foi possível processar sua pergunta no momento. Tente novamente mais tarde."
        
        # Adiciona resposta do assistente
        add_chat_message(db, session.id, 'assistant', resposta)
        
        # Atualiza timestamp da sessão
        session.updated_at = datetime.utcnow()
        db.commit()
        
        return ChatResponse(
            session_id=session.id,
            response=resposta
        )
        
    except Exception as e:
        print(f"Erro no chat: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/chat/{cluster_id}/messages")
async def get_chat_messages(
    cluster_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Obtém mensagens de uma sessão de chat."""
    try:
        session = get_chat_session_by_cluster(db, cluster_id)
        if not session:
            return {"messages": [], "session_id": None}
        
        messages = get_chat_messages_by_session(db, session.id)
        
        return {
            "session_id": session.id,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp.isoformat()
                }
                for msg in messages
            ]
        }
        
    except Exception as e:
        print(f"Erro ao obter mensagens: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/cluster/{cluster_id}/update")
async def update_cluster(
    cluster_id: int,
    request: ClusterUpdateRequest,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """Atualiza prioridade e/ou tags de um cluster."""
    try:
        # Verifica se o cluster existe
        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster não encontrado")
        
        alteracoes = []
        
        # Atualiza prioridade se fornecida
        if request.prioridade and request.prioridade != cluster.prioridade:
            if update_cluster_priority(db, cluster_id, request.prioridade, request.motivo):
                alteracoes.append(f"Prioridade alterada de {cluster.prioridade} para {request.prioridade}")
        
        # Atualiza tags se fornecidas
        if request.tags and request.tags != [cluster.tag]:
            if update_cluster_tags(db, cluster_id, request.tags, request.motivo):
                alteracoes.append(f"Tags alteradas de {cluster.tag} para {', '.join(request.tags)}")
        
        if not alteracoes:
            return StatusResponse(
                status="no_changes",
                message="Nenhuma alteração foi necessária"
            )
        
        return StatusResponse(
            status="success",
            message=f"Cluster atualizado com sucesso: {', '.join(alteracoes)}"
        )
        
    except Exception as e:
        print(f"Erro ao atualizar cluster: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/cluster/{cluster_id}/alteracoes")
async def get_cluster_alteracoes_endpoint(
    cluster_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Obtém histórico de alterações de um cluster."""
    try:
        alteracoes = get_cluster_alteracoes(db, cluster_id)
        
        return {
            "cluster_id": cluster_id,
            "alteracoes": [
                {
                    "id": alt.id,
                    "campo_alterado": alt.campo_alterado,
                    "valor_anterior": alt.valor_anterior,
                    "valor_novo": alt.valor_novo,
                    "motivo": alt.motivo,
                    "usuario": alt.usuario,
                    "timestamp": alt.timestamp.isoformat()
                }
                for alt in alteracoes
            ]
        }
        
    except Exception as e:
        print(f"Erro ao obter alterações: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/admin/alteracoes")
async def get_all_alteracoes_endpoint(
    limit: int = 100,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Obtém todas as alterações recentes (endpoint administrativo)."""
    try:
        alteracoes = get_all_cluster_alteracoes(db, limit)
        
        return {
            "total": len(alteracoes),
            "alteracoes": [
                {
                    "id": alt.id,
                    "cluster_id": alt.cluster_id,
                    "campo_alterado": alt.campo_alterado,
                    "valor_anterior": alt.valor_anterior,
                    "valor_novo": alt.valor_novo,
                    "motivo": alt.motivo,
                    "usuario": alt.usuario,
                    "timestamp": alt.timestamp.isoformat()
                }
                for alt in alteracoes
            ]
        }
        
    except Exception as e:
        print(f"Erro ao obter alterações: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS PARA CONFIGURAÇÃO DE PROMPTS
# ==============================================================================

@app.get("/api/settings/prompts")
async def get_prompts_settings() -> Dict[str, Any]:
    """
    Endpoint para obter as configurações atuais dos prompts.
    """
    try:
        # Importa o módulo prompts dinamicamente
        import importlib.util
        import sys
        
        prompts_path = Path(__file__).parent / "prompts.py"
        spec = importlib.util.spec_from_file_location("prompts", prompts_path)
        prompts_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prompts_module)
        
        # Extrai as variáveis relevantes
        try:
            prompt_agrup = prompts_module.PROMPT_AGRUPAMENTO_V1
        except Exception:
            prompt_agrup = ""
        try:
            prompt_resumo_final = prompts_module.PROMPT_RESUMO_FINAL_V3
        except Exception:
            prompt_resumo_final = ""
        try:
            prompt_decisao = prompts_module.PROMPT_DECISAO_CLUSTER_DETALHADO_V1
        except Exception:
            prompt_decisao = ""
        try:
            prompt_chat_cluster = prompts_module.PROMPT_CHAT_CLUSTER_V1
        except Exception:
            prompt_chat_cluster = ""

        prompts_config = {
            "TAGS_SPECIAL_SITUATIONS": prompts_module.TAGS_SPECIAL_SITUATIONS,
            "LISTA_RELEVANCIA_HIERARQUICA": prompts_module.LISTA_RELEVANCIA_HIERARQUICA,
            "PROMPT_EXTRACAO_PERMISSIVO_V8": getattr(prompts_module, "PROMPT_EXTRACAO_PERMISSIVO_V8", ""),
            "PROMPT_AGRUPAMENTO_V1": prompt_agrup,
            "PROMPT_RESUMO_CRITICO_V1": getattr(prompts_module, "PROMPT_RESUMO_CRITICO_V1", ""),
            "PROMPT_RADAR_MONITORAMENTO_V1": getattr(prompts_module, "PROMPT_RADAR_MONITORAMENTO_V1", ""),
            "PROMPT_RESUMO_FINAL_V3": prompt_resumo_final,
            "PROMPT_DECISAO_CLUSTER_DETALHADO_V1": prompt_decisao,
            "PROMPT_CHAT_CLUSTER_V1": prompt_chat_cluster
        }
        
        return {
            "success": True,
            "data": prompts_config
        }
    except Exception as e:
        print(f"❌ Erro ao obter configurações de prompts: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")


@app.put("/api/settings/prompts")
async def update_prompts_settings(
    dados: Dict[str, Any]
) -> StatusResponse:
    """
    Endpoint para atualizar as configurações dos prompts.
    """
    try:
        prompts_path = Path(__file__).parent / "prompts.py"
        
        # Lê o arquivo atual
        with open(prompts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Atualiza as variáveis específicas
        if "TAGS_SPECIAL_SITUATIONS" in dados and isinstance(dados["TAGS_SPECIAL_SITUATIONS"], dict):
            # Converte o dicionário para string Python
            import json
            tags_str = json.dumps(dados["TAGS_SPECIAL_SITUATIONS"], indent=4, ensure_ascii=False)
            # Mantemos aspas duplas para preservar JSON válido dentro do Python
            
            # Substitui a variável no arquivo
            import re
            pattern = r'TAGS_SPECIAL_SITUATIONS\s*=\s*\{.*?\n\}'
            replacement = f'TAGS_SPECIAL_SITUATIONS = {tags_str}'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        if "LISTA_RELEVANCIA_HIERARQUICA" in dados and isinstance(dados["LISTA_RELEVANCIA_HIERARQUICA"], dict):
            # Converte o dicionário para string Python
            import json
            relevancia_str = json.dumps(dados["LISTA_RELEVANCIA_HIERARQUICA"], indent=4, ensure_ascii=False)
            # Mantemos aspas duplas para preservar JSON válido dentro do Python
            
            # Substitui a variável no arquivo
            import re
            pattern = r'LISTA_RELEVANCIA_HIERARQUICA\s*=\s*\{.*?\n\}'
            replacement = f'LISTA_RELEVANCIA_HIERARQUICA = {relevancia_str}'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        if "PROMPT_EXTRACAO_PERMISSIVO_V8" in dados and isinstance(dados["PROMPT_EXTRACAO_PERMISSIVO_V8"], str):
            # Substitui o prompt principal (sem prefixo f para evitar erros de formatação)
            import re
            pattern = r'PROMPT_EXTRACAO_PERMISSIVO_V8\s*=\s*f?"""[\s\S]*?"""'
            replacement = 'PROMPT_EXTRACAO_PERMISSIVO_V8 = """' + dados["PROMPT_EXTRACAO_PERMISSIVO_V8"] + '"""'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if "PROMPT_AGRUPAMENTO_V1" in dados and isinstance(dados["PROMPT_AGRUPAMENTO_V1"], str):
            # Atualiza o prompt de agrupamento
            import re
            pattern = r'PROMPT_AGRUPAMENTO_V1\s*=\s*"""[\s\S]*?"""'
            replacement = 'PROMPT_AGRUPAMENTO_V1 = """' + dados["PROMPT_AGRUPAMENTO_V1"] + '"""'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if "PROMPT_RESUMO_FINAL_V3" in dados and isinstance(dados["PROMPT_RESUMO_FINAL_V3"], str):
            import re
            pattern = r'PROMPT_RESUMO_FINAL_V3\s*=\s*"""[\s\S]*?"""'
            replacement = 'PROMPT_RESUMO_FINAL_V3 = """' + dados["PROMPT_RESUMO_FINAL_V3"] + '"""'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if "PROMPT_DECISAO_CLUSTER_DETALHADO_V1" in dados and isinstance(dados["PROMPT_DECISAO_CLUSTER_DETALHADO_V1"], str):
            import re
            pattern = r'PROMPT_DECISAO_CLUSTER_DETALHADO_V1\s*=\s*"""[\s\S]*?"""'
            replacement = 'PROMPT_DECISAO_CLUSTER_DETALHADO_V1 = """' + dados["PROMPT_DECISAO_CLUSTER_DETALHADO_V1"] + '"""'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if "PROMPT_CHAT_CLUSTER_V1" in dados and isinstance(dados["PROMPT_CHAT_CLUSTER_V1"], str):
            import re
            pattern = r'PROMPT_CHAT_CLUSTER_V1\s*=\s*"""[\s\S]*?"""'
            replacement = 'PROMPT_CHAT_CLUSTER_V1 = """' + dados["PROMPT_CHAT_CLUSTER_V1"] + '"""'
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        # Salva o arquivo atualizado
        with open(prompts_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Tenta recarregar módulos para refletir mudanças em execução
        try:
            import importlib
            import sys
            if 'backend.prompts' in sys.modules:
                importlib.reload(sys.modules['backend.prompts'])
            elif 'prompts' in sys.modules:
                importlib.reload(sys.modules['prompts'])
        except Exception as e:
            print(f"⚠️  Falha ao recarregar módulo de prompts: {e}")
        
        # Retorna no formato compatível com o frontend (success/message)
        return {
            "success": True,
            "message": "Configurações de prompts atualizadas com sucesso"
        }
    except Exception as e:
        print(f"❌ Erro ao atualizar configurações de prompts: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

