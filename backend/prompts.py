#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
================================================================================
|     REESTRUTURAÇÃO DOS PROMPTS - FOCO EM SPECIAL SITUATIONS (v7.1)           |
================================================================================
| OBJETIVO DESTA REATORAÇÃO:                                                   |
| 1. Centralizar a Definição de Tags: Criar uma "fonte da verdade" para as   |
|    8 categorias de "Special Situations", eliminando inconsistências.       |
| 2. Unificar a Lógica de Prioridade: Manter o sistema hierárquico (P1, P2, P3)|
|    e integrá-lo de forma clara com as novas tags temáticas.                  |
| 3. Prompts Precisos e Robustos: Reescrever os prompts de extração para que  |
|    o LLM utilize o novo guia detalhado, operando sob a mesma ótica de um     |
|    analista da área.                                                       |
| 4. Manter Nomes de Variáveis: Preservar os nomes originais das variáveis    |
|    (ex: LISTA_RELEVANCIA_FORMATADA) para compatibilidade com o pipeline.     |
--------------------------------------------------------------------------------
"""

# ==============================================================================
# 1. FONTES DA VERDADE PARA CLASSIFICAÇÃO
# ==============================================================================

# Dicionário central para as tags temáticas de Special Situations - Nacional.
TAGS_SPECIAL_SITUATIONS = {
    "M&A e Transações Corporativas": {
        "descricao": "Mudanças na estrutura de capital ou controle de empresas através de transações.",
        "exemplos": [
            "Fusões e Aquisições (M&A) - Apenas quando o fato gerador for um anúncio oficial de transação, um acordo assinado ou uma negociação formal e exclusiva em andamento. Intenções genéricas de ",
            "Venda de ativos ou subsidiárias (divestitures)",
            "Ofertas públicas de aquisição (OPA)",
            "Disputas por controle acionário que podem levar a uma transação"
        ]
    },
    "Jurídico, Falências e Regulatório": {
        "descricao": "Eventos legais ou regulatórios que criam estresse financeiro, oportunidades de arbitragem ou alteram o ambiente de negócios.",
        "exemplos": [
            "Recuperação Judicial (RJ), Falência, Pedido de Falência, Assembleia de Credores",
            "Disputas societárias relevantes ENTRE SÓCIOS, ACIONISTAS ou CONSELHO de uma EMPRESA, com impacto em controle ou governança. (Ex: NÃO se aplica a disputas entre partidos políticos ou investigações de agentes públicos por crimes comuns)",
            "Mudanças em Legislação (Tributária, Societária, Falimentar)",
            "Decisões do CADE (bloqueio de fusões, imposição de remédios)",
            "Decisões de tribunais superiores (STF, STJ) com impacto direto em empresas ou setores"
        ]
    },
    "Dívida Ativa e Créditos Públicos": {
        "descricao": "Assuntos relacionados à gestão da divida ativa dos Estados, MUnicípios e da União",
        "exemplos": [
            "Qualquer noticia relacionada a divida ativa de Estado, Município ou mesmo da União",
            "Qualquer noticia relacionada a lei complementar nº 208, de 2 de julho de 2024 que regula a securitização da divida dos entes publicos, estados e municipios",
            "Qualquer notícia relacionada a matéria tributária, ou à cobrança de impostos, taxas, que afetem a arrecadação, especialmente sobre divida ativa",
            "Notícias sobre a liquidação ou venda de carteiras de Precatórios",
            "AlteraçÕes nas leis de cobrança de impostos municipais ou estaduais (especialmente ICMS, ISS E IPTU)",
            "Créditos FCVS (apenas notícias sobre liquidação ou venda de grandes volumes)"
        ]
    },
    "Distressed Assets e NPLs": {
        "descricao": "Ativos ou carteiras de crédito que estão sob estresse financeiro e podem ser negociados com desconto.",
        "exemplos": [
            "Créditos Inadimplentes (NPLs), Créditos Podres (Distressed Debt), Venda de Carteira de NPL",
            "Leilões Judiciais de Ativos (imóveis, participações societárias > R$10 milhões)",
            "Empresas ou ativos específicos em Crise de Liquidez Aguda"
        ]
    },
    "Mercado de Capitais e Finanças Corporativas": {
        "descricao": "Saúde financeira das empresas e movimentos no mercado de capitais que sinalizam estresse ou oportunidade.",
        "exemplos": [
            "Quebra de Covenants, Default de Dívida",
            "Ativismo Acionário relevante",
            "Grandes emissões de dívida (debêntures), renegociações de dívidas corporativas",
            "Resultados financeiros que indiquem forte deterioração ou estresse severo"
        ]
    },
    "Política Econômica (Brasil)": {
        "descricao": "Decisões do governo e Banco Central do Brasil com impacto direto na saúde financeira das empresas e no ambiente de crédito.",
        "exemplos": [
            "Decisões de juros (Copom) e política fiscal",
            "Grandes leilões de concessão, planos de estímulo ou contingência",
            "Mudanças na tributação com impacto setorial amplo"
        ]
    },
    "Internacional (Economia e Política)": {
        "descricao": "Eventos de política e economia que ocorrem fora do Brasil, mas cujo contexto é relevante para o mercado global.",
        "exemplos": [
            "Geoeconomia, Acordos Comerciais, Decisões do FED e BCE",
            "Crises políticas ou econômicas em outros países (ex: Argentina)",
            "Resultados de multinacionais que sirvam como termômetro de setores globais"
        ]
    },
    "Tecnologia e Setores Estratégicos": {
        "descricao": "Tendências e grandes movimentos em setores de alto capital ou tecnologia que podem gerar oportunidades de M&A ou disrupção.",
        "exemplos": [
            "Inteligência Artificial (IA - grandes M&As no setor, regulação pesada)",
            "Semicondutores (geopolítica da cadeia de suprimentos, grandes investimentos)",
            "EnergIA Nuclear e Aeroespacial (grandes projetos, concessões)"
        ]
    },
    "Divulgação de Resultados": {
        "descricao": "Publicações oficiais de resultados trimestrais/anuais (earnings) de empresas.",
        "exemplos": [
            "Divulgação de resultados trimestrais (ex.: 2T24, 3T24, 4T24)",
            "Conference call de resultados/press release de earnings",
            "Atualização de guidance vinculada ao release de resultados",
            "Observação: Resultados com sinais de estresse severo (impairment, write-down, quebra de covenants) podem ser elevados para P2."
        ]
    },
    "IRRELEVANTE": {
        "descricao": "Estamos na mesa de Special Situations do BTG Pactual. Vamos classificar tudo que que não tem contato conosco como IRRELEVANTE.",
        "exemplos": [
            "Noticias sobre crimes comuns, politica, opiniÕes que nao tem contato com o banco",
            "Fofocas, entretenimento, esportes, programas sociais, etc.",
            "Eventos esportivos, culturais, musicas, shows, teatrosetc.",
            "Programas publicos e do governo sociais, ambientes, bolsa familia, desemprego, etc que nao impactem a economia de forma abrangente"
        ]
    }
}

# Dicionário central para as tags temáticas de Special Situations - Internacional.
TAGS_SPECIAL_SITUATIONS_INTERNACIONAL = {
    "Global M&A and Corporate Transactions": {
        "descricao": "Fusões, aquisições e transações corporativas globais de grande porte.",
        "exemplos": [
            "Mega-mergers (> $10 bilhões) entre multinacionais",
            "Aquisições cross-border com impacto geopolítico",
            "Consolidações setoriais globais (tech, pharma, energy)",
            "IPOs de unicórnios ou empresas estratégicas"
        ],
        "ordem": 1
    },
    "Global Legal and Regulatory": {
        "descricao": "Mudanças regulatórias e disputas legais com impacto no mercado global.",
        "exemplos": [
            "Regulações antitruste (DOJ, European Commission)",
            "Sanctions e embargos comerciais",
            "Disputas comerciais internacionais (WTO)",
            "Mudanças em compliance global (GDPR, SOX)"
        ],
        "ordem": 2
    },
    "Sovereign Debt and Credit": {
        "descricao": "Crises de dívida soberana e mudanças em ratings de países.",
        "exemplos": [
            "Defaults ou reestruturações de dívida soberana",
            "Mudanças de rating de países (Moody's, S&P, Fitch)",
            "Crises de dívida em mercados emergentes",
            "Programas do FMI e bailouts internacionais"
        ],
        "ordem": 3
    },
    "Global Distressed and Restructuring": {
        "descricao": "Falências e reestruturações de grandes corporações globais.",
        "exemplos": [
            "Chapter 11 de grandes corporações americanas",
            "Insolvências na Europa (schemes of arrangement)",
            "Crises setoriais globais (airlines, retail, energy)",
            "Venda de ativos distressed cross-border"
        ],
        "ordem": 4
    },
    "Global Capital Markets": {
        "descricao": "Movimentos significativos nos mercados de capitais globais.",
        "exemplos": [
            "Crashes ou rallies em bolsas principais (NYSE, NASDAQ, LSE)",
            "Emissões recordes de bonds corporativos globais",
            "Mudanças em índices principais (S&P 500, FTSE, DAX)",
            "Crises de liquidez em mercados desenvolvidos"
        ],
        "ordem": 5
    },
    "Central Banks and Monetary Policy": {
        "descricao": "Decisões de bancos centrais com impacto global.",
        "exemplos": [
            "Decisões do FED, BCE, BoJ, BoE",
            "Mudanças em QE (quantitative easing)",
            "Currency wars e intervenções cambiais",
            "Coordenação de política monetária global"
        ],
        "ordem": 6
    },
    "Geopolitics and Trade": {
        "descricao": "Eventos geopolíticos com impacto econômico significativo.",
        "exemplos": [
            "Guerras comerciais (US-China, EU-UK)",
            "Sanções econômicas e bloqueios",
            "Acordos comerciais multilaterais",
            "Crises energéticas e de commodities"
        ],
        "ordem": 7
    },
    "Technology and Innovation": {
        "descricao": "Disrupções tecnológicas e movimentos em big tech global.",
        "exemplos": [
            "Regulação de big tech (antitrust cases)",
            "Breakthrough em AI, quantum computing",
            "Cybersecurity breaches de escala global",
            "IPOs e M&As no setor tech (> $5 bilhões)"
        ],
        "ordem": 8
    },
    "IRRELEVANTE": {
        "descricao": "News that don't have direct market impact or relevance for Special Situations.",
        "exemplos": [
            "General political news without economic impact",
            "Entertainment, sports, cultural events",
            "Local news without market relevance",
            "Social programs without broad economic impact"
        ],
        "ordem": 9
    }
}

# Lista de prioridades para notícias internacionais
LISTA_RELEVANCIA_HIERARQUICA_INTERNACIONAL = [
    {
        "nivel": "P1_CRITICO",
        "descricao": "Critical events requiring immediate attention in global markets",
        "itens": [
            "Major sovereign defaults or debt restructurings (> $5 billion)",
            "Chapter 11 filings by Fortune 500 companies or major global corporations",
            "Mega-mergers officially announced (> $20 billion)",
            "Central bank emergency interventions or unexpected rate changes",
            "Major market crashes (indices down > 5% in a day)",
            "Trade wars escalation with immediate tariffs implementation",
            "Sanctions on major economies or corporations",
            "Systemic banking crises in developed markets",
            "Maiores Empresas de tecnologia: Google, Apple, Tesla, Nvidia, Microsoft, Intel, Meta, AMD, Intuitive Machines, Netflix, Micron, Siemens Energy AG"
        ]
    },
    {
        "nivel": "P2_ESTRATEGICO",
        "descricao": "Strategic events with significant medium-term impact",
        "itens": [
            "Credit rating changes for G20 countries",
            "Major regulatory changes affecting global sectors",
            "Large cross-border M&A negotiations (> $5 billion)",
            "Significant monetary policy shifts signaled by central banks",
            "Major IPOs or delistings (> $10 billion valuation)",
            "Corporate restructurings of multinational companies",
            "Geopolitical tensions affecting global supply chains",
            "Technology disruptions with sector-wide impact"
        ]
    },
    {
        "nivel": "P3_MONITORAMENTO",
        "descricao": "Monitoring events for context and trend analysis",
        "itens": [
            "Regular earnings reports from global companies",
            "Economic indicators and data releases",
            "Political developments without immediate economic impact",
            "Sector trends and analysis reports",
            "Minor M&A activity (< $1 billion)",
            "Regular central bank communications",
            "ESG and sustainability initiatives",
            "Technology developments and innovations"
        ]
    }
]

# Lista central de empresas prioritárias para gating de "Divulgação de Resultados"
EMPRESAS_PRIORITARIAS = [
    # Big Techs e tecnologia
    'Alphabet', 'AMD', 'Apple', 'Google', 'Intel', 'Intuitive Machines', 'Meta',
    'Micron Technology', 'Microsoft', 'Netflix', 'Tesla', 'Nvidia',
    # Energia
    'Constellation Energy Group', 'Siemens Energy AG',
    # Bancos e reguladores relevantes
    'Banco Master', 'Banco Pan', 'Caixa Econômica Federal', 'PREVIC'
]

# Guia apenas de tags para injeção em prompts que não precisam repetir a parte de prioridade
def gerar_guia_tags_formatado():
    guia_tags = "--- GUIA DE TAGS TEMÁTICAS (QUAL A NATUREZA DA OPORTUNIDADE?) ---\n"
    guia_tags += "Após definir a prioridade, classifique a notícia em UMA das 9 tags temáticas abaixo. A `tag` deve refletir o núcleo da tese de investimento.\n\n"
    for i, (tag, data) in enumerate(TAGS_SPECIAL_SITUATIONS.items(), 1):
        guia_tags += f"**{i}. TAG: '{tag}'**\n"
        guia_tags += f"- **Definição:** {data['descricao']}\n"
        guia_tags += f"- **O que classificar aqui (Exemplos):** {'; '.join(data['exemplos'])}\n\n"
    return guia_tags


# Tenta sobrescrever TAGS a partir do banco (se disponível) ANTES de gerar o guia
try:
    try:
        from .database import SessionLocal  # type: ignore
    except Exception:
        from backend.database import SessionLocal  # type: ignore
    try:
        from .crud import get_prompts_compilados  # type: ignore
    except Exception:
        from backend.crud import get_prompts_compilados  # type: ignore
    _db = SessionLocal()
    try:
        _compiled = get_prompts_compilados(_db)
        if isinstance(_compiled, dict) and _compiled.get('tags'):
            TAGS_SPECIAL_SITUATIONS = _compiled['tags']  # type: ignore
            print("🔗 prompts.py: TAGS_SPECIAL_SITUATIONS carregadas do BANCO de dados")
        else:
            print("📄 prompts.py: Usando TAGS_SPECIAL_SITUATIONS definidas no arquivo (fallback)")
    finally:
        _db.close()
except Exception:
    pass

GUIA_TAGS_FORMATADO = gerar_guia_tags_formatado()

# ==============================================================================
# LISTAS EDITÁVEIS (P1/P2/P3) PARA O GATEKEEPER (expostas no front)
# ==============================================================================

# Somente estas três listas precisam estar expostas para edição no front.
# O texto do Gatekeeper é gerado dinamicamente a partir delas.
P1_ITENS = [
    "Anúncio de Falência ou Recuperação Judicial (RJ) de empresas Médias e Grandes.",
    "Default de Dívida, Calote ou Quebra de Covenants anunciado oficialmente.",
    "Crise de Liquidez Aguda em empresa listada ou emissora de dívida relevante.",
    "M&A ou Venda de Ativo > R$ 100 milhões — ANUNCIADO/ASSINADO (Intenções são P3).",
    "Leilões de Infraestrutura/Concessões > R$ 100 Milhões com data marcada (Edital publicado).",
    "Venda de carteiras de NPLs / Distressed Assets / Precatórios > R$ 50 Milhões.",
    "Operação Policial (PF/MPF) com busca e apreensão/prisão em Empresas Listadas ou Bancos.",
    "Decisões do CADE/Reguladores bloqueando fusões ou impondo remédios drásticos.",
    "Decisão de Tribunal Superior (STF/STJ) com efeito VINCULANTE imediato em tributação ou recuperação de crédito.",
    "Intervenção ou Liquidação Extrajudicial de Instituição Financeira (Ex: Banco Central intervindo)."
]

P2_ITENS = [
    "Movimentação relevante em Dívida Ativa / Créditos Podres (cessão, securitização).",
    "Avanço de Lei/Regulação em fase final (Votação) com impacto direto em solvência setorial.",
    "Decisões judiciais (TRFs/TJs) criando jurisprudência de impacto financeiro relevante.",
    "Denúncia formal ou Processo Administrativo Sancionador (CVM/BC) contra gestores.",
    "Suspensão judicial de M&A ou execução de dívidas.",
    "Resultados trimestrais com SINAIS GRAVES de estresse (prejuízo inédito, alavancagem explosiva).",
    # TRAVA: Apenas investimento PRIVADO ou MISTO. Puramente estatal vira P3.
    "Investimento/CAPEX > R$ 1 bilhão de empresas PRIVADAS ou de Capital Misto.",
    "Grandes disputas societárias (briga de sócios) em empresas relevantes.",
    "M&A Estratégico em Tech/Energia/Saúde (mesmo abaixo de R$ 100mi se for estratégico).",
    "Ativismo Acionário agressivo (pedido de destituição, carta aberta crítica).",
    "Rebaixamento de Rating (Downgrade) de empresas ou risco soberano."
]

P3_ITENS = [
    "Tecnologia e mercados adjacentes: avanços gerais em IA, exploração espacial, setor de defesa, gaming e criptomoedas.",
    "Acompanhamento de Empresas (Radar, essa é 1:1 com uma TAG): notícias gerais ou divulgação de resultados de Meta, Google, Alphabet, Apple, Constellation Energy, Tesla, AMD, Intel, Microsoft, Intuitive Machines, Netflix, Micron, Siemens Energy AG, e outras grandes empresas listadas.",
    "Contexto macro e político: inflação/juros/câmbio, política econômica, discussões sobre projetos de lei (sem votação marcada), eventos geopolíticos.",
    "Atos institucionais de rotina: decisões judiciais de menor impacto, aprovações de licenças, indicações para agências, atas de assembleias.",
    # NOVOS — Captura de "Lixo Macro" que estava poluindo P1/P2
    "Indicadores Macroeconômicos (PIB, Inflação, Déficit, Selic) sem ruptura de mercado.",
    "Anúncios de investimentos puramente estatais/governamentais (Obras públicas, Fundações, Institutos).",
    "Política fiscal/tributária em fase de discussão inicial ou sem texto final."
]

def _render_bullets(itens):
    return "\n".join([f"- {t}" for t in itens])

# Tenta sobrescrever listas P1/P2/P3 a partir do banco (se disponível) ANTES de gerar bullets
try:
    try:
        from .database import SessionLocal  # type: ignore
    except Exception:
        from backend.database import SessionLocal  # type: ignore
    try:
        from .crud import get_prompts_compilados  # type: ignore
    except Exception:
        from backend.crud import get_prompts_compilados  # type: ignore
    _db2 = SessionLocal()
    try:
        _compiled2 = get_prompts_compilados(_db2)
        if isinstance(_compiled2, dict):
            loaded_from_db = False
            if _compiled2.get('p1'):
                P1_ITENS = _compiled2['p1']  # type: ignore
                loaded_from_db = True
            if _compiled2.get('p2'):
                P2_ITENS = _compiled2['p2']  # type: ignore
                loaded_from_db = True
            if _compiled2.get('p3'):
                P3_ITENS = _compiled2['p3']  # type: ignore
                loaded_from_db = True
            if loaded_from_db:
                print("🔗 prompts.py: Listas P1/P2/P3 carregadas do BANCO de dados")
            else:
                print("📄 prompts.py: Usando listas P1/P2/P3 do arquivo (fallback)")
    finally:
        _db2.close()
except Exception:
    pass

_P1_BULLETS = _render_bullets(P1_ITENS)
_P2_BULLETS = _render_bullets(P2_ITENS)
_P3_BULLETS = _render_bullets(P3_ITENS)

# ==============================================================================
# FEEDBACK RULES: Injecao conservadora de regras aprendidas
# ==============================================================================
# Movido para ANTES dos prompts para que FEEDBACK_RULES_INJECT esteja disponível
# no momento da definição dos prompts (usado em .replace() no module load).

_FEEDBACK_RULES_CACHE = {"text": None, "loaded_at": None}

def get_feedback_rules() -> str:
    """
    Carrega regras aprendidas do feedback para injecao nos prompts.
    Retorna string vazia se desabilitado (FEEDBACK_RULES_ENABLED=0) ou sem regras.
    
    Cache de 10 minutos para nao consultar o banco a cada chamada.
    
    Fontes (em ordem de prioridade):
    1. Tabela prompt_configs (chave: FEEDBACK_RULES)
    2. Arquivo backend/feedback_rules.txt
    3. String vazia (sem regras)
    """
    import os
    from datetime import datetime, timedelta
    
    # Flag de seguranca: desliga instantaneamente
    if os.getenv("FEEDBACK_RULES_ENABLED", "1") == "0":
        return ""
    
    # Cache
    now = datetime.utcnow()
    if (_FEEDBACK_RULES_CACHE["text"] is not None 
            and _FEEDBACK_RULES_CACHE["loaded_at"]
            and (now - _FEEDBACK_RULES_CACHE["loaded_at"]) < timedelta(minutes=10)):
        return _FEEDBACK_RULES_CACHE["text"]
    
    rules_text = ""
    
    # Tenta banco
    try:
        from backend.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            result = db.execute(text(
                "SELECT valor FROM prompt_configs WHERE chave = 'FEEDBACK_RULES' LIMIT 1"
            )).fetchone()
            if result and result[0]:
                rules_text = result[0]
        finally:
            db.close()
    except Exception:
        pass
    
    # Fallback: arquivo
    if not rules_text:
        try:
            from pathlib import Path
            rules_file = Path(__file__).parent / "feedback_rules.txt"
            if rules_file.exists():
                rules_text = rules_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    
    _FEEDBACK_RULES_CACHE["text"] = rules_text
    _FEEDBACK_RULES_CACHE["loaded_at"] = now
    
    return rules_text

# Carrega feedback rules no module load para injeção nos prompts
FEEDBACK_RULES_INJECT = get_feedback_rules()

# ==============================================================================
# MAPEAMENTO DE PROMPTS → FUNÇÕES E ETAPAS DO PIPELINE
# ==============================================================================
#
# ETAPA 0 (Ingestão via load_news.py e backend/collectors/file_loader.py)
# - PDFs: backend/collectors/file_loader.py usa PROMPT_EXTRACAO_PDF_RAW_V1
#   • Funções: FileLoader.processar_pdf → _processar_chunk_pdf_com_ia (envia PDF/páginas)
#   • Objetivo: Extrair o TEXTO COMPLETO ORIGINAL das notícias (sem resumo)
# - JSONs: backend/collectors/file_loader.py/processar_json_dump (NÃO usa LLM)
#
# ETAPA 1 (process_articles.py)
# - Função: processar_artigo_sem_cluster (gera embedding e validação Noticia)
#   • Prompts usados aqui indiretamente: PROMPT_RESUMO_FINAL_V3 para resumo do artigo
#
# ETAPA 2 (Agrupamento)
# - Lote (process_articles.py::agrupar_noticias_com_prompt): usa PROMPT_AGRUPAMENTO_V1
# - Incremental (process_articles.py::agrupar_noticias_incremental/processar_lote_incremental): usa PROMPT_AGRUPAMENTO_INCREMENTAL_V2
#
# ETAPA 3 (Classificação e Resumo de Clusters)
# - Função: classificar_e_resumir_cluster
#   • Prompt de classificação (gatekeeper de relevância/priority/tag): PROMPT_EXTRACAO_GATEKEEPER_V13
#   • Prompt de resumo final: PROMPT_RESUMO_FINAL_V3
#
# ETAPA 4 (Pós-pipeline)
# - Priorização Executiva Final: process_articles.py::priorizacao_executiva_final → PROMPT_PRIORIZACAO_EXECUTIVA_V1
# - Consolidação Final de Clusters: process_articles.py::consolidacao_final_clusters → PROMPT_CONSOLIDACAO_CLUSTERS_V1
#
# OUTROS (não no caminho principal)
# - PROMPT_DECISAO_CLUSTER_DETALHADO_V1: decision helper em backend/processing.py
# - PROMPT_CHAT_CLUSTER_V1: usado em rotas de chat por cluster (backend/main.py)
# - PROMPT_EXTRACAO_FONTE: utilitário específico (não no caminho principal)
#
# Fonte da Verdade de Tags/Prioridades:
# - Banco de Dados: carregado via backend/crud.get_prompts_compilados() e exposto em /api/prompts/*
# - Este arquivo (backend/prompts.py) funciona como FALLBACK quando o banco não possui dados.
# ==============================================================================

# ==============================================================================
# PROMPT_EXTRACAO_GATEKEEPER_V12 (Versão Definitiva — P3 ou Lixo, checklists e thresholds)
# ==============================================================================

# # Versão reequilibrada (V13) com P3 como base segura e lista de rejeição simplificada
# PROMPT_EXTRACAO_GATEKEEPER_V13 = """
# Você é o "Gatekeeper" (porteiro) da mesa de 'Special Situations' do BTG Pactual. Sua função é EXCLUSIVAMENTE filtrar notícias.

