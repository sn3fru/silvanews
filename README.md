# BTG AlphaFeed - Plataforma de Inteligência de Mercado

Sistema integrado de processamento e análise de notícias em tempo real para a mesa de Special Situations do BTG Pactual, seguindo o fluxo de negócio AlphaFeed.

## 🚀 **COMO USAR - Guia Rápido**

### **Pré-requisitos**
1. **Anaconda instalado** no sistema
2. **Ambiente pymc2** criado e configurado
3. **Banco PostgreSQL** rodando na porta 5433
4. **Chave da API Gemini** configurada

### **Passo 1: Abrir Anaconda Prompt**
- Pressione `Win + R`
- Digite `anaconda prompt` e pressione Enter
- Ou procure por "Anaconda Prompt" no menu Iniciar

### **Passo 2: Ativar Ambiente e Navegar**
```bash
# Ativar ambiente
conda activate pymc2

# Navegar para o diretório
cd "C:\Users\marcos.silva\OneDrive - ENFORCE GESTAO DE ATIVOS S.A\jupyter\projetos\novo-topnews\pdfs\silva-front\btg_alphafeed"
```

### **Passo 3: Configurar Banco de Dados**
Crie um arquivo `.env` no diretório `backend/`:
```env
DATABASE_URL="postgresql://postgres_local@localhost:5433/devdb"
GEMINI_API_KEY="sua_chave_api_gemini"
```

### **Passo 4: Executar Fluxo Completo**
```bash
# Opção A: Fluxo automatizado (Recomendado)
python run_complete_workflow.py

# Opção B: Execução manual por etapas
python load_news.py --dir ../pdfs --direct --yes  # Carregar artigos brutos
python process_articles.py                        # Processar artigos (extração, agrupamento, resumos)
python start_dev.py                               # Iniciar backend
```

**Nota**: O `load_news.py` agora apenas **carrega artigos brutos** no banco (status: pendente). Todo o processamento (extração de dados, agrupamento, resumos) é feito pelo `process_articles.py`.

### **Passo 5: Acessar o Sistema**
- **Frontend**: http://localhost:8000/frontend
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

### **Passo 6: Usar o Seletor de Data**
- **Data Atual**: Por padrão, mostra dados de hoje
- **Data Histórica**: Clique no botão de data para selecionar outra data
- **Filtro Automático**: O sistema filtra automaticamente notícias, clusters e resumos da data selecionada

---

## 🎯 **Visão Geral da Plataforma**

O BTG AlphaFeed transforma o alto volume de notícias não estruturadas em um feed de eventos de negócio claros, priorizados e acionáveis. Em vez de apresentar uma lista cronológica de artigos, a plataforma identifica o "fato gerador" por trás das notícias, agrupa todas as perspectivas sobre aquele fato e o apresenta como um único evento coeso.

### **Fluxo de Negócio (5 Fases)**

#### 1. **Coleta Universal de Artigos Brutos**
- **Fontes**: Crawlers Web, Telegram, PDFs, JSONs
- **Processamento**: 
  - **PDFs**: Extração inteligente de notícias individuais (comportamento padrão)
  - **JSONs**: Processamento direto (já vem pré-processado)
- **Repositório**: Central único de "artigos brutos"
- **Resultado**: Artigos com status "pendente" no banco

#### 2. **Detecção e Agrupamento Dinâmico de Eventos**
- **Processamento em Lote**: Processa todas as notícias primeiro
- **Agrupamento Inteligente**: Usa LLM para agrupar por fato gerador (inspirado no `silva.py`)
- **Criação de Clusters**: Agrupa por fato gerador após processamento
- **Resultado**: Clusters de eventos com artigos associados

#### 3. **Triagem e Classificação de Prioridade**
- **P1 - Crítico**: Falências, M&A direto, crises de liquidez
- **P2 - Estratégico**: Mudanças regulatórias, disputas corporativas
- **P3 - Monitoramento**: Contexto macro, tendências setoriais

#### 4. **Geração Seletiva de Resumos Executivos**
- **P1**: Resumo longo (parágrafo completo, sem limites)
- **P2**: Resumo médio (3-4 frases, com limite)
- **P3**: Resumo curto (uma frase)

#### 5. **Apresentação e Interação**
- **Feed Orientado a Eventos**: Clusters ordenados por prioridade
- **Seletor de Data**: Visualização histórica por data
- **Rastreabilidade Total**: Acesso aos artigos originais
- **Drill-Down**: Clique no evento → ver artigos fonte

---

## 🏗️ **Arquitetura Detalhada**

### **Estrutura do Projeto**
```
btg_alphafeed/
├── backend/                    # API FastAPI
│   ├── main.py                # Endpoints principais (950 linhas)
│   ├── models.py              # Modelos Pydantic
│   ├── database.py            # Configuração SQLAlchemy (285 linhas)
│   ├── crud.py                # Operações de banco
│   ├── processing.py          # Lógica de processamento (559 linhas)
│   ├── prompts.py             # Prompts para LLM
│   ├── utils.py               # Funções auxiliares
│   ├── requirements.txt       # Dependências Python
│   ├── .env                   # Configurações (invisível)
│   └── collectors/            # Coletores de dados
│       ├── __init__.py
│       ├── exemplo_coletor.py # Exemplo de coletor
│       └── file_loader.py     # Carregador de arquivos
├── frontend/                  # Interface web
│   ├── index.html             # Interface principal (154 linhas)
│   ├── script.js              # Lógica frontend (456 linhas)
│   ├── style.css              # Estilos CSS
│   └── settings.html          # Interface de configurações
├── tests/                     # Scripts de teste
│   └── test_imports.py        # Teste de importações
├── README.md                  # Este arquivo
├── load_news.py               # Script de carregamento (135 linhas)
├── process_articles.py        # Script de processamento (398 linhas)
├── run_complete_workflow.py   # Fluxo automatizado (185 linhas)
├── test_fluxo_completo.py     # Teste completo (164 linhas)
├── test_ajustes.py            # Teste das alterações (200+ linhas)
├── start_dev.py               # Script de inicialização (135 linhas)
└── limpar_banco.py            # Utilitário de limpeza (278 linhas)
```

### **Tecnologias Utilizadas**

