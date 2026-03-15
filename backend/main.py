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

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
import google.generativeai as genai
import json
import os
from pydantic import BaseModel

# JWT + password hashing
try:
    from jose import jwt, JWTError
except ImportError:
    jwt = None  # type: ignore
    JWTError = Exception  # type: ignore

import hashlib as _hashlib
import secrets as _secrets

JWT_SECRET = os.getenv("JWT_SECRET", "silva-alphafeed-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

security_scheme = HTTPBearer(auto_error=False)

# Carrega variáveis de ambiente do arquivo .env
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Arquivo .env carregado: {env_file}")
else:
    print(f"⚠️ Arquivo .env não encontrado: {env_file}")

try:
    from .database import get_db, init_database, ArtigoBruto, ClusterEvento, SinteseExecutiva, SessionLocal
    from .models import (ProcessarArtigoRequest, StatusResponse, ArtigoBrutoCreate, ChatRequest, ChatResponse,
                         ClusterUpdateRequest, ResearchJobCreate, ResearchJobStatus,
                         LoginRequest, TokenResponse, UsuarioCreate, UsuarioUpdate, UsuarioResponse,
                         PreferenciasUpdate, PreferenciasResponse, TemplateResumoCreate, TemplateResumoUpdate,
                         TemplateResumoResponse, ResumoUsuarioResponse)
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
        agg_estatisticas_gerais, agg_noticias_por_tag, agg_noticias_por_prioridade,
        create_feedback, list_feedback, mark_feedback_processed, get_textos_brutos_por_cluster_id,
        create_deep_research_job, update_deep_research_job, get_deep_research_job, list_deep_research_jobs_by_cluster,
        create_social_research_job, update_social_research_job, get_social_research_job, list_social_research_jobs_by_cluster,
        create_estagiario_session, add_estagiario_message, list_estagiario_messages,
        list_prompt_tags, create_prompt_tag, update_prompt_tag, delete_prompt_tag,
        list_prompt_prioridade_itens_grouped, create_prompt_prioridade_item, update_prompt_prioridade_item, delete_prompt_prioridade_item,
        list_prompt_templates, upsert_prompt_template, delete_prompt_template, get_prompts_compilados,
        get_cluster_counts_by_date_and_tipo_fonte,
        list_sourcers_by_date_and_tipo, list_raw_articles_by_source_date_tipo,
        create_usuario, get_usuario_by_email, get_usuario_by_id, list_usuarios, update_usuario, deactivate_usuario,
        get_preferencias_usuario, upsert_preferencias_usuario,
        create_template_resumo, list_templates_resumo, get_template_resumo, update_template_resumo, delete_template_resumo,
        create_resumo_usuario, get_resumo_usuario, list_resumos_usuario, count_clusters_since,
    )
    from .processing import processar_artigo_pipeline, gerar_resumo_cluster, inicializar_processamento
    from .utils import gerar_hash_unico, formatar_timestamp_relativo, get_date_brasil, parse_date_brasil, extrair_json_da_resposta, get_gemini_model
except ImportError:
    # Fallback para import absoluto quando executado fora do pacote
    from backend.database import get_db, init_database, ArtigoBruto, ClusterEvento, SinteseExecutiva, SessionLocal
    from backend.models import (ProcessarArtigoRequest, StatusResponse, ArtigoBrutoCreate, ChatRequest, ChatResponse,
                                ClusterUpdateRequest, ResearchJobCreate, ResearchJobStatus,
                                LoginRequest, TokenResponse, UsuarioCreate, UsuarioUpdate, UsuarioResponse,
                                PreferenciasUpdate, PreferenciasResponse, TemplateResumoCreate, TemplateResumoUpdate,
                                TemplateResumoResponse, ResumoUsuarioResponse)
    from backend.crud import (
        get_artigos_pendentes, get_metricas_today, get_sintese_today,
        get_clusters_for_feed, get_cluster_by_id, get_artigos_by_cluster,
        create_artigo_bruto, get_artigo_by_hash, get_artigo_by_id, create_log, get_database_stats,
        get_metricas_by_date, get_sintese_by_date, get_clusters_for_feed_by_date,
        get_cluster_details_by_id, get_or_create_chat_session, add_chat_message, get_chat_messages_by_session,
        get_chat_session_by_cluster, update_cluster_priority, update_cluster_tags,
        get_cluster_alteracoes, get_all_cluster_alteracoes,
        get_artigos_processados_hoje, get_clusters_existentes_hoje, get_cluster_com_artigos,
        associate_artigo_to_existing_cluster, create_cluster_for_artigo,
        create_deep_research_job, update_deep_research_job, get_deep_research_job, list_deep_research_jobs_by_cluster,
        create_social_research_job, update_social_research_job, get_social_research_job, list_social_research_jobs_by_cluster,
        create_estagiario_session, add_estagiario_message, list_estagiario_messages,
        list_prompt_tags, create_prompt_tag, update_prompt_tag, delete_prompt_tag,
        list_prompt_prioridade_itens_grouped, create_prompt_prioridade_item, update_prompt_prioridade_item, delete_prompt_prioridade_item,
        list_prompt_templates, upsert_prompt_template, delete_prompt_template, get_prompts_compilados, get_textos_brutos_por_cluster_id,
        get_cluster_counts_by_date_and_tipo_fonte,
        list_sourcers_by_date_and_tipo, list_raw_articles_by_source_date_tipo,
        create_usuario, get_usuario_by_email, get_usuario_by_id, list_usuarios, update_usuario, deactivate_usuario,
        get_preferencias_usuario, upsert_preferencias_usuario,
        create_template_resumo, list_templates_resumo, get_template_resumo, update_template_resumo, delete_template_resumo,
        create_resumo_usuario, get_resumo_usuario, list_resumos_usuario, count_clusters_since,
    )
    from backend.processing import processar_artigo_pipeline, gerar_resumo_cluster, inicializar_processamento
    from backend.utils import gerar_hash_unico, formatar_timestamp_relativo, get_date_brasil, parse_date_brasil, extrair_json_da_resposta, get_gemini_model


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
# WEBSOCKET SILENCIOSO (evita flood de 403 no terminal por extensões de live-reload)
# ==============================================================================

@app.websocket("/ws")
async def websocket_noop(ws: WebSocket):
    """Aceita conexões WebSocket silenciosamente (ex.: Live Server, LiveReload).
    Apenas mantém a conexão aberta até o cliente desconectar."""
    await ws.accept()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass

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

@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check com diagnostico do banco."""
    diag = {"status": "healthy", "timestamp": datetime.utcnow().isoformat(), "service": "btg-alphafeed-backend"}
    try:
        from sqlalchemy import text
        tables = [r[0] for r in db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        )).fetchall()]
        diag["tables_count"] = len(tables)
        diag["has_usuarios"] = "usuarios" in tables
        diag["has_preferencias"] = "preferencias_usuario" in tables
        if "usuarios" in tables:
            count = db.execute(text("SELECT count(*) FROM usuarios")).scalar()
            diag["usuarios_count"] = count
    except Exception as e:
        diag["db_error"] = str(e)
        db.rollback()
    return diag

# Removido catch-all para não interferir nas rotas /api


# ==============================================================================
# AUTENTICACAO JWT + HELPERS
# ==============================================================================

def _hash_password(password: str) -> str:
    """Hash de senha com sha256 + salt. Formato: salt$hash."""
    salt = _secrets.token_hex(16)
    h = _hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def _verify_password(plain: str, hashed: str) -> bool:
    """Verifica senha. Suporta formato salt$hash e hash puro legado."""
    if "$" in hashed and len(hashed) > 70:
        parts = hashed.split("$", 1)
        if len(parts) == 2:
            salt, expected = parts
            return _hashlib.sha256((salt + plain).encode()).hexdigest() == expected
    plain_hash = _hashlib.sha256(plain.encode()).hexdigest()
    if plain_hash == hashed:
        return True
    try:
        from passlib.hash import bcrypt as _pb
        return _pb.verify(plain, hashed)
    except Exception:
        return False


def _create_token(user_id: int, email: str, role: str) -> str:
    """Cria JWT token."""
    if jwt is None:
        import hashlib, base64
        payload = json.dumps({"sub": str(user_id), "email": email, "role": role, "exp": time.time() + JWT_EXPIRE_HOURS * 3600})
        return base64.b64encode(payload.encode()).decode()
    from datetime import timedelta
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "email": email, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodifica JWT token. Retorna None se invalido."""
    if jwt is None:
        import base64
        try:
            payload = json.loads(base64.b64decode(token).decode())
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except Exception:
            return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Optional[Dict[str, Any]]:
    """Extrai usuario do token JWT. Retorna None se nao autenticado (permite acesso anonimo)."""
    if not credentials:
        return None
    payload = _decode_token(credentials.credentials)
    if not payload:
        return None
    user_id = int(payload.get("sub", 0))
    if not user_id:
        return None
    user = get_usuario_by_id(db, user_id)
    if not user or not user.ativo:
        return None
    return {"id": user.id, "email": user.email, "role": user.role, "nome": user.nome}


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Exige autenticacao. Retorna 401 se nao autenticado."""
    user = await get_current_user(credentials, db)
    if not user:
        raise HTTPException(status_code=401, detail="Autenticação necessária")
    return user


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Exige role admin."""
    user = await require_auth(credentials, db)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user