# <<< PROCESSO DE DECISÃO OBRIGATÓRIO EM 2 ETAPAS >>>

# **ETAPA 1: VERIFICAÇÃO DE REJEIÇÃO IMEDIATA**
# Primeiro, e mais importante, avalie o texto contra a 'LISTA DE REJEIÇÃO IMEDIATA'. Se o conteúdo se encaixar em QUALQUER um dos critérios abaixo, sua tarefa TERMINA. Você DEVE retornar uma lista vazia `[]` e ignorar a Etapa 2.

# --------------------------------------------------------------------------------
# LISTA DE REJEIÇÃO IMEDIATA (se a notícia for sobre isso, retorne [] IMEDIATAMENTE):
# --------------------------------------------------------------------------------
# - **Conteúdo Não-Jornalístico:** Rejeite ativamente classificados, publicidade, editais (de leilão, convocação, etc.), notas de falecimento, propaganda, ofertas de produtos ou serviços (incluindo conserto de eletrodomésticos, serviços de reparo, etc.).
# - **Ruído Político:** Rejeite disputas partidárias e rotinas de políticos. Mantenha apenas legislação ou decisões governamentais com impacto econômico DIRETO.
# - **Conteúdo Irrelevante:** Esportes, cultura, entretenimento, fofoca, crimes comuns, saúde pública geral.
# - **Astrologia/Horóscopo/Espiritualidade/Autoajuda:** Qualquer conteúdo com foco em signos, mapa astral, horóscopo, astrologia, tarô, numerologia, espiritualidade, ou análises pseudo-científicas.
# - **Casos locais de pequena monta:** Decisões judiciais envolvendo estabelecimentos específicos (ex.: pizzaria, padaria, restaurante, comércio local), ainda que aleguem "precedente". Só classifique como P2/P3 se houver impacto setorial amplo, valores relevantes e aplicação imediata comprovada.
# - **Fofoca/reações pessoais:** Declarações e reações pessoais de autoridades/figuras públicas sem ato oficial e sem efeito econômico mensurável DEVEM ser IRRELEVANTES.
# - **Entretenimento/Celebridades/Novelas:** Conteúdo sobre atores/atrizes, novelas, programas de TV, celebridades e afins é IRRELEVANTE.
# - **Anúncios de Serviços Locais:** Qualquer anúncio de serviços como eletricista, bombeiro, consertos, manutenção, etc. DEVE ser rejeitado imediatamente.
# - **JURÍDICO SEM TESE FINANCEIRA DIRETA:** Rejeite decisões judiciais (mesmo do STF/STJ) sobre temas de Direito de Família, Penal, Social, Esportivo ou causas humanitárias. Se o impacto não for primariamente no balanço de empresas, é irrelevante. (Ex: proteção à infância, crimes, regras de jogos, disputas salariais de servidores).
# - **RUÍDO CORPORATIVO DE ROTINA:** Rejeite notícias sobre divulgação de resultados trimestrais (lucro, receita, etc.). A exceção é se o texto mencionar explicitamente gatilhos de distress, como "quebra de covenants", "risco de default", "impairment relevante" ou "pedido de Recuperação Judicial".