#### **Backend**
- **FastAPI**: Framework web moderno e rápido
- **SQLAlchemy**: ORM para PostgreSQL
- **PostgreSQL**: Banco de dados principal
- **Google Gemini API**: LLM para processamento
- **Pydantic**: Validação de dados
- **Uvicorn**: Servidor ASGI

#### **Frontend**
- **Vanilla JavaScript**: Lógica client-side
- **CSS Grid/Flexbox**: Layout responsivo
- **HTML5**: Estrutura semântica
- **Fetch API**: Comunicação com backend

#### **Processamento**
- **Embeddings**: Vetores de similaridade (implementação simples)
- **Cosine Similarity**: Métrica de similaridade
- **JSON Processing**: Extração e validação de dados
- **Background Tasks**: Processamento assíncrono

---

## 📊 **Estrutura do Banco de Dados**

### **Tabelas Principais**

#### **artigos_brutos** - Artigos Coletados
- `id`, `hash_unico`, `texto_bruto`, `url_original`, `fonte_coleta`
- `status` (pendente, processado, irrelevante, erro)
- `titulo_extraido`, `texto_processado`, `jornal`, `autor`
- `tag`, `prioridade`, `relevance_score`, `embedding`, `cluster_id`
- **Índices**: status+created_at, hash_unico, fonte_coleta+created_at, tag+prioridade

#### **clusters_eventos** - Agrupamentos de Eventos
- `id`, `titulo_cluster`, `resumo_cluster`, `tag`, `prioridade`
- `embedding_medio`, `status`, `total_artigos`
- **Índices**: status+created_at, tag+prioridade

#### **sinteses_executivas** - Sínteses Diárias
- `id`, `data_sintese`, `texto_sintese`
- Métricas: total_noticias_coletadas, total_eventos_unicos, etc.

#### **logs_processamento** - Logs do Sistema
- `id`, `timestamp`, `nivel`, `componente`, `mensagem`, `detalhes`
- **Índices**: timestamp, nivel+componente

#### **configuracoes_coleta** - Configurações dos Coletores
- `id`, `nome_coletor`, `ativo`, `configuracao`
- Controle de execução: ultima_execucao, proxima_execucao, intervalo_minutos

#### **chat_sessions** - Sessões de Chat
- `id`, `cluster_id`, `created_at`, `updated_at`
- **Relacionamentos**: cluster, messages
- **Índices**: cluster_id, created_at, updated_at

#### **chat_messages** - Mensagens do Chat
- `id`, `session_id`, `role`, `content`, `timestamp`
- **Relacionamentos**: session
- **Índices**: session_id, timestamp, role

#### **cluster_alteracoes** - Histórico de Alterações
- `id`, `cluster_id`, `campo_alterado`, `valor_anterior`, `valor_novo`, `motivo`, `usuario`, `timestamp`
- **Relacionamentos**: cluster
- **Índices**: cluster_id, timestamp, campo_alterado, usuario

---

## 📡 **Endpoints da API**

### **Principais**
- `GET /api/feed` - Feed principal do frontend (suporta parâmetro `data`)
- `GET /api/cluster/{id}` - Detalhes de um cluster

### **Chat e Interação**
- `POST /api/chat/send` - Envia mensagem para chat de um cluster
- `GET /api/chat/{cluster_id}/messages` - Obtém mensagens de uma sessão de chat

### **Gerenciamento de Clusters**
- `PUT /api/cluster/{cluster_id}/update` - Atualiza prioridade e tags de um cluster
- `GET /api/cluster/{cluster_id}/alteracoes` - Obtém histórico de alterações de um cluster
- `GET /api/admin/alteracoes` - Obtém todas as alterações recentes (endpoint administrativo)

### **Internos (para coletores)**
- `POST /internal/novo-artigo` - Criar novo artigo
- `POST /internal/processar-artigo` - Processar artigo

### **Administração**
- `GET /admin/stats` - Estatísticas do sistema
- `POST /admin/processar-pendentes` - Processar artigos pendentes
- `POST /admin/gerar-resumo/{cluster_id}` - Gerar resumo de cluster
- `POST /admin/carregar-arquivos` - Carregar notícias de arquivos
- `POST /admin/upload-file` - Upload de arquivos PDF/JSON
- `GET /admin/upload-progress/{file_id}` - Verificar progresso do upload em tempo real
- `POST /admin/process-articles` - Processar artigos pendentes (equivalente ao process_articles.py)
- `GET /admin/processing-status` - Verificar status do processamento

### **Settings (CRUD Completo)**
- `GET /api/settings/artigos` - Listar artigos com paginação
- `GET /api/settings/artigos/{id}` - Detalhes de artigo
- `PUT /api/settings/artigos/{id}` - Atualizar artigo
- `DELETE /api/settings/artigos/{id}` - Excluir artigo
- `GET /api/settings/clusters` - Listar clusters
- `GET /api/settings/clusters/{id}` - Detalhes de cluster
- `PUT /api/settings/clusters/{id}` - Atualizar cluster
- `DELETE /api/settings/clusters/{id}` - Excluir cluster
- `GET /api/settings/sinteses` - Listar sínteses
- `GET /api/settings/sinteses/{id}` - Detalhes de síntese
- `PUT /api/settings/sinteses/{id}` - Atualizar síntese
- `DELETE /api/settings/sinteses/{id}` - Excluir síntese

### **Saúde**
- `GET /health` - Status do sistema

---

## 🎨 **Interface Frontend**

### **Componentes Principais**

#### **Seletor de Data (Novo)**
- **Localização**: Topo do frontend, acima das métricas
- **Funcionalidade**: Permite selecionar data específica para visualização
- **Estados**: 
  - Data atual (padrão)
  - Data histórica (destaque visual)
- **Filtro**: Busca automaticamente notícias, clusters e resumos da data selecionada

#### **Painel de Controle (Sidebar)**
- **Logo**: BTG AlphaFeed
- **Filtros de Prioridade**: P1 Crítico, P2 Estratégico, P3 Monitoramento
- **Mesas de Análise**: Special Situations, Dívida Ativa, Crise de Liquidez, M&A Setor Elétrico
- **Filtros de Categoria**: Governo & Política, Economia & Tecnologia, Judiciário, Empresas Privadas

