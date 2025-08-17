// Configurações globais
const API_BASE = (typeof window !== 'undefined' ? window.location.origin : '') + '/api';
let currentTab = 'artigos';
let currentPage = 1;
let currentItem = null;

// Inicialização
document.addEventListener('DOMContentLoaded', function() {
    loadArtigos();
    carregarTagsDisponiveis(); // Carrega tags disponíveis ao carregar a página
    setupSortingAndFilters();
});

// Navegação entre tabs
function showTab(tabName) {
    // Atualiza tabs
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    document.querySelector(`[onclick="showTab('${tabName}')"]`).classList.add('active');
    document.getElementById(tabName).classList.add('active');
    
    currentTab = tabName;
    currentPage = 1;
    
    // Carrega dados da tab
    switch(tabName) {
        case 'artigos':
            loadArtigos();
            break;
        case 'clusters':
            loadClusters();
            break;
        case 'prompts':
            loadPrompts();
            break;
        case 'bi':
            carregarBI();
            break;
        case 'feedback':
            carregarFeedback();
            break;
    }
}

// =======================================
// PROMPTS TAB FUNCTIONALITY
// =======================================

// Navegação entre sub-tabs de prompts
document.addEventListener('DOMContentLoaded', function() {
    // Setup dos botões de sub-tab de prompts
    document.querySelectorAll('.prompt-tab-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const tabName = this.dataset.tab;
            showPromptSubTab(tabName);
        });
    });
});

function showPromptSubTab(tabName) {
    // Remove classe ativo de todos os botões e conteúdos
    document.querySelectorAll('.prompt-tab-btn').forEach(btn => btn.classList.remove('ativo'));
    document.querySelectorAll('.prompt-tab-content').forEach(content => content.classList.remove('ativo'));
    
    // Adiciona classe ativo ao botão e conteúdo selecionados
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('ativo');
    document.getElementById(tabName).classList.add('ativo');
    
    // Carrega dados específicos da sub-tab
    switch(tabName) {
        case 'tab-tags':
            loadPromptTags();
            break;
        case 'tab-prioridades':
            loadPromptPrioridades();
            break;
        case 'tab-prompt':
            loadPromptResumo();
            break;
        case 'tab-outros':
            loadOutrosPrompts();
            break;
    }
}

function loadPrompts() {
    // Carrega a primeira sub-tab por padrão
    showPromptSubTab('tab-tags');
}

// Carregamento de Tags
async function loadPromptTags() {
    const loadingEl = document.getElementById('tags-loading');
    const errorEl = document.getElementById('tags-error');
    const successEl = document.getElementById('tags-success');
    const listEl = document.getElementById('tags-list');
    
    try {
        loadingEl.style.display = 'block';
        errorEl.style.display = 'none';
        successEl.style.display = 'none';
        listEl.style.display = 'none';
        
        const response = await fetch('/api/prompts/tags');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const tags = await response.json();
        renderPromptTags(tags);
        
        loadingEl.style.display = 'none';
        listEl.style.display = 'block';
        
    } catch (error) {
        console.error('Erro ao carregar tags:', error);
        loadingEl.style.display = 'none';
        errorEl.textContent = `Erro ao carregar tags: ${error.message}`;
        errorEl.style.display = 'block';
    }
}

function renderPromptTags(tags) {
    const listEl = document.getElementById('tags-list');
    
    if (!tags || tags.length === 0) {
        listEl.innerHTML = '<p class="text-center text-muted">Nenhuma tag configurada. Adicione a primeira tag!</p>';
        return;
    }
    
    const tagsHtml = tags.map(tag => `
        <div class="prompt-item-card">
            <div class="prompt-item-header">
                <h4 class="prompt-item-title">${tag.nome}</h4>
                <div class="prompt-item-actions">
                    <button class="btn-edit-small" onclick="editPromptTag(${tag.id})">✏️ Editar</button>
                    <button class="btn-delete-small" onclick="deletePromptTag(${tag.id})">🗑️ Excluir</button>
                </div>
            </div>
            <div class="prompt-item-content">
                <div class="prompt-item-descricao">${tag.descricao}</div>
                ${tag.exemplos && tag.exemplos.length > 0 ? `
                    <div class="prompt-item-exemplos">
                        <strong>Exemplos:</strong>
                        <ul>
                            ${tag.exemplos.map(exemplo => `<li>${exemplo}</li>`).join('')}
                        </ul>
                    </div>
                ` : ''}
            </div>
            <div class="prompt-item-meta">
                <span>📊 Ordem: ${tag.ordem}</span>
                <span>🕒 Atualizado: ${new Date(tag.updated_at).toLocaleString('pt-BR')}</span>
            </div>
        </div>
    `).join('');
    
    listEl.innerHTML = tagsHtml;
}

// Carregamento de Prioridades
async function loadPromptPrioridades() {
    const loadingEl = document.getElementById('prioridades-loading');
    const errorEl = document.getElementById('prioridades-error');
    const successEl = document.getElementById('prioridades-success');
    const listEl = document.getElementById('prioridades-list');
    
    try {
        loadingEl.style.display = 'block';
        errorEl.style.display = 'none';
        successEl.style.display = 'none';
        listEl.style.display = 'none';
        
        const response = await fetch('/api/prompts/prioridades');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const prioridades = await response.json();
        renderPromptPrioridades(prioridades);
        
        loadingEl.style.display = 'none';
        listEl.style.display = 'block';
        
    } catch (error) {
        console.error('Erro ao carregar prioridades:', error);
        loadingEl.style.display = 'none';
        errorEl.textContent = `Erro ao carregar prioridades: ${error.message}`;
        errorEl.style.display = 'block';
    }
}

function renderPromptPrioridades(prioridades) {
    const listEl = document.getElementById('prioridades-list');
    
    if (!prioridades || prioridades.length === 0) {
        listEl.innerHTML = '<p class="text-center text-muted">Nenhum item de prioridade configurado. Adicione o primeiro item!</p>';
        return;
    }
    
    // Agrupa por nível de prioridade
    const grupos = {
        'P1_CRITICO': { titulo: 'P1 - CRÍTICO', items: [], cor: '#dc3545' },
        'P2_ESTRATEGICO': { titulo: 'P2 - ESTRATÉGICO', items: [], cor: '#ffc107' },
        'P3_MONITORAMENTO': { titulo: 'P3 - MONITORAMENTO', items: [], cor: '#17a2b8' }
    };
    
    prioridades.forEach(item => {
        if (grupos[item.nivel]) {
            grupos[item.nivel].items.push(item);
        }
    });
    
    let prioridadesHtml = '';
    
    Object.entries(grupos).forEach(([nivel, grupo]) => {
        if (grupo.items.length > 0) {
            prioridadesHtml += `
                <div class="prompt-item-card" style="border-left: 4px solid ${grupo.cor}">
                    <div class="prompt-item-header">
                        <h4 class="prompt-item-title" style="color: ${grupo.cor}">${grupo.titulo}</h4>
                    </div>
                    ${grupo.items.map(item => `
                                                     <div class="prompt-item-content" style="margin-bottom: 15px; padding: 15px; background: white; border-radius: 4px; border: 1px solid #dee2e6;">
                                 <div class="prompt-item-header">
                                     <h5 style="margin: 0 0 10px 0; color: #495057;">${item.texto}</h5>
                                     <div class="prompt-item-actions">
                                         <button class="btn-edit-small" onclick="editPromptPrioridade(${item.id})">✏️ Editar</button>
                                         <button class="btn-delete-small" onclick="deletePromptPrioridade(${item.id})">🗑️ Excluir</button>
                                     </div>
                                 </div>
                                 <div class="prompt-item-meta">
                                     <span>📊 Ordem: ${item.ordem}</span>
                                     <span>🕒 Atualizado: ${new Date(item.updated_at).toLocaleString('pt-BR')}</span>
                                 </div>
                             </div>
                    `).join('')}
                </div>
            `;
        }
    });
    
    if (prioridadesHtml === '') {
        prioridadesHtml = '<p class="text-center text-muted">Nenhum item de prioridade configurado. Adicione o primeiro item!</p>';
    }
    
    listEl.innerHTML = prioridadesHtml;
}

// Carregamento de outros prompts
async function loadPromptResumo() {
    try {
        const response = await fetch('/api/prompts/templates/resumo');
        if (response.ok) {
            const template = await response.json();
            if (template && template.conteudo) {
                document.getElementById('prompt-resumo').value = template.conteudo;
            }
        }
    } catch (error) {
        console.error('Erro ao carregar prompt de resumo:', error);
    }
}

async function loadOutrosPrompts() {
    try {
        // Carrega prompt de relevância
        const responseRelevancia = await fetch('/api/prompts/templates/relevancia');
        if (responseRelevancia.ok) {
            const template = await responseRelevancia.json();
            if (template && template.conteudo) {
                document.getElementById('prompt-relevancia').value = template.conteudo;
            }
        }
        
        // Carrega prompt de extração
        const responseExtracao = await fetch('/api/prompts/templates/extracao');
        if (responseExtracao.ok) {
            const template = await responseExtracao.json();
            if (template && template.conteudo) {
                document.getElementById('prompt-extracao').value = template.conteudo;
            }
        }
    } catch (error) {
        console.error('Erro ao carregar outros prompts:', error);
    }
}