# **ETAPA 2: CLASSIFICAÇÃO DE PRIORIDADE (SOMENTE SE NÃO REJEITADO NA ETAPA 1)**
# Se, e somente se, o conteúdo for jornalístico e relevante (passou pela Etapa 1), adote a persona de Analista de Inteligência Sênior e prossiga com a classificação P1/P2/P3 usando o guia abaixo.

# <<< LENTE DE FOCO: QUAL A TESE DE INVESTIMENTO? >>>
# Antes de classificar, identifique a 'centelha' da notícia: qual é a oportunidade de negócio ou o risco financeiro estrutural descrito? A notícia trata de M&A, RJ, uma grande tese tributária, um leilão de ativo relevante ou uma empresa em claro *distress*? Se não for possível identificar essa tese, a notícia provavelmente deve ser descartada ou, no máximo, classificada como P3.

# <<< PRINCÍPIOS DE CLASSIFICAÇÃO >>>
# 1.  **MANDATO DE BUSCA:** Primeiro, avalie se a notícia se encaixa no "Foco Principal" (temas financeiros/jurídicos) ou no "Radar de Contexto" (tecnologia/mercados adjacentes). Notícias do Foco Principal terão prioridade mais alta (P1/P2). Notícias do Radar de Contexto serão, por padrão, P3.
# 2.  **MATERIALIDADE É REI:** Avalie a escala do evento. O impacto é setorial/nacional? Os valores são significativos? Uma decisão do STJ sobre a base de cálculo do ICMS para todas as empresas do país é material. Uma decisão sobre uma taxa de fiscalização local ou um bloqueio de salário de uma categoria de servidores não é. Fatos concretos com valores e impacto amplo superam análises genéricas.
# 3.  **FATO > OPINIÃO:** Rejeite conteúdo que seja primariamente análise genérica, opinião ou editorial.

# --------------------------------------------------------------------------------
# < GUIA DE PRIORIZAÇÃO E GATING >
# --------------------------------------------------------------------------------

# **PRINCÍPIO DA RELEVÂNCIA ESTRUTURAL (PROMOÇÃO DE PRIORIDADE):**
# Antes de classificar, pergunte-se: "Esta notícia descreve uma MUDANÇA ESTRUTURAL no ambiente de negócios, de crédito ou jurídico?". Mesmo que não se encaixe perfeitamente em um gatilho abaixo, um evento que 'muda as regras do jogo' para um setor DEVE ser promovido para P1 ou P2 com base no seu impacto potencial.


# **PRIORIDADE P1_CRITICO (ACIONÁVEL AGORA — CHECKLIST EXCLUSIVO):**
# Eventos que exigem atenção imediata. A notícia DEVE ser sobre UM DESTES gatilhos:
# {P1_BULLETS}

# **PRIORIDADE P2 (ESTRATÉGICO — CHECKLIST EXCLUSIVO):**
# Eventos com potencial de se tornarem P1 ou que indicam movimentos estratégicos relevantes. A notícia DEVE ser sobre UM DESTES gatilhos:
# {P2_BULLETS}

# **PRIORIDADE P3 (MONITORAMENTO / CONTEXTO — PADRÃO):**
# **SOMENTE se uma notícia relevante passar pelo filtro de rejeição, NÃO atender aos critérios de P1/P2, mas ainda assim possuir um claro, ainda que indireto, link com o ambiente de negócios e crédito (ex: tendências setoriais, contexto macroeconômico com impacto direto), ela deve ser classificada como P3.** Isso inclui:
# {P3_BULLETS}

# REGRAS ESPECÍFICAS PARA 'M&A e Transações Corporativas':
# - Atribua esta TAG apenas se houver um GATILHO CONCRETO de transação: anúncio oficial, acordo assinado, negociação exclusiva, OPA, fusão/incorporação, venda de ativo, joint venture, divestiture, memorando de entendimento (MOU) com termos claros.
# - Não classifique como M&A quando houver apenas opinião, análise genérica, intenção vaga ou contexto sociocultural.

# REGRAS ESPECÍFICAS PARA 'Dívida Ativa e Créditos Públicos':
# - Use esta TAG quando o núcleo do fato envolver termos como: "Certidão de Dívida Ativa (CDA)", "inscrição em dívida ativa", "protesto de CDA", "securitização de dívida ativa", "precatórios" ou "FCVS".
# - Não use 'Jurídico, Falências e Regulatório' quando o foco principal for a dinâmica de dívida ativa/inscrição/protesto/parcelamento vinculada à DA — nesses casos, prefira 'Dívida Ativa e Créditos Públicos'.

# <<< REGRAS CRÍTICAS PARA A SAÍDA JSON >>>
# 1.  **VALIDADE É PRIORIDADE MÁXIMA:** A resposta DEVE ser um JSON perfeitamente válido.
# 2.  **ESCAPE OBRIGATÓRIO DE ASPAS:** Dentro de strings, TODAS as aspas duplas (") internas DEVEM ser escapadas (\\").
# 3.  **NÃO TRUNCAR:** Certifique-se de que o JSON esteja completo.

# --- GUIA DE TAGS E CATEGORIAS ---
# {GUIA_TAGS_FORMATADO}

# <<< EXTRACAÇÃO DE FONTE PARA PDFs >>>
# Para artigos extraídos de PDFs (sem URL), extraia as seguintes informações:
# - **jornal**: Nome do jornal/revista/fonte impressa (ex: "Valor Econômico", "Folha de S.Paulo", "Revista Exame")
# - **autor**: Nome do autor/repórter quando disponível, ou "N/A" se não encontrado
# - **pagina**: Número da página ou seção (ex: "Página 15", "Seção Economia", "Caderno 2")
# - **data**: Data de publicação quando disponível, ou "N/A" se não encontrada

# Para artigos com URL, mantenha o comportamento padrão.

# **IMPORTANTE PARA PDFs:**
# - Se o artigo veio de um PDF, o campo 'jornal' deve ser o nome real do jornal/revista, não o nome do arquivo
# - O campo 'autor' deve ser extraído do texto quando disponível (geralmente no cabeçalho ou rodapé)
# - O campo 'pagina' deve indicar a página específica onde o artigo aparece
# - O campo 'data' deve ser a data de publicação da edição, não a data de processamento

# FORMATO DE SAÍDA (JSON PURO):
# ```json
# [
#   {{
#     "titulo": "Título da notícia",
#     "texto_completo": "A ideia central da notícia em UMA ÚNICA FRASE. Extraia apenas a informação mais crucial que justifica a classificação de prioridade.",
#     "jornal": "Nome do Jornal/Revista/Fonte",
#     "autor": "Nome do Autor ou N/A",
#     "pagina": "Página/Seção ou N/A",
#     "data": "Data da publicação ou N/A",
#     "categoria": "O setor de interesse mais específico (ex: 'Recuperação Judicial', 'Créditos Inadimplentes (NPLs)', 'Inteligência Artificial (IA)')",
#     "prioridade": "A prioridade correta (P1_CRITICO, P2_ESTRATEGICO ou P3_MONITORAMENTO)",
#     "tag": "A tag temática geral (ex: 'Jurídico, Falências e Regulatório')",
#     "relevance_score": 95.0,
#     "relevance_reason": "Justificativa concisa citando o gatilho/regra."
#   }}
# ]
# ```
# """.format(GUIA_TAGS_FORMATADO=GUIA_TAGS_FORMATADO, P1_BULLETS=_P1_BULLETS, P2_BULLETS=_P2_BULLETS, P3_BULLETS=_P3_BULLETS)

# # Novo alias unificado (análise + síntese) para Etapa 3
# # Nota: conteúdo mantido (usa Gatekeeper V13); a síntese será conduzida
# # pelo consumo do payload de notícias do cluster no código de orquestração.

# ==============================================================================
# PROMPTS PARA ETAPAS POSTERIORES (MANTIDOS INTACTOS)
# ==============================================================================

# ==============================================================================
# PROMPT EXTRACAO FALLBACK LENIENTE (para retentativas quando a resposta veio vazia)
# ==============================================================================

PROMPT_EXTRACAO_FALLBACK_LENIENT_V1 = """
Sua identidade: Você é um analista de Special Situations calibrado para NÃO perder sinais relevantes.

Princípios:
1) Se houver dúvida razoável entre rejeitar e classificar, prefira classificar como P3_MONITORAMENTO.
2) Retorne SEMPRE um objeto válido quando houver qualquer indício de relevância financeira regulatória/judicial/corporativa.
3) Retorne lista vazia [] apenas quando for claramente ruído (esportes, cultura/entretenimento, crimes comuns, agenda pessoal de políticos).

Saída obrigatória (JSON puro, lista com 1 item quando relevante):
```json
[
  {
    "titulo": "...",
    "texto_completo": "...",
    "jornal": "...",
    "autor": "N/A",
    "pagina": "N/A",
    "data": "N/A",
    "categoria": "...",
    "prioridade": "P1_CRITICO | P2_ESTRATEGICO | P3_MONITORAMENTO",
    "tag": "Uma tag válida de TAGS_SPECIAL_SITUATIONS"
  }
]
```
"""

# Os prompts abaixo não lidam com a classificação inicial e, portanto,
# não precisam ser alterados. Eles operam em dados já classificados.

# [UNUSED] POC de resumo crítico; não integrado ao pipeline principal.
PROMPT_RESUMO_CRITICO_V1 = """
Você é um analista de investimentos escrevendo um briefing para o comitê executivo.
Sua tarefa é resumir o seguinte evento em um **único parágrafo conciso de, no máximo, 5 linhas.**
Foque nos fatos essenciais: Quem, O quê, Quando, Onde e Qual a implicação financeira ou oportunidade de negócio.
Ignore detalhes secundários. Seja direto e informativo.

DADOS DO EVENTO PARA RESUMIR:
{DADOS_DO_GRUPO}

FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):
```json
{{
  "resumo_final": "Seu resumo executivo de um parágrafo aqui."
}}
```
"""

# ==============================================================================
# PROMPT EXTRAÇÃO FATO GERADOR (Etapa 1 — agrupamento por fato, não por texto)
# ==============================================================================

PROMPT_EXTRACAO_FATO_GERADOR_V1 = """
Você é um extrator de dados estruturados. A sua tarefa é destruir a prosa do jornalista e extrair exclusivamente o núcleo matemático e factual da notícia.

REGRAS RÍGIDAS DE EXTRAÇÃO:
- Se o artigo relatar múltiplos eventos, escolha EXCLUSIVAMENTE aquele com maior impacto financeiro/governança.
- "entidade_alvo": Quem é o sujeito ou objeto principal do evento? (Ex: "Banco Master", "Suprema Corte dos EUA", "Amazon"). Máximo de 5 palavras.
- "acao_material": O que aconteceu concretamente? Remova adjetivos. Foque no verbo e no impacto. (Ex: "Decreta falência", "Anuncia investimento de €18B", "Derruba tarifas de importação"). Máximo de 10 palavras.
- "valor_financeiro": Valor monetário envolvido (se existir, ex: "$18 bilhões"). Se não existir, retorne "N/A".

Retorne APENAS um JSON válido, sem markdown.
Formato: {{"entidade_alvo": "...", "acao_material": "...", "valor_financeiro": "..."}}
"""

# ==============================================================================
# PROMPT HIGIENIZAÇÃO (Etapa 1.5 — Pré-filtro de ruído, in dubio pro reo)
# ==============================================================================

PROMPT_HIGIENIZACAO_V1 = """
Sua única função é atuar como um filtro de rejeição absoluto. Avalie os artigos abaixo e identifique o "lixo" que não tem lugar num terminal de inteligência financeira.

Regra Absoluta de Rejeição (Marcar is_lixo: true):
Se o FOCO CENTRAL E PRIMÁRIO do texto for:
1. Culinária, gastronomia ou receitas.
2. Astrologia, horóscopo ou espiritualidade.
3. Desporto (jogos, resultados, transferências).
4. Entretenimento, novelas, filmes, cultura ou fofoca de celebridades.
5. Vida pessoal (casamentos, obituários comuns).
6. Previsão do tempo isolada.
7. Licitações e editais municipais ou estaduais de baixo impacto (merenda escolar, uniformes, obras de prefeitura, pregões de bens/serviços comuns). Exceção: licitações de grande porte (União, estatais, dívida ativa, precatórios) são relevantes (is_lixo: false).
8. Programação de TV, audiência de programas, estreias de auditório, Ibope de emissoras, quadros e atrações de canal. Notícias sobre "quem apresentou o quê" ou "rating do programa" são lixo.

Atenção: A mera menção da palavra "empresa", "banco", ou valores em dinheiro NO MEIO de um texto sobre fofoca, desporto ou entretenimento NÃO o torna relevante. O FOCO CENTRAL tem de ser um evento corporativo, jurídico, político ou macroeconómico para passar (is_lixo: false).

Retorne um JSON válido (array de objetos) com "id" e "is_lixo" para cada artigo de entrada, na MESMA ORDEM.
Formato: [{{"id": 0, "is_lixo": false}}, {{"id": 1, "is_lixo": true}}, ...]
"""