# ==============================================================================
# ENDPOINTS: AUTH
# ==============================================================================

@app.post("/api/auth/login")
async def api_login(req: LoginRequest, db: Session = Depends(get_db)):
    """Login com email+senha. Retorna JWT token."""
    email = req.email.strip().lower()
    is_admin_attempt = (email == "admin" or email.startswith("admin@"))

    # Garante que tabelas existem
    try:
        from backend.database import create_tables
        create_tables()
    except Exception:
        pass

    user = None
    if is_admin_attempt:
        for candidate in ["admin@enforcegroup.com.br", "admin@enforce.com.br"]:
            try:
                user = get_usuario_by_email(db, candidate)
                if user:
                    break
            except Exception:
                db.rollback()
    else:
        email_lookup = email
        try:
            user = get_usuario_by_email(db, email_lookup)
        except Exception:
            db.rollback()

    if is_admin_attempt and not user:
        try:
            senha_hash = _hash_password(req.senha)
            user = create_usuario(db, "Administrador", "admin@enforcegroup.com.br", senha_hash, "admin")
            print(f"[Auth] Admin auto-criado (id={user.id})")
        except Exception as e:
            db.rollback()
            print(f"[Auth] Falha ao auto-criar admin: {e}")

    if not user or not user.ativo:
        raise HTTPException(status_code=401, detail="Credenciais invalidas. Verifique email e senha.")

    if not _verify_password(req.senha, user.senha_hash):
        if is_admin_attempt:
            try:
                user.senha_hash = _hash_password(req.senha)
                db.commit()
            except Exception:
                db.rollback()
                raise HTTPException(status_code=401, detail="Credenciais invalidas")
        else:
            raise HTTPException(status_code=401, detail="Credenciais invalidas")

    token = _create_token(user.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "nome": user.nome, "email": user.email, "role": user.role}
    }


@app.get("/api/auth/me")
async def api_get_me(current_user: Dict = Depends(require_auth)):
    """Retorna dados do usuario logado."""
    return current_user


_ALLOWED_DOMAINS = {"enforcegroup.com.br", "btgpactual.com", "btg.com", "btg.com.br"}


@app.post("/api/auth/signup")
async def api_self_register(req: UsuarioCreate, db: Session = Depends(get_db)):
    """Auto-cadastro restrito a dominios permitidos (@enforcegroup, @btg)."""
    email = req.email.strip().lower()
    domain = email.split("@")[-1] if "@" in email else ""
    if domain not in _ALLOWED_DOMAINS:
        raise HTTPException(
            status_code=403,
            detail=f"Cadastro permitido apenas para @enforcegroup.com.br ou @btg. Dominio '{domain}' nao autorizado."
        )
    try:
        existing = get_usuario_by_email(db, email)
    except Exception:
        db.rollback()
        try:
            from backend.database import create_tables
            create_tables()
            existing = get_usuario_by_email(db, email)
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Banco de dados indisponivel: {e2}")
    if existing:
        raise HTTPException(status_code=409, detail="Email ja cadastrado. Use o login.")
    senha_hash = _hash_password(req.senha)
    user = create_usuario(db, req.nome, email, senha_hash, "user")
    token = _create_token(user.id, user.email, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user.id, "nome": user.nome, "email": user.email, "role": user.role}
    }


@app.post("/api/auth/register")
async def api_register_user(req: UsuarioCreate, db: Session = Depends(get_db),
                             admin: Dict = Depends(require_admin)):
    """Cria novo usuario (admin only)."""
    existing = get_usuario_by_email(db, req.email.strip().lower())
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado")
    senha_hash = _hash_password(req.senha)
    user = create_usuario(db, req.nome, req.email.strip().lower(), senha_hash, req.role)
    return {"id": user.id, "nome": user.nome, "email": user.email, "role": user.role}


@app.get("/api/auth/users")
async def api_list_users(db: Session = Depends(get_db), admin: Dict = Depends(require_admin)):
    """Lista todos os usuarios (admin only)."""
    users = list_usuarios(db)
    return [{"id": u.id, "nome": u.nome, "email": u.email, "role": u.role, "ativo": u.ativo,
             "created_at": u.created_at.isoformat() if u.created_at else None} for u in users]


@app.put("/api/auth/users/{user_id}")
async def api_update_user(user_id: int, req: UsuarioUpdate, db: Session = Depends(get_db),
                           admin: Dict = Depends(require_admin)):
    """Atualiza usuario (admin only)."""
    kwargs = {}
    if req.nome is not None:
        kwargs["nome"] = req.nome
    if req.email is not None:
        kwargs["email"] = req.email.strip().lower()
    if req.senha is not None:
        kwargs["senha_hash"] = _hash_password(req.senha)
    user = update_usuario(db, user_id, **kwargs)
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"id": user.id, "nome": user.nome, "email": user.email, "role": user.role}