// =======================================
// CARREGAMENTO DINÂMICO DE TAGS
// =======================================
let tagsDisponiveis = [];

async function carregarTagsDisponiveis() {
    try {
        // Busca clusters para extrair as tags
        const response = await fetch('/api/feed?page=1&limit=100');
        if (!response.ok) {
            throw new Error('Falha ao carregar clusters');
        }
        
        const data = await response.json();
        const clusters = data.clusters || [];
        
        // Extrai tags únicas dos clusters
        const tagsUnicas = new Set();
        clusters.forEach(cluster => {
            if (cluster.tag) {
                tagsUnicas.add(cluster.tag);
            }
        });
        
        tagsDisponiveis = Array.from(tagsUnicas).sort();
        
        console.log('Tags carregadas dos clusters:', tagsDisponiveis);
        populateTagFiltersIfNeeded();
    } catch (error) {
        console.error('Erro ao carregar tags dos clusters:', error);
        // Fallback para tags antigas se a API falhar
        tagsDisponiveis = ['Governo e Politica', 'Economia e Tecnologia', 'Judicionario', 'Empresas Privadas'];
        populateTagFiltersIfNeeded();
    }
}

function generateTagOptions(selectedTag) {
    if (!tagsDisponiveis || tagsDisponiveis.length === 0) {
        // Fallback se as tags não foram carregadas
        return `
            <option value="Governo e Politica" ${selectedTag === 'Governo e Politica' ? 'selected' : ''}>Governo e Politica</option>
            <option value="Economia e Tecnologia" ${selectedTag === 'Economia e Tecnologia' ? 'selected' : ''}>Economia e Tecnologia</option>
            <option value="Judicionario" ${selectedTag === 'Judicionario' ? 'selected' : ''}>Judicionario</option>
            <option value="Empresas Privadas" ${selectedTag === 'Empresas Privadas' ? 'selected' : ''}>Empresas Privadas</option>
        `;
    }
    
    return tagsDisponiveis.map(tag => 
        `<option value="${tag}" ${selectedTag === tag ? 'selected' : ''}>${tag}</option>`
    ).join('');
}

function populateTagFiltersIfNeeded() {
    const artigosTagSelect = document.getElementById('artigos-filter-tag');
    if (artigosTagSelect && artigosTagSelect.options.length <= 1) {
        const promptTags = ['M&A e Transações Corporativas','Jurídico, Falências e Regulatório','Dívida Ativa e Créditos Públicos','Distressed Assets e NPLs','Mercado de Capitais e Finanças Corporativas','Política Econômica (Brasil)','Internacional (Economia e Política)','Tecnologia e Setores Estratégicos'];
        const opts = promptTags.map(t => `<option value="${t}">${t}</option>`).join('');
        artigosTagSelect.innerHTML = '<option value="">Todas</option>' + opts + '<option value="Outras">Outras</option>';
    }
    const clustersTagSelect = document.getElementById('clusters-filter-tag');
    if (clustersTagSelect && clustersTagSelect.options.length <= 1) {
        const promptTags = ['M&A e Transações Corporativas','Jurídico, Falências e Regulatório','Dívida Ativa e Créditos Públicos','Distressed Assets e NPLs','Mercado de Capitais e Finanças Corporativas','Política Econômica (Brasil)','Internacional (Economia e Política)','Tecnologia e Setores Estratégicos'];
        const opts = promptTags.map(t => `<option value="${t}">${t}</option>`).join('');
        clustersTagSelect.innerHTML = '<option value="">Todas</option>' + opts + '<option value="Outras">Outras</option>';
    }
    // Re-render lists to apply any selected tag filter
    if (artigosState.rows.length) renderArtigosFilteredSorted();
    if (clustersState.rows.length) renderClustersFilteredSorted();
}

// =======================================
// ORDENACAO E FILTROS (CLIENTE)
// =======================================
let artigosState = { rows: [], sortKey: 'created_at', sortDir: 'desc' };
let clustersState = { rows: [], sortKey: 'created_at', sortDir: 'desc' };

// Mapeia nome da tag para classe de cor usada no feed principal
function getTagColorClass(tagName) {
    const tagColorMap = {
        'Internacional (Economia e Política)': 'tag-1',
        'Jurídico, Falências e Regulatório': 'tag-2',
        'M&A e Transações Corporativas': 'tag-3',
        'Mercado de Capitais e Finanças Corporativas': 'tag-4',
        'Política Econômica (Brasil)': 'tag-5',
        'Tecnologia e Setores Estratégicos': 'tag-6',
        'Dívida Ativa e Créditos Públicos': 'tag-7',
        'Distressed Assets e NPLs': 'tag-8',
        'IRRELEVANTE': 'tag-9',
        'PENDING': 'tag-10'
    };
    if (tagColorMap[tagName]) return tagColorMap[tagName];
    // Fallback determinístico
    let hash = 0;
    for (let i = 0; i < String(tagName || '').length; i++) {
        hash = String(tagName).charCodeAt(i) + ((hash << 5) - hash);
    }
    const colorIndex = Math.abs(hash) % 10 + 1;
    return `tag-${colorIndex}`;
}

function setupSortingAndFilters() {
    // Sorting handlers
    document.querySelectorAll('#artigos-table thead th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            toggleSort('artigos', th.dataset.key);
        });
    });
    document.querySelectorAll('#clusters-table thead th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            toggleSort('clusters', th.dataset.key);
        });
    });

    // Filter handlers - artigos
    const artigoFilterIds = ['id','titulo','jornal','status','tag','prioridade','date'];
    artigoFilterIds.forEach(fid => {
        const el = document.getElementById(`artigos-filter-${fid}`);
        if (el) el.addEventListener('input', () => { currentPage = 1; loadArtigos(); });
        if (el && el.tagName === 'SELECT') el.addEventListener('change', () => { currentPage = 1; loadArtigos(); });
    });
    // Filter handlers - clusters
    const clusterFilterIds = ['id','titulo','tag','prioridade','status','total','date'];
    clusterFilterIds.forEach(fid => {
        const el = document.getElementById(`clusters-filter-${fid}`);
        if (el) el.addEventListener('input', () => { currentPage = 1; loadClusters(); });
        if (el && el.tagName === 'SELECT') el.addEventListener('change', () => { currentPage = 1; loadClusters(); });
    });
}

function toggleSort(tab, key) {
    const state = tab === 'artigos' ? artigosState : clustersState;
    if (state.sortKey === key) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
        state.sortKey = key;
        state.sortDir = 'asc';
    }
    updateSortIndicators(tab);
    currentPage = 1;
    if (tab === 'artigos') loadArtigos(); else loadClusters();
}

function updateSortIndicators(tab) {
    const table = document.getElementById(`${tab}-table`);
    if (!table) return;
    const state = tab === 'artigos' ? artigosState : clustersState;
    table.querySelectorAll('thead th.sortable').forEach(th => {
        th.classList.remove('sorted-asc', 'sorted-desc');
        if (th.dataset.key === state.sortKey) {
            th.classList.add(state.sortDir === 'asc' ? 'sorted-asc' : 'sorted-desc');
        }
    });
}

function compareValues(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return -1;
    if (b == null) return 1;
    // Try dates
    const ad = Date.parse(a);
    const bd = Date.parse(b);
    if (!isNaN(ad) && !isNaN(bd)) return ad - bd;
    // Numbers
    const an = Number(a);
    const bn = Number(b);
    if (!isNaN(an) && !isNaN(bn)) return an - bn;
    // Strings
    return String(a).localeCompare(String(b), 'pt-BR', { sensitivity: 'base' });
}

function passesTextFilter(value, filterText) {
    if (!filterText) return true;
    return String(value || '').toLowerCase().includes(String(filterText).toLowerCase());
}

function passesNumericFilter(value, filterText) {
    if (!filterText) return true;
    const v = Number(value);
    if (isNaN(v)) return false;
    const m = filterText.trim();
    const op = m.startsWith('>=') || m.startsWith('<=') || m.startsWith('>') || m.startsWith('<') || m.startsWith('=') ? null : '=';
    const expr = op ? op + m : m;
    const re = /^(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)$/;
    const mm = expr.match(re);
    if (!mm) return false;
    const operator = mm[1];
    const num = Number(mm[2]);
    switch (operator) {
        case '>': return v > num;
        case '<': return v < num;
        case '>=': return v >= num;
        case '<=': return v <= num;
        case '=': return v === num;
        default: return true;
    }
}

function passesDateFilter(valueISO, filterDateStr) {
    if (!filterDateStr) return true;
    if (!valueISO) return false;
    const d1 = new Date(valueISO);
    const d2 = new Date(filterDateStr);
    return d1.getFullYear() === d2.getFullYear() && d1.getMonth() === d2.getMonth() && d1.getDate() === d2.getDate();
}