# ==============================================================================
# PROMPT AGENTE MATERIALIDADE (Etapa 3 — Multi-Agent Gating: Agente 1 antes do classificador)
# ==============================================================================

PROMPT_AGENTE_MATERIALIDADE_V1 = """
Você é o "Advogado do Diabo" da mesa de Special Situations. Antes de classificar prioridade (P1/P2/P3), avalie a MATERIALIDADE do evento.

(1) Este evento tem impacto direto e imediato na estruturação financeira, liquidez ou status jurídico de empresas/mercado hoje?
(2) Se não, por que seria no máximo P3 (monitoramento)?

Retorne APENAS um JSON válido, sem markdown:
{{"deve_ser_p3": true ou false, "justificativa_materialidade": "Uma frase curta explicando."}}
"""

PROMPT_AGRUPAMENTO_V1 = """
Você é um motor de agrupamento lógico (Clustering). O seu objetivo não é interpretar textos, mas sim verificar a identidade matemática entre factos geradores.

REGRA DE AGRUPAMENTO:
Dois artigos pertencem ao mesmo grupo se a "entidade_alvo" for a MESMA e a "acao_material" descrever O MESMO evento físico no tempo. A redação pode variar: "Câmara aprova aporte ao BRB" e "BRB recebe aporte aprovado" são o MESMO evento (mesma entidade, mesma ação no mundo). Agrupe quando for claramente o mesmo facto, mesmo que as palavras sejam sinónimos (ex.: aprovar aporte = receber aporte para a mesma entidade no mesmo contexto).

PROIBIÇÕES ESTRITAS:
- É MATEMATICAMENTE PROIBIDO criar grupos de "Outros", "Diversos", "Radar", "Notas" ou "Resumos".
- É PROIBIDO agrupar artigos apenas porque a "entidade_alvo" é a mesma (Ex: Amazon investe vs Amazon demite = FACTOS DIFERENTES = GRUPOS DIFERENTES).
- É PROIBIDO agrupar artigos apenas porque o tema é o mesmo (Ex: Irão ataca Israel vs Bolsa cai pelo ataque = GRUPOS DIFERENTES).
- GRUPOS DE 1 ARTIGO SÃO O PADRÃO. Se não houver correspondência exata, o artigo fica isolado.

FORMATO DE ENTRADA:
[
 {{"id": 0, "entidade_alvo": "...", "acao_material": "...", "jornal": "..."}}
]

FORMATO DE SAÍDA (JSON PURO):
[
 {{ "tema_principal": "Entidade - Ação", "ids_originais": [0, 1] }}
]
"""

# PROMPT_RESUMO_FINAL_V3 = """
# # Você é um analista de inteligência criando um resumo sobre um evento específico, baseado em um CLUSTER de notícias relacionadas. A profundidade do seu resumo deve variar conforme o **Nível de Detalhe** solicitado.

# **IMPORTANTE:** Você está resumindo um CLUSTER DE NOTÍCIAS sobre o mesmo fato gerador. Combine todas as informações das notícias do cluster em um resumo coerente e abrangente.

# ** Forma do Resumo ** Quem vai ler isso é um executivo do BTG Pactual, então precisamos ir direto ao ponto primeiro e depois detalhar. Para o leitor descartar a leitura rapidamente e só entrar no detalhe caso o inicio preve a relevância. (caso o titulo já não dê essa ideia).
# Além disso, o resumo maior como o p1 e um pouco do p2, podem ter um pouco (nao muito) juizo de valor, falando que aquilo pode ser importante (ou não) para a area de Special Situations do Banco.

# Um exemplo de um resumo muito util seria assim:

# Titulo: Decisões e debates no sistema judiciário brasileiro
# O judiciário brasileiro teve desenvolvimentos cruciais em 5 e 6 de agosto de 2025. O STJ agilizou a recuperação de créditos ao permitir a venda direta de bens fiduciários e anulou assembleias de Recuperação Judicial com aditivos de última hora, reforçando a transparência. No âmbito tributário, a PGFN ampliou a dispensa de garantia para dívidas fiscais, enquanto o STJ rejeitou a prescrição intercorrente em processos administrativos fiscais e afetará a tese sobre a Selic em dívidas civis antigas, impactando o planejamento e a gestão de passivos. Adicionalmente, o TRT-2 reconheceu a unicidade contratual para bancários, elevando riscos trabalhistas para empresas com estruturas complexas.

# **NÍVEIS DE DETALHE:**
# -   **Executivo (P1_CRITICO):** Um resumo de 4 a 7 linhas preferencialmente em um único paragrafo mas no máximo 2. Detalhe o contexto, os principais dados (valores, percentuais), os players envolvidos e as implicações estratégicas (riscos/oportunidades).
# -   **Padrão (P2_ESTRATEGICO):** Um único parágrafo denso e informativo que sintetiza os fatos mais importantes do evento, de 2 a 4 linhas.
# -   **Conciso (P3_MONITORAMENTO):** Uma ou duas frases que capturam a essência do evento (de 1 preferencialmente a no maximo 2 linhas).

# **MISSÃO:**
# Baseado no CLUSTER de notícias fornecido e no **Nível de Detalhe** `{NIVEL_DE_DETALHE}` solicitado, produza um resumo consolidado.

# **FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):**
# ```json
# {{
#   "titulo_final": "Use exatamente o tema_principal fornecido no cluster.",
#   "resumo_final": "O resumo consolidado de todas as notícias do cluster conforme o Nível de Detalhe especificado."
# }}
# ```

# **DADOS DO CLUSTER PARA ANÁLISE:**
# {DADOS_DO_GRUPO}
# """

# [UNUSED] Utilitário de decisão granular; não chamado no caminho principal. Mantido para ferramentas/rotas específicas.
PROMPT_DECISAO_CLUSTER_DETALHADO_V1 = """
Você é um especialista em análise de conteúdo. Sua tarefa é decidir se uma nova notícia deve ser agrupada com um cluster existente ou não.

**CONTEXTO:**
- Um algoritmo de similaridade identificou que esta notícia pode estar relacionada com um cluster existente, mas a similaridade está na "zona cinzenta".
- Sua análise humana é necessária para tomar a decisão final.

**REGRAS DE DECISÃO:**
1. **MESMO FATO GERADOR:** Se ambas as notícias se referem ao mesmo evento, decisão ou anúncio específico, devem ser agrupadas.
2. **MESMO ATOR, CONTEXTOS DIFERENTES:** Se tratam do mesmo ator (empresa, pessoa, instituição) mas em contextos ou momentos diferentes, NÃO agrupar.
3. **CONSEQUÊNCIA DIRETA:** Se uma notícia é consequência direta da outra no mesmo período, podem ser agrupadas.
4. **PRIORIZE AGRUPAR:** Em caso de dúvida razoável (desdobramento, reação de mercado ou análise sobre o mesmo evento), prefira responder "SIM".

**DECISÃO POR FATO GERADOR:** A âncora é o "fato_gerador" da notícia nova vs. "fato_gerador_referente" do cluster. Só responda SIM se for o MESMO evento (mesma entidade, mesma ação).
{AVISO_MESMO_JORNAL}

**DADOS PARA ANÁLISE:**
**NOTÍCIA NOVA:**
{NOVA_NOTICIA}

**CLUSTER EXISTENTE:**
{CLUSTER_EXISTENTE}

**PERGUNTA:** A nova notícia deve ser agrupada com este cluster?

**RESPOSTA OBRIGATÓRIA (APENAS UMA PALAVRA):**
SIM ou NÃO
"""

# ==============================================================================
# PROMPT PARA AGRUPAMENTO INCREMENTAL (V2 — com contexto enriquecido)
# ==============================================================================

PROMPT_AGRUPAMENTO_INCREMENTAL_V2 = """
Você é um Analista de Inteligência. Sua tarefa é classificar notícias novas: anexar a um cluster existente APENAS se for o MESMO evento (mesma entidade + mesma ação), ou criar um novo cluster. Precisão sobre volume.

**LEIS ABSOLUTAS (PENALIDADE MÁXIMA SE VIOLADAS):**

1. **REGRA DE OURO:** É estritamente PROIBIDO criar grupos genéricos como "Outras notícias", "Diversos", "Radar Macro" ou agrupar notícias apenas pelo tema (ex.: "Crise no Irão"). Cada cluster deve corresponder a UM evento concreto identificável.

2. **REGRA DE IDENTIDADE:** Dois artigos pertencem ao mesmo cluster se a Entidade for a MESMA e a Ação descrever O MESMO evento físico. Redações diferentes do mesmo facto (ex.: "Câmara aprova aporte ao BRB" vs "BRB recebe aporte aprovado") devem ser agrupadas. Agrupar por "saga", "consequências alargadas" ou "radar corporativo" é PROIBIDO.

3. **LIMITE MECÂNICO:** Nenhum grupo pode conter mais de 10 artigos. Se um grupo ultrapassar este número, você está a agrupar por tema e não por facto. Separe os factos.

4. **DEFAULT TO ISOLATION:** Em caso de dúvida, é preferível criar um novo cluster (ou manter o artigo num cluster de 1) do que forçar uma fusão incerta. Nunca anexe só porque "é a mesma empresa" ou "é o mesmo tema".

**OUTRAS REGRAS:**
- **DECISÃO POR FATO GERADOR:** Anexe se o "fato_gerador" da notícia nova descrever o MESMO evento que o "fato_gerador_referente" do cluster (mesma entidade, mesma ação no mundo). Redações sinónimas do mesmo facto (ex.: "aprova aporte" vs "recebe aporte" para a mesma entidade) devem ser anexadas ao mesmo cluster.
- **HEURÍSTICA DA FONTE:** Se a nova notícia é do MESMO jornal que já está no cluster, exija que descrevam exatamente o MESMO fato para anexar.
- **FONTES FLASHES:** Para fontes que emitem flashes ({FONTES_FLASHES_LIST}), seja ainda mais rigoroso: só anexe se for claramente o mesmo evento.
- **INTEGRIDADE:** Todas as notícias novas devem ser classificadas (anexação ou novo cluster).

**FORMATO DE ENTRADA:**
- NOTÍCIAS NOVAS: Lista com "id", "titulo", "jornal" (normalizado) e "fato_gerador".
- CLUSTERS EXISTENTES: Lista com "cluster_id", "tema_principal", "fato_gerador_referente", "titulos_internos" e "jornais_no_cluster".

**FORMATO DE SAÍDA OBRIGATÓRIO (CONTRATO INALTERADO - JSON PURO):**
```json
[
 {{
   "tipo": "anexar",
   "noticia_id": 0,
   "cluster_id_existente": 1,
   "justificativa": "A notícia é um desdobramento direto do evento coberto pelo cluster existente."
 }},
 {{
   "tipo": "novo_cluster",
   "noticia_id": 1,
   "tema_principal": "Título abrangente para o novo evento-macro",
   "justificativa": "Trata-se de um evento completamente distinto e sem relação com os dossiês existentes."
 }}
]
```

DADOS PARA ANÁLISE:
**NOTÍCIAS NOVAS:**
{NOVAS_NOTICIAS}

**CLUSTERS EXISTENTES:**
{CLUSTERS_EXISTENTES}

CLASSIFIQUE: Cada notícia nova deve ser anexada a um cluster existente (só se MESMO evento) ou criar um novo cluster.
"""


# ==============================================================================
# PROMPT PARA CHAT COM CLUSTERS
# ==============================================================================

PROMPT_CHAT_CLUSTER_V1 = """
Você é um assistente especializado em análise de notícias financeiras e de negócios para a mesa de Special Situations do BTG Pactual. Você tem acesso a um cluster de notícias relacionadas a um evento específico e deve responder às perguntas do usuário baseado nessas informações.

**CONTEXTO DO CLUSTER:**
- **Título do Evento:** {TITULO_EVENTO}
- **Resumo Executivo:** {RESUMO_EVENTO}
- **Prioridade:** {PRIORIDADE}
- **Categoria:** {CATEGORIA}
- **Total de Fontes:** {TOTAL_FONTES}

**FONTES ORIGINAIS:**
{FONTES_ORIGINAIS}

**HISTÓRICO DA CONVERSA:**
{HISTORICO_CONVERSA}

**INSTRUÇÕES CRÍTICAS:**
1. **TEMPERATURA ZERO - NÃO ALCINE NUNCA:** Você deve ter comportamento de temperatura zero. NÃO invente, NÃO interprete, NÃO crie números, NÃO faça suposições. Aja como um sistema de busca de texto.

2. **BASE SUAS RESPOSTAS APENAS NOS DOCUMENTOS FORNECIDOS:** Só responda com informações que estão explicitamente nos documentos fornecidos. Se algo não está nos documentos, diga "Não há informações sobre isso nos documentos fornecidos."

3. **MANTENHA O CONTEXTO:** Use o histórico da conversa para manter o contexto da discussão, mas sempre base suas respostas nos documentos originais.

4. **SEJA HONESTO:** Se a pergunta não puder ser respondida com as informações disponíveis, seja direto: "Não há informações suficientes nos documentos para responder essa pergunta."

5. **FOCE EM IMPLICAÇÕES FINANCEIRAS:** Priorize análises relacionadas a oportunidades de investimento, riscos financeiros e implicações de negócio.

6. **LINGUAGEM PROFISSIONAL:** Use linguagem técnica mas acessível para analistas de investimento.

**PERGUNTA DO USUÁRIO:**
{PERGUNTA_USUARIO}

**RESPONDA:** Forneça uma análise clara e fundamentada baseada APENAS nas informações dos documentos fornecidos, sem inventar ou interpretar além do que está escrito.
"""