#### **Painel de Métricas (Header)**
- **Notícias Coletadas**: Total de artigos da data selecionada
- **Eventos Únicos**: Total de clusters ativos da data
- **Análises Críticas (P1)**: Clusters de prioridade crítica
- **Em Monitoramento (P2+P3)**: Clusters estratégicos e de monitoramento
- **Settings**: Botão para acessar configurações

#### **Feed de Notícias**
- **Síntese Executiva**: Resumo da data selecionada
- **Cards de Clusters**: Cada card representa um evento único
  - **P1/P2**: Cards individuais com título, fontes, resumo e botão "Aprofundar Análise"
  - **P3 - Monitoramento**: Cards agrupados por tag com lista de notícias em bullets
    - Primeiras 2-3 palavras em negrito
    - Resto do texto em fonte normal
    - Clique em qualquer bullet abre modal com detalhes completos
    - Total de artigos do grupo no cabeçalho

#### **Modal de Deep-Dive**
- **Título do Evento**: Nome do cluster
- **Resumo Executivo**: Texto completo do resumo (sempre visível)
- **Fontes Originais**: Lista de artigos que compõem o evento (sempre visível)
- **Abas de Navegação**: 
  - Conversar com o Cluster: Chat interativo com LLM
  - Gerenciar Análise: Edição de prioridade e tags
- **Lista de Fontes**: Títulos dos artigos originais com links

#### **Chat Interativo**
- **Sessões Persistentes**: Chat salvo no banco de dados
- **Contexto Completo**: LLM tem acesso a todas as fontes do cluster
- **Prompt Especializado**: Prompt otimizado para análise de Special Situations
- **Interface Responsiva**: Mensagens do usuário e assistente diferenciadas
- **Loading States**: Indicadores de processamento durante resposta do LLM

#### **Gerenciamento de Clusters**
- **Edição de Prioridade**: Alteração entre P1, P2 e P3
- **Gerenciamento de Tags**: Adição/remoção de tags com interface visual
- **Histórico de Alterações**: Registro completo de todas as modificações
- **Motivo das Alterações**: Campo opcional para justificar mudanças
- **Validação**: Verificação de integridade antes de salvar

#### **Interface de Settings**
- **CRUD Completo**: Para artigos, clusters e sínteses
- **Paginação**: Navegação por páginas
- **Filtros**: Por status, categoria, prioridade
- **Edição Inline**: Modificar dados diretamente na interface

### **Funcionalidades JavaScript**

#### **Gerenciamento de Estado**
- `currentApiData`: Armazena dados atuais da API
- `refreshInterval`: Controle de atualização automática
- `selectedDate`: Data selecionada pelo usuário
- `isHistoricalView`: Indica se está visualizando dados históricos

#### **Comunicação com API**
- `fetchApiData()`: Busca dados do feed principal (com suporte a data)
- `fetchClusterDetails()`: Busca detalhes de cluster específico
- Tratamento de erros e retry automático

#### **Renderização Dinâmica**
- `renderMetricas()`: Atualiza painel de métricas
- `renderSintese()`: Atualiza síntese executiva
- `renderFeed()`: Renderiza cards de clusters
- `filterAndRender()`: Aplica filtros e re-renderiza

#### **Interatividade**
- **Seletor de Data**: Clique para abrir calendário, seleção automática
- **Filtros**: Prioridade e categoria com atualização em tempo real
- **Modal**: Abertura/fechamento com carregamento assíncrono
- **Deep-Dive**: Navegação entre abas e visualização de fontes
- **Auto-refresh**: Atualização automática a cada 30 segundos

#### **UX/UI**
- **Loading States**: Indicadores de carregamento
- **Error Handling**: Mensagens de erro amigáveis
- **Success Feedback**: Confirmações de ações
- **Responsive Design**: Adaptação a diferentes tamanhos de tela
- **Estado Histórico**: Destaque visual quando visualizando dados antigos

#### **Funcionalidades P3 - Monitoramento (NOVO)**
- **Agrupamento por Tag**: Notícias P3 são agrupadas por categoria/tag
- **Cards Consolidados**: Um card maior por tag contém todas as notícias P3 daquela categoria
- **Lista de Bullets**: Notícias listadas como bullets simples dentro do card
- **Formatação Inteligente**: Primeiras 2-3 palavras em negrito, resto em fonte normal
- **Interatividade Mantida**: Clique em qualquer bullet abre modal com detalhes completos
- **Contador de Artigos**: Total de artigos do grupo exibido no cabeçalho do card
- **Estilo Distintivo**: Design diferenciado para cards P3 (gradiente cinza, borda lateral)

---

## 🔧 **Scripts Disponíveis**

### **`load_news.py` (135 linhas) - ATUALIZADO**
- ✅ **Comportamento Padrão**: Carregamento de artigos brutos (sem processamento)
- ✅ **JSONs**: Processamento direto dos dados originais (sem prioridade/tags)
- ✅ **PDFs**: OCR + LLM para extrair notícias individuais no formato do JSON
- ✅ **Estrutura Unificada**: JSONs e PDFs usam a mesma estrutura de dados
- ✅ **Dados Originais**: Salva apenas dados originais, sem processamento
- ✅ **Status Pendente**: Artigos criados com status "pendente" para processamento posterior
- ✅ **Suporte a Múltiplas Fontes**: PDFs e JSONs
- ✅ **Modo Direto ou via API**: Conexão direta ou HTTP
- ✅ **Deduplicação Automática**: Por hash único
- ✅ **Processamento em Lote**: Diretório completo ou arquivo específico
- ✅ **Logs de Progresso**: Feedback detalhado

### **`process_articles.py` (775 linhas) - ATUALIZADO**
- ✅ **Processamento em Lote**: Processa TODAS as notícias primeiro
- ✅ **Agrupamento Inteligente**: Usa LLM para agrupar por fato gerador (inspirado no `silva.py`)
- ✅ **Criação de Clusters**: Agrupa por fato gerador após processamento
- ✅ **Geração Seletiva**: Resumos diferentes por prioridade
  - **P1**: Resumo longo (parágrafo completo, sem limites)
  - **P2**: Resumo médio (3-4 frases, com limite)
  - **P3**: Resumo curto (uma frase)