function renderArtigosFilteredSorted() {
    // Fill tag filter options once
    const tagSelect = document.getElementById('artigos-filter-tag');
    if (tagSelect && tagSelect.options.length <= 1 && Array.isArray(tagsDisponiveis)) {
        tagSelect.innerHTML = '<option value="">Todas</option>' + tagsDisponiveis.map(t => `<option value="${t}">${t}</option>`).join('');
    }
    const fId = document.getElementById('artigos-filter-id')?.value || '';
    const fTitulo = document.getElementById('artigos-filter-titulo')?.value || '';
    const fJornal = document.getElementById('artigos-filter-jornal')?.value || '';
    const fStatus = document.getElementById('artigos-filter-status')?.value || '';
    const fTag = document.getElementById('artigos-filter-tag')?.value || '';
    const fPrior = document.getElementById('artigos-filter-prioridade')?.value || '';
    const fDate = document.getElementById('artigos-filter-date')?.value || '';

    let rows = artigosState.rows.filter(row => {
        const okId = fId ? passesNumericFilter(row.id, fId) : true;
        const okTitulo = passesTextFilter(row.titulo_extraido || row.texto_bruto, fTitulo);
        const okJornal = passesTextFilter(row.jornal, fJornal);
        const okStatus = fStatus ? String(row.status) === fStatus : true;
        const okTag = fTag ? String(row.tag) === fTag : true;
        const okPrior = fPrior ? String(row.prioridade) === fPrior : true;
        const okDate = passesDateFilter(row.created_at, fDate);
        return okId && okTitulo && okJornal && okStatus && okTag && okPrior && okDate;
    });

    rows.sort((a, b) => {
        const dir = artigosState.sortDir === 'asc' ? 1 : -1;
        return compareValues(a[artigosState.sortKey], b[artigosState.sortKey]) * dir;
    });

    const tbody = document.getElementById('artigos-tbody');
    tbody.innerHTML = '';
    rows.forEach(artigo => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${artigo.id}</td>
            <td>${artigo.titulo_extraido || (artigo.texto_bruto ? artigo.texto_bruto.substring(0, 50) + '...' : '')}</td>
            <td>${artigo.jornal || '-'}</td>
            <td><span class="status-badge status-${artigo.status}">${artigo.status}</span></td>
            <td>${artigo.tag ? `<span class="tag-badge">${artigo.tag}</span>` : '-'}</td>
            <td>${artigo.prioridade ? `<span class="priority-badge ${artigo.prioridade}">${artigo.prioridade}</span>` : '-'}</td>
            <td>${formatDate(artigo.created_at)}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn-edit" onclick="editArtigo(${artigo.id})">Editar</button>
                    <button class="btn-delete" onclick="deleteArtigo(${artigo.id})">Excluir</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });
    updateSortIndicators('artigos');
}

function renderClustersFilteredSorted() {
    // Fill tag filter options once
    const tagSelect = document.getElementById('clusters-filter-tag');
    if (tagSelect && tagSelect.options.length <= 1 && Array.isArray(tagsDisponiveis)) {
        tagSelect.innerHTML = '<option value="">Todas</option>' + tagsDisponiveis.map(t => `<option value="${t}">${t}</option>`).join('');
    }

    const fId = document.getElementById('clusters-filter-id')?.value || '';
    const fTitulo = document.getElementById('clusters-filter-titulo')?.value || '';
    const fTag = document.getElementById('clusters-filter-tag')?.value || '';
    const fPrior = document.getElementById('clusters-filter-prioridade')?.value || '';
    const fStatus = document.getElementById('clusters-filter-status')?.value || '';
    const fTotal = document.getElementById('clusters-filter-total')?.value || '';
    const fDate = document.getElementById('clusters-filter-date')?.value || '';

    let rows = clustersState.rows.filter(row => {
        const okId = fId ? passesNumericFilter(row.id, fId) : true;
        const okTitulo = passesTextFilter(row.titulo_cluster, fTitulo);
        const okTag = fTag ? String(row.tag) === fTag : true;
        const okPrior = fPrior ? String(row.prioridade) === fPrior : true;
        const okStatus = fStatus ? String(row.status) === fStatus : true;
        const okTotal = fTotal ? passesNumericFilter(row.total_artigos, fTotal) : true;
        const okDate = passesDateFilter(row.created_at, fDate);
        return okId && okTitulo && okTag && okPrior && okStatus && okTotal && okDate;
    });

    rows.sort((a, b) => {
        const dir = clustersState.sortDir === 'asc' ? 1 : -1;
        return compareValues(a[clustersState.sortKey], b[clustersState.sortKey]) * dir;
    });

    const tbody = document.getElementById('clusters-tbody');
    tbody.innerHTML = '';
    rows.forEach(cluster => {
        const row = document.createElement('tr');
        const tagClass = cluster.tag ? getTagColorClass(cluster.tag) : '';
        row.innerHTML = `
            <td>${cluster.id}</td>
            <td>${cluster.titulo_cluster}</td>
            <td><span class="tag ${tagClass}">${cluster.tag}</span></td>
            <td><span class="priority-badge ${cluster.prioridade}">${cluster.prioridade}</span></td>
            <td><span class="status-badge status-${cluster.status}">${cluster.status}</span></td>
            <td>${cluster.total_artigos}</td>
            <td>${formatDate(cluster.created_at)}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn-edit" onclick="editCluster(${cluster.id})">Editar</button>
                    <button class="btn-delete" onclick="deleteCluster(${cluster.id})">Excluir</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });
    updateSortIndicators('clusters');
}

// ==============================================================================
// FUNÇÕES PARA ARTIGOS
// ==============================================================================

async function loadArtigos() {
    showLoading('artigos');
    
    try {
        const params = new URLSearchParams();
        params.set('page', currentPage);
        params.set('limit', 20);
        // Filtros
        const fId = document.getElementById('artigos-filter-id')?.value || '';
        const fTitulo = document.getElementById('artigos-filter-titulo')?.value || '';
        const fJornal = document.getElementById('artigos-filter-jornal')?.value || '';
        const fStatus = document.getElementById('artigos-filter-status')?.value || '';
        const fTag = document.getElementById('artigos-filter-tag')?.value || '';
        const fPrior = document.getElementById('artigos-filter-prioridade')?.value || '';
        const fDate = document.getElementById('artigos-filter-date')?.value || '';
        if (fId && /^\d+$/.test(fId)) params.set('id', fId);
        if (fTitulo) params.set('titulo', fTitulo);
        if (fJornal) params.set('jornal', fJornal);
        if (fStatus) params.set('status', fStatus);
        if (fTag) params.set('tag', fTag);
        if (fPrior) params.set('prioridade', fPrior);
        if (fDate) params.set('date', fDate);
        // Ordenação
        if (artigosState.sortKey) params.set('sort_by', artigosState.sortKey);
        if (artigosState.sortDir) params.set('sort_dir', artigosState.sortDir);

        const response = await fetch(`${API_BASE}/settings/artigos?${params.toString()}`);
        const data = await response.json();
        
        if (response.ok) {
            displayArtigos(data);
        } else {
            showError('artigos', 'Erro ao carregar artigos: ' + data.detail);
        }
    } catch (error) {
        showError('artigos', 'Erro de conexão: ' + error.message);
    }
}

function displayArtigos(data) {
    // atualiza estado e renderiza exatamente os dados retornados
    artigosState.rows = Array.isArray(data.artigos) ? data.artigos : [];
    // apenas renderiza (sem refiltrar no cliente para não podar a página)
    const tbody = document.getElementById('artigos-tbody');
    tbody.innerHTML = '';
    artigosState.rows.forEach(artigo => {
        const row = document.createElement('tr');
        const tagClass = artigo.tag ? getTagColorClass(artigo.tag) : '';
        row.innerHTML = `
            <td>${artigo.id}</td>
            <td>${artigo.titulo_extraido || (artigo.texto_bruto ? artigo.texto_bruto.substring(0, 50) + '...' : '')}</td>
            <td>${artigo.jornal || '-'}</td>
            <td><span class="status-badge status-${artigo.status}">${artigo.status}</span></td>
            <td>${artigo.tag ? `<span class="tag-badge">${artigo.tag}</span>` : '-'}</td>
            <td>${artigo.prioridade ? `<span class="priority-badge ${artigo.prioridade}">${artigo.prioridade}</span>` : '-'}</td>
            <td>${formatDate(artigo.created_at)}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn-edit" onclick="editArtigo(${artigo.id})">Editar</button>
                    <button class="btn-delete" onclick="deleteArtigo(${artigo.id})">Excluir</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });

    showTable('artigos');
    createPagination('artigos', data.page, data.pages, loadArtigos);
}