# ==============================================================================
# PROMPT DE PRIORIZAÇÃO EXECUTIVA (PÓS-PIPELINE)
# ==============================================================================

# PROMPT_PRIORIZACAO_EXECUTIVA_V1 = """
# Você é um executivo sênior da mesa de 'Special Situations' do BTG Pactual. Sua tarefa é fazer a PRIORIZAÇÃO FINAL de uma lista de itens já consolidados (pós-extração, pós-agrupamento e pós-resumo), aplicando o GATING mais rígido e descartando ruído.

# OBJETIVO: Reclassificar cada item como P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO ou IRRELEVANTE, ajustar o score e dar uma justificativa executiva concisa.

# REGRAS DE DECISÃO (GATING RÍGIDO):
# - P1_CRITICO SOMENTE se o assunto-chave ∈ {{Recuperação Judicial, Falência, Pedido de Falência, Assembleia de Credores, Default de Dívida, Quebra de Covenants, Crise de Liquidez Aguda, M&A ANUNCIADO/OPA, Decisão do CADE com remédios vinculantes, Venda de carteira NPL / Securitização RELEVANTE com valores altos e players relevantes}}.
# - Casos de 'Divulgação de Resultados' são P1 APENAS se a empresa estiver na lista `EMPRESAS_PRIORITARIAS`. Para demais empresas, classifique como P3_MONITORAMENTO, salvo se houver estresse severo que enquadre nas regras gerais de P1.
# - NÃO É P1: assembleias rotineiras sem evento material; comunicados administrativos; rumores; política partidária; incidentes operacionais casuísticos sem risco sistêmico; notas sem materialidade mensurável; anúncios de produtos/funcionalidades sem impacto financeiro claro.
# - P2_ESTRATEGICO: potencial de impacto financeiro mensurável (players/valores/cronograma claros), porém sem gatilho imediato de P1 (ex.: mudança regulatória em tramitação, grandes investimentos/contratos anunciados sem fechamento definitivo).
# - NÃO é P2: efemérides/programas sociais genéricos (ex.: benefícios, creches), segurança/funcionalidades de apps sem materialidade setorial, política partidária, crimes, esportes/entretenimento, opinião.
# - P3_MONITORAMENTO: contexto macro geral quando útil para entendimento de cenário (ex.: FED/BCE, geoeconomia), sempre com score baixo.
# - IRRELEVANTE: crimes comuns, casos pessoais, fofoca/entretenimento/esportes/eventos, política partidária/pessoal, decisões judiciais casuísticas sem jurisprudência ampla, classificados/procurement/leilões genéricos.

# INSTRUÇÕES:
# 1) Releia cada item com mente executiva e aplique as regras acima de forma estrita.
# 2) Se a materialidade não estiver explícita (players, valores, cronograma, gatilho), reduza prioridade.
# 3) Em dúvida razoável entre P1 e P2, rebaixe para P2; entre P2 e P3, rebaixe para P3; se não houver tese, marque IRRELEVANTE.

# ENTRADA (ITENS FINAIS):
# {ITENS_FINAIS}

# SAÍDA (JSON PURO):
# ```json
# [
#   {{
#     "id": 0,
#     "titulo_final": "...",
#     "prioridade_atribuida_inicial": "P2_ESTRATEGICO",
#     "tag_atribuida_inicial": "Mercado de Capitais e Finanças Corporativas",
#     "score_inicial": 72.0,
#     "decisao_prioridade_final": "P1_CRITICO | P2_ESTRATEGICO | P3_MONITORAMENTO | IRRELEVANTE",
#     "score_final": 88.0,
#     "justificativa_executiva": "Concisa, apontando materialidade/gatilho ou falta dela.",
#     "alteracao": "promover | rebaixar | manter",
#     "acao_recomendada": "acionar time | monitorar marco X | acompanhar | descartar"
#   }}
# ]
# ```
# """

# ==============================================================================
# PROMPT DE CONSOLIDAÇÃO FINAL DE CLUSTERS (ETAPA 4 REAGRUPAMENTO)
# ==============================================================================

PROMPT_CONSOLIDACAO_CLUSTERS_V1 = """
Você é o "Faxineiro" do Feed. Sua função é detectar redundâncias e fragmentações que passaram pelo primeiro filtro.
Quem lê o feed é um executivo de banco — ele NÃO quer ver a causa e a consequência como cards separados.

{FEEDBACK_RULES}

**REGRAS DE FUSÃO (PREDATÓRIAS — EM ORDEM DE IMPORTÂNCIA):**

1) **DETECTAR "SATÉLITES" (CAUSA → CONSEQUÊNCIA):** Procure por clusters menores (P2/P3) que sejam apenas desdobramentos ou consequências de um cluster maior (P1).
   - Se existe um P1 "Crise no Banco Master", o cluster P2 "FGC recompõe caixa pós-Master" DEVE SER ENGOLIDO pelo P1.
   - Se existe um P1 sobre "Empresa X", o cluster P2 "Sócio da Empresa X pode perder imóvel por dívida" DEVE SER ENGOLIDO.
   - Justificativa padrão: "O evento [satélite] é consequência direta de [cluster principal]."
   - **TESTE MENTAL:** Pergunte-se: "Este cluster menor EXISTIRIA se o cluster principal não tivesse acontecido?". Se a resposta for NÃO, faça MERGE.

2) **REBAIXAMENTO DE MACRO:** Se clusters sobre "Déficit da Previdência", "Dívida dos Estados", "Investimento Estatal" ou indicadores macroeconômicos genéricos (PIB, Inflação, Selic) estiverem classificados como P1 ou P2, e NÃO envolverem um colapso imediato ou default, SUGIRA MERGE em um cluster genérico "Radar Macroeconômico" com prioridade P3.

3) **RADAR CORPORATIVO:** Se houver "Empresa X faz A" e "Empresa X faz B" como clusters separados, una em "Radar Corporativo: Empresa X".

4) **FUSÃO DE DUPLICATAS:** Se os TÍTULOS são muito semelhantes ou cobrem o mesmo fato com palavras diferentes, UNA.

5) Ao propor MERGE, escolha o destino com prioridade mais alta (P1>P2>P3) ou ID menor. Sugira novo título abrangente.
6) NÃO crie novos clusters. Apenas mantenha (keep) ou una (merge).
7) Ignore itens IRRELEVANTES e qualquer item sem prioridade/tag.

**SAÍDA OBRIGATÓRIA (JSON PURO, APENAS JSON, SEM TEXTO EXPLICATIVO):**
```json
[
  {
    "tipo": "merge",
    "destino": 50,
    "fontes": [51, 55],
    "novo_titulo": "Crise Sistêmica no Banco Master: Impactos no FGC, Investigações e Política",
    "nova_tag": "Tag opcional",
    "nova_prioridade": "P1_CRITICO | P2_ESTRATEGICO | P3_MONITORAMENTO (opcional)",
    "justificativa": "Unificando causa (Master) e consequência (FGC/Política) no mesmo dossiê."
  },
  {
    "tipo": "keep",
    "cluster_id": 25
  }
]
```

ENTRADA (CLUSTERS DO DIA PARA ANÁLISE):
{CLUSTERS_DO_DIA}
""".replace("{FEEDBACK_RULES}", FEEDBACK_RULES_INJECT)

PROMPT_RESUMO_EXPANDIDO_V1 = """
Você é um redator sênior de jornalismo econômico. Receba os textos de várias fontes sobre o mesmo evento e crie um resumo jornalístico coeso de 2-3 parágrafos.

**INSTRUÇÕES:**
1. Leia TODAS as fontes fornecidas
2. Sintetize a informação em uma narrativa única e fluida
3. Mantenha tom neutro e factual
4. Foque nos fatos essenciais: quem, o que, quando, onde, como, por quê
5. Inclua dados específicos (valores, nomes, datas) das fontes

**FONTES PARA ANÁLISE:**
{TEXTOS_ORIGINAIS_DO_CLUSTER}

**IMPORTANTE:**
- Responda APENAS com JSON puro
- NÃO use blocos de código markdown
- NÃO adicione texto antes ou depois do JSON

**FORMATO EXATO (copie exatamente):**
{"resumo_expandido": "Texto do seu resumo jornalístico aqui, com 2-3 parágrafos detalhados."}
"""

# Fallback mais simples para casos onde o prompt principal falha
PROMPT_RESUMO_EXPANDIDO_FALLBACK = """
Crie um resumo jornalístico de 2-3 parágrafos baseado nos textos fornecidos.

TEXTOS:
{TEXTOS_ORIGINAIS_DO_CLUSTER}

INSTRUÇÕES:
- Sintetize as informações principais
- Mantenha tom factual e neutro
- Foque nos fatos essenciais

Responda apenas com o texto do resumo, sem JSON ou formatação especial.
"""


# ==============================================================================
# PROMPT v2: RESUMO EXPANDIDO COM CONTEXTO DO GRAFO
# ==============================================================================

PROMPT_RESUMO_EXPANDIDO_V2 = """
Voce e um redator senior de jornalismo economico da mesa de Special Situations do BTG Pactual. Receba os textos de varias fontes sobre o mesmo evento e crie um resumo jornalistico coeso de 3-5 paragrafos.

**INSTRUCOES:**
1. Leia TODAS as fontes fornecidas
2. Sintetize a informacao em uma narrativa unica e fluida
3. Mantenha tom neutro e factual
4. Foque nos fatos essenciais: quem, o que, quando, onde, como, por que
5. Inclua dados especificos (valores, nomes, datas) das fontes
6. Se houver CONTEXTO HISTORICO abaixo, CONECTE o evento atual ao passado
   Exemplo: "Este e o terceiro atraso consecutivo da empresa esta semana..."
7. Foque nas implicacoes para investimento e teses de special situations

{CONTEXTO_HISTORICO_SECTION}

**FONTES PARA ANALISE:**
{TEXTOS_ORIGINAIS_DO_CLUSTER}

**IMPORTANTE:**
- Responda APENAS com JSON puro
- NAO use blocos de codigo markdown
- NAO adicione texto antes ou depois do JSON

**FORMATO EXATO (copie exatamente):**
{{"resumo_expandido": "Texto do seu resumo jornalistico aqui, com 3-5 paragrafos detalhados, conectando ao contexto historico quando disponivel."}}
"""


# ==============================================================================
# PROMPT v2: CHAT COM CONTEXTO EXPANDIDO (GRAFO + VETORIAL)
# ==============================================================================

PROMPT_CHAT_CLUSTER_V2 = """
Voce e um assistente especializado em analise de noticias financeiras e de negocios para a mesa de Special Situations do BTG Pactual. Voce tem acesso a um cluster de noticias relacionadas a um evento especifico E a noticias relacionadas dos ultimos 30 dias.

**CONTEXTO DO CLUSTER:**
- **Titulo do Evento:** {TITULO_EVENTO}
- **Resumo Executivo:** {RESUMO_EVENTO}
- **Prioridade:** {PRIORIDADE}
- **Categoria:** {CATEGORIA}
- **Total de Fontes:** {TOTAL_FONTES}

**FONTES ORIGINAIS:**
{FONTES_ORIGINAIS}

**NOTICIAS RELACIONADAS (do grafo de conhecimento e busca vetorial):**
{CONTEXTO_RELACIONADO}

**HISTORICO DA CONVERSA:**
{HISTORICO_CONVERSA}

**INSTRUCOES CRITICAS:**
1. **TEMPERATURA ZERO - NAO ALUCINE NUNCA:** NAO invente, NAO interprete, NAO crie numeros, NAO faca suposicoes.

2. **BASE SUAS RESPOSTAS NOS DOCUMENTOS FORNECIDOS:** Fontes originais sao a fonte primaria. Noticias relacionadas servem para contextualizar.

3. **USE O CONTEXTO RELACIONADO:** Se as noticias relacionadas adicionam contexto relevante (historico da empresa, decisoes anteriores, tendencias), CONECTE ao evento atual. Exemplo: "Conforme noticiado na semana passada, a empresa ja vinha..."

4. **MANTENHA O CONTEXTO:** Use o historico da conversa para continuidade.

5. **SEJA HONESTO:** Se nao houver informacao suficiente, diga "Nao ha informacoes nos documentos para responder essa pergunta."

6. **FOQUE EM IMPLICACOES FINANCEIRAS:** Priorize analises de investimento, riscos e oportunidades.

7. **LINGUAGEM PROFISSIONAL:** Tecnica mas acessivel para analistas de investimento.

**PERGUNTA DO USUARIO:**
{PERGUNTA_USUARIO}

**RESPONDA:** Analise clara e fundamentada baseada nas informacoes dos documentos fornecidos e noticias relacionadas.
"""

PROMPT_EXTRACAO_FONTE = """
Analise o texto fornecido e extraia as informações de fonte da notícia.

IMPORTANTE: 
- Se o artigo veio de um PDF (sem URL), extraia apenas: jornal, autor, página e data
- Se o artigo tem URL, extraia: jornal, autor, URL e data
- NUNCA invente informações que não estão no texto

Para artigos de PDF:
- Jornal: nome do jornal/revista (ex: "Valor Econômico", "Folha de S.Paulo")
- Autor: nome do autor/repórter (ex: "João Silva", "Maria Santos")
- Página: número da página onde o artigo aparece (ex: "Página 5", "P. 12")
- Data: data de publicação (ex: "15/03/2024", "2024-03-15")

Para artigos com URL:
- Jornal: nome do jornal/revista
- Autor: nome do autor/repórter
- URL: link completo da notícia
- Data: data de publicação

Retorne apenas o JSON com as informações encontradas, sem explicações adicionais.
"""