- ✅ **Logs Detalhados**: Progresso e estatísticas
- ✅ **Tratamento de Erros**: Fallbacks e recuperação
- ✅ **Performance Otimizada**: Índices por data para queries rápidas

### **`test_fluxo_completo.py` (164 linhas)**
- ✅ Testa todo o pipeline
- ✅ Verifica clusterização
- ✅ Valida acesso a artigos originais
- ✅ Testa endpoints da API
- ✅ Validação de dados

### **`test_ajustes.py` (200+ linhas) - NOVO**
- ✅ Testa seletor de data no frontend
- ✅ Verifica funções de busca por data
- ✅ Valida novo fluxo de processamento
- ✅ Testa importações e conexões
- ✅ Verifica arquivos atualizados

### **`run_complete_workflow.py` (185 linhas)**
- ✅ Automatiza todo o fluxo
- ✅ Execução sequencial das etapas
- ✅ Tratamento de erros
- ✅ Verificações de ambiente
- ✅ Feedback em tempo real

### **`start_dev.py` (135 linhas)**
- ✅ Inicialização do backend
- ✅ Configuração de CORS
- ✅ Servir frontend estático
- ✅ Logs de inicialização

### **`limpar_banco.py` (278 linhas)**
- ✅ Utilitário de limpeza do banco
- ✅ Remoção seletiva de dados
- ✅ Backup antes da limpeza
- ✅ Confirmações de segurança

---

## 🏷️ **Classificação e Tags**

### **Tags (categoria):**
- `Governo e Politica`: Política econômica doméstica
- `Economia e Tecnologia`: Inovação e negócios tech
- `Judicionario`: Decisões judiciais e legislativas
- `Empresas Privadas`: Movimentos corporativos

### **Prioridades:**
- `P1_CRITICO`: Falências, M&A direto, crises de liquidez
- `P2_ESTRATEGICO`: Mudanças regulatórias, disputas corporativas
- `P3_MONITORAMENTO`: Contexto macro, tendências setoriais

---

## 📁 **Formatos de Arquivo Suportados**

### **JSON (dump_crawlers)**
```json
[
  {
    "id_hash": "hash_unico",
    "titulo": "Título da notícia",
    "subtitulo": "Subtítulo da notícia",
    "texto_completo": "Texto completo da notícia...",
    "link": "https://exemplo.com/noticia",
    "fonte": "Valor Econômico",
    "categoria": "Finanças",
    "data_publicacao": "2025-08-01T10:00:00Z",
    "data_ultima_modificacao": "2025-08-01T10:00:00Z",
    "tags": ["tag1", "tag2"]
  }
]
```

### **PDF**
Arquivos PDF são processados usando OCR (PyMuPDF) + LLM para extrair notícias individuais no mesmo formato do JSON.

- Estrutura gerada por notícia (artigo bruto):
  - `texto_bruto`: texto completo da notícia detectada no PDF
  - `url_original`: sempre `null` (PDF não contém link)
  - `metadados`:
    - `titulo`: título extraído para a notícia
    - `fonte_original`: jornal (extraído do PDF; fallback: nome do arquivo)
    - `arquivo_origem`: nome do PDF
    - `tipo_arquivo`: `pdf`
    - `data_processamento`: timestamp local GMT-3
    - Campos auxiliares quando disponíveis: `jornal`, `pagina`, `autor`, `data_publicacao`, `categoria`
    - Campos apenas informativos vindos do LLM: `tag_ia`, `prioridade_ia`, `relevance_score_ia`, `relevance_reason_ia`

- Fallback sem IA (quando não há `GEMINI_API_KEY` ou cliente indisponível):
  - O arquivo é dividido por páginas e cada página vira um artigo bruto com:
    - `metadados.fonte_original = <nome_do_arquivo_sem_extensão>`
    - `metadados.jornal = <nome_do_arquivo_sem_extensão>`
    - `metadados.pagina = <número da página>`
  - Observação: a divisão por notícias dentro da página requer IA. Sem IA, geramos 1 artigo por página para manter a ingestão.

---

## 🔄 **Pipeline de Processamento - ATUALIZADO**

### **ETAPA 1: Carregamento de Notícias (load_news.py)**
- **JSONs**: Processamento direto dos dados originais (sem prioridade/tags)
- **PDFs**: OCR + LLM para extrair notícias individuais no formato do JSON
  - Cada notícia do PDF vira um artigo bruto separado
  - `metadados.fonte_original` é sempre o jornal correto (ou derivado do arquivo)
  - `metadados.pagina` e `metadados.autor` são preenchidos quando disponíveis
- **Resultado**: Artigos brutos com dados originais e status "pendente" no banco
- **Sem processamento**: Apenas carregamento bruto, sem extração de dados ou agrupamento

### **ETAPA 2: Processar TODAS as Notícias (process_articles.py)**
- Busca todos os artigos pendentes
- Processa cada artigo individualmente
- Extrai dados estruturados com LLM
- Gera embeddings para similaridade
- Atualiza status para "processado"

### **ETAPA 3: Criar Clusters/Agrupamentos**
- Busca todos os artigos processados hoje
- **Agrupamento Inteligente**: Usa LLM para agrupar por fato gerador (inspirado no `silva.py`)
- Cria novos clusters ou adiciona a existentes
- Atualiza embedding médio dos clusters

### **ETAPA 4: Gerar Resumos Seletivos**
- **P1 - Crítico**: Resumo longo (parágrafo completo, sem limites)
- **P2 - Estratégico**: Resumo médio (3-4 frases, com limite)
- **P3 - Monitoramento**: Resumo curto (uma frase)

### **ETAPA 5: Atualização no Banco**
- Atualiza clusters com resumos
- Registra timestamps de processamento
- Cria logs detalhados

---

## 📈 **Melhorias Implementadas**

### **1. Seletor de Data (NOVO)**
- ✅ **Interface**: Seletor no topo do frontend
- ✅ **Funcionalidade**: Filtro por data específica
- ✅ **API**: Endpoint suporta parâmetro de data
- ✅ **Backend**: Funções de busca por data
- ✅ **UX**: Destaque visual para dados históricos

### **2. Novo Fluxo de Processamento**
- ❌ **Antes**: Processamento incremental
- ✅ **Agora**: Processamento em lote seguido de clusterização

