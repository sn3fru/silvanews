// =======================================
// CONFIGURAÇÃO DA API
// =======================================
const API_BASE = window.location.origin; // Usa o mesmo domínio da aplicação

// =======================================
// REFERÊNCIAS AOS ELEMENTOS DO DOM
// =======================================
// Seletor de Data
const dataAtual = document.getElementById('data-atual');
const dataTexto = document.getElementById('data-texto');
const dataInput = document.getElementById('data-input');
const dataAnterior = document.getElementById('data-anterior');
const dataProxima = document.getElementById('data-proxima');

// Métricas e Síntese
const metricColetadas = document.getElementById('metric-coletadas');
const metricEventos = document.getElementById('metric-eventos');
const metricP1 = document.getElementById('metric-p1');
const metricP2P3 = document.getElementById('metric-p2p3');

// Feed
const feedContainer = document.getElementById('feed-container');
const cardTemplate = document.getElementById('card-template');

// Modal
const modal = document.getElementById('modal-deep-dive');
const modalCloseBtn = document.getElementById('modal-close-btn');
const modalTitulo = document.getElementById('modal-titulo');
const modalResumo = document.getElementById('modal-resumo');
const modalTabs = document.querySelector('.modal-tabs');
const modalCopyBtn = document.getElementById('modal-copy-btn');
const tabContents = document.querySelectorAll('.tab-content');
const listaFontesContainer = document.getElementById('lista-fontes-container');

// Filtros
const filtrosPrioridadeContainer = document.getElementById('filtros-prioridade');
const filtrosCategoriaContainer = document.getElementById('filtros-categoria');
const btnCriarFeed = document.getElementById('btn-criar-feed');

// =======================================
// VARIÁVEIS GLOBAIS
// =======================================
// Variável removida - agora usa clustersCarregados diretamente
let refreshInterval = null; // Intervalo para atualização automática
let currentClusterId = null; // ID do cluster atual no modal
let currentChatSession = null; // Sessão de chat atual
let currentTags = []; // Tags atuais do cluster
let currentClusterDetails = null; // Detalhes do cluster atualmente aberto no modal

// Helpers de data sem impacto de fuso (tratam 'YYYY-MM-DD' como data local)
function parseLocalDate(yyyyMmDd) {
    if (!yyyyMmDd) return new Date();
    const [y, m, d] = yyyyMmDd.split('-').map(Number);
    return new Date(y, (m || 1) - 1, d || 1);
}

function formatLocalYYYYMMDD(dateObj) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

// Função para obter a data de hoje no formato YYYY-MM-DD
function getTodayDate() {
    // SOLUÇÃO DEFINITIVA: Usa data exata do sistema
    const hoje = new Date();
    const ano = hoje.getFullYear();
    const mes = String(hoje.getMonth() + 1).padStart(2, '0');
    const dia = String(hoje.getDate()).padStart(2, '0');
    const dataFormatada = `${ano}-${mes}-${dia}`;
    
    console.log('getTodayDate() - DATA EXATA:', {
        hoje: dataFormatada
    });
    return dataFormatada;
}

let selectedDate = getTodayDate(); // Data selecionada (YYYY-MM-DD)
let currentDate = getTodayDate(); // Data atual para navegação

console.log('Inicialização - selectedDate:', selectedDate);
console.log('Inicialização - currentDate:', currentDate);
let isHistoricalView = false; // Se está visualizando dados históricos

// Variáveis de carregamento progressivo
let isLoading = false;
let loadingProgress = 0; // 0-100%
let currentLoadingPhase = ''; // 'P1', 'P2', 'P3'

// Cache inteligente
const clusterCache = new Map();
const CACHE_TTL_DAYS = 7; // 7 dias para dias anteriores
const CACHE_TTL_MINUTES = 5; // 5 minutos para dia atual

// Estado dos clusters carregados
let clustersCarregados = [];
let clustersP1 = [];
let clustersP2 = [];
let clustersP3 = [];

// =======================================
// INICIALIZAÇÃO
// =======================================
document.addEventListener('DOMContentLoaded', async () => {
    // Aguarda um pouco mais para garantir que o CSS esteja carregado
    setTimeout(async () => {
        try {
            setupEventListeners();
            atualizarDataTexto(); // Atualiza o texto da data antes de carregar
            
            // Carrega o feed primeiro (que já chama carregarTagsDisponiveis internamente)
            await carregarFeed();
        } catch (error) {
            console.error('❌ Erro na inicialização:', error);
        }
    }, 100);
});

// =======================================
// FUNÇÕES DE CACHE E CARREGAMENTO PROGRESSIVO
// =======================================

function getCacheKey(date) {
    return `clusters_${date}`;
}

function isCacheValid(cacheKey, isCurrentDay = false) {
    const cached = clusterCache.get(cacheKey);
    if (!cached) return false;
    
    const now = new Date();
    const cacheAge = now - cached.timestamp;
    
    if (isCurrentDay) {
        // Para dia atual: 5 minutos
        return cacheAge < (CACHE_TTL_MINUTES * 60 * 1000);
    } else {
        // Para dias anteriores: 7 dias
        return cacheAge < (CACHE_TTL_DAYS * 24 * 60 * 60 * 1000);
    }
}

function saveToCache(date, data) {
    const cacheKey = getCacheKey(date);
    clusterCache.set(cacheKey, {
        data: data,
        timestamp: new Date().getTime()
    });
}

function getFromCache(date) {
    const cacheKey = getCacheKey(date);
    const cached = clusterCache.get(cacheKey);
    return cached ? cached.data : null;
}

function updateLoadingProgress(phase, progress) {
    currentLoadingPhase = phase;
    loadingProgress = progress;
    
    // Atualiza a barra de loading
    const loadingProgressEl = document.getElementById('loading-progress');
    const loadingBar = document.getElementById('loading-bar');
    const loadingText = document.getElementById('loading-text');
    
    if (loadingProgressEl && loadingBar && loadingText) {
        // Mostra a barra se estiver oculta
        if (loadingProgressEl.style.display === 'none') {
            loadingProgressEl.style.display = 'block';
        }
        
        loadingBar.style.width = `${progress}%`;
        loadingText.textContent = `Carregando ${phase}... ${progress}%`;
        
        if (progress >= 100) {
            setTimeout(() => {
                loadingProgressEl.style.display = 'none';
            }, 1000);
        }
    }
}

// Busca todas as páginas para uma prioridade específica, acumulando todos os clusters do dia
async function fetchTodasPaginasPorPrioridade(date, priority, pageSize = 50, onPageLoaded = null) {
    let page = 1;
    let temProxima = true;
    const acumulado = [];
    let metricasPrimeiraPagina = null;

    while (temProxima) {
        const url = `/api/feed?data=${date}&priority=${priority}&page=${page}&page_size=${pageSize}`;
        const resp = await fetch(url);
        if (!resp.ok) break;
        const data = await resp.json();

        if (page === 1 && data.metricas) {
            metricasPrimeiraPagina = data.metricas;
        }

        const itens = data.feed || [];
        if (itens.length > 0) acumulado.push(...itens);

        if (typeof onPageLoaded === 'function') {
            try { onPageLoaded({ page, pageSize, carregados: acumulado.length }); } catch (_) {}
        }

        const paginacao = data.paginacao || {};
        temProxima = !!paginacao.tem_proxima;
        page += 1;
    }

    return { itens: acumulado, metricas: metricasPrimeiraPagina };
}

async function carregarClustersPorPrioridade(date) {
    console.log('🚀 Iniciando carregamento progressivo para:', date);
    
    // Verifica cache primeiro
    const isCurrentDay = date === getTodayDate();
    const cachedData = getFromCache(date);
    
    if (cachedData && isCacheValid(getCacheKey(date), isCurrentDay)) {
        console.log('✅ Usando dados do cache para data:', date);
        clustersCarregados = cachedData.clusters;
        clustersP1 = cachedData.p1;
        clustersP2 = cachedData.p2;
        clustersP3 = cachedData.p3;
        
        renderizarClusters();
        if (cachedData.metricas) {
            console.log('📊 Atualizando métricas do cache:', cachedData.metricas);
            atualizarMetricas(cachedData.metricas);
        } else {
            console.warn('⚠️ Cache não contém métricas, carregando da API');
            // Se o cache não tem métricas, força recarregamento
            const p1Response = await fetch(`/api/feed?data=${date}&priority=P1_CRITICO&page=1&page_size=50`);
            if (p1Response.ok) {
                const p1Data = await p1Response.json();
                if (p1Data.metricas) {
                    console.log('📊 Métricas carregadas da API:', p1Data.metricas);
                    atualizarMetricas(p1Data.metricas);
                }
            }
        }
        await carregarTagsDisponiveis();
        return;
    }
    
    // Inicia carregamento progressivo
    isLoading = true;
    clustersCarregados = [];
    clustersP1 = [];
    clustersP2 = [];
    clustersP3 = [];
    
    try {
        // Fase 1: Carrega P1 (crítico) - TODAS AS PÁGINAS
        updateLoadingProgress('P1 (Crítico)', 10);
        console.log('📊 Carregando P1 (todas as páginas)...');

        let metricas = { coletadas: 0, eventos: 0, fontes: 0 };
        const p1 = await fetchTodasPaginasPorPrioridade(
            date,
            'P1_CRITICO',
            50,
            ({ page, carregados }) => updateLoadingProgress(`P1 (pág. ${page})`, Math.min(10 + page * 5, 35))
        );
        clustersP1 = p1.itens;
        clustersCarregados = [...clustersP1];
        if (p1.metricas) {
            metricas = p1.metricas;
            atualizarMetricas(metricas);
        }
        renderizarClusters();
        updateLoadingProgress('P1 (Crítico)', 35);
        console.log(`✅ P1 carregado (total): ${clustersP1.length} clusters`);

        // Fase 2: Carrega P2 (estratégico) - TODAS AS PÁGINAS
        updateLoadingProgress('P2 (Estratégico)', 40);
        console.log('📊 Carregando P2 (todas as páginas)...');
        const p2 = await fetchTodasPaginasPorPrioridade(
            date,
            'P2_ESTRATEGICO',
            50,
            ({ page }) => updateLoadingProgress(`P2 (pág. ${page})`, Math.min(40 + page * 5, 70))
        );
        clustersP2 = p2.itens;
        clustersCarregados = [...clustersP1, ...clustersP2];
        renderizarClusters();
        updateLoadingProgress('P2 (Estratégico)', 70);
        console.log(`✅ P2 carregado (total): ${clustersP2.length} clusters`);

        // Fase 3: Carrega P3 (monitoramento) - TODAS AS PÁGINAS
        updateLoadingProgress('P3 (Monitoramento)', 75);
        console.log('📊 Carregando P3 (todas as páginas)...');
        const p3 = await fetchTodasPaginasPorPrioridade(
            date,
            'P3_MONITORAMENTO',
            50,
            ({ page }) => updateLoadingProgress(`P3 (pág. ${page})`, Math.min(75 + page * 5, 95))
        );
        clustersP3 = p3.itens;
        clustersCarregados = [...clustersP1, ...clustersP2, ...clustersP3];
        renderizarClusters();
        updateLoadingProgress('P3 (Monitoramento)', 95);
        console.log(`✅ P3 carregado (total): ${clustersP3.length} clusters`);

        // Finaliza carregamento
        updateLoadingProgress('Finalizando', 100);

        // Carrega tags e atualiza contadores
        await carregarTagsDisponiveis();

        // Salva no cache
        const cacheData = {
            clusters: clustersCarregados,
            p1: clustersP1,
            p2: clustersP2,
            p3: clustersP3,
            metricas: metricas
        };
        saveToCache(date, cacheData);
        console.log('💾 Cache salvo para data:', date, 'com métricas:', metricas);

        console.log(`🎉 Carregamento completo: ${clustersCarregados.length} clusters`);

        // Garante que as métricas sejam sempre atualizadas
        if (!metricas || Object.keys(metricas).length === 0) {
            console.warn('⚠️ Métricas vazias, definindo valores padrão');
            metricas = { coletadas: 0, eventos: 0, fontes: 0 };
            atualizarMetricas(metricas);
        }

    } catch (error) {
        console.error('❌ Erro no carregamento progressivo:', error);
        updateLoadingProgress('Erro', 0);
    } finally {
        isLoading = false;
    }
}



