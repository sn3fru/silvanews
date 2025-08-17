# Migração de Prompts para Banco de Dados

## Resumo das Mudanças

Este documento descreve as mudanças implementadas para migrar as configurações de prompts (tags, prioridades e templates) do arquivo `backend/prompts.py` para o banco de dados PostgreSQL, mantendo total compatibilidade com o código existente.

## Problema Resolvido

**Antes**: As configurações de tags e prioridades estavam hardcoded no arquivo `backend/prompts.py`, causando perda de dados quando a aplicação era redeployada no Heroku.

**Depois**: As configurações são armazenadas no banco de dados PostgreSQL, permitindo edições persistentes em produção via interface web.

## Arquitetura Implementada

### 1. Novas Tabelas no Banco

```sql
-- Tabela para tags temáticas
CREATE TABLE prompt_tags (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(120) UNIQUE NOT NULL,
    descricao TEXT NOT NULL,
    exemplos JSONB DEFAULT '[]',
    ordem INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Tabela para itens de prioridade
CREATE TABLE prompt_prioridade_itens (
    id SERIAL PRIMARY KEY,
    nivel VARCHAR(50) NOT NULL, -- P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO
    item VARCHAR(200) NOT NULL,
    descricao TEXT NOT NULL,
    ordem INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Tabela para templates de prompts
CREATE TABLE prompt_templates (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(100) UNIQUE NOT NULL,
    descricao TEXT,
    conteudo TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
```

### 2. Modificações no Backend

#### `backend/database.py`
- Adicionadas as novas classes de modelo: `PromptTag`, `PromptPrioridadeItem`, `PromptTemplate`

#### `backend/crud.py`
- Novas funções CRUD para gerenciar prompts
- Função `get_prompts_compilados()` que retorna estruturas idênticas às variáveis originais

#### `backend/prompts.py`
- **Mantida compatibilidade total**: As variáveis `TAGS_SPECIAL_SITUATIONS`, `P1_ITENS`, `P2_ITENS`, `P3_ITENS` continuam funcionando exatamente como antes
- **Carregamento automático**: No import, o sistema tenta carregar do banco e fallback para os valores hardcoded se necessário
- **Transparência**: O código downstream não precisa saber que os dados vêm do banco

#### `backend/main.py`
- Novos endpoints REST para gerenciar prompts:
  - `GET/POST/PUT/DELETE /api/prompts/tags`
  - `GET/POST/PUT/DELETE /api/prompts/prioridades`
  - `GET/POST/DELETE /api/prompts/templates/{nome}`

### 3. Modificações no Frontend

#### `frontend/settings.html`
- Nova aba "Prompts" com 4 sub-tabs:
  - **Tags**: Edição visual de tags temáticas
  - **Prioridades**: Edição de itens por nível de prioridade
  - **Resumo/Clusterizador**: Edição do prompt principal
  - **Outros Prompts**: Prompts adicionais (relevância, extração)

#### `frontend/settings.js`
- Funcionalidade completa de CRUD para tags e prioridades
- Interface intuitiva para adicionar, editar e excluir itens
- Modais responsivos para edição

### 4. Sistema de Migração

#### `migrate_incremental.py`
- Nova função `migrate_prompts()` para sincronizar prompts entre ambientes
- Opção `--include-prompts` para incluir prompts na migração incremental

#### `seed_prompts.py`
- Script para popular o banco com dados iniciais
- Extrai automaticamente os valores do `prompts.py` original

## Como Usar

### 1. Primeira Execução (Desenvolvimento)

```bash
# 1. Criar as tabelas (automático ao rodar o backend)
python start_dev.py

# 2. Popular com dados iniciais
python seed_prompts.py

# 3. Verificar no frontend
# Acesse /frontend/settings.html → aba "Prompts"
```

### 2. Edição via Frontend

1. Acesse `/frontend/settings.html`
2. Clique na aba "Prompts"
3. Use as sub-tabs para editar:
   - **Tags**: Adicione/edite tags temáticas com exemplos
   - **Prioridades**: Configure itens por nível de prioridade
   - **Prompts**: Edite templates de prompts

### 3. Migração para Produção

```bash
# Migração incremental incluindo prompts
python migrate_incremental.py \
  --source "postgresql://..." \
  --dest "postgres://..." \
  --include-prompts
```

## Compatibilidade e Fallback

### Sistema de Fallback
1. **Primeira prioridade**: Banco de dados PostgreSQL
2. **Segunda prioridade**: Valores hardcoded em `backend/prompts.py`
3. **Transparência**: O código existente não precisa ser modificado

### Estruturas Mantidas
```python
# Estas variáveis continuam funcionando exatamente como antes
TAGS_SPECIAL_SITUATIONS  # Dict com tags e exemplos
P1_ITENS                 # Lista de itens P1
P2_ITENS                 # Lista de itens P2  
P3_ITENS                 # Lista de itens P3

# Funções continuam funcionando
gerar_guia_tags_formatado()
gerar_guia_prioridades_formatado()
```

## Benefícios da Implementação

### ✅ Vantagens
- **Persistência**: Edições em produção não são perdidas
- **Interface Visual**: Edição intuitiva via web
- **Versionamento**: Histórico de mudanças no banco
- **Compatibilidade**: Zero impacto no código existente
- **Flexibilidade**: Fácil adição/remoção de tags e prioridades
- **Migração**: Sincronização automática entre ambientes

### ⚠️ Considerações
- **Dependência do Banco**: Sistema requer PostgreSQL funcionando
- **Fallback**: Em caso de falha do banco, usa valores hardcoded
- **Migração**: Necessário executar `seed_prompts.py` após criar tabelas

## Troubleshooting

### Problema: "Tabela não existe"
```bash
# Solução: Criar tabelas
python start_dev.py
```

### Problema: "Dados não carregam"
```bash
# Solução: Popular banco
python seed_prompts.py
```

### Problema: "Erro de conexão com banco"
- Verificar se PostgreSQL está rodando
- Verificar variável `DATABASE_URL` no `.env`
- Sistema automaticamente fallback para valores hardcoded

## Próximos Passos

### Funcionalidades Futuras
- **Histórico de Mudanças**: Log de quem editou o quê e quando
- **Validação**: Regras de negócio para evitar configurações inválidas
- **Backup/Restore**: Exportação/importação de configurações
- **Auditoria**: Rastreamento de mudanças para compliance

### Melhorias Técnicas
- **Cache**: Cache Redis para prompts frequentemente acessados
- **Validação**: Schemas JSON para validação de configurações
- **API**: Endpoints para integração com sistemas externos

## Conclusão

A migração foi implementada com foco total na **compatibilidade** e **transparência**. O sistema existente continua funcionando exatamente como antes, mas agora com a flexibilidade de editar configurações via interface web e persistir mudanças no banco de dados.

A implementação segue o princípio de **zero breaking changes** e oferece um upgrade significativo na usabilidade e robustez do sistema.