### **3. Resumos Diferenciados por Prioridade**
- ❌ **Antes**: Resumos iguais para todas as prioridades
- ✅ **Agora**: 
  - **P1**: Resumo longo (parágrafo completo)
  - **P2**: Resumo médio (3-4 frases)
  - **P3**: Resumo curto (uma frase)

### **4. Rastreabilidade Total**
- ✅ **Frontend**: Acesso aos artigos originais via drill-down
- ✅ **Backend**: Relacionamentos corretos entre clusters e artigos
- ✅ **API**: Endpoints para detalhes completos

### **5. Interface Administrativa**
- ✅ **Settings**: CRUD completo para todos os dados
- ✅ **Paginação**: Navegação eficiente
- ✅ **Filtros**: Busca e filtragem avançada
- ✅ **Edição**: Modificação inline de dados

### **6. Otimizações de Performance (NOVO)**
- ✅ **Índices de Performance**: Índices por data para queries rápidas
- ✅ **Paginação**: 20 itens por página no frontend
- ✅ **Carregamento Lazy**: Textos completos carregados sob demanda
- ✅ **Scroll Infinito**: Carrega mais notícias automaticamente
- ✅ **Modal de Detalhes**: Detalhes completos em modal elegante
- ✅ **Queries Otimizadas**: Índices compostos para filtros complexos

### **7. Robustez e Confiabilidade**
- ✅ **Logs Detalhados**: Rastreamento completo de operações
- ✅ **Tratamento de Erros**: Fallbacks e recuperação
- ✅ **Validação**: Pydantic para integridade de dados
- ✅ **Deduplicação**: Hash único para evitar duplicatas

### **8. Agrupamento P3 - Monitoramento (NOVO)**
- ✅ **Agrupamento por Tag**: Notícias P3 agrupadas por categoria
- ✅ **Cards Consolidados**: Interface diferenciada para P3
- ✅ **Lista de Bullets**: Apresentação simplificada das notícias P3
- ✅ **Formatação Inteligente**: Primeiras palavras em negrito
- ✅ **Interatividade Mantida**: Modal de detalhes funciona para bullets P3
- ✅ **Estilo Distintivo**: Design diferenciado para cards P3

### **9. Chat Interativo com Clusters (NOVO)**
- ✅ **Botão Renomeado**: "Conversar com a Notícia" em vez de "Aprofundar Análise"
- ✅ **Modal Reorganizado**: Resumo e fontes sempre visíveis
- ✅ **Chat Persistente**: Sessões salvas no banco de dados
- ✅ **LLM Integrado**: Prompt especializado para análise de Special Situations
- ✅ **Interface Responsiva**: Mensagens diferenciadas por tipo
- ✅ **Loading States**: Indicadores de processamento
- ✅ **Temperatura Zero**: LLM configurado para não alucinar ou inventar informações
- ✅ **Contexto Completo**: Histórico completo da conversa enviado para o LLM
- ✅ **UX Melhorada**: Barra de chat posicionada acima das mensagens

### **10. Gerenciamento Avançado de Clusters (NOVO)**
- ✅ **Edição de Prioridade**: Alteração entre P1, P2 e P3
- ✅ **Gerenciamento de Tags**: Interface visual para adicionar/remover tags
- ✅ **Histórico de Alterações**: Registro completo de modificações
- ✅ **Validação de Dados**: Verificação antes de salvar
- ✅ **Auditoria**: Rastreamento de quem fez o quê e quando

### **11. Upload e Processamento de Arquivos (NOVO)**
- ✅ **Upload Multiplo**: Interface para upload de múltiplos arquivos PDF e JSON
- ✅ **Processamento Inteligente**: PDFs processados com OCR e extração de notícias via LLM
- ✅ **Processamento Direto**: JSONs processados diretamente para extração de notícias
- ✅ **Processamento de Artigos**: Botão para executar processamento equivalente ao `process_articles.py`
- ✅ **Progresso Visual Detalhado**: Sistema de etapas visuais com indicadores de progresso
  - **Etapas Visuais**: Upload → Processamento → Banco → Concluído
  - **Progresso em Tempo Real**: Contador de artigos processados
  - **Status Detalhado**: Informações sobre arquivo atual e progresso
  - **Logs Visuais**: Feedback completo sobre cada etapa do processamento
- ✅ **Monitoramento Avançado**: Interface com progresso granular e status em tempo real
- ✅ **Resultados Detalhados**: Feedback completo sobre arquivos processados e artigos criados

### **12. Sistema de Progresso Visual (NOVO)**
- ✅ **Etapas Visuais**: Sistema de 4 etapas com ícones e cores
  - **📤 Enviando arquivo**: Etapa inicial de upload
  - **⚙️ Processando conteúdo**: Extração e análise do arquivo
  - **💾 Salvando no banco**: Persistência dos dados
  - **✅ Concluído**: Finalização do processo
- ✅ **Indicadores de Status**: Cores dinâmicas (cinza → azul → verde)
- ✅ **Progresso Real em Tempo Real**: Contador de artigos processados com dados reais do backend
- ✅ **Informações Detalhadas**: Nome do arquivo, progresso atual, status do processamento
- ✅ **Feedback Visual**: Transições suaves entre etapas
- ✅ **Logs em Tempo Real**: Informações detalhadas sobre cada etapa do processamento
- ✅ **Polling Inteligente**: Sistema de polling que verifica progresso real a cada segundo
- ✅ **Tracking de Progresso**: Backend atualiza progresso em tempo real durante processamento
- ✅ **Timeout Proteção**: Sistema para evitar polling infinito (máximo 5 minutos)

### **13. Agrupamento Incremental com Pivot Automático (RESTAURADO)**
- ✅ **Processamento Inteligente**: Quando o botão "Processar Artigos Pendentes" é clicado após upload de notícias
- ✅ **Pivot Automático**: Sistema escolhe automaticamente o algoritmo correto:
  - **Se há clusters existentes**: Usa agrupamento incremental (anexa a clusters existentes)
  - **Se não há clusters**: Usa agrupamento original (cria clusters do zero)