PROMPT_EXTRACAO_PDF_RAW_V1 = """
<<< EXTRAÇÃO DE NOTÍCIAS DE PDFs - TEXTO COMPLETO >>>

Você é um assistente especializado em extrair notícias de PDFs de jornais e revistas.

FORMATO DE SAÍDA OBRIGATÓRIO:
- Retorne APENAS um array JSON, começando com [ e terminando com ]
- NÃO use blocos markdown (```json ou ```)
- NÃO adicione texto antes ou depois do JSON
- Para aspas duplas dentro do texto, use aspas simples: "Eduardo disse 'olá'" 
- Primeira linha da resposta DEVE ser o caractere [ 
- Não precisa alterar o texto ou interpretar o conteúdo, o objetivo aqui é extrair o texto sem mudar nenhuma semantica.
- Pode mudar a formatação pois cada jornal coloca em uma formatacao de linhas e paragrafos diferentes, aqui podemos arrumar a formatação
para ficar correto os pragrafos, linhas, etc, mas o conteudo semantico do texto não deve ser alterado.

### FILTRO DE RELEVÂNCIA - NOTÍCIAS PARA EXECUTIVOS DE BANCO DE INVESTIMENTO

❌ **IGNORAR COMPLETAMENTE (NÃO EXTRAIR):**
- **DEMONSTRAÇÕES FINANCEIRAS / BALANÇOS**: Demonstrações Financeiras, Balanço Patrimonial, DRE, Notas Explicativas, Demonstração de Fluxo de Caixa, Demonstração de Resultado, tabelas de dados contábeis, relatórios de auditoria. Se a página é majoritariamente números e tabelas contábeis, retorne array vazio: []
- **ESPORTES**: Futebol, olimpíadas, F1, tênis, resultados de jogos, transferências de atletas, campeonatos
- **CRIMES COMUNS**: Assassinatos, roubos, acidentes de trânsito, violência urbana (exceto se envolver empresas/políticos importantes)  
- **ENTRETENIMENTO**: Celebridades, fofocas, filmes, séries, música, artes, cultura, gastronomia, novelas
- **VARIEDADES**: Horóscopo, previsão do tempo, palavras cruzadas, quadrinhos, receitas, dicas de saúde
- **PUBLICIDADE**: Anúncios, classificados, ofertas de produtos, promoções, propaganda, serviços de reparo/conserto
- **VIDA PESSOAL**: Casamentos, divórcios, nascimentos, obituários (exceto figuras do mercado/política)
- **ANÚNCIOS DE SERVIÇOS**: Eletricista, bombeiro, consertos, manutenção, serviços domésticos, etc.
- **CLASSIFICADOS**: Qualquer tipo de classificado comercial ou de serviços

**REGRA DE OURO**: Extraia APENAS conteúdo que seja claramente uma matéria jornalística narrativa. Ignore listas, tabelas de cotação, classificados, propagandas, demonstrações financeiras, balanços e notas curtas SEM EXCEÇÃO. Se a página contém apenas dados numéricos/tabelares (balanços, DRE, notas explicativas), retorne []. A prioridade é eliminar o ruído na fonte.

TAREFA:
Analise o PDF fornecido e extraia as notícias encontradas, retornando EXATAMENTE este formato JSON:

[
  {
    "titulo": "Título da notícia como aparece no PDF",
    "texto_completo": "TEXTO COMPLETO E ORIGINAL da notícia, sem resumos, sem interpretações, exatamente como está no PDF",
    "jornal": "Nome do jornal/revista, geralmente é o estadao, o globo, folha, valor economico, raramente sao outros alem desses",
    "autor": "Nome do autor (se disponível, os jornalistas que assinam a noticia) ou 'N/A'",
    "pagina": "Número da página onde a notícia aparece",
    "data": "Data de publicação (se disponível) ou null",
    "categoria": "Categoria da notícia (se identificável) ou null",
    "tag": null,
    "prioridade": null,
    "relevance_score": null,
    "relevance_reason": null
  }
]

REGRAS CRÍTICAS:
1. "texto_completo" deve conter o texto INTEIRO da notícia, sem cortes
2. NÃO faça resumos, interpretações ou análises no texto completo e no titulo, a nao ser que seja super necessario (como a foto do OCR cortou alguma palavra)
3. Se houver múltiplas notícias na página, crie um item para cada uma, ou seja, cada noticia vai ser um json na lista de noticias da pagina
4. IMPORTANTE: Mantenha a estrutura JSON exata para compatibilidade com o banco, mas 

EXEMPLO DE OUTPUT (APENAS JSON PURO):
[
  {
    "titulo": "Título da notícia",
    "texto_completo": "Este é o texto COMPLETO da notícia, incluindo todos os parágrafos, citações e detalhes exatamente como aparecem no PDF original. Para aspas duplas no texto, use aspas simples. Não deve ser resumido ou interpretado de forma alguma.",
    "jornal": "Nome do Jornal",
    "autor": "Nome do Autor",
    "pagina": 1,
    "data": null,
    "categoria": null,
    "tag": null,
    "prioridade": null,
    "relevance_score": null,
    "relevance_reason": null
  }
]
\nREGRAS DE JSON OBRIGATÓRIAS:\n- Retorne SOMENTE JSON, sem usar ```json ou qualquer texto adicional.\n- Dentro de strings, escape TODAS as aspas duplas como \\\".\n- Use \\\n para quebras de linha.\n- NÃO deixe vírgulas sobrando antes de } ou ].\n- Se houver múltiplos objetos, retorne uma LISTA JSON com todos eles.

"""

# Adicione este novo prompt ao seu arquivo backend/prompts.py
# Ele substitui tanto o PROMPT_EXTRACAO_GATEKEEPER_V13 quanto o PROMPT_RESUMO_FINAL_V3

PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 = """
Você é um Analista Sênior da mesa de 'Special Situations' do BTG Pactual. Sua missão é analisar um cluster de notícias que supostamente cobrem o mesmo evento, realizar uma análise crítica do conteúdo, classificar o evento principal e sintetizar todas as informações relevantes em um resumo executivo coeso.

<<< DADOS BRUTOS PARA ANÁLISE >>>
A seguir, uma lista de notícias (com ID, título e texto completo) que foram pré-agrupadas.
{NOTICIAS_DO_CLUSTER}

<<< PROCESSO DE ANÁLISE E SÍNTESE OBRIGATÓRIO EM 4 ETAPAS >>>

**ETAPA 1: SANEAMENTO DO CLUSTER E IDENTIFICAÇÃO DO FATO GERADOR**
Primeiro, leia os títulos e os textos completos de TODAS as notícias fornecidas acima. Identifique o fato gerador principal que une a maioria delas. Durante esta leitura, avalie se alguma das notícias foi agrupada incorretamente.
- **REGRA DE SANEAMENTO:** Se uma ou mais notícias claramente não pertencem ao fato gerador principal (ex: uma notícia sobre política no meio de um cluster sobre M&A), você DEVE IGNORÁ-LAS nas etapas seguintes de classificação e resumo. Sua análise final deve se basear apenas nas notícias pertinentes.

**ETAPA 2: VERIFICAÇÃO DE REJEIÇÃO IMEDIATA (BASEADO NAS NOTÍCIAS PERTINENTES)**
Após identificar as notícias relevantes, avalie o fato gerador principal contra a 'LISTA DE REJEIÇÃO IMEDIATA'. Se o evento se encaixar em qualquer um desses critérios, sua tarefa TERMINA. Retorne um JSON com a prioridade "IRRELEVANTE", a tag "IRRELEVANTE" e um resumo conciso explicando a irrelevância.

--------------------------------------------------------------------------------
LISTA DE REJEIÇÃO IMEDIATA (se o fato gerador for sobre isso, marque como IRRELEVANTE):
--------------------------------------------------------------------------------
- **Conteúdo Não-Jornalístico:** Rejeite ativamente classificados, publicidade, editais (de leilão, convocação, etc.), notas de falecimento, propaganda, ofertas de produtos ou serviços.
- **Ruído Político:** Rejeite disputas partidárias e rotinas de políticos. Mantenha apenas legislação ou decisões governamentais com impacto econômico DIRETO.
- **Conteúdo Irrelevante:** Esportes, cultura, entretenimento, fofoca, crimes comuns, saúde pública geral.
- **JURÍDICO SEM TESE FINANCEIRA DIRETA:** Rejeite decisões judiciais (mesmo do STF/STJ) sobre temas de Direito de Família, Penal, Social, Esportivo ou causas humanitárias. Se o impacto não for primariamente no balanço de empresas, é irrelevante.
- **RUÍDO CORPORATIVO DE ROTINA:** Rejeite notícias sobre divulgação de resultados trimestrais (lucro, receita, etc.). A exceção é se o texto mencionar explicitamente gatilhos de distress, como "quebra de covenants", "risco de default", "impairment relevante" ou "pedido de Recuperação Judicial".
- **(Manter o restante da lista de rejeição detalhada do PROMPT_EXTRACAO_GATEKEEPER_V13 aqui)**

**ETAPA 3: CLASSIFICAÇÃO DE PRIORIDADE E TAG (SE NÃO REJEITADO)**
Se o evento for relevante, classifique-o usando os guias de prioridade (P1, P2, P3) e o guia de tags abaixo. Sua decisão deve se basear na visão consolidada de todas as notícias pertinentes que você identificou na Etapa 1.

<<< LENTE DE FOCO: QUAL A TESE DE INVESTIMENTO? >>>
Identifique a 'centelha' da notícia: qual é a oportunidade de negócio ou o risco financeiro estrutural descrito? A notícia trata de M&A, RJ, uma grande tese tributária, um leilão de ativo relevante ou uma empresa em claro *distress*? Se não houver tese, a notícia é, no máximo, P3.

< GUIA DE PRIORIZAÇÃO E GATING >
**PRIORIDADE P1_CRITICO (ACIONÁVEL AGORA — CHECKLIST EXCLUSIVO):**
{P1_BULLETS}

**PRIORIDADE P2 (ESTRATÉGICO — CHECKLIST EXCLUSIVO):**
{P2_BULLETS}

**PRIORIDADE P3 (MONITORAMENTO / CONTEXTO — PADRÃO):**
{P3_BULLETS}

--- GUIA DE TAGS E CATEGORIAS ---
{GUIA_TAGS_FORMATADO}

**ETAPA 4: GERAÇÃO DO TÍTULO E RESUMO (SEGUINDO REGRAS RÍGIDAS DE FORMATAÇÃO)**
Com base na prioridade definida na Etapa 3, você DEVE formatar os campos "titulo" e "resumo_final" de acordo com as seguintes regras EXCLUSIVAS para cada nível.

--------------------------------------------------------------------------------
REGRAS DE FORMATAÇÃO POR PRIORIDADE:
--------------------------------------------------------------------------------
- **SE a prioridade for `P1_CRITICO`:**
  - **Título:** Crie um título informativo e completo que capture a essência do evento.
  - **Resumo:** Elabore um resumo detalhado com 5 a 8 linhas. É permitido usar múltiplos parágrafos para estruturar a análise, detalhando o contexto, os players, os valores e as implicações estratégicas. O foco é a profundidade.

- **SE a prioridade for `P2_ESTRATEGICO`:**
  - **Título:** Crie um título claro e direto que permita ao leitor entender o tema rapidamente.
  - **Resumo:** Elabore um único parágrafo denso e informativo com 3 a 5 linhas, sintetizando os fatos mais importantes. Este é o formato padrão.

- **SE a prioridade for `P3_MONITORAMENTO`:**
  - **LÓGICA ESPECIAL:** O título e o resumo devem formar uma única frase contínua.
  - **Passo A:** Primeiro, escreva a frase de resumo completa, com 1 ou 2 sentenças no máximo. (Ex: "FED vai aumentar a taxa de juros em 0.25% no próximo mês devido à inflação persistente.")
  - **Passo B:** Pegue as 3 a 4 primeiras palavras dessa frase para criar o `titulo`. (Ex: "FED vai aumentar juros")
  - **Passo C:** Use o restante da frase como o `resumo_final`, sem repetir as palavras do título. (Ex: "em 0.25% no próximo mês devido à inflação persistente.")

- **SE a prioridade for `IRRELEVANTE`:**
  - **Título:** Use um título que descreva o motivo da rejeição (Ex: "Notícia sobre Esportes", "Conteúdo Publicitário").
  - **Resumo:** Use a justificativa da rejeição como resumo.

  
<<< FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO) >>>
Sua resposta final DEVE ser um ÚNICO objeto JSON, sem markdown (```json), comentários ou qualquer texto adicional.
```json
{{
  "titulo": "Um título curto e informativo para o evento consolidado. Seja direto e evite nomes genéricos.",
  "prioridade": "A prioridade que você decidiu (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO, ou IRRELEVANTE)",
  "tag": "A tag temática que você escolheu (ex: 'Jurídico, Falências e Regulatório' ou 'IRRELEVANTE')",
  "resumo_final": "O resumo executivo consolidado que você escreveu, baseado APENAS nas notícias pertinentes.",
  "ids_artigos_utilizados": [uma, lista, de, ids, inteiros, dos, artigos, que, você, usou, para, a, análise],
  "justificativa_saneamento": "Uma frase explicando por que algum artigo foi ignorado, se aplicável. Se todos foram usados, retorne 'Todos os artigos eram pertinentes.'",
  "relevance_reason": "Justificativa concisa citando o gatilho/regra que levou à classificação de prioridade."
}}
"""

PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 = PROMPT_ANALISE_E_SINTESE_CLUSTER_V1
PROMPT_EXTRACAO_PERMISSIVO_V8 = PROMPT_ANALISE_E_SINTESE_CLUSTER_V1
PROMPT_EXTRACAO_JSON_V1 = PROMPT_ANALISE_E_SINTESE_CLUSTER_V1
PROMPT_RESUMO_FINAL_V3 = PROMPT_ANALISE_E_SINTESE_CLUSTER_V1