// =======================================
// CONFIGURAÇÃO DE EVENT LISTENERS
// =======================================
function setupEventListeners() {
    // Seletor de data
    if (dataAnterior) dataAnterior.addEventListener('click', () => navegarData(-1));
    if (dataProxima) dataProxima.addEventListener('click', () => navegarData(1));
    if (dataTexto) dataTexto.addEventListener('click', () => dataInput && dataInput.showPicker());
    if (dataInput) dataInput.addEventListener('change', (e) => {
        currentDate = e.target.value;
        atualizarDataTexto();
        carregarFeed();
    });

    // Scroll infinito removido - agora usa carregamento progressivo por prioridade

    // Filtros de Prioridade
    if (filtrosPrioridadeContainer) filtrosPrioridadeContainer.addEventListener('click', (e) => {
        if (e.target.classList.contains('filtro-btn')) {
            const currentActive = e.target.classList.contains('ativo');
            filtrosPrioridadeContainer.querySelectorAll('.filtro-btn').forEach(btn => btn.classList.remove('ativo'));
            if (!currentActive) e.target.classList.add('ativo');
            filterAndRender();
        }
    });
    
    // Filtros de Categoria
    if (filtrosCategoriaContainer) filtrosCategoriaContainer.addEventListener('change', filterAndRender);

    // Modal
    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeModal);
    if (modal) modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    // Botão Copiar no modal
    if (modalCopyBtn) {
        modalCopyBtn.addEventListener('click', async () => {
            const id = currentClusterId;
            if (!id) return;
            // Preferir detalhes já carregados no modal
            if (currentClusterDetails) {
                await copyClusterToClipboard(currentClusterDetails);
                return;
            }
            // Fallback: procurar no cache do feed
            let cluster = (clustersCarregados || []).find(c => String(c.id) === String(id));
            if (!cluster) {
                try {
                    const details = await carregarDetalhesCluster(id);
                    if (details) {
                        currentClusterDetails = details;
                        await copyClusterToClipboard(details);
                        return;
                    }
                } catch (_) {}
                showErrorMessage('Cluster não encontrado');
                return;
            }
            await copyClusterToClipboard(cluster);
        });
    }

    // Tabs do Modal
    if (modalTabs) modalTabs.addEventListener('click', (e) => {
        if (e.target.classList.contains('tab-btn')) {
            modalTabs.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('ativo'));
            tabContents.forEach(content => content.classList.add('oculto'));
            
            e.target.classList.add('ativo');
            const targetTab = e.target.getAttribute('data-tab');
            const targetContent = document.getElementById(targetTab);
            if (targetContent) {
                targetContent.classList.remove('oculto');
            }
        }
    });



    // Botão criar feed
    if (btnCriarFeed) btnCriarFeed.addEventListener('click', () => {
        showNotification('Funcionalidade em desenvolvimento', 'info');
    });

    // Modal de configuração de prompts
    const modalPromptsConfig = document.getElementById('modal-prompts-config');
    const modalPromptsCloseBtn = document.getElementById('modal-prompts-close-btn');
    const promptsTabs = document.querySelector('.prompts-tabs');
    const promptTabContents = document.querySelectorAll('.prompt-tab-content');
    
    if (modalPromptsCloseBtn) modalPromptsCloseBtn.addEventListener('click', closePromptsModal);
    if (modalPromptsConfig) modalPromptsConfig.addEventListener('click', (e) => {
        if (e.target === modalPromptsConfig) closePromptsModal();
    });

    // Tabs do modal de prompts
    if (promptsTabs) promptsTabs.addEventListener('click', (e) => {
        const btn = e.target.closest('.prompt-tab-btn');
        if (!btn) return;

        // Atualiza estado dos botões
        promptsTabs.querySelectorAll('.prompt-tab-btn').forEach(b => b.classList.remove('ativo'));
        btn.classList.add('ativo');

        // Atualiza estado dos conteúdos (usa classe 'ativo' conforme CSS)
        promptTabContents.forEach(content => {
            content.classList.remove('ativo');
            content.classList.add('oculto');
        });

        const targetTab = btn.getAttribute('data-tab');
        const targetContent = document.getElementById(targetTab);
        if (targetContent) {
            targetContent.classList.remove('oculto');
            targetContent.classList.add('ativo');
        }
    });

    // Botões de ação do modal de prompts
    const savePromptsBtn = document.getElementById('save-prompts-btn');
    const cancelPromptsBtn = document.getElementById('cancel-prompts-btn');
    const resetPromptsBtn = document.getElementById('reset-prompts-btn');
    
    if (savePromptsBtn) savePromptsBtn.addEventListener('click', salvarConfiguracoesPrompts);
    if (cancelPromptsBtn) cancelPromptsBtn.addEventListener('click', closePromptsModal);
    if (resetPromptsBtn) resetPromptsBtn.addEventListener('click', restaurarConfiguracoesPadrao);

    // Feed de clusters (delegação de eventos)
    if (feedContainer) feedContainer.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-deep-dive')) {
            const card = e.target.closest('.card-cluster');
            if (card) {
                const clusterId = card.getAttribute('data-cluster-id');
                if (clusterId) {
                    openModal(clusterId);
                }
            }
        }

        // Botões de feedback (like/dislike)
        const thumbBtn = e.target.closest('.btn-thumb');
        if (thumbBtn) {
            const card = thumbBtn.closest('.card-cluster');
            const clusterId = card ? card.getAttribute('data-cluster-id') : thumbBtn.getAttribute('data-cluster-id');
            if (!clusterId) return;
            const tipo = thumbBtn.classList.contains('up') ? 'like' : 'dislike';
            registrarFeedbackCluster(clusterId, tipo, thumbBtn);
        }
    });

    // Link Special Situations - abre modal de configuração
    const specialSituationsLink = document.querySelector('.feed-link.ativo');
    if (specialSituationsLink) {
        specialSituationsLink.addEventListener('click', (e) => {
            e.preventDefault();
            openPromptsModal();
        });
    }

    // Chat
    const chatInput = document.getElementById('chat-input');
    const chatSendBtn = document.getElementById('chat-send-btn');
    const btnDeepResearch = document.getElementById('btn-deep-research');
    const btnSocialResearch = document.getElementById('btn-social-research');
    
    if (chatInput && chatSendBtn) {
        chatSendBtn.addEventListener('click', enviarMensagemChat);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                enviarMensagemChat();
            }
        });
    }

    if (btnDeepResearch) {
        btnDeepResearch.addEventListener('click', iniciarDeepResearch);
    }
    if (btnSocialResearch) {
        btnSocialResearch.addEventListener('click', iniciarSocialResearch);
    }

    // Gerenciamento de tags
    const editTagsInput = document.getElementById('edit-tags-input');
    if (editTagsInput) {
        editTagsInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const tag = e.target.value.trim();
                if (tag) {
                    adicionarTag(tag);
                    e.target.value = '';
                }
            }
        });
    }

    // Botões de gerenciamento
    const saveChangesBtn = document.getElementById('save-changes-btn');
    const cancelEditBtn = document.getElementById('cancel-edit-btn');
    
    if (saveChangesBtn) {
        saveChangesBtn.addEventListener('click', salvarAlteracoes);
    }
    
    if (cancelEditBtn) {
        cancelEditBtn.addEventListener('click', () => {
            // Recarrega dados originais
            if (currentClusterId) {
                carregarDetalhesCluster(currentClusterId).then(clusterData => {
                    if (clusterData) {
                        carregarDadosEdicao(clusterData);
                    }
                });
            }
        });
    }
}

// =======================================
// FUNÇÕES DE NAVEGAÇÃO DE DATA
// =======================================
function navegarData(dias) {
    console.log('🔄 navegarData chamado com dias:', dias, 'data atual:', currentDate);
    const data = parseLocalDate(currentDate);
    data.setDate(data.getDate() + dias);
    currentDate = formatLocalYYYYMMDD(data);
    console.log('📅 Nova data selecionada:', currentDate);
    atualizarDataTexto();
    carregarFeed();
}

// Função removida - agora usa carregamento progressivo por prioridade

function atualizarDataTexto() {
    if (!dataTexto) return;
    
    const data = parseLocalDate(currentDate);
    const hoje = new Date();
    const ontem = new Date(hoje);
    ontem.setDate(hoje.getDate() - 1);

    if (data.toDateString() === hoje.toDateString()) {
        dataTexto.textContent = 'Hoje';
    } else if (data.toDateString() === ontem.toDateString()) {
        dataTexto.textContent = 'Ontem';
    } else {
        dataTexto.textContent = data.toLocaleDateString('pt-BR');
    }
}

// =======================================
// FUNÇÕES DE CARREGAMENTO DE DADOS
// =======================================
async function carregarMetricas(date) {
    try {
        const resp = await fetch(`/api/feed?data=${date}&page=1&page_size=1`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data && data.metricas) {
            atualizarMetricas(data.metricas);
        }
    } catch (e) {
        console.warn('⚠️ Falha ao carregar métricas para a data', date, e);
    }
}

async function carregarFeed() {
    if (isLoading) return;
    
    try {
        console.log('🚀 carregarFeed chamado para data:', currentDate);
        // Atualiza métricas específicas da data
        await carregarMetricas(currentDate);
        // Usa o novo sistema de carregamento progressivo
        await carregarClustersPorPrioridade(currentDate);
        
    } catch (error) {
        console.error('❌ Erro ao carregar feed:', error);
        mostrarErro('Erro ao carregar notícias. Tente novamente.');
    }
}

function renderizarClusters() {
    if (!feedContainer) return;
    
    // Limpa o container
    feedContainer.innerHTML = '';
    
    if (clustersCarregados.length === 0) {
        showEmptyFeedMessage();
        return;
    }
    
    console.log('🎨 Renderizando', clustersCarregados.length, 'clusters');
    
    // Renderiza clusters P1 e P2 normalmente
    const clustersP1P2 = clustersCarregados.filter(c => 
        c.prioridade === 'P1_CRITICO' || c.prioridade === 'P2_ESTRATEGICO'
    );
    
    clustersP1P2.forEach(cluster => {
        const card = criarCardCluster(cluster);
        feedContainer.appendChild(card);
    });
    
    // Renderiza clusters P3 agrupados por tag
    const clustersP3 = clustersCarregados.filter(c => c.prioridade === 'P3_MONITORAMENTO');
    if (clustersP3.length > 0) {
        const gruposP3 = agruparClustersP3PorTag(clustersP3);
        gruposP3.forEach(grupo => {
            const card = criarCardGrupoP3(grupo);
            feedContainer.appendChild(card);
        });
    }
}

// Função removida - agora usa carregamento progressivo por prioridade

async function carregarDetalhesCluster(clusterId) {
    try {
        const response = await fetch(`/api/cluster/${clusterId}`);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const clusterDetails = await response.json();
        return clusterDetails;
        
    } catch (error) {
        console.error('Erro ao carregar detalhes do cluster:', error);
        mostrarErro('Erro ao carregar detalhes da notícia');
        return null;
    }
}

// =======================================
// FUNÇÕES DE RENDERIZAÇÃO
// =======================================
function atualizarMetricas(metricas) {
    console.log('🔄 atualizarMetricas chamado com:', metricas);
    const metricColetadas = document.getElementById('metric-coletadas');
    const metricEventos = document.getElementById('metric-eventos');
    const metricFontes = document.getElementById('metric-fontes');
    const metricComResumo = document.getElementById('metric-com-resumo');
    
    if (!metricColetadas || !metricEventos || !metricFontes) {
        console.error('❌ Elementos de métricas não encontrados');
        return;
    }
    
    console.log('📊 Atualizando métricas na UI:', {
        coletadas: metricas.coletadas,
        eventos: metricas.eventos,
        fontes: metricas.fontes
    });
    
    metricColetadas.textContent = (metricas.coletadas || 0).toLocaleString('pt-BR');
    metricEventos.textContent = (metricas.eventos || 0).toLocaleString('pt-BR');
    metricFontes.textContent = (metricas.fontes || 0).toLocaleString('pt-BR');
    if (metricComResumo) {
        metricComResumo.textContent = (metricas.com_resumo || 0).toLocaleString('pt-BR');
    }
    
    console.log('✅ Métricas atualizadas na UI');
}