- ✅ **Identificação de Novos Artigos**: Sistema identifica automaticamente artigos processados hoje que não foram associados a clusters
- ✅ **Clusters Existentes**: Busca todos os clusters criados no mesmo dia para análise
- ✅ **Prompt Especializado**: Novo prompt `PROMPT_AGRUPAMENTO_INCREMENTAL_V1` para análise incremental
- ✅ **Lógica Idêntica**: Prompt mantém a mesma lógica do agrupamento original para evitar bias
- ✅ **Proteção de Clusters**: LLM recebe instruções explícitas para NÃO alterar clusters existentes
- ✅ **Classificação Inteligente**: Para cada artigo novo, o LLM decide:
  - **Anexar**: Se o artigo se refere ao mesmo fato gerador de um cluster existente
  - **Novo Cluster**: Se o artigo se refere a um fato gerador diferente
- ✅ **Integridade Total**: Todos os artigos novos são classificados (anexados ou em novos clusters)
- ✅ **Logs Detalhados**: Rastreamento completo de anexações e novos clusters criados
- ✅ **Performance Otimizada**: Processamento eficiente com mapeamento de IDs e validações
- ✅ **Otimização de Dados**: Passa apenas títulos e IDs para o LLM, evitando timeouts com centenas de artigos
- ✅ **FUNÇÃO IMPLEMENTADA**: `agrupar_noticias_incremental()` agora está funcionando corretamente
- ✅ **PIVOT AUTOMÁTICO**: `processar_artigos_pendentes()` agora escolhe automaticamente entre incremental e em lote

### **14. Correção de Bug de Duplicação (NOVO)**
- ✅ **Problema Identificado**: Clusters duplicados sendo criados devido a processamento duplo
- ✅ **Causa Raiz**: `process_articles.py` fazia clusterização tanto na ETAPA 1 quanto na ETAPA 2
- ✅ **Solução Implementada**: 
  - **ETAPA 1**: Processamento de artigos sem clusterização
  - **ETAPA 2**: Agrupamento inteligente com prompt (única clusterização)
- ✅ **Verificações de Duplicação**: 
  - `create_cluster`: Verifica clusters existentes antes de criar
  - `associate_artigo_to_cluster`: Evita associações duplicadas
- ✅ **Contagem Correta**: `total_artigos` agora reflete o número real de artigos associados

### **15. Estrutura de Dados Unificada (NOVO)**
- ✅ **Problema Identificado**: Dados de processamento (prioridade, tags) sendo salvos nos artigos brutos
- ✅ **Solução Implementada**: Separação clara entre dados originais e dados processados
- ✅ **Novos Campos no Banco**: 
  - `subtitulo`: Subtítulo original da notícia (TEMPORARIAMENTE COMENTADO)
  - `data_ultima_modificacao`: Data de última modificação (TEMPORARIAMENTE COMENTADO)
  - `id_hash_original`: ID hash original do JSON (TEMPORARIAMENTE COMENTADO)
  - `fonte_original`: Fonte original (ex: "Valor Econômico") (TEMPORARIAMENTE COMENTADO)
  - `tags_originais`: Tags originais como array JSON (TEMPORARIAMENTE COMENTADO)
- ✅ **Estrutura Unificada**: JSONs e PDFs agora usam a mesma estrutura de dados
- ✅ **Processamento Limpo**: Prioridade e tags são definidas apenas no processamento, não no carregamento
- ⚠️ **NOTA**: Novos campos estão comentados temporariamente para evitar quebra do sistema. Serão adicionados via migração quando necessário.

### **16. Correção do Fluxo de Classificação (NOVO)**
- ✅ **Problema Identificado**: ETAPA 2 estava mostrando prioridades (P3_MONITORAMENTO) quando deveria só agrupar
- ✅ **Causa**: Código estava definindo prioridade na ETAPA 2 baseado nos artigos individuais
- ✅ **Solução Implementada**: 
  - **ETAPA 2**: Só agrupa notícias por fato gerador (sem classificar)
  - **ETAPA 3**: Usa prompts do `prompts.py` para classificar cada cluster completo
  - **Fluxo Correto**: Agrupamento → Classificação → Resumo
- ✅ **Tags Unificadas**: Modelos agora usam as 8 tags do `TAGS_SPECIAL_SITUATIONS` diretamente
- ✅ **Modo Debug**: Adicionado debug detalhado para rastrear prompts enviados ao Gemini e respostas recebidas
- ✅ **Tratamento de Irrelevantes**: Notícias irrelevantes são marcadas como "IRRELEVANTE" e omitidas do feed
- ✅ **Resultado**: Separação clara entre agrupamento e classificação, usando prompts especializados

### **17. Migração de Tags Antigas (NOVO)**
- ✅ **Problema Identificado**: Artigos existentes no banco tinham tags antigas que não são mais válidas
- ✅ **Causa**: Mudança de 4 tags antigas para 8 tags especializadas do `TAGS_SPECIAL_SITUATIONS`
- ✅ **Solução Implementada**: 
  - **Função de Migração**: `migrar_tag_antiga_para_nova()` converte tags antigas para novas
  - **Função de Correção**: `corrigir_tag_invalida()` atualizada para usar as 8 tags especializadas
  - **Mapeamento**: 'Economia e Tecnologia' → 'Internacional (Economia e Política)'
  - **Compatibilidade**: Artigos antigos são processados sem erro de validação
- ✅ **Resultado**: Sistema funciona com artigos antigos e novos, usando tags especializadas

### **18. Tags Dinâmicas no Frontend (NOVO)**
- ✅ **Problema Identificado**: Frontend ainda usava tags fixas antigas (4 categorias)
- ✅ **Causa**: HTML e JavaScript tinham tags hardcoded em vez de usar as tags reais dos clusters
- ✅ **Solução Implementada**: 
  - **Carregamento dos Clusters**: Frontend busca clusters existentes para extrair tags únicas
  - **Extração Dinâmica**: Tags são extraídas dos clusters reais no banco de dados
  - **Filtros Atualizados**: Categorias no frontend agora usam tags dinâmicas dos dados
  - **Fallback**: Se API falhar, usa tags antigas como backup
- ✅ **Resultado**: Frontend agora exibe as categorias reais baseadas nos clusters existentes