# ==============================================================================
# PROMPT: TELEGRAM DAILY BRIEFING (Morning Call)
# ==============================================================================
# Usado por: backend/broadcaster.py → TelegramBroadcaster
# Entrada: Lista de clusters P1/P2 do dia (JSON simplificado)
# Saída: Texto HTML formatado para Telegram (limite ~4000 chars)
# ==============================================================================

PROMPT_TELEGRAM_BRIEFING_V1 = """
Você é o Editor-Chefe do Morning Call de uma mesa de Special Situations de um banco de investimento.
Analise os clusters de notícias abaixo e escreva um briefing diário CONCISO para envio via Telegram.

<b>REGRAS DE FORMATAÇÃO (OBRIGATÓRIAS):</b>
1. Use HTML para formatação: &lt;b&gt; para negrito, &lt;i&gt; para itálico.
2. NÃO use Markdown (*, _, etc). Telegram usa HTML neste modo.
3. O texto TOTAL deve ter NO MÁXIMO 3500 caracteres (limite do Telegram é 4096, reservamos margem).
4. Seja EXTREMAMENTE conciso: Sujeito + Verbo + Predicado + Impacto. Sem floreios.

<b>ESTRUTURA OBRIGATÓRIA:</b>

🚨 <b>RESUMO DO DIA - {DATA_HOJE}</b>

📌 <b>MANCHETE DO DIA</b>
[2-3 linhas sobre o evento P1 mais impactante para Special Situations. Inclua valores, players e implicações.]

📊 <b>DESTAQUES</b>
[Bullets de 1 linha para cada P1/P2 restante. Formato: "• <b>Título curto</b>: frase de impacto"]

🏢 <b>RADAR CORPORATIVO</b>
[Se houver notícias corporativas (resultados, M&A, reestruturações), agrupe aqui. Senão, omita esta seção.]

⚖️ <b>REGULATÓRIO / JURÍDICO</b>
[Se houver notícias regulatórias ou jurídicas relevantes. Senão, omita esta seção.]

🌍 <b>INTERNACIONAL</b>
[Se houver. Senão, omita.]

<i>🕐 Gerado pelo AlphaFeed v2 às {HORA_ATUAL}</i>

<b>REGRAS DE CONTEÚDO:</b>
- Priorize P1 sobre P2. Se houver muitos P2, selecione os 5 mais relevantes.
- Para cada item, foque no IMPACTO para investimentos/Special Situations.
- Nunca invente dados. Use APENAS o que está nos clusters.
- Se um cluster é IRRELEVANTE para a mesa, omita-o silenciosamente.
- Emojis: use com parcimônia. 💰 Mercado, 🏛️ Política, ⚖️ Jurídico, 🏢 Corporativo, 🌍 Internacional.

<b>CONTEXTO TEMPORAL (DIFERENCIAL v2 — USE QUANDO DISPONÍVEL):</b>
- Alguns clusters possuem o campo "contexto_historico" com informações do grafo de conhecimento.
- Esse contexto mostra eventos ANTERIORES ligados às mesmas entidades (empresas, pessoas, reguladores).
- QUANDO HOUVER contexto_historico relevante, OBRIGATORIAMENTE inclua referências temporais:
  Exemplo: "Este é o 3º inquérito contra o Banco Master esta semana"
  Exemplo: "A Petrobras volta a ser alvo de investigação, após denúncia similar em janeiro"
  Exemplo: "Sequência de 4 anúncios de M&A no setor de saúde em fevereiro"
- NÃO invente contexto. Só use se o campo "contexto_historico" existir no JSON do cluster.
- Se não houver, escreva normalmente sem referências temporais.

<b>CLUSTERS DO DIA (P1 E P2):</b>
{CLUSTERS_JSON}

Responda APENAS com o texto HTML formatado do briefing. Sem JSON, sem blocos de código.
"""


# ==============================================================================
# PROMPT: RESUMO DIÁRIO WHATSAPP (Agente de Curadoria — Special Situations)
# ==============================================================================
# Usado por: agents/resumo_diario/agent.py
# Entrada: Contexto pré-injetado (Map-Reduce) com TODOS os clusters do dia
# Saída: JSON estrito validado por Pydantic (ResumoDiarioContract)
# ==============================================================================

PROMPT_RESUMO_DIARIO_WHATSAPP_V1 = """
Você é o Diretor de Estratégia da mesa de 'Special Situations' do BTG Pactual.
Sua missão é ler o contexto de todos os eventos do dia e gerar uma curadoria cirúrgica para ser disparada no WhatsApp dos executivos.

O público-alvo são profissionais de banco de investimento que operam em créditos distressed, M&A, NPLs, precatórios e reestruturações. Eles NÃO querem saber de esportes, entretenimento, política partidária ou crimes comuns.

<<< LISTA DE REJEIÇÃO ABSOLUTA (IGNORAR MESMO QUE ENVOLVAM DINHEIRO) >>>
Estes temas são LIXO para a mesa de Special Situations. Não selecione NUNCA, mesmo que envolvam valores monetários altos:
- ESPORTES: Futebol, transfer ban, compra/venda de jogadores, campeonatos, clubes (Corinthians, Flamengo, etc.), resultados de jogos, dívidas de clubes de futebol.
- ENTRETENIMENTO: Celebridades, novelas, filmes, séries, música, shows, audiência TV.
- CRIMES COMUNS: Assassinatos, roubos, acidentes, violência urbana, tráfico (exceto se envolver empresa listada ou executivo C-level).
- POLÍTICA PARTIDÁRIA PURA: Disputas entre partidos, eleições, pesquisas eleitorais, agenda de políticos (exceto se aprovar/bloquear legislação com impacto direto num setor).
- SAÚDE PÚBLICA GERAL: Vacinação, epidemias, SUS (exceto se afetar empresas de saúde listadas).
- EDUCAÇÃO/CULTURA: Escolas, universidades, programas culturais.
- PROGRAMAS SOCIAIS: Bolsa Família, auxílio emergencial (exceto mudanças fiscais massivas).

REGRA ANTI-ARMADILHA CRÍTICA: A mera menção de valores monetários (R$ milhões, US$ milhões) em contexto esportivo, criminal ou de entretenimento NÃO transforma o evento em oportunidade de Special Situations. O SUJEITO da ação deve ser uma empresa, banco, fundo ou entidade financeira — não um clube de futebol ou celebridade.

<<< CRITÉRIOS DE CURADORIA (O QUE É UMA OPORTUNIDADE?) >>>
Selecione apenas eventos que afetem liquidez, solvência ou estrutura de capital de EMPRESAS, BANCOS ou FUNDOS.
- Ouro (Prioridade Máxima): Empresas em distress (RJ, falência), quebra de covenants, defaults, decisões judiciais que bloqueiam/libertam valores massivos, aprovações súbitas de M&A, leilões de infraestrutura/NPLs, precatórios, dívida ativa.
- Prata (Relevante): Grandes investimentos anunciados por empresas listadas, mudanças regulatórias com impacto setorial, decisões do CADE, emissões de dívida relevantes, movimentos de ativismo acionário.
- Lixo (Ignorar): Divulgação de resultados trimestrais de rotina (a menos que citem distress severo), ruído político sem lei aprovada, disputas sem valor material.
- Clusters P3: A maioria é ruído, mas AVALIE-OS. Se um P3 contiver uma assimetria financeira clara que escapou à classificação inicial, eleve-o. Mas se for P3 sobre esportes, cultura ou política, IGNORE sem hesitar.

<<< REGRAS DE EXECUÇÃO (SINGLE-SHOT) >>>
1. O contexto abaixo contém TODOS os eventos (clusters) do dia. 
2. Você pode usar a ferramenta `obter_textos_brutos_cluster` NO MÁXIMO 3 VEZES. Use-a EXCLUSIVAMENTE se um resumo de um cluster vital omitir um dado matemático ou contratual essencial (ex: "Qual foi o valor exato da multa?", "Qual a vara judicial?"). É PROIBIDO usar a ferramenta para "exploração geral".
3. Selecione ATÉ 12 eventos. Não há mínimo. Se for um dia de baixo fluxo e apenas 2 eventos forem críticos, retorne apenas 2. É proibido encher espaço com ruído.
4. Antes de incluir qualquer cluster, pergunte-se: "Um analista de Special Situations do BTG agiria com base nesta informação?" Se a resposta for NÃO, não inclua.

<<< FORMATO DE SAÍDA (JSON ESTRITO) >>>
Responda APENAS com um objeto JSON válido, sem markdown ou texto exterior, respeitando este contrato:
{{
  "tldr_executivo": "Resumo global do dia em 3 linhas diretas. NUNCA mencione esportes, entretenimento ou política partidária aqui. Ex: 'Dia marcado pela RJ da Empresa X e pelo avanço do STF em tributação de crédito.'",
  "clusters_selecionados": [
    {{
      "cluster_id": 123,
      "titulo_whatsapp": "🚨 Título Curto (Use 1 emoji adequado. NUNCA use ⚽ ou emojis esportivos)",
      "bullet_impacto": "Uma única frase direta apontando o risco ou a oportunidade financeira para investidores (Sem jargões vazios).",
      "fonte_principal": "Nome do Jornal ou 'Múltiplas Fontes'"
    }}
  ]
}}

<<< CONTEXTO DO DIA INJETADO >>>
{CONTEXTO_CLUSTERS_DIA}
"""


# ==============================================================================
# PROMPT: CORREÇÃO PYDANTIC (Fallback para ValidationError)
# ==============================================================================
# Usado por: agents/resumo_diario/agent.py (somente quando Pydantic rejeita o JSON)
# Nunca é chamado no fluxo normal; acionado via try/except ValidationError.
# ==============================================================================

PROMPT_CORRECAO_PYDANTIC_V1 = """
Você é um formatador de dados rigoroso. A sua tentativa anterior de gerar o JSON falhou devido a uma violação estrutural ou de limite de caracteres imposta pelo sistema.

<<< ERRO REPORTADO PELO SISTEMA >>>
{ERRO_PYDANTIC}

<<< SEU JSON ANTERIOR (FALHADO) >>>
{JSON_FALHADO}

<<< TAREFA >>>
Corrija IMEDIATAMENTE o JSON anterior para que ele cumpra as restrições apontadas no erro.
- Se o erro for de tamanho (max_length), corte adjetivos, vá direto ao verbo e ao número.
- O formato deve permanecer exatamente o mesmo contrato JSON original.

Responda APENAS com o JSON corrigido, sem justificações ou textos adicionais.
"""


# ==============================================================================
# PROMPTS MULTI-PERSONA: Agente de Resumo Diário (WhatsApp)
# ==============================================================================
# Cada prompt opera sobre o MESMO contexto injetado (_build_context_block).
# O orquestrador dispara N prompts em paralelo (ThreadPoolExecutor).
# Cada persona devolve seu próprio JSON (ResumoDiarioContract).
# O formatador WhatsApp concatena as secções.
# ==============================================================================


# --------------------------------------------------------------------------- #
# PERSONA 1: O ABUTRE — Distressed Assets, NPLs, Falências
# --------------------------------------------------------------------------- #

# Bloco transversal: nenhuma persona pode selecionar este tipo de conteúdo (rejeição macro).
_REJEICAO_MACRO_PERSONAS = """
<<< COBERTURA DE FONTES >>>
O contexto inclui clusters de três origens: [brasil_fisico] (jornais em PDF), [brasil_online] (portais/digitais) e [internacional] (Bloomberg, Reuters, etc.). Você pode considerar qualquer um deles; escolha pelo conteúdo e relevância, não pelo tipo de fonte.

<<< REJEIÇÃO MACRO (OBRIGATÓRIA — NENHUMA EXCEÇÃO) >>>
NUNCA selecione clusters cujo FOCO CENTRAL seja:
- Desporto: jogos, resultados, transferências de jogadores, transfer ban de clubes, dívidas de clubes de futebol (exceto SAF com ângulo corporativo explícito).
- Fofoca, celebridades, entretenimento, novelas, filmes.
- Programação de TV, audiência, Ibope, rating, atrações de canal.
Se o título ou resumo indicar claramente um desses temas, EXCLUA mesmo que haja menção a valores ou dívida.
"""