function renderSintese(sintese) {
    if (!feedContainer) return;
    
    const sinteseElement = document.createElement('article');
    sinteseElement.className = 'card-sintese';
    sinteseElement.innerHTML = `
        <div class="card-header">
            <h2 class="card-titulo">⭐ Síntese Executiva do Dia - ${formatarDataTitulo(currentDate)}</h2>
        </div>
        <p class="card-resumo">${sintese.texto_sintese || 'Síntese em processamento...'}</p>
    `;
    feedContainer.appendChild(sinteseElement);
}

function criarCardCluster(cluster) {
    const card = document.createElement('article');
    card.className = 'card-cluster';
    // Adiciona classe de prioridade
    const prioridadeClass = getPrioridadeClass(cluster.prioridade);
    card.classList.add(prioridadeClass);
    card.dataset.clusterId = cluster.id;
    
    // Gera cor da tag baseada no nome
    const tagColorClass = getTagColorClass(cluster.tag);
    
    card.innerHTML = `
        <div class="card-header">
            <div class="card-title-area">
                <h3 class="card-titulo">${cluster.titulo_final}</h3>
                <div class="card-actions-feedback">
                    <button class="btn-thumb up" data-cluster-id="${cluster.id}" title="Gostei (like)">👍</button>
                    <button class="btn-thumb down" data-cluster-id="${cluster.id}" title="Não gostei (dislike)">👎</button>
                </div>
            </div>
            <div class="card-contador-fontes" title="Número de fontes agrupadas">
                <span>📰</span>
                <span class="contador">${cluster.total_artigos}</span>
            </div>
        </div>
        <p class="card-resumo">${cluster.resumo_final}</p>
        <div class="card-footer">
            <div class="card-footer-left">
                <span class="card-timestamp">${cluster.timestamp}</span>
                <div class="card-tags">
                    <span class="tag ${tagColorClass}">${cluster.tag}</span>
                </div>
            </div>
            <div class="card-footer-right">
                <button class="btn btn-secundario btn-copy" data-cluster-id="${cluster.id}">📋 Copiar</button>
                <button class="btn btn-deep-dive" onclick="openModal(${cluster.id})">
                    💬 Conversar com a notícia
                </button>
            </div>
        </div>
    `;
    // Marca feedback persistido (se existir)
    try {
        const upBtn = card.querySelector('.btn-thumb.up');
        const downBtn = card.querySelector('.btn-thumb.down');
        const fb = cluster && cluster.feedback ? cluster.feedback : null;
        if (fb && (upBtn || downBtn)) {
            if (fb.last === 'like') {
                upBtn && upBtn.classList.add('active');
            } else if (fb.last === 'dislike') {
                downBtn && downBtn.classList.add('active');
            } else if ((fb.likes || 0) > (fb.dislikes || 0)) {
                upBtn && upBtn.classList.add('active');
            } else if ((fb.dislikes || 0) > (fb.likes || 0)) {
                downBtn && downBtn.classList.add('active');
            }
        }
    } catch (_) {}
    return card;
}

// =======================================
// FUNÇÕES DO MODAL
// =======================================
async function openModal(clusterId) {
    if (!clusterId) return;
    
    try {
        showModalLoading();
        currentClusterId = clusterId;
        
        const clusterData = await carregarDetalhesCluster(clusterId);
        if (!clusterData) {
            hideModalLoading();
            return;
        }
        
        currentClusterDetails = clusterData;

        // Preenche dados básicos
        if (modalTitulo) modalTitulo.textContent = clusterData.titulo_final;
        if (modalResumo) modalResumo.textContent = clusterData.resumo_final;
        
        // Renderiza fontes
        renderizarFontes(clusterData.fontes);
        
        // Carrega chat
        await carregarChat(clusterId);
        
        // Carrega dados para edição
        carregarDadosEdicao(clusterData);
        
        // Carrega histórico de alterações
        await carregarAlteracoes(clusterId);
        
        hideModalLoading();
        if (modal) modal.classList.remove('oculto');
        
    } catch (error) {
        console.error('Erro ao abrir modal:', error);
        hideModalLoading();
        showErrorMessage('Erro ao carregar detalhes do evento');
    }
}

function closeModal() {
    if (modal) modal.classList.add('oculto');
}

function showModalLoading() {
    if (modalTitulo) modalTitulo.textContent = 'Carregando...';
    if (modalResumo) modalResumo.textContent = 'Buscando informações detalhadas do evento...';
    if (listaFontesContainer) listaFontesContainer.innerHTML = '<li>Carregando fontes...</li>';
}

function hideModalLoading() {
    // Não faz nada, os dados reais substituem o loading
}

function mostrarModalDetalhes(clusterDetails) {
    if (modalTitulo) modalTitulo.textContent = clusterDetails.titulo_final;
    if (modalResumo) modalResumo.textContent = clusterDetails.resumo_final;
    
    // Renderiza fontes
    if (listaFontesContainer) {
        listaFontesContainer.innerHTML = '';
        if (clusterDetails.fontes && clusterDetails.fontes.length > 0) {
            clusterDetails.fontes.forEach(fonte => {
                const li = document.createElement('li');
                const icon = fonte.tipo === 'pdf' ? '📄' : '🔗';
                li.innerHTML = `
                    <span>${icon} ${fonte.nome}</span>
                    <a href="${fonte.url}" target="_blank" class="btn btn-terciario">Acessar Original</a>
                `;
                listaFontesContainer.appendChild(li);
            });
        } else {
            listaFontesContainer.innerHTML = '<li>Nenhuma fonte disponível</li>';
        }
    }
    
    if (modal) modal.classList.remove('oculto');
}

// ================================
// COPIAR PARA CLIPBOARD (cluster)
// ================================
function formatarDataBR(isoStr) {
    try {
        const d = isoStr ? new Date(isoStr) : new Date();
        return new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo' }).format(d);
    } catch {
        return new Date().toLocaleDateString('pt-BR');
    }
}

function extrairFonteELink(cluster) {
    // Usa as fontes fornecidas pelo backend; nome = arquivo PDF ou site; url apenas quando existir
    let fonte = 'N/A';
    let link = null;
    if (Array.isArray(cluster.fontes) && cluster.fontes.length > 0) {
        const primeira = cluster.fontes[0];
        fonte = primeira && primeira.nome ? primeira.nome : 'N/A';
        link = primeira && primeira.url ? primeira.url : null;
    }
    return { fonte, link };
}

function buildClipboardPayload(cluster) {
    const titulo = cluster.titulo_final || cluster.titulo_cluster || 'Sem título';
    const resumo = cluster.resumo_final || cluster.resumo_cluster || 'Sem resumo';
    const { fonte, link } = extrairFonteELink(cluster);
    // Captura autor/página se existirem na primeira fonte
    let fonteDetalhe = fonte;
    if (Array.isArray(cluster.fontes) && cluster.fontes.length > 0) {
        const f0 = cluster.fontes[0];
        const partes = [];
        if (f0.pagina && String(f0.pagina).toLowerCase() !== 'n/a') partes.push(`pág. ${f0.pagina}`);
        if (f0.autor && String(f0.autor).toLowerCase() !== 'n/a') partes.push(`por ${f0.autor}`);
        if (partes.length) fonteDetalhe = `${fonte} (${partes.join(', ')})`;
    }
    const dataStr = formatarDataBR(cluster.timestamp || cluster.created_at);

    const text = `*Título:* ${titulo} / *Fonte:* ${fonteDetalhe} / ${dataStr}\n*Resumo:* ${resumo}${link ? `\n*Link:* ${link}` : ''}`;

    const html = `<div>
  <div><b>Título:</b> ${titulo} / <b>Fonte:</b> ${fonteDetalhe} / ${dataStr}</div>
  <div><b>Resumo:</b> ${resumo}</div>
  ${link ? `<div><b>Link:</b> <a href="${link}">${link}</a></div>` : ``}
</div>`;

    return { text, html };
}

async function copyClusterToClipboard(cluster) {
    const { text, html } = buildClipboardPayload(cluster);

    let success = false;

    // 1) Tentar texto simples (alta compatibilidade)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            success = true;
        } catch (_) {}
    }

    // 2) Tentar rich text (HTML) como best-effort, sem alterar sucesso se falhar
    if (navigator.clipboard && window.ClipboardItem) {
        try {
            const data = [new ClipboardItem({
                'text/plain': new Blob([text], { type: 'text/plain' }),
                'text/html': new Blob([html], { type: 'text/html' })
            })];
            await navigator.clipboard.write(data);
            success = true;
        } catch (_) {}
    }

    // 3) Fallback com textarea se ainda não copiou
    if (!success) {
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.setAttribute('readonly', '');
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            success = true;
        } catch (_) {}
    }

    if (success) {
        if (typeof showSuccessMessage === 'function') {
            showSuccessMessage('Resumo copiado');
        } else {
            showNotification('Resumo copiado', 'success');
        }
        return true;
    } else {
        showErrorMessage('Falha ao copiar');
        return false;
    }
}

// Delegação de eventos para botões Copiar
document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-copy');
    if (!btn) return;
    const id = btn.getAttribute('data-cluster-id');
    let cluster = (clustersCarregados || []).find(c => String(c.id) === String(id));
    if (!cluster) {
        // Tenta carregar detalhes direto da API como fallback
        try {
            const details = await carregarDetalhesCluster(id);
            if (details) {
                await copyClusterToClipboard(details);
                return;
            }
        } catch (_) {}
        showErrorMessage('Cluster não encontrado');
        return;
    }
    await copyClusterToClipboard(cluster);
});

// =============================
// FEEDBACK: like / dislike
// =============================
async function registrarFeedbackCluster(clusterId, tipo, btnEl) {
    try {
        // Busca detalhes do cluster para obter um artigo_id válido
        const details = await carregarDetalhesCluster(clusterId);
        if (!details || !Array.isArray(details.artigos) || details.artigos.length === 0) {
            showErrorMessage('Não foi possível identificar um artigo deste cluster');
            return;
        }

        const artigoId = details.artigos[0].id;
        const url = `/api/feedback?artigo_id=${encodeURIComponent(artigoId)}&feedback=${encodeURIComponent(tipo)}`;
        const resp = await fetch(url, { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            showErrorMessage(`Erro ao registrar feedback: ${data.detail || resp.status}`);
            return;
        }

        // Feedback visual rápido
        if (btnEl) {
            btnEl.classList.add('active');
            setTimeout(() => btnEl.classList.remove('active'), 1200);
        }
        showNotification(`Feedback '${tipo}' registrado`, 'success');
    } catch (e) {
        showErrorMessage('Falha ao registrar feedback');
        console.error(e);
    }
}

function renderizarFontes(fontes) {
    if (!listaFontesContainer) return;
    
    listaFontesContainer.innerHTML = '';
    if (fontes && fontes.length > 0) {
        fontes.forEach(fonte => {
            const li = document.createElement('li');
            const icon = fonte.tipo === 'pdf' ? '📄' : '🔗';
            li.innerHTML = `
                <span>${icon} ${fonte.nome}</span>
                <a href="${fonte.url}" target="_blank" class="btn btn-terciario">Acessar Original</a>
            `;
            listaFontesContainer.appendChild(li);
        });
    } else {
        listaFontesContainer.innerHTML = '<li>Nenhuma fonte disponível</li>';
    }
}

async function carregarChat(clusterId) {
    try {
        const response = await fetch(`/api/chat/${clusterId}/messages`);
        if (response.ok) {
            const data = await response.json();
            currentChatSession = data.session_id;
            renderizarChat(data.messages);
        }
    } catch (error) {
        console.error('Erro ao carregar chat:', error);
    }
}

function renderizarChat(messages) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;
    
    chatMessages.innerHTML = '';
    
    if (messages.length === 0) {
        chatMessages.innerHTML = '<div class="message system">Faça uma pergunta sobre este evento.</div>';
        return;
    }
    
    messages.forEach(msg => {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${msg.role}`;
        messageDiv.textContent = msg.content;
        chatMessages.appendChild(messageDiv);
    });
    
    // Scroll para a última mensagem
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function iniciarDeepResearch() {
    if (!currentClusterId) return;
    try {
        const resp = await fetch(`/api/research/deep/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cluster_id: currentClusterId })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Falha ao iniciar deep research');
        showNotification('Deep research iniciado', 'success');
        acompanharJob('deep', data.job_id);
    } catch (e) {
        console.error(e);
        showErrorMessage('Erro ao iniciar deep research');
    }
}