async function editArtigo(id) {
    try {
        const response = await fetch(`${API_BASE}/settings/artigos/${id}`);
        const artigo = await response.json();
        
        if (response.ok) {
            showEditModal('artigo', artigo);
        } else {
            alert('Erro ao carregar artigo: ' + artigo.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

async function deleteArtigo(id) {
    if (!confirm('Tem certeza que deseja excluir este artigo?')) return;
    
    try {
        const response = await fetch(`${API_BASE}/settings/artigos/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSuccess('artigos', 'Artigo excluído com sucesso!');
            loadArtigos();
        } else {
            const error = await response.json();
            alert('Erro ao excluir artigo: ' + error.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

// ==============================================================================
// FUNÇÕES PARA CLUSTERS
// ==============================================================================

async function loadClusters() {
    showLoading('clusters');
    
    try {
        const params = new URLSearchParams();
        params.set('page', currentPage);
        params.set('limit', 20);
        // Filtros
        const fId = document.getElementById('clusters-filter-id')?.value || '';
        const fTitulo = document.getElementById('clusters-filter-titulo')?.value || '';
        const fTag = document.getElementById('clusters-filter-tag')?.value || '';
        const fPrior = document.getElementById('clusters-filter-prioridade')?.value || '';
        const fStatus = document.getElementById('clusters-filter-status')?.value || '';
        const fTotal = document.getElementById('clusters-filter-total')?.value || '';
        const fDate = document.getElementById('clusters-filter-date')?.value || '';
        if (fId && /^\d+$/.test(fId)) params.set('id', fId);
        if (fTitulo) params.set('titulo', fTitulo);
        if (fTag) params.set('tag', fTag);
        if (fPrior) params.set('prioridade', fPrior);
        if (fStatus) params.set('status', fStatus);
        if (fTotal) {
            const m = fTotal.match(/^(>=|<=|>|<|=)\s*(\d+)$/);
            if (m) { params.set('total_op', m[1]); params.set('total_val', m[2]); }
        }
        if (fDate) params.set('date', fDate);
        // Ordenação
        if (clustersState.sortKey) params.set('sort_by', clustersState.sortKey);
        if (clustersState.sortDir) params.set('sort_dir', clustersState.sortDir);

        const response = await fetch(`${API_BASE}/settings/clusters?${params.toString()}`);
        const data = await response.json();
        
        if (response.ok) {
            displayClusters(data);
        } else {
            showError('clusters', 'Erro ao carregar clusters: ' + data.detail);
        }
    } catch (error) {
        showError('clusters', 'Erro de conexão: ' + error.message);
    }
}

function displayClusters(data) {
    clustersState.rows = Array.isArray(data.clusters) ? data.clusters : [];
    const tbody = document.getElementById('clusters-tbody');
    tbody.innerHTML = '';
    clustersState.rows.forEach(cluster => {
        const row = document.createElement('tr');
        const tagClass = cluster.tag ? getTagColorClass(cluster.tag) : '';
        row.innerHTML = `
            <td>${cluster.id}</td>
            <td>${cluster.titulo_cluster}</td>
            <td><span class="tag ${tagClass}">${cluster.tag}</span></td>
            <td><span class="priority-badge ${cluster.prioridade}">${cluster.prioridade}</span></td>
            <td><span class="status-badge status-${cluster.status}">${cluster.status}</span></td>
            <td>${cluster.total_artigos}</td>
            <td>${formatDate(cluster.created_at)}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn-edit" onclick="editCluster(${cluster.id})">Editar</button>
                    <button class="btn-delete" onclick="deleteCluster(${cluster.id})">Excluir</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });

    showTable('clusters');
    createPagination('clusters', data.page, data.pages, loadClusters);
}

async function editCluster(id) {
    try {
        const response = await fetch(`${API_BASE}/settings/clusters/${id}`);
        const cluster = await response.json();
        
        if (response.ok) {
            showEditModal('cluster', cluster);
        } else {
            alert('Erro ao carregar cluster: ' + cluster.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

async function deleteCluster(id) {
    if (!confirm('Tem certeza que deseja excluir este cluster? Os artigos associados serão desvinculados.')) return;
    
    try {
        const response = await fetch(`${API_BASE}/settings/clusters/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSuccess('clusters', 'Cluster excluído com sucesso!');
            loadClusters();
        } else {
            const error = await response.json();
            alert('Erro ao excluir cluster: ' + error.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

// ==============================================================================
// FUNÇÕES PARA SÍNTESES
// ==============================================================================

async function loadSinteses() {
    showLoading('sinteses');
    
    try {
        const response = await fetch(`${API_BASE}/settings/sinteses?page=${currentPage}&limit=20`);
        const data = await response.json();
        
        if (response.ok) {
            displaySinteses(data);
        } else {
            showError('sinteses', 'Erro ao carregar sínteses: ' + data.detail);
        }
    } catch (error) {
        showError('sinteses', 'Erro de conexão: ' + error.message);
    }
}

function displaySinteses(data) {
    const tbody = document.getElementById('sinteses-tbody');
    tbody.innerHTML = '';
    
    data.sinteses.forEach(sintese => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${sintese.id}</td>
            <td>${formatDate(sintese.data_sintese)}</td>
            <td>${sintese.texto_sintese}</td>
            <td>${sintese.total_noticias_coletadas}</td>
            <td>${sintese.total_eventos_unicos}</td>
            <td>${sintese.total_analises_criticas}</td>
            <td>
                <div class="action-buttons">
                    <button class="btn-edit" onclick="editSintese(${sintese.id})">Editar</button>
                    <button class="btn-delete" onclick="deleteSintese(${sintese.id})">Excluir</button>
                </div>
            </td>
        `;
        tbody.appendChild(row);
    });
    
    showTable('sinteses');
    createPagination('sinteses', data.page, data.pages, loadSinteses);
}

async function editSintese(id) {
    try {
        const response = await fetch(`${API_BASE}/settings/sinteses/${id}`);
        const sintese = await response.json();
        
        if (response.ok) {
            showEditModal('sintese', sintese);
        } else {
            alert('Erro ao carregar síntese: ' + sintese.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

async function deleteSintese(id) {
    if (!confirm('Tem certeza que deseja excluir esta síntese?')) return;
    
    try {
        const response = await fetch(`${API_BASE}/settings/sinteses/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSuccess('sinteses', 'Síntese excluída com sucesso!');
            loadSinteses();
        } else {
            const error = await response.json();
            alert('Erro ao excluir síntese: ' + error.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
}

// ==============================================================================
// FUNÇÕES DO MODAL
// ==============================================================================

function showEditModal(type, item) {
    currentItem = { type, item };
    
    const modal = document.getElementById('editModal');
    const title = document.getElementById('modal-title');
    const fields = document.getElementById('modal-fields');
    
    title.textContent = `Editar ${type.charAt(0).toUpperCase() + type.slice(1)}`;
    
    // Gera campos baseado no tipo
    fields.innerHTML = generateFormFields(type, item);
    
    modal.style.display = 'block';
}

function generateFormFields(type, item) {
    switch(type) {
        case 'artigo':
            return `
                <div class="form-group">
                    <label>Título Extraído</label>
                    <input type="text" name="titulo_extraido" value="${item.titulo_extraido || ''}" />
                </div>
                <div class="form-group">
                    <label>Texto Original da Notícia (PDF/URL)</label>
                    <textarea name="texto_original" rows="12" style="width: 100%; font-family: monospace; font-size: 11px; resize: vertical; background-color: #f8f9fa;" readonly>${item.texto_bruto || 'Texto original não disponível'}</textarea>
                </div>
                <div class="form-group">
                    <label>Texto Processado/Resumido</label>
                    <textarea name="texto_processado" rows="8" style="width: 100%; font-family: monospace; font-size: 11px; resize: vertical; background-color: #e9ecef;">${item.texto_processado || 'Texto processado não disponível'}</textarea>
                </div>
                <div class="form-group">
                    <label>Jornal</label>
                    <input type="text" name="jornal" value="${item.jornal || ''}" />
                </div>
                <div class="form-group">
                    <label>Autor</label>
                    <input type="text" name="autor" value="${item.autor || ''}" />
                </div>
                <div class="form-group">
                    <label>Página (se PDF)</label>
                    <input type="text" name="pagina" value="${item.pagina || ''}" />
                </div>
                <div class="form-group">
                    <label>Data de Publicação</label>
                    <input type="date" name="data_publicacao" value="${item.data_publicacao ? item.data_publicacao.split('T')[0] : ''}" />
                </div>
                <div class="form-group">
                    <label>Fonte de Coleta</label>
                    <input type="text" name="fonte_coleta" value="${item.fonte_coleta || ''}" readonly />
                </div>
                <div class="form-group">
                    <label>Tag</label>
                    <select name="tag">
                        <option value="">Selecione...</option>
                        <option value="Governo e Politica" ${item.tag === 'Governo e Politica' ? 'selected' : ''}>Governo e Politica</option>
                        <option value="Economia e Tecnologia" ${item.tag === 'Economia e Tecnologia' ? 'selected' : ''}>Economia e Tecnologia</option>
                        <option value="Judicionario" ${item.tag === 'Judicionario' ? 'selected' : ''}>Judicionario</option>
                        <option value="Empresas Privadas" ${item.tag === 'Empresas Privadas' ? 'selected' : ''}>Empresas Privadas</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Prioridade</label>
                    <select name="prioridade">
                        <option value="">Selecione...</option>
                        <option value="P1_CRITICO" ${item.prioridade === 'P1_CRITICO' ? 'selected' : ''}>P1 - Crítico</option>
                        <option value="P2_ESTRATEGICO" ${item.prioridade === 'P2_ESTRATEGICO' ? 'selected' : ''}>P2 - Estratégico</option>
                        <option value="P3_MONITORAMENTO" ${item.prioridade === 'P3_MONITORAMENTO' ? 'selected' : ''}>P3 - Monitoramento</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Relevance Score</label>
                    <input type="number" name="relevance_score" value="${item.relevance_score || ''}" min="0" max="100" step="0.1" />
                </div>
                <div class="form-group">
                    <label>Relevance Reason</label>
                    <textarea name="relevance_reason" rows="3">${item.relevance_reason || ''}</textarea>
                </div>
            `;
            
        case 'cluster':
            return `
                <div class="form-group">
                    <label>Título do Cluster</label>
                    <input type="text" name="titulo_cluster" value="${item.titulo_cluster || ''}" />
                </div>
                <div class="form-group">
                    <label>Resumo do Cluster</label>
                    <textarea name="resumo_cluster">${item.resumo_cluster || ''}</textarea>
                </div>
                <div class="form-group">
                    <label>Tag</label>
                    <select name="tag">
                        <option value="">Selecione...</option>
                        ${generateTagOptions(item.tag)}
                    </select>
                </div>
                <div class="form-group">
                    <label>Prioridade</label>
                    <select name="prioridade">
                        <option value="">Selecione...</option>
                        <option value="P1_CRITICO" ${item.prioridade === 'P1_CRITICO' ? 'selected' : ''}>P1 - Crítico</option>
                        <option value="P2_ESTRATEGICO" ${item.prioridade === 'P2_ESTRATEGICO' ? 'selected' : ''}>P2 - Estratégico</option>
                        <option value="P3_MONITORAMENTO" ${item.prioridade === 'P3_MONITORAMENTO' ? 'selected' : ''}>P3 - Monitoramento</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Status</label>
                    <select name="status">
                        <option value="ativo" ${item.status === 'ativo' ? 'selected' : ''}>Ativo</option>
                        <option value="arquivado" ${item.status === 'arquivado' ? 'selected' : ''}>Arquivado</option>
                        <option value="descartado" ${item.status === 'descartado' ? 'selected' : ''}>Descartado</option>
                    </select>
                </div>
            `;
            
        case 'sintese':
            return `
                <div class="form-group">
                    <label>Texto da Síntese</label>
                    <textarea name="texto_sintese" style="min-height: 200px;">${item.texto_sintese || ''}</textarea>
                </div>
            `;
            
        default:
            return '<p>Formulário não disponível para este tipo.</p>';
    }
}

function closeModal() {
    document.getElementById('editModal').style.display = 'none';
    currentItem = null;
}

// ==============================================================================
// FUNÇÕES AUXILIARES
// ==============================================================================

function showLoading(tab) {
    document.getElementById(`${tab}-loading`).style.display = 'block';
    document.getElementById(`${tab}-table`).style.display = 'none';
    document.getElementById(`${tab}-pagination`).style.display = 'none';
    document.getElementById(`${tab}-error`).style.display = 'none';
    document.getElementById(`${tab}-success`).style.display = 'none';
}

function showTable(tab) {
    document.getElementById(`${tab}-loading`).style.display = 'none';
    document.getElementById(`${tab}-table`).style.display = 'table';
    document.getElementById(`${tab}-pagination`).style.display = 'flex';
}

// ======================= BI =======================
async function carregarBI() {
    try {
        // Mostra loading
        const biContent = document.getElementById('bi');
        biContent.innerHTML = '<div class="loading">Carregando dados do BI...</div>';
        
        // Timeout para evitar travamento
        const timeoutPromise = new Promise((_, reject) => {
            setTimeout(() => reject(new Error('Timeout: BI demorou muito para carregar')), 30000);
        });
        
        // Função principal com timeout
        const biPromise = carregarBIDados();
        const result = await Promise.race([biPromise, timeoutPromise]);
        
        // Se chegou aqui, carregou com sucesso
        biContent.innerHTML = result.html;
        
        // Renderiza os gráficos após o HTML estar carregado
        setTimeout(() => {
            renderizarGraficos(result.tagsData, result.prioridadesData);
        }, 100);
        
    } catch (e) {
        console.error('Erro ao carregar BI', e);
        const biContent = document.getElementById('bi');
        biContent.innerHTML = `
            <div class="error">
                Erro ao carregar dados do BI: ${e.message}
                <br><br>
                <button class="btn btn-primary" onclick="carregarBI()">Tentar Novamente</button>
            </div>
        `;
    }
}

async function carregarBIDados() {
    // Estatísticas gerais
    const stats = await fetch(`${API_BASE}/bi/estatisticas-gerais`);
    const statsData = await stats.json();
    
    // séries por dia (invertendo a ordem)
    const s = await fetch(`${API_BASE}/bi/series-por-dia?dias=30`);
    const sd = await s.json();
    
    // por fonte
    const f = await fetch(`${API_BASE}/bi/noticias-por-fonte?limit=20`);
    const fd = await f.json();
    
    // Gráfico por tag
    const tags = await fetch(`${API_BASE}/bi/noticias-por-tag?limit=10`);
    const tagsData = await tags.json();
    
    // Gráfico por prioridade
    const prioridades = await fetch(`${API_BASE}/bi/noticias-por-prioridade`);
    const prioridadesData = await prioridades.json();
    
    // Retorna HTML completo
    return {
        html: `
            <div class="upload-section">
                <h3>📊 Estatísticas Gerais</h3>
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-number" id="total-dias">${statsData.dias_diferentes || 0}</div>
                        <div class="stat-label">Dias com Notícias</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number" id="total-artigos">${statsData.total_artigos || 0}</div>
                        <div class="stat-label">Total de Artigos</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-number" id="total-clusters">${statsData.total_clusters || 0}</div>
                        <div class="stat-label">Total de Clusters</div>
                    </div>
                </div>
            </div>
            
            <div class="upload-section">
                <h3>📈 Séries por Dia (Últimos 30 dias)</h3>
                <table class="data-table" id="bi-series-table">
                    <thead><tr><th>Dia</th><th>Artigos</th><th>Clusters</th></tr></thead>
                    <tbody>
                        ${(sd.series || []).reverse().map(item => 
                            `<tr><td>${item.dia}</td><td>${item.num_artigos}</td><td>${item.num_clusters}</td></tr>`
                        ).join('')}
                    </tbody>
                </table>
            </div>
            
            <div class="upload-section">
                <h3>📰 Notícias por Fonte (Top 20)</h3>
                <table class="data-table" id="bi-fonte-table">
                    <thead><tr><th>Fonte</th><th>Qtd</th></tr></thead>
                    <tbody>
                        ${(fd.itens || []).map(i => 
                            `<tr><td>${i.jornal}</td><td>${i.qtd}</td></tr>`
                        ).join('')}
                    </tbody>
                </table>
            </div>
            
            <!-- Gráficos de Pizza -->
            <div class="charts-section">
                <div class="chart-container">
                    <div class="chart-card">
                        <h3>🏷️ Notícias por Tag (Top 10)</h3>
                        <canvas id="chart-tags" width="400" height="400"></canvas>
                    </div>
                    <div class="chart-card">
                        <h3>🎯 Notícias por Prioridade</h3>
                        <canvas id="chart-prioridade" width="400" height="400"></canvas>
                    </div>
                </div>
            </div>
            
            <div class="upload-section">
                <h3>�� Estimativa de Custos</h3>
                <button class="btn btn-secondary" onclick="carregarEstimativaCustos()">Calcular Estimativa</button>
                <div id="custos-output" class="upload-results" style="display:none;"></div>
            </div>
        `,
        tagsData: tagsData,
        prioridadesData: prioridadesData
    };
}

// Função para renderizar os gráficos após o HTML estar carregado
function renderizarGraficos(tagsData, prioridadesData) {
    try {
        // Renderiza gráfico de tags
        if (tagsData && tagsData.itens && tagsData.itens.length > 0) {
            criarGraficoTags(tagsData.itens);
        }
        
        // Renderiza gráfico de prioridades
        if (prioridadesData && prioridadesData.itens && prioridadesData.itens.length > 0) {
            criarGraficoPrioridade(prioridadesData.itens);
        }
    } catch (e) {
        console.error('Erro ao renderizar gráficos:', e);
    }
}

// Função para criar gráfico de pizza das tags
function criarGraficoTags(dados) {
    try {
        const ctx = document.getElementById('chart-tags');
        if (!ctx) {
            console.warn('Canvas chart-tags não encontrado');
            return;
        }
        
        // Destroi gráfico anterior se existir
        if (window.chartTags) {
            window.chartTags.destroy();
        }
        
        // Valida dados
        if (!Array.isArray(dados) || dados.length === 0) {
            console.warn('Dados de tags inválidos ou vazios');
            return;
        }
        
        const labels = dados.map(item => item.tag || 'Sem Tag');
        const data = dados.map(item => item.qtd || 0);
        
        // Cores para as tags
        const cores = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
            '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384'
        ];
        
        window.chartTags = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: cores.slice(0, labels.length),
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Erro ao criar gráfico de tags:', e);
    }
}

// Função para criar gráfico de pizza das prioridades
function criarGraficoPrioridade(dados) {
    try {
        const ctx = document.getElementById('chart-prioridade');
        if (!ctx) {
            console.warn('Canvas chart-prioridade não encontrado');
            return;
        }
        
        // Destroi gráfico anterior se existir
        if (window.chartPrioridade) {
            window.chartPrioridade.destroy();
        }
        
        // Valida dados
        if (!Array.isArray(dados) || dados.length === 0) {
            console.warn('Dados de prioridades inválidos ou vazios');
            return;
        }
        
        const labels = dados.map(item => item.prioridade || 'Sem Prioridade');
        const data = dados.map(item => item.qtd || 0);
        
        // Cores específicas para prioridades
        const cores = {
            'P1_CRITICO': '#dc3545',
            'P2_ESTRATEGICO': '#ffc107',
            'P3_MONITORAMENTO': '#17a2b8',
            'Sem Prioridade': '#6c757d'
        };
        
        const backgroundColor = labels.map(label => cores[label] || '#6c757d');
        
        window.chartPrioridade = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: backgroundColor,
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    } catch (e) {
        console.error('Erro ao criar gráfico de prioridades:', e);
    }
}

async function carregarEstimativaCustos() {
    try {
        // execução indireta: chama um endpoint futuro? Aqui apenas placeholder local
        // Como não temos endpoint, mostramos instrução para executar o script localmente
        const el = document.getElementById('custos-output');
        el.style.display = 'block';
        el.innerHTML = `
            <div>
                Para estimar custos, rode no servidor: <code>python estimativa_custos.py</code>.
                Em breve podemos expor um endpoint para retornar a análise formatada.
            </div>
        `;
    } catch (e) {
        console.error('Erro estimativa custos', e);
    }
}

// ======================= FEEDBACK =======================
async function enviarFeedback() {
    const artigoId = Number(document.getElementById('fb-artigo-id').value);
    const tipo = document.getElementById('fb-tipo').value;
    if (!artigoId || !tipo) return alert('Preencha os campos');
    try {
        const resp = await fetch(`${API_BASE}/feedback?artigo_id=${artigoId}&feedback=${tipo}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) return alert('Erro: ' + (data.detail || 'falha'));
        alert('Feedback registrado');
        carregarFeedback();
    } catch (e) {
        alert('Erro de conexão: ' + e.message);
    }
}

async function carregarFeedback() {
    try {
        const resp = await fetch(`${API_BASE}/feedback`);
        const data = await resp.json();
        const tbody = document.querySelector('#fb-table tbody');
        tbody.innerHTML = '';
        (data.itens || []).forEach(fb => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${fb.id}</td>
                <td>${fb.artigo_id}</td>
                <td>${fb.feedback}</td>
                <td>${fb.processed ? 'Sim' : 'Não'}</td>
                <td>${fb.created_at}</td>
                <td>${fb.processed ? '' : `<button class="btn-edit" onclick="processarFeedback(${fb.id})">Marcar processado</button>`}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error('Erro ao carregar feedback', e);
    }
}

async function processarFeedback(id) {
    try {
        const resp = await fetch(`${API_BASE}/feedback/${id}/process`, { method: 'POST' });
        if (!resp.ok) {
            const data = await resp.json();
            return alert('Erro: ' + (data.detail || 'falha'));
        }
        carregarFeedback();
    } catch (e) {
        alert('Erro de conexão: ' + e.message);
    }
}

function showError(tab, message) {
    document.getElementById(`${tab}-loading`).style.display = 'none';
    document.getElementById(`${tab}-error`).style.display = 'block';
    document.getElementById(`${tab}-error`).textContent = message;
}

function showSuccess(tab, message) {
    document.getElementById(`${tab}-success`).style.display = 'block';
    document.getElementById(`${tab}-success`).textContent = message;
    
    setTimeout(() => {
        document.getElementById(`${tab}-success`).style.display = 'none';
    }, 3000);
}

function createPagination(tab, pageNumber, totalPages, loadFunction) {
    const pagination = document.getElementById(`${tab}-pagination`);
    pagination.innerHTML = '';
    
    if (totalPages <= 1) return;
    
    // Botão anterior
    if (pageNumber > 1) {
        const prevBtn = document.createElement('button');
        prevBtn.textContent = '← Anterior';
        prevBtn.onclick = () => {
            // atualiza a página global corretamente
            currentPage = pageNumber - 1;
            loadFunction();
        };
        pagination.appendChild(prevBtn);
    }
    
    // Páginas
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= pageNumber - 2 && i <= pageNumber + 2)) {
            const pageBtn = document.createElement('button');
            pageBtn.textContent = i;
            pageBtn.className = i === pageNumber ? 'active' : '';
            pageBtn.onclick = () => {
                // atualiza a página global corretamente
                currentPage = i;
                loadFunction();
            };
            pagination.appendChild(pageBtn);
        } else if (i === pageNumber - 3 || i === pageNumber + 3) {
            const ellipsis = document.createElement('span');
            ellipsis.textContent = '...';
            ellipsis.style.padding = '8px 16px';
            pagination.appendChild(ellipsis);
        }
    }
    
    // Botão próximo
    if (pageNumber < totalPages) {
        const nextBtn = document.createElement('button');
        nextBtn.textContent = 'Próximo →';
        nextBtn.onclick = () => {
            // atualiza a página global corretamente
            currentPage = pageNumber + 1;
            loadFunction();
        };
        pagination.appendChild(nextBtn);
    }
}

function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('pt-BR') + ' ' + date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

// ==============================================================================
// HANDLER DO FORMULÁRIO
// ==============================================================================

document.getElementById('editForm').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    if (!currentItem) return;
    
    const formData = new FormData(e.target);
    const data = {};
    
    for (let [key, value] of formData.entries()) {
        if (value !== '') {
            data[key] = value;
        }
    }
    
    try {
        const response = await fetch(`${API_BASE}/settings/${currentItem.type}s/${currentItem.item.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            closeModal();
            showSuccess(currentItem.type + 's', `${currentItem.type.charAt(0).toUpperCase() + currentItem.type.slice(1)} atualizado com sucesso!`);
            
            // Recarrega a lista
            switch(currentItem.type) {
                case 'artigo':
                    loadArtigos();
                    break;
                case 'cluster':
                    loadClusters();
                    break;
                case 'sintese':
                    loadSinteses();
                    break;
            }
        } else {
            const error = await response.json();
            alert('Erro ao atualizar: ' + error.detail);
        }
    } catch (error) {
        alert('Erro de conexão: ' + error.message);
    }
});

// Fecha modal ao clicar fora
window.onclick = function(event) {
    const modal = document.getElementById('editModal');
    if (event.target === modal) {
        closeModal();
    }
}

// ==============================================================================
// UPLOAD FUNCTIONALITY
// ==============================================================================

// Inicialização dos elementos de upload
document.addEventListener('DOMContentLoaded', function() {
    loadArtigos();
    
    // Setup upload functionality
    const uploadBtn = document.getElementById('upload-btn');
    const fileUpload = document.getElementById('file-upload');
    const processArticlesBtn = document.getElementById('process-articles-btn');
    
    if (uploadBtn) {
        uploadBtn.addEventListener('click', async () => {
            // Em vez de apenas abrir o seletor, dispara o mesmo fluxo do CLI
            // Equivalente a: python load_news.py --dir ../pdfs --direct --yes
            const uploadStatus = document.getElementById('upload-status');
            const uploadProgress = document.getElementById('upload-progress');
            const progressText = document.querySelector('#upload-progress .progress-text');

            if (uploadStatus) uploadStatus.innerHTML = '';
            if (uploadProgress) uploadProgress.style.display = 'block';
            if (progressText) progressText.textContent = 'Iniciando carregamento da pasta ../pdfs...';

            try {
                const resp = await fetch(`${API_BASE}/admin/carregar-arquivos`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ diretorio: '../pdfs' })
                });
                const data = await resp.json();
                if (resp.ok) {
                    if (uploadStatus) uploadStatus.innerHTML = `<div class="success">✅ ${data.message}</div>`;
                } else {
                    if (uploadStatus) uploadStatus.innerHTML = `<div class="error">❌ ${data.detail || 'Erro ao iniciar carregamento'}</div>`;
                }
            } catch (err) {
                if (uploadStatus) uploadStatus.innerHTML = `<div class="error">❌ Erro de conexão: ${err.message}</div>`;
            } finally {
                // Oculta barra após breve delay
                setTimeout(() => { if (uploadProgress) uploadProgress.style.display = 'none'; }, 1200);
            }
        });
    }
    
    if (fileUpload) {
        fileUpload.addEventListener('change', handleFileUpload);
    }
    
    if (processArticlesBtn) {
        processArticlesBtn.addEventListener('click', handleProcessArticles);
    }
});

async function handleFileUpload(event) {
    const files = event.target.files;
    if (!files || files.length === 0) return;
    
    const uploadStatus = document.getElementById('upload-status');
    const uploadProgress = document.getElementById('upload-progress');
    const uploadResults = document.getElementById('upload-results');
    const progressFill = document.querySelector('#upload-progress .progress-fill');
    const progressText = document.querySelector('#upload-progress .progress-text');
    
    // Elementos do progresso detalhado
    const currentFilename = document.getElementById('current-filename');
    const currentProgress = document.getElementById('current-progress');
    const totalArticles = document.getElementById('total-articles');
    const processingStatusText = document.getElementById('processing-status-text');
    
    // Elementos das etapas
    const stepUpload = document.getElementById('step-upload');
    const stepProcessing = document.getElementById('step-processing');
    const stepDatabase = document.getElementById('step-database');
    const stepComplete = document.getElementById('step-complete');
    
    // Reset UI
    uploadStatus.innerHTML = '';
    uploadResults.style.display = 'none';
    uploadProgress.style.display = 'block';
    
    // Reset etapas
    [stepUpload, stepProcessing, stepDatabase, stepComplete].forEach(step => {
        step.classList.remove('active', 'completed');
    });
    
    let processedFiles = 0;
    const totalFiles = files.length;
    const results = [];
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        
        // Atualizar nome do arquivo atual
        currentFilename.textContent = file.name;
        
        // Etapa 1: Upload
        stepUpload.classList.add('active');
        processingStatusText.textContent = 'Enviando arquivo...';
        processingStatusText.className = 'processing';
        
        // Update progress
        const progress = ((i + 1) / totalFiles) * 100;
        progressFill.style.width = `${progress}%`;
        progressText.textContent = `Processando ${file.name}... (${i + 1}/${totalFiles})`;
        
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            // Etapa 2: Processamento
            stepUpload.classList.remove('active');
            stepUpload.classList.add('completed');
            stepProcessing.classList.add('active');
            processingStatusText.textContent = 'Processando conteúdo...';
            
            const response = await fetch(`${API_BASE}/admin/upload-file`, {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (response.ok) {
                // Etapa 3: Banco de dados
                stepProcessing.classList.remove('active');
                stepProcessing.classList.add('completed');
                stepDatabase.classList.add('active');
                processingStatusText.textContent = 'Salvando no banco...';
                
                // Se temos file_id, fazemos polling do progresso real
                if (result.data && result.data.file_id) {
                    const fileId = result.data.file_id;
                    await pollUploadProgress(fileId, currentProgress, totalArticles, processingStatusText);
                } else {
                    // Fallback para progresso simulado
                    if (result.data && result.data.artigos_processados) {
                        const totalArtigos = result.data.artigos_processados;
                        totalArticles.textContent = totalArtigos;
                        
                        // Simular progresso dos artigos
                        for (let artigo = 1; artigo <= totalArtigos; artigo++) {
                            currentProgress.textContent = artigo;
                            processingStatusText.textContent = `Processando artigo ${artigo}/${totalArtigos}...`;
                            await new Promise(resolve => setTimeout(resolve, 50));
                        }
                    }
                }
                
                // Etapa 4: Concluído
                stepDatabase.classList.remove('active');
                stepDatabase.classList.add('completed');
                stepComplete.classList.add('active');
                processingStatusText.textContent = 'Concluído com sucesso!';
                processingStatusText.className = 'success';
                
                results.push({
                    filename: file.name,
                    status: 'success',
                    message: result.message,
                    data: result.data
                });
                processedFiles++;
                
                // Aguardar um pouco para mostrar a conclusão
                await new Promise(resolve => setTimeout(resolve, 1000));
                
            } else {
                // Em caso de erro
                stepProcessing.classList.remove('active');
                processingStatusText.textContent = 'Erro no processamento';
                processingStatusText.className = 'error';
                
                results.push({
                    filename: file.name,
                    status: 'error',
                    message: result.detail || 'Erro desconhecido'
                });
            }
        } catch (error) {
            // Em caso de erro de conexão
            stepProcessing.classList.remove('active');
            processingStatusText.textContent = 'Erro de conexão';
            processingStatusText.className = 'error';
            
            results.push({
                filename: file.name,
                status: 'error',
                message: `Erro de conexão: ${error.message}`
            });
        }
    }
    
    // Hide progress and show results
    uploadProgress.style.display = 'none';
    uploadResults.style.display = 'block';
    
    // Display results
    const resultsContent = document.getElementById('upload-results-content');
    let resultsHtml = '';
    
    results.forEach(result => {
        const statusClass = result.status === 'success' ? 'success' : 'error';
        const statusIcon = result.status === 'success' ? '✅' : '❌';
        
        resultsHtml += `
            <div class="upload-result-item ${statusClass}">
                <strong>${statusIcon} ${result.filename}</strong><br>
                <span>${result.message}</span>
                ${result.data ? `<br><small>Artigos processados: ${result.data.artigos_processados || 0}</small>` : ''}
            </div>
        `;
    });
    
    resultsContent.innerHTML = resultsHtml;
    
    // Update status
    const successCount = results.filter(r => r.status === 'success').length;
    const errorCount = results.filter(r => r.status === 'error').length;
    
    if (successCount === totalFiles) {
        uploadStatus.innerHTML = `<div class="success">✅ Todos os ${totalFiles} arquivos foram processados com sucesso!</div>`;
    } else if (errorCount === totalFiles) {
        uploadStatus.innerHTML = `<div class="error">❌ Erro ao processar todos os ${totalFiles} arquivos.</div>`;
    } else {
        uploadStatus.innerHTML = `<div class="info">⚠️ ${successCount} arquivos processados com sucesso, ${errorCount} com erro.</div>`;
    }
    
    // Reset file input
    event.target.value = '';
}

async function pollUploadProgress(fileId, currentProgressElement, totalArticlesElement, statusElement) {
    const maxAttempts = 300; // 5 minutos (300 * 1 segundo)
    let attempts = 0;
    
    while (attempts < maxAttempts) {
        try {
            const response = await fetch(`${API_BASE}/admin/upload-progress/${fileId}`);
            
            if (response.ok) {
                const progress = await response.json();
                
                // Atualiza elementos do progresso
                const cur = progress.current_article || 0;
                const tot = progress.total_articles || 0;
                currentProgressElement.textContent = cur;
                totalArticlesElement.textContent = tot;
                statusElement.textContent = progress.message || 'Processando...';

                // Atualiza barra de progresso principal da seção de upload
                const uploadProgressFill = document.querySelector('#upload-progress .progress-fill');
                const uploadProgressText = document.querySelector('#upload-progress .progress-text');
                if (uploadProgressFill && tot > 0) {
                    const pct = Math.min(100, Math.round((cur / tot) * 100));
                    uploadProgressFill.style.width = pct + '%';
                    if (uploadProgressText) {
                        uploadProgressText.textContent = `Processando arquivos... ${cur}/${tot} (${pct}%)`;
                    }
                }
                
                // Atualiza classe de status
                if (progress.status === 'completed') {
                    statusElement.className = 'success';
                    break;
                } else if (progress.status === 'error') {
                    statusElement.className = 'error';
                    break;
                } else {
                    statusElement.className = 'processing';
                }
                
            } else {
                console.warn('Erro ao obter progresso:', response.status);
            }
            
        } catch (error) {
            console.warn('Erro ao fazer polling do progresso:', error);
        }
        
        attempts++;
        await new Promise(resolve => setTimeout(resolve, 1000)); // Poll a cada 1 segundo
    }
    
    if (attempts >= maxAttempts) {
        statusElement.textContent = 'Timeout - Verifique o status manualmente';
        statusElement.className = 'error';
    }
}

async function handleProcessArticles() {
    const processingStatus = document.getElementById('processing-status');
    const processingProgress = document.getElementById('processing-progress');
    const processArticlesBtn = document.getElementById('process-articles-btn');
    const progressFill = document.querySelector('#processing-progress .progress-fill');
    const progressText = document.querySelector('#processing-progress .progress-text');
    
    // Disable button and show progress
    processArticlesBtn.disabled = true;
    processArticlesBtn.textContent = '🔄 Processando...';
    processingStatus.innerHTML = '';
    processingProgress.style.display = 'block';
    
    try {
        // Start processing
        const response = await fetch(`${API_BASE}/admin/process-articles`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            processingStatus.innerHTML = `<div class="success">✅ Processamento iniciado com sucesso!</div>`;
            progressText.textContent = 'Processamento em andamento...';
            
            // Poll for status
            await pollProcessingStatus();
        } else {
            processingStatus.innerHTML = `<div class="error">❌ Erro ao iniciar processamento: ${result.detail}</div>`;
        }
    } catch (error) {
        processingStatus.innerHTML = `<div class="error">❌ Erro de conexão: ${error.message}</div>`;
    } finally {
        // Re-enable button
        processArticlesBtn.disabled = false;
        processArticlesBtn.textContent = '🔄 Processar Artigos Pendentes';
        processingProgress.style.display = 'none';
    }
}

async function pollProcessingStatus() {
    const processingStatus = document.getElementById('processing-status');
    const progressText = document.querySelector('#processing-progress .progress-text');
    const progressFill = document.querySelector('#processing-progress .progress-fill');
    
    let attempts = 0;
    const maxAttempts = 600; // até 10 minutos
    
    while (attempts < maxAttempts) {
        try {
            const response = await fetch(`${API_BASE}/admin/processing-status`);
            const result = await response.json();
            
            if (response.ok) {
                if (result.status === 'completed') {
                    processingStatus.innerHTML = `<div class="success">✅ Processamento concluído! ${result.message}</div>`;
                    return;
                } else if (result.status === 'error') {
                    processingStatus.innerHTML = `<div class="error">❌ Erro no processamento: ${result.message}</div>`;
                    return;
                } else {
                    // Atualiza barra de progresso com ETA
                    const total = result.data?.total || 0;
                    const processed = result.data?.processed || 0;
                    const eta = result.data?.eta_seconds;
                    const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
                    if (progressFill) progressFill.style.width = pct + '%';
                    const etaStr = (eta || eta === 0) ? ` | ETA: ~${Math.ceil(eta)}s` : '';
                    progressText.textContent = `Processando artigos... ${processed}/${total} (${pct}%)${etaStr}`;
                    await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2 seconds
                }
            }
        } catch (error) {
            console.error('Erro ao verificar status:', error);
        }
        
        attempts++;
    }
    
    processingStatus.innerHTML = `<div class="info">⚠️ Timeout - Verifique o status manualmente</div>`;
} 

// =======================================
// PROMPTS CRUD FUNCTIONS
// =======================================

// Funções para Tags
let editingTagId = null;

function showAddTagModal() {
    editingTagId = null;
    document.getElementById('tag-modal-title').textContent = 'Adicionar Nova Tag';
    document.getElementById('tagForm').reset();
    document.getElementById('tagModal').style.display = 'block';
}

function editPromptTag(tagId) {
    editingTagId = tagId;
    document.getElementById('tag-modal-title').textContent = 'Editar Tag';
    
    // Busca os dados da tag para preencher o formulário
    fetch(`/api/prompts/tags/${tagId}`)
        .then(response => response.json())
        .then(tag => {
            document.getElementById('tag-nome').value = tag.nome;
            document.getElementById('tag-descricao').value = tag.descricao;
            document.getElementById('tag-exemplos').value = tag.exemplos ? tag.exemplos.join('\n') : '';
            document.getElementById('tag-ordem').value = tag.ordem || 0;
            document.getElementById('tagModal').style.display = 'block';
        })
        .catch(error => {
            console.error('Erro ao carregar tag:', error);
            alert('Erro ao carregar dados da tag');
        });
}

function closeTagModal() {
    document.getElementById('tagModal').style.display = 'none';
    editingTagId = null;
}

async function deletePromptTag(tagId) {
    if (!confirm('Tem certeza que deseja excluir esta tag? Esta ação não pode ser desfeita.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/prompts/tags/${tagId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSuccessMessage('tags', 'Tag excluída com sucesso!');
            loadPromptTags(); // Recarrega a lista
        } else {
            throw new Error('Falha ao excluir tag');
        }
    } catch (error) {
        console.error('Erro ao excluir tag:', error);
        showErrorMessage('tags', 'Erro ao excluir tag: ' + error.message);
    }
}

// Funções para Prioridades
let editingPrioridadeId = null;

function showAddPrioridadeModal() {
    editingPrioridadeId = null;
    document.getElementById('prioridade-modal-title').textContent = 'Adicionar Novo Item de Prioridade';
    document.getElementById('prioridadeForm').reset();
    document.getElementById('prioridadeModal').style.display = 'block';
}

function editPromptPrioridade(prioridadeId) {
    editingPrioridadeId = prioridadeId;
    document.getElementById('prioridade-modal-title').textContent = 'Editar Item de Prioridade';
    
            // Busca os dados da prioridade para preencher o formulário
        fetch(`/api/prompts/prioridades/${prioridadeId}`)
            .then(response => response.json())
            .then(prioridade => {
                document.getElementById('prioridade-nivel').value = prioridade.nivel;
                document.getElementById('prioridade-item').value = prioridade.texto;
                document.getElementById('prioridade-ordem').value = prioridade.ordem || 0;
                document.getElementById('prioridadeModal').style.display = 'block';
            })
        .catch(error => {
            console.error('Erro ao carregar prioridade:', error);
            alert('Erro ao carregar dados da prioridade');
        });
}

function closePrioridadeModal() {
    document.getElementById('prioridadeModal').style.display = 'none';
    editingPrioridadeId = null;
}

async function deletePromptPrioridade(prioridadeId) {
    if (!confirm('Tem certeza que deseja excluir este item de prioridade? Esta ação não pode ser desfeita.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/prompts/prioridades/${prioridadeId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showSuccessMessage('prioridades', 'Item de prioridade excluído com sucesso!');
            loadPromptPrioridades(); // Recarrega a lista
        } else {
            throw new Error('Falha ao excluir item de prioridade');
        }
    } catch (error) {
        console.error('Erro ao excluir prioridade:', error);
        showErrorMessage('prioridades', 'Erro ao excluir item de prioridade: ' + error.message);
    }
}

// Funções para salvar prompts
async function salvarPromptResumo() {
    const conteudo = document.getElementById('prompt-resumo').value;
    
    try {
        const response = await fetch('/api/prompts/templates/resumo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conteudo })
        });
        
        if (response.ok) {
            alert('Prompt de resumo salvo com sucesso!');
        } else {
            throw new Error('Falha ao salvar prompt');
        }
    } catch (error) {
        console.error('Erro ao salvar prompt de resumo:', error);
        alert('Erro ao salvar prompt: ' + error.message);
    }
}

async function salvarOutrosPrompts() {
    const relevancia = document.getElementById('prompt-relevancia').value;
    const extracao = document.getElementById('prompt-extracao').value;
    
    try {
        // Salva prompt de relevância
        const responseRelevancia = await fetch('/api/prompts/templates/relevancia', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conteudo: relevancia })
        });
        
        // Salva prompt de extração
        const responseExtracao = await fetch('/api/prompts/templates/extracao', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conteudo: extracao })
        });
        
        if (responseRelevancia.ok && responseExtracao.ok) {
            alert('Prompts salvos com sucesso!');
        } else {
            throw new Error('Falha ao salvar alguns prompts');
        }
    } catch (error) {
        console.error('Erro ao salvar prompts:', error);
        alert('Erro ao salvar prompts: ' + error.message);
    }
}

// Event listeners para formulários
document.addEventListener('DOMContentLoaded', function() {
    // Form de tag
    document.getElementById('tagForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const formData = {
            nome: document.getElementById('tag-nome').value,
            descricao: document.getElementById('tag-descricao').value,
            exemplos: document.getElementById('tag-exemplos').value.split('\n').filter(line => line.trim()),
            ordem: parseInt(document.getElementById('tag-ordem').value) || 0
        };
        
        try {
            const url = editingTagId ? `/api/prompts/tags/${editingTagId}` : '/api/prompts/tags';
            const method = editingTagId ? 'PUT' : 'POST';
            
            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            
            if (response.ok) {
                closeTagModal();
                showSuccessMessage('tags', editingTagId ? 'Tag atualizada com sucesso!' : 'Tag criada com sucesso!');
                loadPromptTags();
            } else {
                throw new Error('Falha ao salvar tag');
            }
        } catch (error) {
            console.error('Erro ao salvar tag:', error);
            showErrorMessage('tags', 'Erro ao salvar tag: ' + error.message);
        }
    });
    
    // Form de prioridade
    document.getElementById('prioridadeForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const formData = {
            nivel: document.getElementById('prioridade-nivel').value,
            texto: document.getElementById('prioridade-item').value,
            ordem: parseInt(document.getElementById('prioridade-ordem').value) || 0
        };
        
        try {
            const url = editingPrioridadeId ? `/api/prompts/prioridades/${editingPrioridadeId}` : '/api/prompts/prioridades';
            const method = editingPrioridadeId ? 'PUT' : 'POST';
            
            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(formData)
            });
            
            if (response.ok) {
                closePrioridadeModal();
                showSuccessMessage('prioridades', editingPrioridadeId ? 'Item de prioridade atualizado com sucesso!' : 'Item de prioridade criado com sucesso!');
                loadPromptPrioridades();
            } else {
                throw new Error('Falha ao salvar item de prioridade');
            }
        } catch (error) {
            console.error('Erro ao salvar prioridade:', error);
            showErrorMessage('prioridades', 'Erro ao salvar item de prioridade: ' + error.message);
        }
    });
});

// Funções auxiliares para mensagens
function showSuccessMessage(tab, message) {
    const successEl = document.getElementById(`${tab}-success`);
    if (successEl) {
        successEl.textContent = message;
        successEl.style.display = 'block';
        setTimeout(() => successEl.style.display = 'none', 5000);
    }
}

function showErrorMessage(tab, message) {
    const errorEl = document.getElementById(`${tab}-error`);
    if (errorEl) {
        errorEl.textContent = message;
        errorEl.style.display = 'block';
        setTimeout(() => errorEl.style.display = 'none', 5000);
    }
} 