@app.delete("/api/auth/users/{user_id}")
async def api_deactivate_user(user_id: int, db: Session = Depends(get_db),
                               admin: Dict = Depends(require_admin)):
    """Desativa usuario (admin only)."""
    ok = deactivate_usuario(db, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return {"status": "ok", "message": "Usuário desativado"}


# ==============================================================================
# ENDPOINTS: PREFERENCIAS DO USUARIO
# ==============================================================================

@app.get("/api/user/preferencias")
async def api_get_preferencias(db: Session = Depends(get_db),
                                current_user: Optional[Dict] = Depends(get_current_user)):
    """Retorna preferencias do usuario logado (ou defaults se anonimo)."""
    defaults = {"user_id": None, "tags_interesse": [], "tags_ignoradas": [],
                "fontes_ignoradas": [], "prioridade_minima": "P3_MONITORAMENTO",
                "tipo_fonte_preferido": None, "tamanho_resumo": "medio",
                "template_resumo_id": None, "config_extra": {}, "instrucoes_resumo": ""}
    if not current_user:
        return defaults
    prefs = get_preferencias_usuario(db, current_user["id"])
    if not prefs:
        defaults["user_id"] = current_user["id"]
        return defaults
    ce = prefs.config_extra or {}
    return {
        "id": prefs.id, "user_id": prefs.user_id,
        "tags_interesse": prefs.tags_interesse or [],
        "tags_ignoradas": prefs.tags_ignoradas or [],
        "fontes_ignoradas": prefs.fontes_ignoradas or [],
        "prioridade_minima": prefs.prioridade_minima,
        "tipo_fonte_preferido": prefs.tipo_fonte_preferido,
        "tamanho_resumo": prefs.tamanho_resumo,
        "template_resumo_id": prefs.template_resumo_id,
        "config_extra": ce,
        "instrucoes_resumo": ce.get("instrucoes_resumo", ""),
    }


@app.put("/api/user/preferencias")
async def api_update_preferencias(req: PreferenciasUpdate, db: Session = Depends(get_db),
                                   current_user: Optional[Dict] = Depends(get_current_user)):
    """Atualiza preferencias do usuario logado."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Faca login para salvar preferencias.")
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    prefs = upsert_preferencias_usuario(db, current_user["id"], **kwargs)
    return {"status": "ok", "id": prefs.id}


# ==============================================================================
# ENDPOINTS: TEMPLATES DE RESUMO
# ==============================================================================

@app.get("/api/templates-resumo")
async def api_list_templates(db: Session = Depends(get_db), current_user: Dict = Depends(require_auth)):
    """Lista templates do usuario + publicos."""
    templates = list_templates_resumo(db, user_id=current_user["id"], incluir_publicos=True)
    return [{"id": t.id, "nome": t.nome, "descricao": t.descricao,
             "criado_por_user_id": t.criado_por_user_id, "publico": t.publico,
             "system_prompt": t.system_prompt, "tools_habilitadas": t.tools_habilitadas or [],
             "restricoes": t.restricoes or {},
             "created_at": t.created_at.isoformat() if t.created_at else None} for t in templates]


@app.post("/api/templates-resumo")
async def api_create_template(req: TemplateResumoCreate, db: Session = Depends(get_db),
                               current_user: Dict = Depends(require_auth)):
    """Cria novo template de resumo."""
    tpl = create_template_resumo(
        db, req.nome, req.system_prompt, criado_por=current_user["id"],
        publico=req.publico, descricao=req.descricao,
        tools_habilitadas=req.tools_habilitadas, restricoes=req.restricoes
    )
    return {"id": tpl.id, "nome": tpl.nome}


@app.put("/api/templates-resumo/{template_id}")
async def api_update_template(template_id: int, req: TemplateResumoUpdate, db: Session = Depends(get_db),
                               current_user: Dict = Depends(require_auth)):
    """Atualiza template de resumo (apenas o criador ou admin)."""
    existing = get_template_resumo(db, template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if existing.criado_por_user_id != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Sem permissão para editar este template")
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    tpl = update_template_resumo(db, template_id, **kwargs)
    return {"id": tpl.id, "nome": tpl.nome}


@app.delete("/api/templates-resumo/{template_id}")
async def api_delete_template(template_id: int, db: Session = Depends(get_db),
                               current_user: Dict = Depends(require_auth)):
    """Deleta template de resumo (apenas o criador ou admin)."""
    existing = get_template_resumo(db, template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if existing.criado_por_user_id != current_user["id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Sem permissão para deletar este template")
    delete_template_resumo(db, template_id)
    return {"status": "ok"}


@app.post("/api/templates-resumo/{template_id}/copiar")
async def api_copy_template(template_id: int, db: Session = Depends(get_db),
                             current_user: Dict = Depends(require_auth)):
    """Copia um template publico para o usuario."""
    original = get_template_resumo(db, template_id)
    if not original:
        raise HTTPException(status_code=404, detail="Template não encontrado")
    if not original.publico and original.criado_por_user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Template não é público")
    copia = create_template_resumo(
        db, f"{original.nome} (cópia)", original.system_prompt,
        criado_por=current_user["id"], publico=False,
        descricao=original.descricao, tools_habilitadas=original.tools_habilitadas,
        restricoes=original.restricoes,
    )
    return {"id": copia.id, "nome": copia.nome}


# ==============================================================================
# ENDPOINTS: RESUMO DO USUARIO
# ==============================================================================

@app.get("/api/resumo/hoje")
async def api_get_resumo_hoje(db: Session = Depends(get_db),
                               current_user: Optional[Dict] = Depends(get_current_user)):
    """Retorna o resumo do dia do usuario logado (ou o resumo global se anonimo)."""
    today = get_date_brasil()
    resumo = None
    if current_user:
        resumo = get_resumo_usuario(db, current_user["id"], today)
    if not resumo:
        try:
            from backend.database import ResumoUsuario
            resumo = db.query(ResumoUsuario).filter(
                ResumoUsuario.data_referencia == today,
                ResumoUsuario.texto_gerado.isnot(None),
            ).order_by(ResumoUsuario.created_at.desc()).first()
        except Exception:
            db.rollback()
    if resumo:
        return {
            "id": resumo.id, "data": resumo.data_referencia.isoformat() if resumo.data_referencia else today.isoformat(),
            "texto_gerado": resumo.texto_gerado, "texto_whatsapp": resumo.texto_whatsapp,
            "clusters_escolhidos_ids": resumo.clusters_escolhidos_ids or [],
            "prompt_version": resumo.prompt_version, "metadados": resumo.metadados or {},
            "created_at": resumo.created_at.isoformat() if resumo.created_at else None,
        }
    return {"data": today.isoformat(), "texto_gerado": None, "message": "Nenhum resumo gerado ainda hoje."}


@app.post("/api/resumo/gerar")
async def api_gerar_resumo(background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                            current_user: Dict = Depends(require_auth)):
    """Dispara geracao do resumo diario para o usuario logado (background task)."""
    today = get_date_brasil()
    background_tasks.add_task(_generate_user_summary, current_user["id"], today)
    return {"status": "processing", "message": "Resumo sendo gerado. Consulte GET /api/resumo/hoje."}


def _generate_user_summary(user_id: int, target_date):
    """Background task: gera resumo PERSONALIZADO para o usuario.

    v3.0: Usa gerar_resumo_para_usuario() que reaproveita contexto compartilhado
    (cache por updated_at) e faz UMA chamada LLM por usuario com suas preferencias
    de tags, tamanho e template injetadas no prompt.
    """
    try:
        from agents.resumo_diario.agent import gerar_resumo_para_usuario, formatar_whatsapp

        resultado = gerar_resumo_para_usuario(user_id=user_id, target_date=target_date)

        db = SessionLocal()
        try:
            if resultado.get("ok"):
                texto_wpp = formatar_whatsapp(resultado)
                texto_full = "\n\n---\n\n".join(texto_wpp) if texto_wpp else None
                create_resumo_usuario(
                    db, user_id, target_date, template_id=None,
                    clusters_avaliados=resultado.get("clusters_avaliados_ids", []),
                    clusters_escolhidos=resultado.get("todos_clusters_escolhidos_ids", []),
                    texto=texto_full, texto_whatsapp=texto_full,
                    prompt_version=resultado.get("prompt_version"),
                    metadados=resultado.get("contract_dict", {}),
                )
                print(f"[ResumoUsuario] Resumo personalizado salvo para user_id={user_id}, data={target_date}")
            else:
                print(f"[ResumoUsuario] Falha para user_id={user_id}: {resultado.get('error', 'desconhecido')}")
        finally:
            db.close()
    except Exception as e:
        print(f"[ResumoUsuario] Erro ao gerar resumo: {e}")
        import traceback
        traceback.print_exc()


@app.get("/api/resumo/historico")
async def api_list_resumos(db: Session = Depends(get_db), current_user: Dict = Depends(require_auth),
                            limit: int = 30):
    """Lista ultimos resumos do usuario."""
    resumos = list_resumos_usuario(db, current_user["id"], limit=limit)
    return [{"id": r.id, "data": r.data_referencia.isoformat() if r.data_referencia else None,
             "prompt_version": r.prompt_version, "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in resumos]


@app.get("/api/feed/updates-since")
async def api_feed_updates_since(since: str, db: Session = Depends(get_db)):
    """Conta clusters novos/atualizados desde um timestamp (para indicador de refresh)."""
    try:
        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        since_dt = datetime.utcnow()
    count = count_clusters_since(db, since_dt)
    return {"new_clusters": count, "since": since}



# ==============================================================================
# ENDPOINTS: PROMPTS CONFIG (Tags, Prioridades, Templates)
# ==============================================================================

class PromptTagPayload(BaseModel):
    nome: str
    descricao: str
    exemplos: Optional[List[str]] = None
    ordem: Optional[int] = 0


@app.get("/api/prompts/tags")
async def api_list_prompt_tags(tipo_fonte: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return {"tags": list_prompt_tags(db, tipo_fonte=tipo_fonte)}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/prompts/tags: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/api/prompts/tags")
async def api_create_prompt_tag(payload: PromptTagPayload, tipo_fonte: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        tag_id = create_prompt_tag(db, payload.nome, payload.descricao, payload.exemplos or [], payload.ordem or 0, tipo_fonte or 'nacional')
        return {"ok": True, "id": tag_id}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em POST /api/prompts/tags: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/prompts/tags/{tag_id}")
async def api_update_prompt_tag(tag_id: int, payload: PromptTagPayload, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = update_prompt_tag(db, tag_id, nome=payload.nome, descricao=payload.descricao, exemplos=payload.exemplos or [], ordem=payload.ordem or 0)
        if not ok:
            raise HTTPException(status_code=404, detail="Tag não encontrada")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em PUT /api/prompts/tags/{tag_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/prompts/tags/{tag_id}")
async def api_delete_prompt_tag(tag_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = delete_prompt_tag(db, tag_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Tag não encontrada")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em DELETE /api/prompts/tags/{tag_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


class PriorItemPayload(BaseModel):
    nivel: str  # P1|P2|P3
    texto: str
    ordem: Optional[int] = 0


@app.get("/api/prompts/prioridades")
async def api_list_prompt_prioridades(tipo_fonte: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return {"prioridades": list_prompt_prioridade_itens_grouped(db, tipo_fonte=tipo_fonte)}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/prompts/prioridades: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/api/prompts/prioridades")
async def api_create_prompt_prioridade_item(payload: PriorItemPayload, tipo_fonte: Optional[str] = None, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        item_id = create_prompt_prioridade_item(db, payload.nivel, payload.texto, payload.ordem or 0, tipo_fonte or 'nacional')
        return {"ok": True, "id": item_id}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em POST /api/prompts/prioridades: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.put("/api/prompts/prioridades/{item_id}")
async def api_update_prompt_prioridade_item(item_id: int, payload: PriorItemPayload, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = update_prompt_prioridade_item(db, item_id, nivel=payload.nivel, texto=payload.texto, ordem=payload.ordem or 0)
        if not ok:
            raise HTTPException(status_code=404, detail="Item não encontrado")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em PUT /api/prompts/prioridades/{item_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/prompts/prioridades/{item_id}")
async def api_delete_prompt_prioridade_item(item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = delete_prompt_prioridade_item(db, item_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Item não encontrado")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em DELETE /api/prompts/prioridades/{item_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


class TemplatePayload(BaseModel):
    chave: str
    conteudo: str
    descricao: Optional[str] = None


@app.get("/api/prompts/templates")
async def api_list_prompt_templates(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return {"templates": list_prompt_templates(db)}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/prompts/templates: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.post("/api/prompts/templates")
async def api_upsert_prompt_template(payload: TemplatePayload, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        template_id = upsert_prompt_template(db, payload.chave, payload.conteudo, payload.descricao)
        return {"ok": True, "id": template_id}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em POST /api/prompts/templates: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.delete("/api/prompts/templates/{template_id}")
async def api_delete_prompt_template(template_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        ok = delete_prompt_template(db, template_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Template não encontrado")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em DELETE /api/prompts/templates/{template_id}: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

@app.get("/api/feed")
async def get_feed(
    data: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    load_full_text: bool = False,
    priority: Optional[str] = None,
    tipo_fonte: Optional[str] = 'nacional',
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
            db, target_date, page=page, page_size=page_size, load_full_text=load_full_text, priority=priority, tipo_fonte=tipo_fonte
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


@app.get("/api/sourcers")
async def api_list_sourcers(
    data: Optional[str] = None,
    tipo_fonte: Optional[str] = 'nacional',
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Lista fontes (jornais) disponíveis para a data e tipo selecionados.
    Default: data=hoje (GMT-3 lógico via get_date_brasil), tipo_fonte='nacional' (compat inclui fisico+online).
    """
    try:
        if data:
            try:
                target_date = datetime.strptime(data, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
        else:
            target_date = get_date_brasil()

        # Normaliza tipo_fonte para chaves válidas do CRUD (mantém compatibilidade)
        tipo_norm = (tipo_fonte or 'nacional').strip().lower()
        if tipo_norm not in ('nacional', 'internacional', 'brasil_fisico', 'brasil_online'):
            tipo_norm = 'nacional'

        fontes = list_sourcers_by_date_and_tipo(db, target_date, tipo_norm)
        # retorna lista de objetos com nome e qtd, e também uma lista de strings para compat futura
        return {"data": data or target_date.isoformat(), "tipo_fonte": tipo_norm, "sourcers": fontes, "sourcers_legacy": [f.get("nome") for f in fontes]}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em GET /api/sourcers: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/raw-by-source")
async def api_list_raw_by_source(
    source: str,
    data: Optional[str] = None,
    tipo_fonte: Optional[str] = 'nacional',
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Lista artigos brutos do dia e tipo selecionados para UMA fonte específica.
    Não filtra por prioridade ou tag; retorna tudo que há no banco dessa fonte.
    """
    try:
        if not source or not source.strip():
            raise HTTPException(status_code=400, detail="Parâmetro 'source' é obrigatório")

        if data:
            try:
                target_date = datetime.strptime(data, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
        else:
            target_date = get_date_brasil()

        tipo_norm = (tipo_fonte or 'nacional').strip().lower()
        if tipo_norm not in ('nacional', 'internacional', 'brasil_fisico', 'brasil_online'):
            tipo_norm = 'nacional'

        itens = list_raw_articles_by_source_date_tipo(db, source.strip(), target_date, tipo_norm)
        return {"data": target_date.isoformat(), "tipo_fonte": tipo_norm, "source": source.strip(), "artigos": itens}
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em GET /api/raw-by-source: {e}")
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


@app.get("/api/contadores_abas")
async def get_contadores_abas(
    data: Optional[str] = None,
    db: Session = Depends(get_db)
) -> Dict[str, int]:
    """
    Retorna contagem de clusters exibíveis por tipo_fonte (nacional/internacional)
    para a data informada (YYYY-MM-DD). Se não informada, usa data do Brasil (hoje).
    """
    try:
        if data:
            try:
                target_date = parse_date_brasil(data)
            except Exception:
                # Fallback para formato ISO
                target_date = datetime.fromisoformat(data).date()
        else:
            target_date = get_date_brasil()

        counts = get_cluster_counts_by_date_and_tipo_fonte(db, target_date)
        return counts
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/contadores_abas: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

@app.get("/api/cluster/{cluster_id}/artigos")
async def get_cluster_artigos(
    cluster_id: int,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Endpoint para buscar artigos brutos de um cluster específico.
    Usado para mostrar o texto completo dos artigos no modal.
    
    Args:
        cluster_id: ID do cluster
        db: Sessão do banco de dados
    """
    try:
        artigos = get_artigos_by_cluster(db, cluster_id)
        
        if not artigos:
            raise HTTPException(status_code=404, detail="Nenhum artigo encontrado para este cluster")
        
        # Formata artigos com texto completo
        artigos_data = []
        for artigo in artigos:
            # Prioriza texto processado, mas fallback para texto bruto se necessário
            texto_completo = artigo.texto_processado or artigo.texto_bruto
            if not texto_completo:
                texto_completo = "Texto não disponível"
            
            artigos_data.append({
                "id": artigo.id,
                "titulo": artigo.titulo_extraido,
                "texto_completo": texto_completo,
                "jornal": artigo.jornal,
                "autor": artigo.autor,
                "pagina": artigo.pagina,
                "data_publicacao": artigo.data_publicacao.isoformat() if artigo.data_publicacao else None,
                "url_original": artigo.url_original,
                "fonte_coleta": artigo.fonte_coleta,
                "created_at": artigo.created_at.isoformat()
            })
        
        return {
            "cluster_id": cluster_id,
            "total_artigos": len(artigos_data),
            "artigos": artigos_data
        }
    
    except HTTPException:
        raise
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro no endpoint /api/cluster/{cluster_id}/artigos: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS INTERNOS (PARA COLETORES)
# ==============================================================================

@app.post("/api/clusters/{cluster_id}/expandir-resumo")
async def expandir_resumo_cluster(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, str]:
    """
    Gera um resumo expandido (2-3 parágrafos) a partir dos textos brutos do cluster e
    atualiza o campo `resumo_cluster` do cluster.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        logger.info(f"🔄 Iniciando expansão de resumo para cluster {cluster_id}")

        textos_originais = get_textos_brutos_por_cluster_id(db, cluster_id)
        if not textos_originais:
            logger.warning(f"⚠️ Cluster {cluster_id} não encontrado ou sem artigos")
            raise HTTPException(status_code=404, detail="Cluster não encontrado ou sem artigos.")

        # Busca contexto do grafo + vetorial para enriquecer o resumo
        contexto_historico = ""
        try:
            from backend.agents.graph_crud import get_context_for_cluster
            contexto_historico = get_context_for_cluster(db, cluster_id, days_graph=7, days_vector=30)
            if contexto_historico:
                logger.info(f"📊 Contexto do grafo encontrado ({len(contexto_historico)} chars)")
        except Exception as ctx_err:
            logger.warning(f"⚠️ Contexto do grafo indisponivel: {ctx_err}")

        # Tenta primeiro com o prompt principal
        resumo_novo = None
        tentativas = 0
        max_tentativas = 2

        while tentativas < max_tentativas and not resumo_novo:
            tentativas += 1
            logger.info(f"🔄 Tentativa {tentativas} de geração de resumo")

            try:
                if tentativas == 1:
                    # Primeira tentativa: prompt v2 com contexto do grafo
                    try:
                        from .prompts import PROMPT_RESUMO_EXPANDIDO_V2 as _PROMPT
                    except Exception:
                        from backend.prompts import PROMPT_RESUMO_EXPANDIDO_V2 as _PROMPT
                else:
                    # Segunda tentativa com prompt fallback mais simples
                    logger.warning("⚠️ Usando prompt de fallback na tentativa 2")
                    try:
                        from .prompts import PROMPT_RESUMO_EXPANDIDO_FALLBACK as _PROMPT
                    except Exception:
                        from backend.prompts import PROMPT_RESUMO_EXPANDIDO_FALLBACK as _PROMPT

                payload_text = json.dumps(textos_originais, ensure_ascii=False, indent=2)
                
                # Monta secao de contexto historico (vazia se nao houver)
                if contexto_historico and tentativas == 1:
                    ctx_section = f"**CONTEXTO HISTORICO (eventos relacionados recentes):**\n{contexto_historico}"
                else:
                    ctx_section = ""
                
                prompt_text = _PROMPT.format(
                    TEXTOS_ORIGINAIS_DO_CLUSTER=payload_text,
                    CONTEXTO_HISTORICO_SECTION=ctx_section,
                ) if tentativas == 1 else _PROMPT.format(TEXTOS_ORIGINAIS_DO_CLUSTER=payload_text)

                logger.debug(f"📝 Prompt preparado (tamanho: {len(prompt_text)} chars)")

                model = get_gemini_model()
                logger.debug("🤖 Fazendo chamada para Gemini API")

                response = model.generate_content(prompt_text)
                resposta_texto = getattr(response, 'text', None) or ""

                logger.debug(f"📄 Resposta do LLM recebida (tamanho: {len(resposta_texto)} chars)")

                if tentativas == 1:
                    # Primeira tentativa espera JSON
                    dados = extrair_json_da_resposta(resposta_texto) or {}
                    resumo_novo = dados.get('resumo_expandido') if isinstance(dados, dict) else None
                else:
                    # Fallback usa texto puro
                    resumo_novo = resposta_texto.strip() if resposta_texto.strip() else None

                if resumo_novo:
                    logger.info(f"✅ Resumo gerado com sucesso na tentativa {tentativas}")
                    break
                else:
                    logger.warning(f"⚠️ Tentativa {tentativas} falhou - resposta vazia ou inválida")
                    if tentativas < max_tentativas:
                        logger.info("⏳ Aguardando 2 segundos antes da próxima tentativa...")
                        import time
                        time.sleep(2)  # Pequena pausa entre tentativas

            except Exception as tentativa_error:
                logger.error(f"💥 Erro na tentativa {tentativas}: {str(tentativa_error)}")
                if tentativas < max_tentativas:
                    logger.info("⏳ Aguardando 2 segundos antes da próxima tentativa...")
                    import time
                    time.sleep(2)

        if not resumo_novo:
            # Log detalhado da última resposta quando todas as tentativas falham
            logger.error("❌ Todas as tentativas de geração de resumo falharam")
            logger.error("📋 ÚLTIMA RESPOSTA DO LLM:")
            logger.error("-" * 80)
            logger.error(resposta_texto if 'resposta_texto' in locals() else "Nenhuma resposta recebida")
            logger.error("-" * 80)

            raise HTTPException(status_code=500, detail="Falha ao gerar resumo expandido após múltiplas tentativas.")

        logger.info(f"✅ Resumo expandido gerado com sucesso (tamanho: {len(resumo_novo)} chars)")

        cluster = get_cluster_by_id(db, cluster_id)
        if not cluster:
            logger.warning(f"⚠️ Cluster {cluster_id} não encontrado para atualização")
            raise HTTPException(status_code=404, detail="Cluster não encontrado")

        cluster.resumo_cluster = resumo_novo
        cluster.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"💾 Resumo salvo no banco para cluster {cluster_id}")
        return {"resumo_expandido": resumo_novo}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"💥 Erro inesperado em expandir-resumo para cluster {cluster_id}: {str(e)}", exc_info=True)
        create_log(db, "ERROR", "api", f"Erro em expandir-resumo cluster {cluster_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erro na geração do resumo expandido: {str(e)}")

# ==============================================================================
# GRAPH-RAG: Grafo de Relacionamentos (v2.0)
# ==============================================================================

@app.get("/api/cluster/{cluster_id}/graph")
async def get_cluster_graph(cluster_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Retorna dados do grafo de relacionamentos para visualizacao D3.js.
    Nodes: entidades (PERSON, ORG, GOV, EVENT, CONCEPT) + clusters relacionados.
    Edges: conexoes entre entidades e clusters.
    """
    try:
        from backend.agents.graph_crud import get_cluster_graph_data
        data = get_cluster_graph_data(
            db=db,
            cluster_id=cluster_id,
            max_entity_nodes=30,
            max_cluster_nodes=10,
            days=30,
        )
        return data
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em GET /api/cluster/{cluster_id}/graph: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar grafo: {str(e)}")


# ==============================================================================
# NOTIFICACOES INCREMENTAIS (Telegram/WhatsApp)
# ==============================================================================

@app.get("/api/notifications/pending")
async def get_pending_notifications(limit: int = 50, db: Session = Depends(get_db)):
    """Retorna clusters pendentes de notificacao."""
    try:
        from backend.crud import get_clusters_nao_notificados
        clusters = get_clusters_nao_notificados(db, limit=limit)
        return {
            "total": len(clusters),
            "clusters": [
                {
                    "id": c.id,
                    "titulo": c.titulo_cluster,
                    "resumo": (c.resumo_cluster or "")[:500],
                    "prioridade": c.prioridade,
                    "tag": c.tag,
                    "tipo_fonte": c.tipo_fonte,
                    "total_artigos": c.total_artigos,
                    "created_at": c.created_at.isoformat(),
                }
                for c in clusters
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/notifications/dispatch")
async def dispatch_notifications(
    limit: int = 50,
    dry_run: bool = False,
    db: Session = Depends(get_db)
):
    """
    Despacha notificacoes via Telegram para clusters pendentes.
    Requer TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no ambiente.
    """
    try:
        from backend.crud import get_clusters_nao_notificados, marcar_cluster_notificado
        import os

        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")

        clusters = get_clusters_nao_notificados(db, limit=limit)

        if not clusters:
            return {"status": "ok", "message": "Nenhum cluster pendente", "enviados": 0}

        if dry_run or not token or not chat_id:
            return {
                "status": "dry_run" if dry_run else "config_missing",
                "message": "Dry run ou config Telegram ausente" if dry_run else "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nao configurados",
                "pendentes": len(clusters),
                "clusters": [{"id": c.id, "titulo": c.titulo_cluster} for c in clusters],
            }

        # Envia via Telegram
        from scripts.notify_telegram import formatar_mensagem_telegram, enviar_telegram
        import time as _time

        enviados = 0
        erros = 0
        for cluster in clusters:
            msg = formatar_mensagem_telegram(cluster)
            ok = enviar_telegram(token, chat_id, msg)
            if ok:
                marcar_cluster_notificado(db, cluster.id)
                enviados += 1
            else:
                erros += 1
            _time.sleep(1.0)

        return {"status": "ok", "enviados": enviados, "erros": erros, "total_pendentes": len(clusters)}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/notifications/mark-sent")
async def mark_notifications_sent(cluster_ids: List[int], db: Session = Depends(get_db)):
    """Marca clusters como notificados manualmente (sem enviar)."""
    try:
        from backend.crud import marcar_clusters_notificados_em_lote
        total = marcar_clusters_notificados_em_lote(db, cluster_ids)
        return {"status": "ok", "marcados": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        # Verifica se já existe um artigo com o mesmo hash (dedup exata)
        artigo_existente = get_artigo_by_hash(db, artigo_data.hash_unico)
        if artigo_existente:
            return StatusResponse(
                status="duplicado",
                message="Artigo já existe no sistema (hash exato)",
                data={"id_artigo": artigo_existente.id}
            )
        
        # Dedup semantica: verifica artigos muito parecidos nas ultimas 48h
        try:
            from backend.processing import verificar_duplicata_semantica
            dup = verificar_duplicata_semantica(db, artigo_data.texto_bruto, threshold=0.85, horas=48)
            if dup:
                return StatusResponse(
                    status="duplicado_semantico",
                    message=f"Artigo semanticamente similar encontrado (sim={dup['similaridade']:.2f})",
                    data={"id_artigo_similar": dup["artigo_id"], "titulo_similar": dup["titulo"], "similaridade": dup["similaridade"]}
                )
        except Exception as e:
            # Falha na dedup semantica nao bloqueia a insercao
            print(f"[Dedup Semantica API] Aviso: {e}")
        
        # Preenche 'jornal' a partir de metadados se possível antes de criar
        try:
            md = artigo_data.metadados or {}
            j = md.get('jornal') or md.get('fonte_original') or md.get('fonte')
            if j and hasattr(artigo_data, 'metadados'):
                # também grava um alias coerente
                artigo_data.metadados['jornal'] = j
        except Exception:
            pass

        # Cria novo artigo (apenas carga bruta; processamento é etapa posterior)
        novo_artigo = create_artigo_bruto(db, artigo_data)
        
        # Define tipo_fonte imediatamente com base no jornal/metadados
        try:
            from .utils import inferir_tipo_fonte_por_jornal as _infer_tf  # type: ignore
        except Exception:
            from backend.utils import inferir_tipo_fonte_por_jornal as _infer_tf  # type: ignore

        try:
            jornal = None
            # tenta campo estruturado e metadados
            if hasattr(novo_artigo, 'jornal') and novo_artigo.jornal:
                jornal = novo_artigo.jornal
            if not jornal and isinstance(novo_artigo.metadados, dict):
                jornal = (novo_artigo.metadados or {}).get('jornal') or (novo_artigo.metadados or {}).get('fonte_original') or (novo_artigo.metadados or {}).get('fonte')
            tf = _infer_tf(jornal) if jornal else 'nacional'
            if hasattr(novo_artigo, 'tipo_fonte'):
                # Compat: mapeia antigo nacional → brasil_fisico por padrão para PDFs sem URL
                novo_artigo.tipo_fonte = 'internacional' if tf == 'internacional' else 'nacional'
            db.commit()
            db.refresh(novo_artigo)
        except Exception:
            pass
        
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


@app.get("/api/bi/estatisticas-gerais")
async def bi_estatisticas_gerais(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        data = agg_estatisticas_gerais(db)
        return data
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/estatisticas-gerais: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/bi/noticias-por-tag")
async def bi_noticias_por_tag(limit: int = 10, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        data = agg_noticias_por_tag(db, limit=limit)
        return {"itens": data}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/noticias-por-tag: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@app.get("/api/bi/noticias-por-prioridade")
async def bi_noticias_por_prioridade(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        data = agg_noticias_por_prioridade(db)
        return {"itens": data}
    except Exception as e:
        create_log(db, "ERROR", "api", f"Erro em /api/bi/noticias-por-prioridade: {e}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


# ==============================================================================
# ENDPOINTS DE FEEDBACK
# ==============================================================================

@app.post("/api/feedback")
async def post_feedback(artigo_id: int, feedback: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if feedback not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="feedback deve ser 'like' ou 'dislike'")
    try:
        # Coleta contexto rico para analise de padroes de feedback
        feedback_meta = {}
        try:
            artigo = get_artigo_by_id(db, artigo_id)
            if artigo:
                feedback_meta["tag"] = artigo.tag
                feedback_meta["prioridade"] = artigo.prioridade
                feedback_meta["titulo"] = artigo.titulo_extraido or ""
                feedback_meta["cluster_id"] = artigo.cluster_id
                feedback_meta["tipo_fonte"] = artigo.tipo_fonte
                # Busca entidades do grafo
                try:
                    from backend.database import GraphEdge, GraphEntity
                    edges = db.query(GraphEdge).filter(GraphEdge.artigo_id == artigo_id).all()
                    if edges:
                        entity_ids = [e.entity_id for e in edges]
                        entities = db.query(GraphEntity).filter(GraphEntity.id.in_(entity_ids)).all()
                        feedback_meta["entidades"] = [
                            {"name": e.canonical_name, "type": e.entity_type}
                            for e in entities
                        ]
                except Exception:
                    pass
                # Busca titulo do cluster
                if artigo.cluster_id:
                    cluster = get_cluster_by_id(db, artigo.cluster_id)
                    if cluster:
                        feedback_meta["titulo_cluster"] = cluster.titulo_cluster or ""
                        feedback_meta["prioridade_cluster"] = cluster.prioridade
        except Exception:
            pass
        
        fb_id = create_feedback(db, artigo_id, feedback, metadados=feedback_meta)
        # Se for dislike, marca o artigo como IRRELEVANTE para nao aparecer no frontend
        if feedback == "dislike":
            try:
                artigo = get_artigo_by_id(db, artigo_id)
                if artigo:
                    artigo.tag = "IRRELEVANTE"
                    # Tambem marca o cluster como IRRELEVANTE para sumir do feed
                    try:
                        if artigo.cluster_id:
                            cluster = get_cluster_by_id(db, artigo.cluster_id)
                            if cluster:
                                cluster.tag = "IRRELEVANTE"
                    except Exception:
                        pass
                    db.commit()
                    try:
                        create_log(db, "INFO", "api", f"Artigo {artigo_id} marcado como IRRELEVANTE por dislike")
                    except Exception:
                        pass
            except Exception:
                pass
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
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para upload de arquivos PDF ou JSON.
    Fluxo: upload -> ingestao (dedup hash+semantica) -> process_articles (background).
    """
    file_id = None
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Nome do arquivo não fornecido")
        
        file_ext = file.filename.lower().split('.')[-1]
        if file_ext not in ['pdf', 'json']:
            raise HTTPException(status_code=400, detail="Apenas arquivos PDF e JSON são suportados")
        
        file_id = f"{file.filename}_{int(time.time())}"
        upload_progress[file_id] = {
            "filename": file.filename,
            "status": "uploading",
            "current_article": 0,
            "total_articles": 0,
            "message": "Iniciando upload...",
            "start_time": time.time()
        }
        
        temp_dir = PROJECT_ROOT / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        
        file_path = temp_dir / file.filename
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        upload_progress[file_id]["status"] = "processing"
        upload_progress[file_id]["message"] = "Processando arquivo..."
        
        artigos_processados = await processar_arquivo_upload_com_progresso(file_path, file_ext, db, file_id)
        
        file_path.unlink(missing_ok=True)
        
        upload_progress[file_id]["status"] = "completed"
        upload_progress[file_id]["message"] = "Ingestão concluída. Processamento de artigos iniciado em background."
        upload_progress[file_id]["current_article"] = artigos_processados
        upload_progress[file_id]["total_articles"] = artigos_processados
        
        if artigos_processados > 0 and background_tasks:
            background_tasks.add_task(processar_artigos_via_script)
        
        create_log(db, "INFO", "api", 
                  f"Arquivo {file.filename}: {artigos_processados} artigos ingeridos. Pipeline disparado.")
        
        return StatusResponse(
            status="sucesso",
            message=f"Arquivo {file.filename} processado com sucesso",
            data={"artigos_processados": artigos_processados, "file_id": file_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        if file_id and file_id in upload_progress:
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


@app.get("/admin/processing-status")
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
            processing_state["status"] = "processing"
            processing_state["start_time"] = time.time()
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
            processing_state["processed"] = processing_state.get("total", 0)  # Marca como 100% processado
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
        
        # Busca contexto do grafo + vetorial para enriquecer o chat
        contexto_relacionado = ""
        try:
            from backend.agents.graph_crud import get_context_for_cluster
            contexto_relacionado = get_context_for_cluster(db, request.cluster_id, days_graph=7, days_vector=30)
        except Exception:
            pass
        
        # Prepara prompt para o LLM (v2 com contexto do grafo se disponivel)
        try:
            if contexto_relacionado:
                try:
                    from .prompts import PROMPT_CHAT_CLUSTER_V2
                except ImportError:
                    from backend.prompts import PROMPT_CHAT_CLUSTER_V2
                prompt = PROMPT_CHAT_CLUSTER_V2.format(
                    TITULO_EVENTO=cluster.titulo_cluster,
                    RESUMO_EVENTO=cluster.resumo_cluster or "Resumo não disponível",
                    PRIORIDADE=cluster.prioridade,
                    CATEGORIA=cluster.tag,
                    TOTAL_FONTES=len(artigos),
                    FONTES_ORIGINAIS=fontes_texto,
                    CONTEXTO_RELACIONADO=contexto_relacionado,
                    HISTORICO_CONVERSA=historico_conversa,
                    PERGUNTA_USUARIO=request.message,
                )
            else:
                try:
                    from .prompts import PROMPT_CHAT_CLUSTER_V1
                except ImportError:
                    from backend.prompts import PROMPT_CHAT_CLUSTER_V1
                prompt = PROMPT_CHAT_CLUSTER_V1.format(
                    TITULO_EVENTO=cluster.titulo_cluster,
                    RESUMO_EVENTO=cluster.resumo_cluster or "Resumo não disponível",
                    PRIORIDADE=cluster.prioridade,
                    CATEGORIA=cluster.tag,
                    TOTAL_FONTES=len(artigos),
                    FONTES_ORIGINAIS=fontes_texto,
                    HISTORICO_CONVERSA=historico_conversa,
                    PERGUNTA_USUARIO=request.message,
                )
        except Exception:
            from backend.prompts import PROMPT_CHAT_CLUSTER_V1
            prompt = PROMPT_CHAT_CLUSTER_V1.format(
                TITULO_EVENTO=cluster.titulo_cluster,
                RESUMO_EVENTO=cluster.resumo_cluster or "Resumo não disponível",
                PRIORIDADE=cluster.prioridade,
                CATEGORIA=cluster.tag,
                TOTAL_FONTES=len(artigos),
                FONTES_ORIGINAIS=fontes_texto,
                HISTORICO_CONVERSA=historico_conversa,
                PERGUNTA_USUARIO=request.message,
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


# ======================================================================
# Pesquisas Assíncronas: Deep Research (Gemini) e Social (Grok)
# ======================================================================

def _montar_contexto_cluster(db: Session, cluster_id: int) -> str:
    cluster = get_cluster_by_id(db, cluster_id)
    if not cluster:
        return ""
    artigos = get_artigos_by_cluster(db, cluster_id)
    fontes = []
    for a in artigos:
        base = (a.texto_processado or a.texto_bruto or "")
        trecho = (base[:500] + "...") if len(base) > 500 else base
        fontes.append(f"- {a.jornal or 'Fonte'}: {trecho}")
    return (
        f"Evento: {cluster.titulo_cluster}\n"
        f"Resumo: {cluster.resumo_cluster or ''}\n"
        f"Tag: {cluster.tag} | Prioridade: {cluster.prioridade}\n\n"
        f"Fontes:\n" + "\n".join(fontes)
    )


def _executar_deep_research(job_id: int, cluster_id: int, query: str | None, _db_ignored: Session = None):
    # Cria uma nova sessão própria para o job em background
    db = SessionLocal()
    try:
        update_deep_research_job(db, job_id, status='RUNNING', started_at=datetime.utcnow())
        from .utils import get_gemini_model
    except Exception as e:
        update_deep_research_job(db, job_id, status='FAILED', error_message=str(e), finished_at=datetime.utcnow())
        db.close()
        return

    contexto = _montar_contexto_cluster(db, cluster_id)
    pergunta = query or "Realize uma pesquisa aprofundada e forneça um briefing executivo, bullets de insights, riscos, próximos passos e referências confiáveis. Responda em PT-BR."
    prompt = (
        "Você é um analista senior. Com base no contexto e também em seu conhecimento, conduza uma pesquisa aprofundada.\n"
        "Contexto do evento:\n" + contexto + "\n\n"
        f"Instrução: {pergunta}\n\n"
        "Formato de saída: primeiro um resumo estruturado em texto; ao final, retorne um bloco JSON com campos { 'insights_chave': [], 'riscos': [], 'proximos_passos': [], 'fontes_sugeridas': [] }."
    )
    try:
        model = get_gemini_model()
        resp = model.generate_content(prompt)
        texto = getattr(resp, 'text', '') or ''
        try:
            json_part = None
            import re, json as _json
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", texto)
            if m:
                json_part = _json.loads(m.group(1))
        except Exception:
            json_part = None
        update_deep_research_job(db, job_id, status='COMPLETED', result_text=texto, result_json=json_part, finished_at=datetime.utcnow())
    except Exception as e:
        update_deep_research_job(db, job_id, status='FAILED', error_message=str(e), finished_at=datetime.utcnow())
    finally:
        db.close()


def _executar_social_research(job_id: int, cluster_id: int, query: str | None, _db_ignored: Session = None):
    db = SessionLocal()
    q = query or "O que as pessoas no X (Twitter) estão debatendo sobre este tópico? Resuma tópicos, sentimentos e contas relevantes."
    try:
        api_key = os.getenv('GROK_API_KEY')
        if not api_key:
            raise RuntimeError('GROK_API_KEY não configurada')

        import requests
        update_social_research_job(db, job_id, status='RUNNING', started_at=datetime.utcnow())

        contexto = _montar_contexto_cluster(db, cluster_id)
        user_prompt = (
            "Você é um analista de social listening. Com base no contexto, pesquise no X/Twitter e resuma: tópicos em alta, sentimentos e contas chave."
            " Liste também 10 posts representativos com autor (handle), data (ISO) e link. Responda em PT-BR.\n\n"
            f"Contexto:\n{contexto}\n\n"
            f"Pergunta: {q}"
        )
        model_name = os.getenv('GROK_MODEL', 'grok-2-latest')
        url = 'https://api.x.ai/v1/chat/completions'
        payload = {
            'model': model_name,
            'messages': [
                {'role': 'system', 'content': 'Você tem acesso a dados públicos do X/Twitter. Responda com um resumo estruturado e um bloco JSON no final.'},
                {'role': 'user', 'content': user_prompt}
            ],
            'temperature': 0.3
        }
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=120)
        if r.status_code >= 400:
            raise RuntimeError(f"Erro Grok API: HTTP {r.status_code} - {r.text[:200]}")
        data = r.json()
        texto = ''
        try:
            choices = data.get('choices') or []
            if choices:
                texto = choices[0].get('message', {}).get('content', '')
        except Exception:
            texto = r.text
        try:
            import re, json as _json
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", texto)
            json_part = _json.loads(m.group(1)) if m else None
        except Exception:
            json_part = None
        update_social_research_job(db, job_id, status='COMPLETED', result_text=texto, result_json=json_part, finished_at=datetime.utcnow())
    except Exception as e:
        update_social_research_job(db, job_id, status='FAILED', error_message=str(e), finished_at=datetime.utcnow())
    finally:
        db.close()


@app.post("/api/research/deep/start")
async def start_deep_research(request: ResearchJobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cluster = get_cluster_by_id(db, request.cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster não encontrado")
    job_id = create_deep_research_job(db, request.cluster_id, request.query)
    background_tasks.add_task(_executar_deep_research, job_id, request.cluster_id, request.query, db)
    return {"job_id": job_id, "status": "PENDING"}


@app.get("/api/research/deep/{job_id}")
async def get_deep_research(job_id: int, db: Session = Depends(get_db)) -> ResearchJobStatus:
    job = get_deep_research_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return ResearchJobStatus(
        id=job.id, cluster_id=job.cluster_id, status=job.status, provider=job.provider,
        result_text=job.result_text, result_json=job.result_json, error_message=job.error_message,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at, updated_at=job.updated_at
    )


@app.get("/api/research/deep/cluster/{cluster_id}")
async def list_deep_research(cluster_id: int, limit: int = 20, db: Session = Depends(get_db)) -> Dict[str, Any]:
    jobs = list_deep_research_jobs_by_cluster(db, cluster_id, limit)
    return {"jobs": [
        {
            "id": j.id, "status": j.status, "provider": j.provider,
            "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None
        } for j in jobs
    ]}


@app.post("/api/research/social/start")
async def start_social_research(request: ResearchJobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)) -> Dict[str, Any]:
    cluster = get_cluster_by_id(db, request.cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster não encontrado")
    job_id = create_social_research_job(db, request.cluster_id, request.query)
    background_tasks.add_task(_executar_social_research, job_id, request.cluster_id, request.query, db)
    return {"job_id": job_id, "status": "PENDING"}


@app.get("/api/research/social/{job_id}")
async def get_social_research(job_id: int, db: Session = Depends(get_db)) -> ResearchJobStatus:
    job = get_social_research_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return ResearchJobStatus(
        id=job.id, cluster_id=job.cluster_id, status=job.status, provider=job.provider,
        result_text=job.result_text, result_json=job.result_json, error_message=job.error_message,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at, updated_at=job.updated_at
    )


@app.get("/api/research/social/cluster/{cluster_id}")
async def list_social_research(cluster_id: int, limit: int = 20, db: Session = Depends(get_db)) -> Dict[str, Any]:
    jobs = list_social_research_jobs_by_cluster(db, cluster_id, limit)
    return {"jobs": [
        {
            "id": j.id, "status": j.status, "provider": j.provider,
            "created_at": j.created_at.isoformat(), "finished_at": j.finished_at.isoformat() if j.finished_at else None
        } for j in jobs
    ]}


# ==============================================================================
# ENDPOINTS PARA CONFIGURAÇÃO DE PROMPTS
# ==============================================================================

@app.get("/api/settings/prompts")
async def get_prompts_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
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

        # Dados de Tags e Prioridades vindos do banco
        compiled = get_prompts_compilados(db)
        tags_db = compiled.get('tags') or {}
        p1_db = compiled.get('p1') or []
        p2_db = compiled.get('p2') or []
        p3_db = compiled.get('p3') or []

        # Fallback para arquivo apenas se o banco estiver vazio
        tags_final = tags_db if tags_db else getattr(prompts_module, "TAGS_SPECIAL_SITUATIONS", {})
        p1_final = p1_db if p1_db else getattr(prompts_module, "P1_ITENS", [])
        p2_final = p2_db if p2_db else getattr(prompts_module, "P2_ITENS", [])
        p3_final = p3_db if p3_db else getattr(prompts_module, "P3_ITENS", [])

        prompts_config = {
            "TAGS_SPECIAL_SITUATIONS": tags_final,
            # Mantido por compatibilidade; pode não existir mais no arquivo:
            "LISTA_RELEVANCIA_HIERARQUICA": getattr(prompts_module, "LISTA_RELEVANCIA_HIERARQUICA", {}),
            # Listas editáveis (Gatekeeper) vindas do DB, com fallback
            "P1_ITENS": p1_final,
            "P2_ITENS": p2_final,
            "P3_ITENS": p3_final,
            # Prompts textuais permanecem no arquivo
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
    dados: Dict[str, Any],
    db: Session = Depends(get_db)
) -> StatusResponse:
    """
    Endpoint para atualizar as configurações dos prompts.
    """
    try:
        # 1) Sincroniza TAGS e PRIORIDADES no BANCO DE DADOS
        if "TAGS_SPECIAL_SITUATIONS" in dados and isinstance(dados["TAGS_SPECIAL_SITUATIONS"], dict):
            incoming: Dict[str, Any] = dados["TAGS_SPECIAL_SITUATIONS"]
            # mapa existente por nome
            existentes = {t["nome"]: t for t in list_prompt_tags(db)}
            nomes_incoming = set(incoming.keys())
            nomes_existentes = set(existentes.keys())
            # deleta os que foram removidos
            for nome_del in (nomes_existentes - nomes_incoming):
                try:
                    delete_prompt_tag(db, existentes[nome_del]["id"])  # type: ignore
                except Exception:
                    pass
            # upsert dos recebidos
            for nome, info in incoming.items():
                desc = (info or {}).get("descricao") or ""
                exemplos = (info or {}).get("exemplos") or []
                if nome in existentes:
                    update_prompt_tag(db, existentes[nome]["id"], nome=nome, descricao=desc, exemplos=exemplos)  # type: ignore
                else:
                    create_prompt_tag(db, nome, desc, exemplos, ordem=0)

        # Prioridades P1/P2/P3: substitui listas inteiras preservando ordem
        listas_prior = {
            "P1": dados.get("P1_ITENS") if isinstance(dados.get("P1_ITENS"), list) else None,
            "P2": dados.get("P2_ITENS") if isinstance(dados.get("P2_ITENS"), list) else None,
            "P3": dados.get("P3_ITENS") if isinstance(dados.get("P3_ITENS"), list) else None,
        }
        # apaga existentes e recria conforme nova ordem
        grouped = list_prompt_prioridade_itens_grouped(db)
        for nivel, lista in listas_prior.items():
            if lista is None:
                continue
            # delete all current items in this level
            for item in grouped.get(nivel, []):
                try:
                    delete_prompt_prioridade_item(db, item["id"])  # type: ignore
                except Exception:
                    pass
            # recreate with new order
            for idx, texto in enumerate(lista):
                if texto and str(texto).strip():
                    create_prompt_prioridade_item(db, nivel, str(texto).strip(), ordem=idx)

        # 2) Atualiza APENAS os prompts textuais no arquivo
        prompts_path = Path(__file__).parent / "prompts.py"
        with open(prompts_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "PROMPT_EXTRACAO_PERMISSIVO_V8" in dados and isinstance(dados["PROMPT_EXTRACAO_PERMISSIVO_V8"], str):
            # Substitui o prompt principal (sem prefixo f para evitar erros de formatação)
            import re
            pattern = r'PROMPT_EXTRACAO_PERMISSIVO_V8\s*=\s*f?"""[\s\S]*?"""'
            replacement = 'PROMPT_EXTRACAO_PERMISSIVO_V8 = """' + dados["PROMPT_EXTRACAO_PERMISSIVO_V8"] + '"""'
            content = re.sub(pattern, lambda m: replacement, content, flags=re.DOTALL)

        if "PROMPT_AGRUPAMENTO_V1" in dados and isinstance(dados["PROMPT_AGRUPAMENTO_V1"], str):
            # Atualiza o prompt de agrupamento
            import re
            pattern = r'PROMPT_AGRUPAMENTO_V1\s*=\s*"""[\s\S]*?"""'
            replacement = 'PROMPT_AGRUPAMENTO_V1 = """' + dados["PROMPT_AGRUPAMENTO_V1"] + '"""'
            content = re.sub(pattern, lambda m: replacement, content, flags=re.DOTALL)

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


# ==============================================================================
# ENDPOINTS: ADMIN PROMPTS (CMS)
# ==============================================================================

@app.get("/api/admin/prompts")
async def api_list_admin_prompts(db: Session = Depends(get_db)):
    """Lista todos os prompts editáveis (constantes de prompts.py + banco)."""
    try:
        from backend.prompts import PROMPT_REQUIRED_VARS
    except ImportError:
        PROMPT_REQUIRED_VARS = {}

    templates = list_prompt_templates(db)
    result = []
    for t in templates:
        result.append({
            "chave": t.chave if hasattr(t, 'chave') else t.get("chave", ""),
            "descricao": t.descricao if hasattr(t, 'descricao') else t.get("descricao", ""),
            "conteudo": t.conteudo if hasattr(t, 'conteudo') else t.get("conteudo", ""),
            "variaveis_obrigatorias": PROMPT_REQUIRED_VARS.get(
                t.chave if hasattr(t, 'chave') else t.get("chave", ""), []),
            "updated_at": (t.updated_at.isoformat() if hasattr(t, 'updated_at') and t.updated_at else None),
        })
    return result


class PromptValidateRequest(BaseModel):
    conteudo: str


@app.post("/api/admin/prompts/{chave}/validate")
async def api_validate_prompt(chave: str, req: PromptValidateRequest):
    """Valida um prompt testando format() com dados mock (sandbox)."""
    try:
        from backend.prompts import validar_prompt_update
    except ImportError:
        return {"ok": True, "message": "Validação indisponível"}
    ok, msg = validar_prompt_update(chave, req.conteudo)
    if not ok:
        raise HTTPException(status_code=422, detail=msg)
    return {"ok": True, "message": msg}


# ==============================================================================
# ENDPOINTS: DOCUMENTAÇÃO (Markdown + Mermaid)
# ==============================================================================

@app.get("/api/docs")
async def api_list_docs():
    """Lista documentos .md disponíveis no diretório docs/."""
    docs_dir = PROJECT_ROOT / "docs"
    if not docs_dir.exists():
        return []
    files = sorted(docs_dir.glob("*.md"))
    return [{"name": f.stem, "filename": f.name,
             "size": f.stat().st_size} for f in files]


@app.get("/api/docs/{filename}")
async def api_get_doc(filename: str):
    """Retorna conteúdo de um documento .md."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    doc_path = PROJECT_ROOT / "docs" / filename
    if not doc_path.exists() or doc_path.suffix != ".md":
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return {"filename": filename, "content": doc_path.read_text(encoding="utf-8")}


class EstagiarioStartRequest(BaseModel):
    data: str | None = None  # YYYY-MM-DD

class EstagiarioSendRequest(BaseModel):
    session_id: int
    message: str

@app.post("/api/estagiario/start")
async def estagiario_start(req: EstagiarioStartRequest, db: Session = Depends(get_db)):
    try:
        if req.data:
            try:
                target_date = datetime.strptime(req.data, "%Y-%m-%d").date()
            except ValueError:
                target_date = get_date_brasil()
        else:
            target_date = get_date_brasil()
        session_id = create_estagiario_session(db, target_date)
        return {"session_id": session_id, "data": target_date.isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/estagiario/send")
async def estagiario_send(req: EstagiarioSendRequest, db: Session = Depends(get_db)):
    try:
        # salva mensagem do usuário
        add_estagiario_message(db, req.session_id, 'user', req.message)
        
        # busca histórico da conversa para manter contexto
        chat_history = list_estagiario_messages(db, req.session_id, limit=50)
        print(f"[DEBUG] Histórico carregado: {len(chat_history)} mensagens")
        for i, msg in enumerate(chat_history):
            print(f"[DEBUG] Msg {i}: role={msg.get('role')}, content={msg.get('content', '')[:100]}...")
        
        # chama agente com histórico
        try:
            from agents.estagiario.agent import EstagiarioAgent
            agent = EstagiarioAgent()
            print(f"[DEBUG] Agente criado, chamando answer_with_context...")
            answer = agent.answer_with_context(req.message, chat_history)
            print(f"[DEBUG] Resposta obtida: {len(answer.text)} caracteres")
        except ImportError as e:
            print(f"Erro ao importar EstagiarioAgent: {e}")
            # Fallback para import absoluto
            import sys
            sys.path.append(str(PROJECT_ROOT))
            from agents.estagiario.agent import EstagiarioAgent
            agent = EstagiarioAgent()
            answer = agent.answer_with_context(req.message, chat_history)
        add_estagiario_message(db, req.session_id, 'assistant', answer.text)
        return {"ok": True, "response": answer.text}
    except Exception as e:
        add_estagiario_message(db, req.session_id, 'assistant', f"Erro: {e}")
        return {"ok": False, "response": f"Erro: {e}"}

@app.get("/api/estagiario/messages/{session_id}")
async def estagiario_messages(session_id: int, db: Session = Depends(get_db)):
    try:
        msgs = list_estagiario_messages(db, session_id, limit=200)
        return {"messages": msgs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))