async function iniciarSocialResearch() {
    if (!currentClusterId) return;
    try {
        const resp = await fetch(`/api/research/social/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cluster_id: currentClusterId })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Falha ao iniciar social research');
        showNotification('Social research iniciado', 'success');
        acompanharJob('social', data.job_id);
    } catch (e) {
        console.error(e);
        showErrorMessage('Erro ao iniciar social research');
    }
}

function renderizarResultadoPesquisa(prefixo, payload) {
    const container = document.getElementById('research-results');
    if (!container) return;
    const header = `${prefixo === 'deep' ? '🔎 Deep Research' : '#️⃣ Social (Grok4)'} — ${payload.status}`;
    const texto = payload.result_text || '';
    const item = document.createElement('div');
    item.className = 'job-item';
    item.innerHTML = `
        <div class="status">${header}</div>
        ${texto ? `<div class="conteudo">${texto.replace(/\n/g, '<br>')}</div>` : ''}
    `;
    container.prepend(item);
}

async function acompanharJob(prefixo, jobId) {
    const url = prefixo === 'deep' ? `/api/research/deep/${jobId}` : `/api/research/social/${jobId}`;
    // Polling simples até finalizar
    let tentativas = 0;
    const maxTentativas = 120; // ~10 min se 5s
    const intervalo = 5000;
    const timer = setInterval(async () => {
        try {
            const resp = await fetch(url);
            const data = await resp.json();
            if (resp.ok) {
                if (data.status === 'COMPLETED' || data.status === 'FAILED') {
                    clearInterval(timer);
                    renderizarResultadoPesquisa(prefixo, data);
                }
            }
        } catch (e) {}
        tentativas += 1;
        if (tentativas >= maxTentativas) clearInterval(timer);
    }, intervalo);
}

function carregarDadosEdicao(clusterData) {
    // Define prioridade atual
    const selectPrioridade = document.getElementById('edit-prioridade');
    if (selectPrioridade) selectPrioridade.value = clusterData.prioridade;
    
    // Define tags atuais
    currentTags = clusterData.tags || [clusterData.tag];
    renderizarTags();
}

function renderizarTags() {
    const tagsList = document.getElementById('edit-tags-list');
    if (!tagsList) return;
    
    tagsList.innerHTML = '';
    
    currentTags.forEach(tag => {
        const tagSpan = document.createElement('span');
        tagSpan.className = 'tag-item';
        tagSpan.innerHTML = `
            ${tag}
            <button class="remove-tag" onclick="removerTag('${tag}')">&times;</button>
        `;
        tagsList.appendChild(tagSpan);
    });
}

function adicionarTag(tag) {
    if (tag && !currentTags.includes(tag)) {
        currentTags.push(tag);
        renderizarTags();
    }
}

function removerTag(tag) {
    currentTags = currentTags.filter(t => t !== tag);
    renderizarTags();
}

async function carregarAlteracoes(clusterId) {
    try {
        const response = await fetch(`/api/cluster/${clusterId}/alteracoes`);
        if (response.ok) {
            const data = await response.json();
            renderizarAlteracoes(data.alteracoes);
        }
    } catch (error) {
        console.error('Erro ao carregar alterações:', error);
    }
}

function renderizarAlteracoes(alteracoes) {
    const container = document.getElementById('alteracoes-container');
    if (!container) return;
    
    if (alteracoes.length === 0) {
        container.innerHTML = '<p>Nenhuma alteração registrada.</p>';
        return;
    }
    
    container.innerHTML = alteracoes.map(alt => `
        <div class="alteracao-item">
            <div class="alteracao-header">
                <span class="campo">${alt.campo_alterado}</span>
                <span class="timestamp">${new Date(alt.timestamp).toLocaleString('pt-BR')}</span>
            </div>
            <div class="alteracao-content">
                <div class="valor-anterior">De: ${alt.valor_anterior || 'N/A'}</div>
                <div class="valor-novo">Para: ${alt.valor_novo}</div>
                ${alt.motivo ? `<div class="motivo">Motivo: ${alt.motivo}</div>` : ''}
            </div>
        </div>
    `).join('');
}

async function enviarMensagemChat() {
    const input = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');
    
    if (!input || !chatMessages || !currentClusterId) return;
    
    const message = input.value.trim();
    if (!message) return;
    
    // Adiciona mensagem do usuário
    const userMessageDiv = document.createElement('div');
    userMessageDiv.className = 'message user';
    userMessageDiv.textContent = message;
    chatMessages.appendChild(userMessageDiv);
    
    // Limpa input e mostra loading
    input.value = '';
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant loading';
    loadingDiv.textContent = 'Processando...';
    chatMessages.appendChild(loadingDiv);
    
    // Scroll para baixo
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    try {
        const response = await fetch('/api/chat/send', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                cluster_id: currentClusterId,
                message: message
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            
            // Remove loading e adiciona resposta
            loadingDiv.remove();
            const assistantMessageDiv = document.createElement('div');
            assistantMessageDiv.className = 'message assistant';
            assistantMessageDiv.textContent = data.response;
            chatMessages.appendChild(assistantMessageDiv);
            
            // Atualiza sessão
            currentChatSession = data.session_id;
            
        } else {
            throw new Error('Erro na resposta do servidor');
        }
        
    } catch (error) {
        console.error('Erro ao enviar mensagem:', error);
        loadingDiv.remove();
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message assistant error';
        errorDiv.textContent = 'Erro ao processar mensagem. Tente novamente.';
        chatMessages.appendChild(errorDiv);
    }
    
    // Scroll para baixo
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

async function salvarAlteracoes() {
    if (!currentClusterId) return;
    
    const selectPrioridade = document.getElementById('edit-prioridade');
    const inputMotivo = document.getElementById('edit-motivo');
    
    if (!selectPrioridade || !inputMotivo) return;
    
    const prioridade = selectPrioridade.value;
    const motivo = inputMotivo.value.trim();
    
    try {
        const response = await fetch(`/api/cluster/${currentClusterId}/update`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                cluster_id: currentClusterId,
                prioridade: prioridade,
                tags: currentTags,
                motivo: motivo || undefined
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            showNotification(data.message, 'success');
            
            // Recarrega alterações
            await carregarAlteracoes(currentClusterId);
            
            // Limpa motivo
            inputMotivo.value = '';
            
        } else {
            throw new Error('Erro ao salvar alterações');
        }
        
    } catch (error) {
        console.error('Erro ao salvar alterações:', error);
        showErrorMessage('Erro ao salvar alterações');
    }
}

// =======================================
// FUNÇÕES DE FILTRAGEM
// =======================================
function filterAndRender() {
    if (!clustersCarregados || !feedContainer) return;
    
    console.log('filterAndRender chamado');
    console.log('Total de clusters disponíveis:', clustersCarregados.length);
    
    // Limpa o feed
    feedContainer.innerHTML = '';
    
    // Aplica filtros aos dados existentes
    let clustersParaRenderizar = [...clustersCarregados];
    
    // Filtro por prioridade
    if (filtrosPrioridadeContainer) {
        const activePriority = filtrosPrioridadeContainer.querySelector('.filtro-btn.ativo');
        console.log('🔍 DEBUG FILTRO PRIORIDADE:');
        console.log('  - Container encontrado:', !!filtrosPrioridadeContainer);
        console.log('  - Botão ativo encontrado:', !!activePriority);
        
        if (activePriority) {
            const priorityValue = activePriority.dataset.priority;
            console.log('  - Prioridade ativa:', priorityValue);
            console.log('  - Clusters antes do filtro:', clustersParaRenderizar.length);
            
            clustersParaRenderizar = clustersParaRenderizar.filter(item => item.prioridade === priorityValue);
            console.log('  - Clusters após filtro de prioridade:', clustersParaRenderizar.length);
        } else {
            console.log('  - Nenhum filtro de prioridade ativo');
        }
    } else {
        console.log('❌ Container de filtros de prioridade não encontrado');
    }
    
    // Filtro por categorias
    if (filtrosCategoriaContainer) {
        const checkedCategories = Array.from(filtrosCategoriaContainer.querySelectorAll('input:checked')).map(cb => cb.value);
        console.log('🔍 DEBUG FILTRO CATEGORIA:');
        console.log('  - Container encontrado:', !!filtrosCategoriaContainer);
        console.log('  - Categorias marcadas:', checkedCategories);
        console.log('  - Clusters antes do filtro:', clustersParaRenderizar.length);
        
        if (checkedCategories.length > 0) {
            clustersParaRenderizar = clustersParaRenderizar.filter(item => {
                const tags = item.tags || [item.tag];
                return tags.some(tag => checkedCategories.includes(tag));
            });
            console.log('  - Clusters após filtro de categoria:', clustersParaRenderizar.length);
        } else {
            console.log('  - Nenhuma categoria marcada, mostrando todos');
        }
    } else {
        console.log('❌ Container de filtros de categoria não encontrado');
    }
    
    // Renderiza os clusters filtrados
    if (clustersParaRenderizar.length > 0) {
        // Separa clusters P3 dos demais
        const clustersP3 = clustersParaRenderizar.filter(cluster => cluster.prioridade === 'P3_MONITORAMENTO');
        const clustersOutros = clustersParaRenderizar.filter(cluster => cluster.prioridade !== 'P3_MONITORAMENTO');
        
        console.log('🔍 FILTRAGEM P3:');
        console.log('  - Total clusters para renderizar:', clustersParaRenderizar.length);
        console.log('  - Clusters com prioridade P3_MONITORAMENTO:', clustersP3.length);
        console.log('  - Clusters com outras prioridades:', clustersOutros.length);
        
        // Debug: mostra todas as prioridades únicas
        const prioridadesUnicas = [...new Set(clustersParaRenderizar.map(c => c.prioridade))];
        console.log('  - Prioridades únicas encontradas:', prioridadesUnicas);
        
        console.log('🔍 DEBUG RENDERIZAÇÃO:');
        console.log('  - Total clusters para renderizar:', clustersParaRenderizar.length);
        console.log('  - Clusters P3 encontrados:', clustersP3.length);
        console.log('  - Clusters outros (P1/P2):', clustersOutros.length);
        
        // Debug detalhado dos P3
        if (clustersP3.length > 0) {
            console.log('  - Detalhes dos P3:');
            clustersP3.forEach((cluster, index) => {
                console.log(`    P3 ${index + 1}: ID=${cluster.id}, Tag="${cluster.tag}", Título="${cluster.titulo_final}", Prioridade="${cluster.prioridade}"`);
            });
        } else {
            console.log('  - ⚠️ Nenhum cluster P3 encontrado para renderizar');
        }
        
        // Renderiza clusters P1 e P2 normalmente
        clustersOutros.forEach(cluster => {
            const card = criarCardCluster(cluster);
            if (feedContainer) feedContainer.appendChild(card);
        });
        
        // Agrupa e renderiza clusters P3 por tag
        if (clustersP3.length > 0) {
            const gruposP3 = agruparClustersP3PorTag(clustersP3);
            console.log('  - Grupos P3 criados:', gruposP3.length);
            gruposP3.forEach((grupo, index) => {
                console.log(`    Grupo P3 ${index + 1}: Tag="${grupo.tag}", Clusters=${grupo.clusters.length}`);
                const card = criarCardGrupoP3(grupo);
                if (feedContainer) feedContainer.appendChild(card);
            });
        } else {
            console.log('  - ⚠️ Nenhum cluster P3 para agrupar');
        }
    } else {
        console.log('Nenhum cluster para renderizar');
        showEmptyFeedMessage();
    }
}

// =======================================
// FUNÇÕES PARA CONTADORES NOS FILTROS
// =======================================
function calcularContadores() {
    if (!clustersCarregados) return;
    
    const clusters = clustersCarregados;
    console.log('Calculando contadores para', clusters.length, 'clusters');
    
    // Contadores de prioridade
    const contadoresPrioridade = {
        'P1_CRITICO': 0,
        'P2_ESTRATEGICO': 0,
        'P3_MONITORAMENTO': 0
    };
    

    
    // Calcula contadores
    clusters.forEach(cluster => {
        console.log('Cluster ID:', cluster.id, 'Prioridade:', cluster.prioridade, 'Tag:', cluster.tag);
        
        // Contador de prioridade
        if (cluster.prioridade && contadoresPrioridade.hasOwnProperty(cluster.prioridade)) {
            contadoresPrioridade[cluster.prioridade]++;
        }
        
        // Contador de categoria (só se contadoresCategoria já foi inicializado)
        if (Object.keys(contadoresCategoria).length > 0) {
            const tags = cluster.tags || [cluster.tag];
            tags.forEach(tag => {
                if (tag && contadoresCategoria.hasOwnProperty(tag)) {
                    contadoresCategoria[tag]++;
                }
            });
        }
    });
    
    console.log('Contadores finais - Prioridade:', contadoresPrioridade);
    console.log('Contadores finais - Categoria:', contadoresCategoria);
    
    // Atualiza filtros de prioridade
    atualizarContadoresPrioridade(contadoresPrioridade);
    
    // Atualiza filtros de categoria
    atualizarContadoresCategoria(contadoresCategoria);
}

function atualizarContadoresPrioridade(contadores) {
    console.log('🔄 Atualizando contadores de prioridade:', contadores);
    
    if (!filtrosPrioridadeContainer) {
        console.log('❌ Container de filtros de prioridade não encontrado');
        return;
    }
    
    const filtrosPrioridade = filtrosPrioridadeContainer.querySelectorAll('.filtro-btn');
    console.log('🔍 Encontrados', filtrosPrioridade.length, 'botões de prioridade');
    
    filtrosPrioridade.forEach(btn => {
        const priority = btn.dataset.priority;
        const contador = contadores[priority] || 0;
        // Preserva o texto original sem parênteses
        const textoOriginal = btn.textContent.split('(')[0].trim();
        btn.textContent = `${textoOriginal} (${contador})`;
        console.log('✅ Atualizado botão', priority, 'com contador:', contador);
    });
    
    console.log('✅ Contadores de prioridade atualizados com sucesso');
}

function atualizarContadoresCategoria(contadores) {
    if (!filtrosCategoriaContainer) return;
    
    const filtrosCategoria = filtrosCategoriaContainer.querySelectorAll('label');
    
    filtrosCategoria.forEach(label => {
        const checkbox = label.querySelector('input');
        const categoria = checkbox.value;
        const contador = contadores[categoria] || 0;
        const tagColorClass = getTagColorClass(categoria);
        const isChecked = checkbox.checked;
        
        // Preserva o estado do checkbox
        label.innerHTML = `
            <input type="checkbox" value="${categoria}" ${isChecked ? 'checked' : ''}>
            <span class="tag ${tagColorClass}">${categoria} (${contador})</span>
        `;
        
        // Reaplica o event listener com a nova regra de seleção (seleção exclusiva ao clicar, toggle geral ao reclicar)
        const newLabel = label;
        newLabel.addEventListener('click', (e) => {
            e.preventDefault();
            aplicarRegraSelecaoCategorias(categoria);
            filterAndRender();
        });
    });
    
    console.log('Contadores de categoria atualizados:', contadores);
}

// =======================================
// CARREGAMENTO DINÂMICO DE TAGS
// =======================================
let tagsDisponiveis = [];
let contadoresCategoria = {}; // Contadores de categoria (serão preenchidos dinamicamente)
// clustersCarregados já declarado no topo

// Aplica regra de seleção de categorias:
// - Inicial: todas marcadas
// - Clique em uma quando todas estão marcadas: desmarca todas e marca apenas a clicada
// - Clique novamente na mesma quando só ela está marcada: marca todas
// - Se existe um subconjunto marcado e clicar em outra: adiciona a clicada ao conjunto
function aplicarRegraSelecaoCategorias(categoriaAlvo) {
    if (!filtrosCategoriaContainer) return;
    const labels = Array.from(filtrosCategoriaContainer.querySelectorAll('label'));
    const checkboxes = labels.map(l => l.querySelector('input[type="checkbox"]'));

    const todasMarcadas = checkboxes.every(cb => cb.checked);
    const marcadas = checkboxes.filter(cb => cb.checked);
    const alvo = checkboxes.find(cb => cb.value === categoriaAlvo);
    if (!alvo) return;

    if (todasMarcadas) {
        // Exclusiva na clicada
        checkboxes.forEach(cb => { cb.checked = false; cb.closest('label').classList.remove('categoria-ativa'); cb.closest('label').classList.add('desabilitado'); });
        alvo.checked = true;
        const labelAlvo = alvo.closest('label');
        labelAlvo.classList.remove('desabilitado');
        labelAlvo.classList.add('categoria-ativa');
        return;
    }

    // Se apenas uma marcada e é a mesma clicada -> marcar todas
    if (marcadas.length === 1 && marcadas[0].value === categoriaAlvo) {
        checkboxes.forEach(cb => { cb.checked = true; cb.closest('label').classList.remove('desabilitado'); cb.closest('label').classList.add('categoria-ativa'); });
        return;
    }

    // Caso geral: alterna apenas a clicada (aditiva)
    alvo.checked = !alvo.checked;
    const labelAlvo2 = alvo.closest('label');
    if (alvo.checked) {
        labelAlvo2.classList.remove('desabilitado');
        labelAlvo2.classList.add('categoria-ativa');
    } else {
        labelAlvo2.classList.remove('categoria-ativa');
        labelAlvo2.classList.add('desabilitado');
    }
}

async function carregarTagsDisponiveis() {
    try {
        console.log('🔄 Extraindo tags dos clusters armazenados');
        
        // Inicializa contadores se não existir
        if (!contadoresCategoria) {
            contadoresCategoria = {};
        }
        
        // Usa os clusters que foram armazenados
        if (!clustersCarregados || clustersCarregados.length === 0) {
            console.log('❌ Nenhum cluster armazenado encontrado, limpando filtros');
            tagsDisponiveis = [];
            contadoresCategoria = {};
            atualizarFiltrosCategoria();
            return;
        }
        
        console.log('📊 Clusters armazenados encontrados:', clustersCarregados.length);
        
        // Extrai tags únicas dos clusters
        const tagsUnicas = new Set();
        clustersCarregados.forEach(cluster => {
            if (cluster.tag) {
                tagsUnicas.add(cluster.tag);
                console.log('🏷️ Tag encontrada no cluster:', cluster.tag);
            }
        });
        
        tagsDisponiveis = Array.from(tagsUnicas).sort();
        
        // Inicializa contadores de categoria com as tags disponíveis
        tagsDisponiveis.forEach(tag => {
            contadoresCategoria[tag] = 0;
        });
        
        // Calcula os contadores reais dos clusters
        const contadoresPrioridade = {
            'P1_CRITICO': 0,
            'P2_ESTRATEGICO': 0,
            'P3_MONITORAMENTO': 0
        };
        
        console.log('🎯 ABORDAGEM ALTERNATIVA: Tudo que não for P1 ou P2 será considerado P3');
        
        clustersCarregados.forEach(cluster => {
            console.log('🔍 DEBUG CLUSTER:', {
                id: cluster.id,
                titulo: cluster.titulo,
                tag: cluster.tag,
                prioridade: cluster.prioridade,
                temTag: !!cluster.tag,
                temPrioridade: !!cluster.prioridade
            });
            
            // Contador de categoria
            if (cluster.tag && contadoresCategoria.hasOwnProperty(cluster.tag)) {
                contadoresCategoria[cluster.tag]++;
                console.log('📊 Incrementando contador para tag:', cluster.tag);
            }
            
            // Contador de prioridade - ABORDAGEM ALTERNATIVA
            if (cluster.prioridade) {
                if (cluster.prioridade === 'P1_CRITICO') {
                    contadoresPrioridade['P1_CRITICO']++;
                    console.log('📊 P1_CRITICO incrementado');
                } else if (cluster.prioridade === 'P2_ESTRATEGICO') {
                    contadoresPrioridade['P2_ESTRATEGICO']++;
                    console.log('📊 P2_ESTRATEGICO incrementado');
                } else {
                    // Tudo que não for P1 ou P2 é considerado P3
                    contadoresPrioridade['P3_MONITORAMENTO']++;
                    console.log('📊 P3_MONITORAMENTO incrementado (prioridade original:', cluster.prioridade, ')');
                }
            } else {
                console.log('⚠️ Cluster sem prioridade definida');
            }
        });
        
        // Atualiza os filtros de categoria no HTML
        atualizarFiltrosCategoria();
        
        // Atualiza os filtros de prioridade
        atualizarContadoresPrioridade(contadoresPrioridade);
        
        console.log('✅ Tags extraídas dos clusters:', tagsDisponiveis);
        console.log('📈 Contadores de categoria calculados:', contadoresCategoria);
        console.log('📈 Contadores de prioridade calculados:', contadoresPrioridade);
        console.log('🎯 RESUMO FINAL - P1:', contadoresPrioridade['P1_CRITICO'], 'P2:', contadoresPrioridade['P2_ESTRATEGICO'], 'P3:', contadoresPrioridade['P3_MONITORAMENTO']);
    } catch (error) {
        console.error('❌ Erro ao extrair tags dos clusters:', error);
        // Fallback para tags antigas se a API falhar
        tagsDisponiveis = ['Governo e Politica', 'Economia e Tecnologia', 'Judicionario', 'Empresas Privadas'];
        tagsDisponiveis.forEach(tag => {
            contadoresCategoria[tag] = 0;
        });
        console.log('🔄 Usando tags de fallback:', tagsDisponiveis);
    }
}

function atualizarFiltrosCategoria() {
    const filtrosCategoriaContainer = document.getElementById('filtros-categoria');
    if (!filtrosCategoriaContainer) {
        console.log('❌ Container de filtros de categoria não encontrado');
        return;
    }
    
    // Verifica se tagsDisponiveis está definido
    if (!tagsDisponiveis || !Array.isArray(tagsDisponiveis)) {
        console.log('⚠️ Tags não disponíveis, usando fallback');
        tagsDisponiveis = ['Governo e Politica', 'Economia e Tecnologia', 'Judicionario', 'Empresas Privadas'];
    }
    
    console.log('🔄 Atualizando filtros de categoria com tags:', tagsDisponiveis);
    
    // Limpa o container
    filtrosCategoriaContainer.innerHTML = '';
    
    // Adiciona as tags dinâmicas
    tagsDisponiveis.forEach(tag => {
        const label = document.createElement('label');
        label.className = 'categoria-ativa';
        
        // Gera cor da tag baseada no nome
        const tagColorClass = getTagColorClass(tag);
        const contador = contadoresCategoria[tag] || 0;
        
        label.innerHTML = `
            <input type="checkbox" value="${tag}" checked>
            <span class="tag ${tagColorClass}">${tag} (${contador})</span>
        `;
        
        // Adiciona event listener conforme a nova regra de seleção
        label.addEventListener('click', (e) => {
            e.preventDefault();
            const categoria = label.querySelector('input').value;
            aplicarRegraSelecaoCategorias(categoria);
            filterAndRender();
        });
        
        filtrosCategoriaContainer.appendChild(label);
        console.log('✅ Adicionado filtro para tag:', tag, 'com contador:', contador);
    });
    
    console.log('✅ Filtros de categoria atualizados');
}

// =======================================
// FUNÇÕES PARA AGRUPAMENTO P3
// =======================================
function agruparClustersP3PorTag(clustersP3) {
    const grupos = {};
    
    clustersP3.forEach(cluster => {
        const tag = cluster.tag || cluster.tags?.[0] || 'Sem Categoria';
        if (!grupos[tag]) {
            grupos[tag] = {
                tag: tag,
                clusters: []
            };
        }
        grupos[tag].clusters.push(cluster);
    });
    
    return Object.values(grupos);
}

function criarCardGrupoP3(grupo) {
    const card = document.createElement('article');
    card.className = 'card-cluster p3-grupo';
    card.dataset.tag = grupo.tag;
    
    // Calcula total de artigos do grupo
    const totalArtigos = grupo.clusters.reduce((total, cluster) => total + (cluster.total_artigos || 0), 0);
    
    card.innerHTML = `
        <div class="card-header">
            <h3 class="card-titulo">📊 ${grupo.tag}</h3>
            <div class="card-contador-fontes" title="Total de notícias no grupo">
                <span>📰</span>
                <span class="contador">${totalArtigos}</span>
            </div>
        </div>
        <div class="card-content">
            <ul class="lista-noticias-p3">
                ${grupo.clusters.map(cluster => `
                    <li class="item-noticia-p3" data-cluster-id="${cluster.id}">
                        <span class="texto-noticia">
                            <strong>${cluster.titulo_final}</strong>
                            ${cluster.resumo_final ? `: ${cluster.resumo_final}` : ''}
                        </span>
                    </li>
                `).join('')}
            </ul>
        </div>
        <div class="card-footer">
            <span class="card-timestamp">${formatarDataTitulo(currentDate)}</span>
            <div class="card-tags">
                <span class="tag">P3 - Monitoramento</span>
            </div>
        </div>
    `;
    
    // Adiciona event listeners para cada item da lista
    const itemsNoticia = card.querySelectorAll('.item-noticia-p3');
    itemsNoticia.forEach(item => {
        item.addEventListener('click', () => {
            const clusterId = item.dataset.clusterId;
            openModal(clusterId);
        });
    });
    
    return card;
}



// =======================================
// FUNÇÕES AUXILIARES
// =======================================
function getPrioridadeClass(prioridade) {
    switch (prioridade) {
        case 'P1_CRITICO': return 'p1';
        case 'P2_ESTRATEGICO': return 'p2';
        case 'P3_MONITORAMENTO': return 'p3';
        default: return 'p3';
    }
}

function getTagColorClass(tagName) {
    // Mapeamento personalizado para as categorias específicas
    const tagColorMap = {
        'Internacional (Economia e Política)': 'tag-1',      // Azul
        'Jurídico, Falências e Regulatório': 'tag-2',         // Vermelho
        'M&A e Transações Corporativas': 'tag-3',             // Verde
        'Mercado de Capitais e Finanças Corporativas': 'tag-4', // Roxo
        'Política Econômica (Brasil)': 'tag-5',               // Laranja
        'Tecnologia e Setores Estratégicos': 'tag-6',         // Ciano
        'Dívida Ativa e Créditos Públicos': 'tag-7',          // Rosa
        'Distressed Assets e NPLs': 'tag-8',                  // Marrom
        'IRRELEVANTE': 'tag-9',                               // Cinza
        'PENDING': 'tag-10'                                   // Cinza Escuro
    };
    
    // Retorna o mapeamento específico ou usa hash como fallback
    if (tagColorMap[tagName]) {
        return tagColorMap[tagName];
    }
    
    // Fallback para tags não mapeadas (hash simples)
    let hash = 0;
    for (let i = 0; i < tagName.length; i++) {
        hash = tagName.charCodeAt(i) + ((hash << 5) - hash);
    }
    const colorIndex = Math.abs(hash) % 10 + 1;
    return `tag-${colorIndex}`;
}

function formatarPrioridade(prioridade) {
    switch (prioridade) {
        case 'P1_CRITICO': return 'P1 - Crítico';
        case 'P2_ESTRATEGICO': return 'P2 - Estratégico';
        case 'P3_MONITORAMENTO': return 'P3 - Monitoramento';
        default: return prioridade;
    }
}

function formatarDataTitulo(data) {
    const dataSelecionada = parseLocalDate(data);
    return dataSelecionada.toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

function mostrarLoading() {
    if (!feedContainer) return;
    
    const loading = document.createElement('div');
    loading.className = 'loading';
    loading.innerHTML = '<div class="spinner"></div><p>Carregando notícias...</p>';
    feedContainer.appendChild(loading);
}

function ocultarLoading() {
    const loading = document.querySelector('.loading');
    if (loading) {
        loading.remove();
    }
}

function mostrarErro(mensagem) {
    if (!feedContainer) return;
    
    const erro = document.createElement('div');
    erro.className = 'erro';
    erro.innerHTML = `<p>❌ ${mensagem}</p>`;
    feedContainer.appendChild(erro);
    
    // Remove o erro após 5 segundos
    setTimeout(() => {
        if (erro.parentNode) {
            erro.remove();
        }
    }, 5000);
}

function showEmptyFeedMessage() {
    if (!feedContainer) return;
    
    const emptyMessage = document.createElement('div');
    emptyMessage.className = 'empty-feed-message';
    emptyMessage.innerHTML = `
        <p>📰 Nenhum evento encontrado para exibir.</p>
        <p>Os novos eventos aparecerão aqui conforme forem processados.</p>
    `;
    emptyMessage.style.cssText = `
        text-align: center;
        padding: 3rem 2rem;
        color: var(--cor-texto-secundario);
        background-color: var(--cor-fundo);
        border-radius: 8px;
        margin: 2rem 0;
    `;
    feedContainer.appendChild(emptyMessage);
}

function showNotification(message, type = 'info') {
    // Remove notificações existentes
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(n => n.remove());
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        border-radius: 6px;
        z-index: 10000;
        font-weight: 500;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        ${type === 'success' ? 'background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;' : ''}
        ${type === 'error' ? 'background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;' : ''}
        ${type === 'info' ? 'background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb;' : ''}
    `;
    
    document.body.appendChild(notification);
    
    // Remove após 3 segundos
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 3000);
}

function showErrorMessage(message) {
    showNotification(message, 'error');
}

// =======================================
// ATUALIZAÇÃO AUTOMÁTICA
// =======================================
function startAutoRefresh() {
    // Atualiza a cada 2 minutos
    if (typeof carregarFeed === 'function') {
        refreshInterval = setInterval(carregarFeed, 2 * 60 * 1000);
    }
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
}

// ==============================================================================
// FUNÇÕES DO MODAL DE CONFIGURAÇÃO DE PROMPTS
// ==============================================================================

let promptsConfigData = null;

async function openPromptsModal() {
    try {
        const modal = document.getElementById('modal-prompts-config');
        if (!modal) return;

        // Mostra loading
        showNotification('Carregando configurações...', 'info');
        
        // Carrega as configurações atuais
        await carregarConfiguracoesPrompts();
        
        // Renderiza os editores
        renderizarEditorTags();
        renderizarEditorPrioridades();
        renderizarEditorPrompt();
        
        // Mostra o modal
        modal.classList.remove('oculto');
        
        showNotification('Configurações carregadas', 'success');
    } catch (error) {
        console.error('❌ Erro ao abrir modal de prompts:', error);
        showErrorMessage('Erro ao carregar configurações');
    }
}

function closePromptsModal() {
    const modal = document.getElementById('modal-prompts-config');
    if (modal) {
        modal.classList.add('oculto');
    }
}

async function carregarConfiguracoesPrompts() {
    try {
        const response = await fetch(`${API_BASE}/api/settings/prompts`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const result = await response.json();
        if (result.success) {
            promptsConfigData = result.data;
        } else {
            throw new Error('Falha ao carregar configurações');
        }
    } catch (error) {
        console.error('❌ Erro ao carregar configurações de prompts:', error);
        throw error;
    }
}

function renderizarEditorTags() {
    const container = document.getElementById('tags-config-container');
    if (!container || !promptsConfigData) return;

    const tags = promptsConfigData.TAGS_SPECIAL_SITUATIONS;
    let html = '<div class="accordion">';

    Object.entries(tags).forEach(([tagName, tagData], index) => {
        html += `
            <div class="tag-config-item" data-tag="${tagName}">
                <div class="tag-config-header">
                    <button class="accordion-toggle" onclick="toggleAccordion(this)" aria-expanded="false" title="Abrir/fechar">${tagName}</button>
                    <button class="chip-close" onclick="removerTagConfig('${tagName}')" title="Remover">×</button>
                </div>
                <div class="tag-config-content oculto">
                    <div class="tag-config-field">
                        <label>Descrição:</label>
                        <textarea class="tag-descricao" data-tag="${tagName}">${tagData.descricao}</textarea>
                    </div>
                    <div class="tag-config-field">
                        <label>Exemplos:</label>
                        <div class="exemplos-list">
                            ${tagData.exemplos.map((exemplo, i) => `
                                <div class="exemplo-item">
                                    <input type="text" value="${exemplo}" data-tag="${tagName}" data-index="${i}">
                                    <button class="chip-close" onclick="removerExemplo('${tagName}', ${i})" title="Excluir">×</button>
                                </div>
                            `).join('')}
                            <input type="text" class="exemplo-inline" placeholder="Escreva um novo exemplo e pressione Enter" onkeypress="if(event.key==='Enter'){adicionarExemploInline('${tagName}', this)}">
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    // Adiciona botão para nova tag
    html += `
        <div style="display:flex;gap:.5rem;align-items:center;margin-top: .5rem;">
            <input id="nova-tag-input" type="text" placeholder="Nova tag..." style="flex:1;">
            <button class="add-exemplo-btn" onclick="adicionarNovaTagInline()">+ Adicionar Tag</button>
        </div>
    `;

    container.innerHTML = html + '</div>';
}

function renderizarEditorPrioridades() {
    const container = document.getElementById('prioridades-config-container');
    if (!container || !promptsConfigData) return;

    // Nova UI: edita apenas listas P1, P2, P3 do Gatekeeper
    const listas = [
        { key: 'P1_ITENS', titulo: 'P1_CRITICO — Itens (Gatekeeper)' },
        { key: 'P2_ITENS', titulo: 'P2_ESTRATEGICO — Itens (Gatekeeper)' },
        { key: 'P3_ITENS', titulo: 'P3_MONITORAMENTO — Itens (Gatekeeper)' }
    ];

    let html = '<div class="accordion">';
    listas.forEach(({ key, titulo }) => {
        const itens = Array.isArray(promptsConfigData[key]) ? promptsConfigData[key] : [];
        html += `
            <div class="prioridade-config-item" data-lista="${key}">
                <div class="prioridade-config-header">
                    <button class="accordion-toggle" onclick="toggleAccordion(this)" aria-expanded="false">${titulo}</button>
                </div>
                <div class="prioridade-config-content oculto">
                    <div class="tag-config-field">
                        <label>Itens:</label>
                        <div class="assuntos-list">
                            ${itens.map((assunto, i) => `
                                <div class="assunto-item">
                                    <input type="text" value="${assunto}" data-lista="${key}" data-index="${i}">
                                    <button class="chip-close" onclick="removerAssuntoLista('${key}', ${i})">×</button>
                                </div>
                            `).join('')}
                            <input type="text" class="assunto-inline" placeholder="Escreva um novo item e pressione Enter" onkeypress="if(event.key==='Enter'){adicionarAssuntoListaInline('${key}', this)}">
                        </div>
                    </div>
                </div>
            </div>
        `;
    });
    container.innerHTML = html + '</div>';
}

function renderizarEditorPrompt() {
    const textarea = document.getElementById('prompt-principal-textarea');
    if (!promptsConfigData) return;
    if (textarea) {
        // Agora este editor usa PROMPT_AGRUPAMENTO_V1
        textarea.value = promptsConfigData.PROMPT_AGRUPAMENTO_V1 || '';
    }

    // Carrega outros prompts na aba correspondente
    const resumoFinal = document.getElementById('prompt-resumo-final');
    if (resumoFinal) resumoFinal.value = promptsConfigData.PROMPT_RESUMO_FINAL_V3 || '';
    const decisaoDetalhado = document.getElementById('prompt-decisao-detalhado');
    if (decisaoDetalhado) decisaoDetalhado.value = promptsConfigData.PROMPT_DECISAO_CLUSTER_DETALHADO_V1 || '';
    const chatCluster = document.getElementById('prompt-chat-cluster');
    if (chatCluster) chatCluster.value = promptsConfigData.PROMPT_CHAT_CLUSTER_V1 || '';
}

// Funções auxiliares para edição de tags
function adicionarNovaTag() {
    const container = document.getElementById('tags-config-container');
    const tagName = prompt('Digite o nome da nova tag:');
    if (!tagName) return;

    const newTagHtml = `
        <div class="tag-config-item" data-tag="${tagName}">
            <div class="tag-config-header">
                <span class="tag-config-title">${tagName}</span>
                <div class="tag-config-actions">
                    <button class="btn btn-secondary" onclick="removerTagConfig('${tagName}')">Remover</button>
                </div>
            </div>
            <div class="tag-config-content">
                <div class="tag-config-field">
                    <label>Descrição:</label>
                    <textarea class="tag-descricao" data-tag="${tagName}">Nova descrição</textarea>
                </div>
                <div class="tag-config-field">
                    <label>Exemplos:</label>
                    <div class="exemplos-list">
                        <div class="exemplo-item">
                            <input type="text" value="Novo exemplo" data-tag="${tagName}" data-index="0">
                            <button onclick="removerExemplo('${tagName}', 0)">&times;</button>
                        </div>
                        <button class="add-exemplo-btn" onclick="adicionarExemplo('${tagName}')">+ Adicionar Exemplo</button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Insere antes do botão "Adicionar Nova Tag"
    const addButton = container.querySelector('.add-exemplo-btn[onclick*="adicionarNovaTag"]');
    if (addButton) {
        addButton.insertAdjacentHTML('beforebegin', newTagHtml);
    }
}

function removerTagConfig(tagName) {
    if (confirm(`Tem certeza que deseja remover a tag "${tagName}"?`)) {
        const tagElement = document.querySelector(`[data-tag="${tagName}"]`);
        if (tagElement) {
            tagElement.remove();
        }
    }
}

function adicionarExemplo(tagName) {
    const exemplosList = document.querySelector(`[data-tag="${tagName}"] .exemplos-list`);
    const addButton = exemplosList.querySelector('.add-exemplo-btn');
    const newIndex = exemplosList.querySelectorAll('.exemplo-item').length;

    const newExemploHtml = `
        <div class="exemplo-item">
            <input type="text" value="Novo exemplo" data-tag="${tagName}" data-index="${newIndex}">
            <button onclick="removerExemplo('${tagName}', ${newIndex})">&times;</button>
        </div>
    `;

    addButton.insertAdjacentHTML('beforebegin', newExemploHtml);
}

function removerExemplo(tagName, index) {
    const exemploItem = document.querySelector(`[data-tag="${tagName}"] .exemplo-item:nth-child(${index + 1})`);
    if (exemploItem) {
        exemploItem.remove();
        // Reindexar os exemplos restantes
        const exemplos = document.querySelectorAll(`[data-tag="${tagName}"] .exemplo-item`);
        exemplos.forEach((item, i) => {
            item.querySelector('input').setAttribute('data-index', i);
            item.querySelector('button').setAttribute('onclick', `removerExemplo('${tagName}', ${i})`);
        });
    }
}

// Funções auxiliares para edição de prioridades
function adicionarAssunto(prioridade) {
    const assuntosList = document.querySelector(`[data-prioridade="${prioridade}"] .assuntos-list`);
    const addButton = assuntosList.querySelector('.add-assunto-btn');
    const newIndex = assuntosList.querySelectorAll('.assunto-item').length;

    const newAssuntoHtml = `
        <div class="assunto-item">
            <input type="text" value="Novo assunto" data-prioridade="${prioridade}" data-index="${newIndex}">
            <button onclick="removerAssunto('${prioridade}', ${newIndex})">&times;</button>
        </div>
    `;

    addButton.insertAdjacentHTML('beforebegin', newAssuntoHtml);
}

function removerAssunto(prioridade, index) {
    const assuntoItem = document.querySelector(`[data-prioridade="${prioridade}"] .assunto-item:nth-child(${index + 1})`);
    if (assuntoItem) {
        assuntoItem.remove();
        // Reindexar os assuntos restantes
        const assuntos = document.querySelectorAll(`[data-prioridade="${prioridade}"] .assunto-item`);
        assuntos.forEach((item, i) => {
            item.querySelector('input').setAttribute('data-index', i);
            item.querySelector('button').setAttribute('onclick', `removerAssunto('${prioridade}', ${i})`);
        });
    }
}

async function salvarConfiguracoesPrompts() {
    try {
        showNotification('Salvando configurações...', 'info');

        // Coleta os dados dos editores
        const dadosAtualizados = coletarDadosEditores();
        
        // Envia para o backend
        const response = await fetch(`${API_BASE}/api/settings/prompts`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(dadosAtualizados)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        if (result.success) {
            showNotification('Configurações salvas com sucesso!', 'success');
            closePromptsModal();
        } else {
            throw new Error(result.message || 'Falha ao salvar configurações');
        }
    } catch (error) {
        console.error('❌ Erro ao salvar configurações:', error);
        showErrorMessage('Erro ao salvar configurações: ' + error.message);
    }
}

function coletarDadosEditores() {
    const dados = {};

    // Coleta dados das tags
    const tagsConfig = {};
    document.querySelectorAll('.tag-config-item').forEach(tagItem => {
        const tagName = tagItem.getAttribute('data-tag');
        const descricao = tagItem.querySelector('.tag-descricao').value;
        const exemplos = Array.from(tagItem.querySelectorAll('.exemplo-item input')).map(input => input.value);

        tagsConfig[tagName] = {
            descricao: descricao,
            exemplos: exemplos
        };
    });
    dados.TAGS_SPECIAL_SITUATIONS = tagsConfig;

    // Coleta apenas listas Gatekeeper P1/P2/P3
    const listas = ['P1_ITENS','P2_ITENS','P3_ITENS'];
    listas.forEach(key => {
        const inputs = Array.from(document.querySelectorAll(`.prioridade-config-item[data-lista="${key}"] .assunto-item input`));
        dados[key] = inputs.map(i => i.value).filter(v => v && v.trim().length);
    });

    // Coleta dados do prompt principal (agora agrupamento)
    const promptTextarea = document.getElementById('prompt-principal-textarea');
    if (promptTextarea) {
        dados.PROMPT_AGRUPAMENTO_V1 = promptTextarea.value;
    }

    // Outros prompts (se presentes)
    const resumoFinal = document.getElementById('prompt-resumo-final');
    if (resumoFinal) {
        dados.PROMPT_RESUMO_FINAL_V3 = resumoFinal.value;
    }
    const decisaoDetalhado = document.getElementById('prompt-decisao-detalhado');
    if (decisaoDetalhado) {
        dados.PROMPT_DECISAO_CLUSTER_DETALHADO_V1 = decisaoDetalhado.value;
    }
    const chatCluster = document.getElementById('prompt-chat-cluster');
    if (chatCluster) {
        dados.PROMPT_CHAT_CLUSTER_V1 = chatCluster.value;
    }

    return dados;
}

// Helpers para editar listas P1/P2/P3
function adicionarAssuntoListaInline(listaKey, inputEl) {
    const value = (inputEl.value || '').trim();
    if (!value) return;
    const list = inputEl.closest('.assuntos-list');
    const index = list.querySelectorAll('.assunto-item').length;
    const html = `
        <div class="assunto-item">
            <input type="text" value="${value}" data-lista="${listaKey}" data-index="${index}">
            <button class="chip-close" onclick="removerAssuntoLista('${listaKey}', ${index})">×</button>
        </div>
    `;
    inputEl.insertAdjacentHTML('beforebegin', html);
    inputEl.value = '';
}

function removerAssuntoLista(listaKey, index) {
    const itens = document.querySelectorAll(`.prioridade-config-item[data-lista="${listaKey}"] .assunto-item`);
    const alvo = Array.from(itens).find(el => {
        const inp = el.querySelector('input');
        return inp && parseInt(inp.getAttribute('data-index')) === index;
    });
    if (alvo) {
        alvo.remove();
        const restantes = document.querySelectorAll(`.prioridade-config-item[data-lista="${listaKey}"] .assunto-item`);
        restantes.forEach((el, i) => {
            const inp = el.querySelector('input');
            const btn = el.querySelector('button');
            if (inp) inp.setAttribute('data-index', i);
            if (btn) btn.setAttribute('onclick', `removerAssuntoLista('${listaKey}', ${i})`);
        });
    }
}

// =============================
// UX Helpers para Accordion e Inline
// =============================
function toggleAccordion(btn) {
    const item = btn.closest('.tag-config-item, .prioridade-config-item');
    const content = item.querySelector('.tag-config-content, .prioridade-config-content');
    const expanded = btn.getAttribute('aria-expanded') === 'true';
    btn.setAttribute('aria-expanded', (!expanded).toString());
    content.classList.toggle('oculto');
}

function adicionarExemploInline(tagName, inputEl) {
    const exemplosList = document.querySelector(`[data-tag="${tagName}"] .exemplos-list`);
    const value = (inputEl.value || '').trim();
    if (!value) return;
    const index = exemplosList.querySelectorAll('.exemplo-item').length;
    const html = `
        <div class="exemplo-item">
            <input type="text" value="${value}" data-tag="${tagName}" data-index="${index}">
            <button class="chip-close" onclick="removerExemplo('${tagName}', ${index})">×</button>
        </div>
    `;
    inputEl.insertAdjacentHTML('beforebegin', html);
    inputEl.value = '';
}

function adicionarAssuntoInline(prioridade, inputEl) {
    const list = document.querySelector(`[data-prioridade="${prioridade}"] .assuntos-list`);
    const value = (inputEl.value || '').trim();
    if (!value) return;
    const index = list.querySelectorAll('.assunto-item').length;
    const html = `
        <div class="assunto-item">
            <input type="text" value="${value}" data-prioridade="${prioridade}" data-index="${index}">
            <button class="chip-close" onclick="removerAssunto('${prioridade}', ${index})">×</button>
        </div>
    `;
    inputEl.insertAdjacentHTML('beforebegin', html);
    inputEl.value = '';
}

function adicionarNovaTagInline() {
    const input = document.getElementById('nova-tag-input');
    if (!input) return;
    const tagName = (input.value || '').trim();
    if (!tagName) return;
    const container = document.getElementById('tags-config-container');
    const html = `
        <div class="tag-config-item" data-tag="${tagName}">
            <div class="tag-config-header">
                <button class="accordion-toggle" onclick="toggleAccordion(this)" aria-expanded="true">${tagName}</button>
                <button class="chip-close" onclick="removerTagConfig('${tagName}')">×</button>
            </div>
            <div class="tag-config-content">
                <div class="tag-config-field">
                    <label>Descrição:</label>
                    <textarea class="tag-descricao" data-tag="${tagName}">Nova descrição</textarea>
                </div>
                <div class="tag-config-field">
                    <label>Exemplos:</label>
                    <div class="exemplos-list">
                        <input type="text" class="exemplo-inline" placeholder="Escreva um novo exemplo e pressione Enter" onkeypress="if(event.key==='Enter'){adicionarExemploInline('${tagName}', this)}">
                    </div>
                </div>
            </div>
        </div>
    `;
    // Insere antes do bloco do input de nova tag
    const marker = container.querySelector('#nova-tag-input').closest('div');
    marker.insertAdjacentHTML('beforebegin', html);
    input.value = '';
}

// Corrige remoções para não depender de nth-child
function removerExemplo(tagName, index) {
    const exemplos = document.querySelectorAll(`[data-tag="${tagName}"] .exemplo-item`);
    const alvo = Array.from(exemplos).find(item => {
        const input = item.querySelector('input');
        return input && parseInt(input.getAttribute('data-index')) === index;
    });
    if (alvo) {
        alvo.remove();
        // Reindexa
        const restantes = document.querySelectorAll(`[data-tag="${tagName}"] .exemplo-item`);
        restantes.forEach((item, i) => {
            const input = item.querySelector('input');
            const btn = item.querySelector('button');
            if (input) input.setAttribute('data-index', i);
            if (btn) btn.setAttribute('onclick', `removerExemplo('${tagName}', ${i})`);
        });
    }
}

function removerAssunto(prioridade, index) {
    const assuntos = document.querySelectorAll(`[data-prioridade="${prioridade}"] .assunto-item`);
    const alvo = Array.from(assuntos).find(item => {
        const input = item.querySelector('input');
        return input && parseInt(input.getAttribute('data-index')) === index;
    });
    if (alvo) {
        alvo.remove();
        const restantes = document.querySelectorAll(`[data-prioridade="${prioridade}"] .assunto-item`);
        restantes.forEach((item, i) => {
            const input = item.querySelector('input');
            const btn = item.querySelector('button');
            if (input) input.setAttribute('data-index', i);
            if (btn) btn.setAttribute('onclick', `removerAssunto('${prioridade}', ${i})`);
        });
    }
}

async function restaurarConfiguracoesPadrao() {
    if (confirm('Tem certeza que deseja restaurar as configurações padrão? Isso irá sobrescrever todas as alterações.')) {
        try {
            showNotification('Restaurando configurações padrão...', 'info');
            
            // Recarrega as configurações originais
            await carregarConfiguracoesPrompts();
            
            // Re-renderiza os editores
            renderizarEditorTags();
            renderizarEditorPrioridades();
            renderizarEditorPrompt();
            
            showNotification('Configurações restauradas', 'success');
        } catch (error) {
            console.error('❌ Erro ao restaurar configurações:', error);
            showErrorMessage('Erro ao restaurar configurações');
        }
    }
}

// Para quando a aba perde o foco, retoma quando ganha foco
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
        // Atualiza imediatamente quando a aba volta ao foco
        if (typeof carregarFeed === 'function') {
            carregarFeed();
        }
    }
});

// =======================================
// ATALHOS DE TECLADO
// =======================================
document.addEventListener('keydown', (e) => {
    // F5 ou Ctrl+R: Atualizar dados
    if (e.key === 'F5' || (e.ctrlKey && e.key === 'r')) {
        e.preventDefault();
        if (typeof carregarFeed === 'function') {
            carregarFeed();
        }
    }
    
    // ESC: Fechar modal
    if (e.key === 'Escape' && modal && !modal.classList.contains('oculto')) {
        closeModal();
    }
});

// =======================================
// INICIALIZAÇÃO FINAL
// =======================================
console.log('🚀 SILVA NEWS AlphaFeed Frontend inicializado');
console.log(`📡 API Base: ${API_BASE}`);

// Inicia atualização automática
setTimeout(() => {
    if (typeof startAutoRefresh === 'function') {
        startAutoRefresh();
    }
}, 1000);

// Adiciona CSS adicional para loading state
const loadingStyle = document.createElement('style');
loadingStyle.textContent = `
    .loading * {
        cursor: wait !important;
    }
    
    .notification {
        animation: slideInRight 0.3s ease-out;
    }
    
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    .empty-feed-message {
        animation: fadeIn 0.5s ease-out;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
`;
document.head.appendChild(loadingStyle);

function inserirCardEstagiario() {
    if (!feedContainer) return;
    const card = document.createElement('article');
    card.className = 'card-cluster estagiario-card';
    card.innerHTML = `
        <div class="card-header">
            <div class="card-title-area">
                <h3 class="card-titulo">🤖 Estagiário — Em construção 🚧</h3>
            </div>
            <div class="card-contador-fontes" title="Agente de apoio">
                <span>🗨️</span>
                <span class="contador">chat</span>
            </div>
        </div>
        <p class="card-resumo">Faça uma pergunta sobre as notícias do dia. O Estagiário consultará as prioridades/tags e responderá com base nos dados.</p>
        <div class="estagiario-chat">
            <div class="estagiario-chat-thread" id="estagiario-thread"></div>
            <div class="estagiario-chat-input">
                <input type="text" id="estagiario-input" placeholder="Pergunte algo..." />
                <button class="btn" id="estagiario-send">Enviar</button>
            </div>
        </div>
    `;
    feedContainer.prepend(card);

    // sessão por dia
    let estagiarioSessionId = null;
    async function ensureSession() {
        if (estagiarioSessionId) return estagiarioSessionId;
        const resp = await fetch('/api/estagiario/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ data: currentDate }) });
        const data = await resp.json();
        estagiarioSessionId = data.session_id;
        return estagiarioSessionId;
    }
    // Renderização simples de Markdown (títulos, negrito, itálico, listas, links)
    function renderMarkdown(mdRaw) {
        let html = (mdRaw || '').toString();
        // Escapes básicos não implementados (texto vem do nosso backend)
        // Títulos
        html = html
            .replace(/^###\s+(.*)$/gim, '<h3>$1</h3>')
            .replace(/^##\s+(.*)$/gim, '<h2>$1</h2>')
            .replace(/^#\s+(.*)$/gim, '<h1>$1</h1>');
        // Negrito e itálico
        html = html
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>');
        // Links [texto](url)
        html = html.replace(/\[(.*?)\]\((https?:\/\/[^\s)]+)\)/gim, '<a href="$2" target="_blank" rel="noopener noreferrer">$1<\/a>');
        // Listas com "- "
        html = html.replace(/^(\-\s+.*(?:\n\-\s+.*)*)/gim, (m) => {
            const items = m.split(/\n/g).map(l => l.replace(/^\-\s+/, '')).map(t => `<li>${t}<\/li>`).join('');
            return `<ul>${items}<\/ul>`;
        });
        // Listas numeradas 1. 2. 3.
        html = html.replace(/^(\d+\.\s+.*(?:\n\d+\.\s+.*)*)/gim, (m) => {
            const items = m.split(/\n/g).map(l => l.replace(/^\d+\.\s+/, '')).map(t => `<li>${t}<\/li>`).join('');
            return `<ol>${items}<\/ol>`;
        });
        // Quebras de parágrafo
        html = html.replace(/\n\n/g, '<br/>' );
        return html;
    }

    async function sendMessage(msg, fromModal=false) {
        const sid = await ensureSession();
        const thread = fromModal ? document.getElementById('estagiario-thread-modal') : document.getElementById('estagiario-thread');
        const userDiv = document.createElement('div');
        userDiv.className = 'estagiario-msg user';
        userDiv.textContent = msg;
        thread.appendChild(userDiv);
        // abre modal de status
        const modal = document.getElementById('modal-estagiario');
        const statusText = document.getElementById('estagiario-status-text');
        const steps = document.getElementById('estagiario-steps');
        if (modal && statusText && steps) {
            modal.classList.remove('oculto');
            statusText.textContent = 'Entendendo pergunta...';
            steps.innerHTML = '';
        }
        try {
            // Etapa 1: Entendendo
            if (steps) steps.innerHTML = '<div>✓ Entendendo</div>';
            await new Promise(r => setTimeout(r, 200));
            // Etapa 2: Planejamento
            if (statusText) statusText.textContent = 'Planejando passos...';
            if (steps) steps.innerHTML += '<div>✓ Planejamento</div>';
            await new Promise(r => setTimeout(r, 200));
            // Etapa 3: Consulta ao DB (antes do await para mostrar progresso)
            if (statusText) statusText.textContent = 'Consultando banco de dados...';
            const resp = await fetch('/api/estagiario/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sid, message: msg }) });
            if (steps) steps.innerHTML += '<div>✓ Consulta ao DB</div>';
            await new Promise(r => setTimeout(r, 150));
            // Etapa 4: Síntese
            if (statusText) statusText.textContent = 'Sintetizando resposta...';
            const data = await resp.json();
            const asDiv = document.createElement('div');
            asDiv.className = 'estagiario-msg assistant';
            asDiv.innerHTML = renderMarkdown(data.response || '');
            thread.appendChild(asDiv);
            thread.scrollTop = thread.scrollHeight;
            // Atualiza select de histórico com a pergunta enviada
            const hist = document.getElementById('estagiario-history-select');
            if (hist) {
                const opt = document.createElement('option');
                opt.value = Date.now().toString();
                opt.textContent = msg.slice(0, 120);
                hist.appendChild(opt);
                hist.value = opt.value;
            }
        } catch (e) {
            const errDiv = document.createElement('div');
            errDiv.className = 'estagiario-msg assistant';
            errDiv.textContent = 'Erro ao processar';
            thread.appendChild(errDiv);
        } finally {
            if (modal) modal.classList.add('oculto');
            const modalChat = document.getElementById('modal-estagiario-chat');
            if (modalChat) {
                modalChat.classList.remove('oculto');
                if (!fromModal) {
                    const modalThread = document.getElementById('estagiario-thread-modal');
                    const cardThread = document.getElementById('estagiario-thread');
                    if (modalThread && cardThread) modalThread.innerHTML = cardThread.innerHTML;
                }
                // bind copiar resposta
                const copyBtn = document.getElementById('btn-estagiario-copiar');
                if (copyBtn && !copyBtn.dataset.bound) {
                    copyBtn.dataset.bound = '1';
                    copyBtn.addEventListener('click', async () => {
                        const al = document.getElementById('estagiario-answer-latest');
                        if (!al) return;
                        const tmp = document.createElement('textarea');
                        tmp.value = al.textContent || '';
                        document.body.appendChild(tmp);
                        tmp.select();
                        document.execCommand('copy');
                        document.body.removeChild(tmp);
                        copyBtn.textContent = '✅ Copiado';
                        setTimeout(() => copyBtn.textContent = '📋 Copiar', 1200);
                    });
                }
                // bind histórico (placeholder)
                const histBtn = document.getElementById('btn-estagiario-historico');
                if (histBtn && !histBtn.dataset.bound) {
                    histBtn.dataset.bound = '1';
                    histBtn.addEventListener('click', async () => {
                        alert('Histórico de conversas do dia — em construção');
                    });
                }
            }
        }
    }
    const input = card.querySelector('#estagiario-input');
    const btn = card.querySelector('#estagiario-send');
    btn.addEventListener('click', async () => {
        const v = (input.value || '').trim();
        if (!v) return;
        input.value = '';
        await sendMessage(v);
    });
    input.addEventListener('keypress', async (e) => {
        if (e.key === 'Enter') {
            const v = (input.value || '').trim();
            if (!v) return;
            input.value = '';
            await sendMessage(v);
        }
    });

    // clique no card: abre modal de chat ampliado (70%)
    card.addEventListener('click', (e) => {
        // evita propagar clique do botão enviar
        if (e.target && (e.target.id === 'estagiario-send' || e.target.id === 'estagiario-input')) return;
        const modalChat = document.getElementById('modal-estagiario-chat');
        if (modalChat) {
            modalChat.classList.remove('oculto');
            const modalThread = document.getElementById('estagiario-thread-modal');
            const cardThread = document.getElementById('estagiario-thread');
            if (modalThread && cardThread) modalThread.innerHTML = cardThread.innerHTML;
            const inputModal = document.getElementById('estagiario-input-modal');
            const sendModal = document.getElementById('estagiario-send-modal');
            if (sendModal && inputModal && !sendModal.dataset.bound) {
                sendModal.dataset.bound = '1';
                sendModal.addEventListener('click', async () => {
                    const v = (inputModal.value || '').trim();
                    if (!v) return;
                    inputModal.value = '';
                    await sendMessage(v, true);
                });
                inputModal.addEventListener('keypress', async (ev) => {
                    if (ev.key === 'Enter') {
                        const v = (inputModal.value || '').trim();
                        if (!v) return;
                        inputModal.value = '';
                        await sendMessage(v, true);
                    }
                });
            }
            // Bind histórico change: apenas rola o thread por enquanto
            const hist = document.getElementById('estagiario-history-select');
            if (hist && !hist.dataset.bound) {
                hist.dataset.bound = '1';
                hist.addEventListener('change', () => {
                    const t = document.getElementById('estagiario-thread-modal');
                    if (t) t.scrollTop = t.scrollHeight;
                });
            }
        }
    });
}

// Hook no fluxo de renderização
const _origRenderizarClusters = renderizarClusters;
renderizarClusters = function() {
    _origRenderizarClusters();
    inserirCardEstagiario();
};