### **19. Correção de Dados de Teste para Datas Vazias (NOVO)**
- ✅ **Problema Identificado**: Datas futuras ou sem registros exibiam dados de teste antigos
- ✅ **Causa**: API retornava dados de teste quando não havia clusters reais na data solicitada
- ✅ **Solução Implementada**: 
  - **Remoção de Dados de Teste**: API agora retorna dados vazios para datas sem registros
  - **Limpeza de Cache**: Frontend limpa dados antigos quando não há clusters
  - **Métricas Zeradas**: Retorna métricas com valores 0 para datas vazias
- ✅ **Resultado**: Datas futuras ou sem dados agora mostram corretamente "sem notícias"

### **20. Padronização de Fuso Horário GMT-3 (NOVO)**
- ✅ **Problema Identificado**: Diferenças de fuso horário entre frontend e backend causavam inconsistências de data
- ✅ **Causa**: Sistema usava fuso horário local do servidor vs. fuso horário do navegador
- ✅ **Solução Implementada**: 
  - **Backend Python**: Criadas funções utilitárias em `utils.py` para GMT-3 (São Paulo/Brasília)
  - **Funções Criadas**: `get_datetime_brasil()`, `get_date_brasil()`, `get_datetime_brasil_str()`, `get_date_brasil_str()`
  - **Substituições**: Todas as ocorrências de `datetime.now()` e `date.today()` padronizadas
  - **Frontend JavaScript**: Ajustado para usar GMT-3 em `getTodayDate()` e comparações de data
- ✅ **Resultado**: Todas as datas e horários agora seguem o mesmo padrão GMT-3 (São Paulo/Brasília)

### **21. Correções Críticas do Processamento de Artigos (NOVO)**
- ✅ **Problema Identificado**: `process_articles.py` falhava no agrupamento com JSON malformado
- ✅ **Causa**: Função `extrair_json_da_resposta` não era robusta e prompt causava truncamento
- ✅ **Solução Implementada**: 
  - **Função Robusta**: `extrair_json_da_resposta` agora tem 3 tentativas de correção
  - **Prompt Otimizado**: Reduzido tamanho de trechos e aumentado `max_output_tokens` para 8192
  - **Configuração Melhorada**: `temperature=0.1` (mais determinístico) e `top_p=0.8`
  - **Debug Detalhado**: Logs com emojis e informações detalhadas de cada etapa
  - **Tratamento de Erros**: Múltiplas tentativas de correção de JSON incompleto
- ✅ **Resultado**: Agrupamento agora funciona de forma robusta e com debug detalhado

### **22. Restauração da Funcionalidade de Agrupamento Incremental (NOVO)**
- ✅ **Problema Identificado**: Funcionalidade de agrupamento incremental foi perdida durante reestruturação
- ✅ **Causa**: Durante as correções do `process_articles.py`, a lógica de pivot automático não foi implementada
- ✅ **Solução Implementada**: 
  - **Função Restaurada**: `agrupar_noticias_incremental()` implementada com lógica completa
  - **Pivot Automático**: `processar_artigos_pendentes()` agora verifica clusters existentes e escolhe o modo correto
  - **Prompt Especializado**: Usa `PROMPT_AGRUPAMENTO_INCREMENTAL_V1` para decisões inteligentes
  - **Lógica Completa**: Anexa a clusters existentes ou cria novos clusters conforme necessário
  - **Debug Detalhado**: Logs com emojis e informações detalhadas de cada decisão
  - **Correção do Prompt**: Chaves `{}` no JSON de exemplo foram escapadas para `{{}}` para evitar conflito com `.format()`
- ✅ **Resultado**: Agrupamento incremental agora funciona corretamente, permitindo receber novas notícias durante o dia

### **23. Correções Críticas de Processamento e Status (NOVO)**
- ✅ **Problema 1 Identificado**: Agrupamento incremental falhava com muitas notícias (174 artigos) devido a truncamento de JSON
- ✅ **Problema 2 Identificado**: `load_news.py` definia tags e prioridades inválidas que poderiam causar erros de validação
- ✅ **Problema 3 Identificado**: Artigos eram marcados como "processado" na ETAPA 1, impedindo reprocessamento se clusterização falhasse
- ✅ **Problema 4 Identificado**: ETAPA 3 processava clusters antigos em vez de apenas clusters novos sem resumo
- ✅ **Problema 5 Identificado**: Inconsistência de status entre ETAPA 1 e ETAPA 2 causava falha no agrupamento
- ✅ **Problema 6 Identificado**: Status "pronto_para_agrupamento" excedia limite de 20 caracteres do banco de dados
- ✅ **Problema 7 Identificado**: Modelo Pydantic não aceitava "PENDING" como valor válido para tag e prioridade
- ✅ **Problema 8 Identificado**: Função `get_artigos_by_cluster` filtrava por status "processado", mas artigos estavam com status "pronto_agrupar"
- ✅ **Problema 9 Identificado**: Clusters P3 não apareciam no frontend devido a falta de logs de debug
- ✅ **Problema 10 Identificado**: Frontend precisava de melhor aproveitamento de espaço e experiência de usuário
- ✅ **Problema 11 Identificado**: Interface precisava de redesign completo com paleta de cores e layout otimizado
- ✅ **Soluções Implementadas**:
  - **Chunking Automático**: Agrupamento incremental agora processa em lotes de 50 notícias para evitar truncamento
  - **Tags/Prioridades Neutras**: `load_news.py` e `process_articles.py` agora definem `tag: 'PENDING'` e `prioridade: 'PENDING'` em vez de valores inválidos
  - **Modelos Pydantic Atualizados**: Adicionado "PENDING" aos tipos `TagType` e `PrioridadeType` para aceitar valores pendentes
  - **Import Corrigido**: Adicionado `get_datetime_brasil_str` ao import de `backend.utils`
  - **Função CRUD Corrigida**: `get_artigos_by_cluster` agora busca artigos independente do status
  - **Logs de Debug Aprimorados**: Adicionados logs detalhados para debug de renderização de clusters P3
  - **Script de Teste**: Criado `test_p3_debug.js` para verificar dados no console do navegador
  - **Paleta de Cores Pastel**: Implementada paleta de 10 cores pastel estilo Tableau para tags
  - **Layout Otimizado**: Footer dos cards reorganizado com timestamp, tags e botão na mesma linha
  - **Tags Coloridas**: Cada tag tem cor única baseada em hash do nome, formato arredondado
  - **Sidebar Redesenhada**: Filtros de categoria agora são tags coloridas clicáveis
  - **Header Reorganizado**: Botão Settings movido para canto superior direito
  - **Métricas Simplificadas**: Apenas Notícias Coletadas, Eventos Únicos e Fontes Diferentes
  - **Contagem de Fontes**: Nova métrica com count distinct de fontes diferentes
  - **Status Inteligente**: Artigos só são marcados como "processado" após clusterização bem-sucedida na ETAPA 2
  - **Status Intermediário**: Novo status "pronto_agrupar" (15 chars) entre "pendente" e "processado"
  - **Função de Marcação**: Nova função `marcar_artigos_processados()` garante consistência de status
  - **Nova Função CRUD**: `update_artigo_dados_sem_status()` atualiza dados sem alterar status
  - **Filtro de Resumo**: ETAPA 3 agora processa apenas clusters sem resumo (`resumo_cluster.is_(None)`)
  - **Lógica Consistente**: ETAPA 1 marca como "pronto_agrupar", ETAPA 2 busca esse status