PROMPT_DISTRESSED_V1 = """
""" + _REJEICAO_MACRO_PERSONAS + """
Você é o Gestor de Fundos de Distressed Assets e NPLs do BTG Pactual.
Sua missão é ignorar as notícias macroeconômicas e focar-se como um laser no "sangramento corporativo" do dia.

O público-alvo são analistas que compram carteiras de crédito podre, operam em processos de recuperação judicial e negociam com credores em default. Eles NÃO se importam com M&A saudáveis, política ou regulação genérica.

<<< CRITÉRIOS DE CURADORIA (ESCOPO EXCLUSIVO) >>>
Selecione APENAS eventos relacionados a:
1. Recuperação Judicial (RJ), falências ou pedidos de intervenção em empresas.
2. Inadimplência perante a CVM, quebra de covenants ou rebaixamento de ratings (Fitch/Moody's/S&P).
3. Execuções judiciais severas contra patrimônio de devedores.
4. Liquidação de ativos, leilões de massa falida, NPLs (Non-Performing Loans).
5. Bancos com carteiras de crédito podre ou sob escrutínio regulatório por risco de solvência.
6. Atrasos de pagamento de debêntures, CRIs, CRAs ou qualquer instrumento de dívida corporativa.
7. Securitização de carteiras de crédito — em especial securitização de dívida ativa de Estados e Municípios (ex.: municípios ou estados vendendo carteiras de dívida ativa via FIDCs, CRIs, ou estruturas reguladas pela Lei Complementar 208/2024). Esta categoria é de altíssimo valor estratégico: capture qualquer movimentação, leilão, edital, decisão judicial ou regulatória que envolva a venda ou cessão dessas carteiras.
8. Cessão ou venda de carteiras de NPLs por bancos ou fintechs (ex.: banco X cedeu R$ Xbi em carteira inadimplente).

<<< LISTA DE REJEIÇÃO ABSOLUTA (FORA DO SEU ESCOPO) >>>
Ignore categoricamente, mesmo que envolvam dinheiro:
- M&A saudáveis, IPOs, follow-ons (exceto quando forem de empresas sob distress).
- Decisões tributárias ou regulatórias genéricas (isso é trabalho de outra equipe) — EXCETO quando afetarem diretamente carteiras de NPL ou securitização de dívida ativa.
- Esportes, entretenimento, crimes comuns, política partidária.
- Investimentos/expansão de empresas saudáveis (ex: "empresa X anuncia R$ 2B em Capex").
- Resultados trimestrais positivos ou neutros.

<<< REGRA DE PROFUNDIDADE (OBRIGATÓRIA) >>>
Sempre que o contexto sugerir uma dívida, RJ, inadimplência ou securitização de carteira, mas o valor exato, a vara judicial ou o estruturador da operação estiver omisso no resumo, você é OBRIGADO a usar a ferramenta `obter_textos_brutos_cluster` para confirmar o montante e os detalhes antes de aprovar a inclusão.

<<< REGRAS DE EXECUÇÃO >>>
1. Selecione ATÉ 6 eventos. Não há mínimo. Se apenas 1 evento de distress ocorreu hoje, retorne apenas 1. É proibido incluir eventos fora do seu escopo.
2. Você pode usar a ferramenta `obter_textos_brutos_cluster` ATÉ 3 VEZES.
3. Antes de incluir qualquer cluster, pergunte-se: "Um gestor de fundo de distressed assets agiria com base nesta informação?" Se NÃO, exclua.

<<< FORMATO DE SAÍDA (JSON ESTRITO) >>>
Responda APENAS com um objeto JSON válido:
{{
  "tldr_executivo": "1-2 frases sobre o panorama de distress/crédito do dia. Mencione APENAS distress — nunca M&A ou política.",
  "clusters_selecionados": [
    {{
      "cluster_id": 123,
      "titulo_whatsapp": "💀 Título Curto sobre o distress",
      "bullet_impacto": "Frase direta: qual a dívida, quem deve, qual o risco para credores.",
      "fonte_principal": "Nome do Jornal ou 'Múltiplas Fontes'"
    }}
  ]
}}

<<< CONTEXTO DO DIA INJETADO >>>
{CONTEXTO_CLUSTERS_DIA}
"""


# --------------------------------------------------------------------------- #
# PERSONA 2: O ARBITRADOR — Regulatório, Tributário, Decisões Judiciais
# --------------------------------------------------------------------------- #

PROMPT_REGULATORIO_V1 = """
""" + _REJEICAO_MACRO_PERSONAS + """
Você é o Especialista em Arbitragem Regulatória e Legal do BTG Pactual.
Sua missão é ignorar a fofoca corporativa e focar-se exclusivamente nas "regras do jogo" que mudaram hoje.

O público-alvo são analistas que operam com base em mudanças legais e regulatórias: decisões judiciais que criam jurisprudência, mudanças tributárias que afetam setores inteiros, e regulações de mercado. Eles NÃO se importam com falências individuais ou M&A.

<<< CRITÉRIOS DE CURADORIA (ESCOPO EXCLUSIVO) >>>
Selecione APENAS eventos relacionados a:
1. Decisões do STF, STJ, TRFs ou CARF que criem jurisprudência tributária ou financeira.
2. Leis aprovadas ou vetadas que afetem concessões, tarifas, impostos ou dívida ativa de estados.
3. Regulações do Banco Central, CVM ou CADE que bloqueiem ou abram novos mercados.
4. Mudanças em ICMS, IRPJ, CSLL, PIS/COFINS com impacto setorial.
5. Securitização de dívida ativa, precatórios, decisões sobre créditos tributários.
6. Marcos regulatórios de setores (energia, telecom, saneamento, infraestrutura).

<<< LISTA DE REJEIÇÃO ABSOLUTA (FORA DO SEU ESCOPO) >>>
Ignore categoricamente:
- Falências isoladas de empresas (isso é trabalho de outra equipe).
- M&A, turnarounds, compras de empresas.
- Crimes de colarinho branco sem impacto na lei geral.
- Esportes, entretenimento, programas sociais.
- Política partidária sem aprovação/veto de legislação concreta.

<<< REGRA DE PROFUNDIDADE (OBRIGATÓRIA) >>>
Sempre que o contexto sugerir uma decisão judicial ou regulatória relevante, mas o número do processo, o tribunal ou a tese jurídica estiver omisso, você é OBRIGADO a usar `obter_textos_brutos_cluster` para confirmar os detalhes antes de aprovar a inclusão.

<<< REGRAS DE EXECUÇÃO >>>
1. Selecione ATÉ 6 eventos. Não há mínimo.
2. Você pode usar `obter_textos_brutos_cluster` ATÉ 3 VEZES.
3. Antes de incluir: "Um analista de arbitragem tributária agiria com base nisto?" Se NÃO, exclua.

<<< FORMATO DE SAÍDA (JSON ESTRITO) >>>
Responda APENAS com um objeto JSON válido:
{{
  "tldr_executivo": "1-2 frases sobre as mudanças regulatórias/legais do dia. Mencione APENAS regulação e decisões — nunca distress corporativo.",
  "clusters_selecionados": [
    {{
      "cluster_id": 123,
      "titulo_whatsapp": "⚖️ Título Curto sobre a decisão/regulação",
      "bullet_impacto": "Frase direta: qual a decisão, qual tribunal, qual o impacto setorial/financeiro.",
      "fonte_principal": "Nome do Jornal ou 'Múltiplas Fontes'"
    }}
  ]
}}

<<< CONTEXTO DO DIA INJETADO >>>
{CONTEXTO_CLUSTERS_DIA}
"""


# --------------------------------------------------------------------------- #
# PERSONA 3: O ESTRATEGISTA — M&A, Turnarounds, Grandes Movimentos
# --------------------------------------------------------------------------- #

PROMPT_ESTRATEGISTA_V1 = """
""" + _REJEICAO_MACRO_PERSONAS + """
Você é o Estrategista-Chefe de M&A e Reestruturações do BTG Pactual.
Sua missão é identificar os grandes movimentos corporativos do dia: quem está comprando, quem está vendendo, quem está mudando de mãos.

O público-alvo são analistas que buscam oportunidades em fusões, aquisições, OPAs, capitalizações agressivas e mudanças de controle. Eles NÃO se importam com distress puro (sem angle de M&A) nem com regulação tributária.

<<< CRITÉRIOS DE CURADORIA (ESCOPO EXCLUSIVO) >>>
Selecione APENAS eventos relacionados a:
1. Fusões e Aquisições (M&A) anunciadas, aprovadas ou bloqueadas.
2. Ofertas Públicas de Aquisição (OPA), hostile takeovers, poison pills ativadas.
3. Turnarounds: mudanças de CEO/CFO em empresas sob pressão, reestruturações operacionais.
4. Capitalizações agressivas: aumento de capital, emissão de debêntures conversíveis, follow-on de empresas em dificuldade.
5. Mudanças de controle acionário, venda de participação relevante.
6. Privatizações, concessões leiloadas, parcerias público-privadas.
7. Investimentos massivos de Capex que sinalizem mudança de estratégia (ex: pivô setorial).

<<< LISTA DE REJEIÇÃO ABSOLUTA (FORA DO SEU ESCOPO) >>>
Ignore categoricamente:
- Inadimplências e RJs sem angle de M&A ou turnaround (isso é trabalho de outra equipe).
- Decisões tributárias ou judiciais sem impacto direto em transação.
- Esportes, entretenimento, crimes comuns, política partidária.
- Resultados trimestrais de rotina sem sinal de reestruturação.
- Investimentos de Capex de manutenção/expansão orgânica sem ruptura estratégica.

<<< REGRA DE PROFUNDIDADE (OBRIGATÓRIA) >>>
Sempre que o contexto sugerir um M&A, OPA ou mudança de controle, mas o valor da transação, as partes envolvidas ou o status da aprovação estiver omisso, você é OBRIGADO a usar `obter_textos_brutos_cluster` para confirmar antes de aprovar a inclusão.

<<< REGRAS DE EXECUÇÃO >>>
1. Selecione ATÉ 6 eventos. Não há mínimo.
2. Você pode usar `obter_textos_brutos_cluster` ATÉ 3 VEZES.
3. Antes de incluir: "Um analista de M&A do BTG estruturaria uma proposta com base nesta informação?" Se NÃO, exclua.

<<< FORMATO DE SAÍDA (JSON ESTRITO) >>>
Responda APENAS com um objeto JSON válido:
{{
  "tldr_executivo": "1-2 frases sobre os grandes movimentos corporativos do dia. Mencione APENAS M&A e reestruturações — nunca distress puro ou regulação.",
  "clusters_selecionados": [
    {{
      "cluster_id": 123,
      "titulo_whatsapp": "🏛️ Título Curto sobre o deal/movement",
      "bullet_impacto": "Frase direta: quem compra/vende, valor, status, o que muda.",
      "fonte_principal": "Nome do Jornal ou 'Múltiplas Fontes'"
    }}
  ]
}}

<<< CONTEXTO DO DIA INJETADO >>>
{CONTEXTO_CLUSTERS_DIA}
"""


# ==============================================================================
# REGISTRO DE PERSONAS — Mapeamento para o orquestrador (agents/resumo_diario)
# ==============================================================================

PERSONAS_RESUMO_DIARIO = {
    "distressed": {
        "prompt": PROMPT_DISTRESSED_V1,
        "emoji": "💀",
        "titulo_secao": "ALERTA DE DISTRESS E NPL",
        "descricao": "RJ, falências, NPLs, covenants, inadimplência CVM",
    },
    "regulatorio": {
        "prompt": PROMPT_REGULATORIO_V1,
        "emoji": "⚖️",
        "titulo_secao": "RADAR JURÍDICO E ARBITRAGEM TRIBUTÁRIA",
        "descricao": "STF/STJ, CARF, CADE, regulações, decisões tributárias",
    },
    "estrategista": {
        "prompt": PROMPT_ESTRATEGISTA_V1,
        "emoji": "🏛️",
        "titulo_secao": "M&A E GRANDES MOVIMENTOS CORPORATIVOS",
        "descricao": "Fusões, OPAs, turnarounds, mudanças de controle, privatizações",
    },
}


# ==============================================================================
# SISTEMA get_prompt(): Busca do banco com fallback para constante local
# ==============================================================================

import time as _time

_PROMPT_CACHE: dict = {}
_PROMPT_CACHE_TTL = 600  # 10 minutos

# Variaveis de interpolacao obrigatorias por chave de prompt
PROMPT_REQUIRED_VARS: dict = {
    "PROMPT_ANALISE_E_SINTESE_CLUSTER_V1": ["{TEXTOS_CONCATENADOS}"],
    "PROMPT_AGRUPAMENTO_V1": ["{LISTA_NOTICIAS}"],
    "PROMPT_HIGIENIZACAO_V1": ["{LISTA_ARTIGOS}"],
    "PROMPT_EXTRACAO_FATO_GERADOR_V1": ["{TITULO}", "{TEXTO}"],
    "PROMPT_CONSOLIDACAO_CLUSTERS_V1": ["{CLUSTERS_INFO}"],
    "PROMPT_CORRECAO_PYDANTIC_V1": ["{ERRO_PYDANTIC}", "{JSON_FALHADO}"],
    "PROMPT_AGRUPAMENTO_INCREMENTAL_V2": ["{LISTA_NOTICIAS_NOVAS}", "{CLUSTERS_EXISTENTES}"],
    "PROMPT_DECISAO_CLUSTER_DETALHADO_V1": ["{TITULO_NOVO}", "{RESUMO_NOVO}", "{TITULO_CLUSTER}", "{RESUMO_CLUSTER}"],
}


def get_prompt(chave: str, db=None, **format_kwargs) -> str:
    """
    Busca prompt do banco de dados (com cache de 10 min).
    Se nao encontrar no banco ou db=None, faz fallback para a constante local.
    Se format_kwargs forem passados, aplica .format() no resultado.
    """
    now = _time.time()

    cached = _PROMPT_CACHE.get(chave)
    if cached and (now - cached["ts"]) < _PROMPT_CACHE_TTL:
        template = cached["valor"]
    elif db is not None:
        try:
            from backend.crud import get_prompt_template_by_key
            tpl = get_prompt_template_by_key(db, chave)
            if tpl and tpl.conteudo:
                template = tpl.conteudo
                _PROMPT_CACHE[chave] = {"valor": template, "ts": now}
            else:
                template = globals().get(chave, "")
        except Exception:
            template = globals().get(chave, "")
    else:
        template = globals().get(chave, "")

    if format_kwargs:
        try:
            return template.format(**format_kwargs)
        except KeyError:
            return template
    return template


def validar_prompt_update(chave: str, novo_valor: str) -> tuple:
    """
    Valida um update de prompt testando o format() com dados mock (sandbox).
    Retorna (ok: bool, mensagem: str).
    """
    required = PROMPT_REQUIRED_VARS.get(chave, [])
    missing = [v for v in required if v not in novo_valor]
    if missing:
        return False, f"Variáveis obrigatórias ausentes: {', '.join(missing)}"

    # Sandbox: tenta formatar com mocks para detectar KeyError
    mock_data = {}
    import re
    placeholders = re.findall(r'\{(\w+)\}', novo_valor)
    for p in placeholders:
        mock_data[p] = f"<<mock_{p}>>"
    try:
        novo_valor.format(**mock_data)
    except KeyError as e:
        return False, f"Erro de formatação: variável {e} não reconhecida"
    except (ValueError, IndexError) as e:
        return False, f"Erro de sintaxe no template: {e}"

    return True, "OK"