- ✅ **Resultado**: Sistema mais robusto, sem perda de dados, reprocessamento possível, processamento eficiente apenas de clusters novos e agrupamento funcionando corretamente

---

## 🛠️ **Troubleshooting**

### **Problema: "Python was not found"**
**Solução**: Use o Anaconda Prompt em vez do CMD do Windows

### **Problema: "UnicodeEncodeError"**
**Solução**: Use os scripts sem emojis (já corrigidos)

### **Problema: "GEMINI_API_KEY não configurada"**
**Solução**: Configure a chave no arquivo `backend/.env`. O sistema tem fallback para OCR completo se não disponível

### **Problema: "Erro de conexão com banco"**
**Solução**: Verifique se o PostgreSQL está rodando na porta 5433

### **Problema: "Nenhum artigo pendente encontrado"**
**Solução**: Execute primeiro o `load_news.py` para carregar artigos

### **Problema: "API não está disponível"**
**Solução**: Use `--direct` no `load_news.py` para conectar diretamente ao banco

### **Problema: "Erro no processamento"**
**Solução**: Verifique os logs e execute `test_fluxo_completo.py` para diagnóstico

### **Problema: "Seletor de data não funciona"**
**Solução**: Execute `test_ajustes.py` para verificar se as alterações estão funcionando

### **Problema: "PDFs não são processados corretamente"**
**Solução**: O `load_news.py` agora apenas carrega artigos brutos. Para processamento inteligente, execute `process_articles.py` após o carregamento.

### **Problema: "Sistema lento com muitas notícias"**
**Solução**: As otimizações de performance foram implementadas. Use paginação e carregamento lazy no frontend

---

## 📊 **Monitoramento**

### **Verificar Status**
```bash
# Status da API
curl "http://localhost:8000/health"

# Estatísticas do sistema
curl "http://localhost:8000/admin/stats"

# Feed com data específica
curl "http://localhost:8000/api/feed?data=2025-01-15"
```

### **Logs**
Os logs são salvos na tabela `logs_processamento` com níveis:
- `INFO`: Operações normais
- `WARNING`: Situações inesperadas
- `ERROR`: Erros que requerem atenção

---

## 🔐 **Segurança**

### **Configurações de Segurança**
1. **Nunca** commitar arquivos `.env`
2. Usar senhas fortes para PostgreSQL
3. Configurar firewall para portas específicas
4. Atualizar dependências regularmente
5. Configurar HTTPS em produção

### **Backup do Banco**
```bash
# Backup automático
pg_dump btg_alphafeed > backup_$(date +%Y%m%d).sql

# Restaurar backup
psql btg_alphafeed < backup_20250101.sql
```

---

## 🧪 **Testes**

### **Teste de Conexão**
```bash
python tests/test_imports.py
```

### **Teste do Fluxo Completo**
```bash
python test_fluxo_completo.py
```

### **Teste das Alterações (NOVO)**
```bash
python test_ajustes.py
```

### **Verificação Manual**
1. Execute o fluxo completo
2. Acesse o frontend
3. Teste o seletor de data
4. Verifique se os clusters aparecem
5. Teste o drill-down nos eventos
6. Confirme acesso aos artigos originais

---

## 🎯 **Resultado Esperado**

Após execução bem-sucedida:
1. ✅ Artigos brutos carregados no banco (notícias individuais dos PDFs)
2. ✅ Artigos processados e classificados
3. ✅ Clusters criados com prioridades corretas (agrupamento inteligente)
4. ✅ Resumos gerados com tamanhos diferenciados por prioridade
5. ✅ Frontend funcionando com seletor de data
6. ✅ Acesso total aos artigos originais
7. ✅ Interface administrativa disponível
8. ✅ Logs detalhados para monitoramento
9. ✅ Visualização histórica por data
10. ✅ Performance otimizada com paginação e carregamento lazy
11. ✅ Modal de detalhes para textos completos
12. ✅ Índices de performance aplicados no banco

---

## 📞 **Suporte**

### **Checklist de Diagnóstico**
- [ ] Ambiente conda `pymc2` ativo
- [ ] PostgreSQL rodando e acessível
- [ ] Arquivo `.env` configurado corretamente
- [ ] Dependências Python instaladas
- [ ] Banco de dados inicializado
- [ ] API Gemini funcionando (ou fallback para OCR)
- [ ] Frontend acessível em localhost:8000
- [ ] Seletor de data funcionando
- [ ] Testes passando (`test_ajustes.py`)
- [ ] Extração inteligente de PDFs funcionando
- [ ] Agrupamento inteligente funcionando
- [ ] Performance otimizada (paginação e carregamento lazy)

### **Logs Úteis**
```bash
# Verificar logs de erro da aplicação
grep ERROR /var/log/btg_alphafeed.log

# Verificar uso de recursos
ps aux | grep python
df -h
free -m
```

Para problemas não resolvidos:
1. Verificar documentação neste README
2. Consultar logs detalhados
3. Testar componentes individualmente
4. Executar `test_ajustes.py` para diagnóstico
5. Reportar problema com logs completos