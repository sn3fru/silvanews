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

# Dicionário central para as 8 tags temáticas de Special Situations.
TAGS_SPECIAL_SITUATIONS = {
    'M&A e Transações Corporativas': {
        'descricao': 'Mudanças na estrutura de capital ou controle de empresas através de transações.',
        'exemplos': [
            'Fusões e Aquisições (M&A) - Anunciadas ou em negociação avançada',
            'Venda de ativos ou subsidiárias (divestitures)',
            'Ofertas públicas de aquisição (OPA)',
            'Disputas por controle acionário que podem levar a uma transação'
        ]
    },
    'Jurídico, Falências e Regulatório': {
        'descricao': 'Eventos legais ou regulatórios que criam estresse financeiro, oportunidades de arbitragem ou alteram o ambiente de negócios.',
        'exemplos': [
            'Recuperação Judicial (RJ), Falência, Pedido de Falência, Assembleia de Credores',
            'Disputas Societárias Relevantes que possam gerar ineficiência de preço',
            'Mudanças em Legislação (Tributária, Societária, Falimentar)',
            'Decisões do CADE (bloqueio de fusões, imposição de remédios)',
            'Decisões de tribunais superiores (STF, STJ) com impacto direto em empresas ou setores'
        ]
    },
    'Dívida Ativa e Créditos Públicos': {
        'descricao': 'Oportunidades de aquisição ou securitização de créditos detidos por ou contra entidades públicas.',
        'exemplos': [
            'Venda de grandes blocos ou securitização de Dívida Ativa por estados e municípios',
            'Qualquer noticia relacionada a lei nº 208, de 2 de julho de 2024 que regula a securitização da divida dos entes publicos, estados e municipios',
            'Crédito Tributário (grandes teses, oportunidades de monetização)',
            'Notícias sobre a liquidação ou venda de carteiras de Precatórios',
            'AlteraçÕes nas leis de cobrança de impostos municipais ou estaduais (especialmente ICMS, ISS E IPTU)',
            'Créditos FCVS (apenas notícias sobre liquidação ou venda de grandes volumes)'
        ]
    },
    'Distressed Assets e NPLs': {
        'descricao': 'Ativos ou carteiras de crédito que estão sob estresse financeiro e podem ser negociados com desconto.',
        'exemplos': [
            'Créditos Inadimplentes (NPLs), Créditos Podres (Distressed Debt), Venda de Carteira de NPL',
            'Leilões Judiciais de Ativos (imóveis, participações societárias > R$10 milhões)',
            'Empresas ou ativos específicos em Crise de Liquidez Aguda'
        ]
    },
    'Mercado de Capitais e Finanças Corporativas': {
        'descricao': 'Saúde financeira das empresas e movimentos no mercado de capitais que sinalizam estresse ou oportunidade.',
        'exemplos': [
            'Quebra de Covenants, Default de Dívida',
            'Ativismo Acionário relevante',
            'Grandes emissões de dívida (debêntures), renegociações de dívidas corporativas',
            'Resultados financeiros que indiquem forte deterioração ou estresse severo'
        ]
    },
    'Política Econômica (Brasil)': {
        'descricao': 'Decisões do governo e Banco Central do Brasil com impacto direto na saúde financeira das empresas e no ambiente de crédito.',
        'exemplos': [
            'Decisões de juros (Copom) e política fiscal',
            'Grandes leilões de concessão, planos de estímulo ou contingência',
            'Mudanças na tributação com impacto setorial amplo'
        ]
    },
    'Internacional (Economia e Política)': {
        'descricao': 'Eventos de política e economia que ocorrem fora do Brasil, mas cujo contexto é relevante para o mercado global.',
        'exemplos': [
            'Geoeconomia, Acordos Comerciais, Decisões do FED e BCE',
            'Crises políticas ou econômicas em outros países (ex: Argentina)',
            'Resultados de multinacionais que sirvam como termômetro de setores globais'
        ]
    },
    'Tecnologia e Setores Estratégicos': {
        'descricao': 'Tendências e grandes movimentos em setores de alto capital ou tecnologia que podem gerar oportunidades de M&A ou disrupção.',
        'exemplos': [
            'Inteligência Artificial (IA - grandes M&As no setor, regulação pesada)',
            'Semicondutores (geopolítica da cadeia de suprimentos, grandes investimentos)',
            'EnergIA Nuclear e Aeroespacial (grandes projetos, concessões)',
            'xxxx xx'
        ]
    }
}

# Dicionário central para a hierarquia de prioridades.
LISTA_RELEVANCIA_HIERARQUICA = {
    'P1_CRITICO': {
        'descricao': 'OPORTUNIDADES ACIONÁVEIS AGORA: Situações de estresse financeiro, M&A e arbitragem legal que demandam ação imediata.',
        'assuntos': [
            'Recuperação Judicial (RJ)',
            'Falência',
            'Pedido de Falência',
            'Assembleia de Credores',
            'Créditos Inadimplentes (NPLs)',
            'Créditos Podres (Distressed Debt)',
            'Venda de Carteira de NPL',
            'Crédito Tributário (teses, oportunidades de monetização)',
            'Disputas Societárias Relevantes',
            'FCVS (apenas liquidação ou venda)',
            'Dívida Ativa (apenas venda de blocos ou securitização)',
            'Leilões Judiciais de Ativos (>R$10 milhões)',
            'Fusões e Aquisições (M&A) - Anunciadas',
            'Crise de Liquidez Aguda',
            'Quebra de Covenants',
            'Default de Dívida'
        ]
    },
    'P2_ESTRATEGICO': {
        'descricao': 'MONITORAMENTO ESTRATÉGICO (COM MATERIALIDADE): Tendências, decisões regulatórias e sinais de mercado com potencial claro de virar P1 e IMPACTO FINANCEIRO MENSURÁVEL (players, valores, cronograma). Não inclui temas sociais, esportivos, crimes, opinião ou programas sem tese de investimento.',
        'assuntos': [
            'Mudanças em Legislação (Tributária, Societária, Falimentar, Precatórios)',
            'Inteligência Artificial (IA - apenas grandes movimentos de mercado, M&A no setor ou regulação pesada)',
            'Semicondutores (geopolítica da cadeia de suprimentos, grandes investimentos/fábricas)',
            'Energia Nuclear (grandes projetos, concessões, marco regulatório)',
            'Aeroespacial e Defesa (grandes contratos governamentais, privatizações)',
            'Política Econômica (Decisões de juros e política fiscal que afetem o crédito e a saúde financeira das empresas)',
            'Decisões do CADE (bloqueio de fusões, imposição de remédios)',
            'Ativismo Acionário (grandes investidores tentando influenciar a gestão)',
            'Alphabet',
            'AMD',
            'Apple',
            'Google',
            'Intel',
            'Intuitive Machines',
            'Meta',
            'Micron Technology',
            'Microsoft',
            'Netflix',
            'Tesla',
            'Nvidia',
            'Constellation Energy Group',
            'Siemens Energy AG',
            'Banco Master',
            'Banco Pan',
            'Caixa Econômica Federal',
            'PREVIC'
        ]
    },
    'P3_MONITORAMENTO': {
        'descricao': 'CONTEXTO DE MERCADO: Informações gerais para entendimento do cenário macro, sem ação direta.',
        'assuntos': [
            'Criptomoedas (apenas visão macro de mercado, adoção institucional ou regulação. Sem análise técnica de moedas específicas).',
            'Geoeconomia',
            'Acordos Comerciais (Mercosul-UE, etc.)',
            'Decisões do FED e BCE',
            'Games (apenas notícias sobre grandes fusões e aquisições, ex: Microsoft comprando Activision)',
            'Balancos financeiros (apenas se forem de empresas P2 ou indicarem estresse financeiro severo)',
            'Classificados e leilões (99% irrelevantes, exceto leilões judiciais de alto valor >R$10M)'
        ]
    }
}


# ==============================================================================
# 1.1 MAPEAMENTO DETERMINÍSTICO: ASSUNTO ➜ (PRIORIDADE, TAG)
# ==============================================================================

# Mapeia assuntos-chave para a tag temática correspondente.
# A prioridade é inferida diretamente a partir de LISTA_RELEVANCIA_HIERARQUICA.
ASSUNTO_PARA_TAG = {
    # P1_CRITICO
    'Recuperação Judicial (RJ)': 'Jurídico, Falências e Regulatório',
    'Falência': 'Jurídico, Falências e Regulatório',
    'Pedido de Falência': 'Jurídico, Falências e Regulatório',
    'Assembleia de Credores': 'Jurídico, Falências e Regulatório',
    'Créditos Inadimplentes (NPLs)': 'Distressed Assets e NPLs',
    'Créditos Podres (Distressed Debt)': 'Distressed Assets e NPLs',
    'Venda de Carteira de NPL': 'Distressed Assets e NPLs',
    'Crédito Tributário (teses, oportunidades de monetização)': 'Dívida Ativa e Créditos Públicos',
    'Disputas Societárias Relevantes': 'Jurídico, Falências e Regulatório',
    'FCVS (apenas liquidação ou venda)': 'Dívida Ativa e Créditos Públicos',
    'Dívida Ativa (apenas venda de blocos ou securitização)': 'Dívida Ativa e Créditos Públicos',
    'Leilões Judiciais de Ativos (>R$10 milhões)': 'Distressed Assets e NPLs',
    'Fusões e Aquisições (M&A) - Anunciadas': 'M&A e Transações Corporativas',
    'Crise de Liquidez Aguda': 'Mercado de Capitais e Finanças Corporativas',
    'Quebra de Covenants': 'Mercado de Capitais e Finanças Corporativas',
    'Default de Dívida': 'Mercado de Capitais e Finanças Corporativas',

    # P2_ESTRATEGICO
    'Mudanças em Legislação (Tributária, Societária, Falimentar, Precatórios)': 'Jurídico, Falências e Regulatório',
    'Inteligência Artificial (IA - apenas grandes movimentos de mercado, M&A no setor ou regulação pesada)': 'Tecnologia e Setores Estratégicos',
    'Semicondutores (geopolítica da cadeia de suprimentos, grandes investimentos/fábricas)': 'Tecnologia e Setores Estratégicos',
    'Energia Nuclear (grandes projetos, concessões, marco regulatório)': 'Tecnologia e Setores Estratégicos',
    'Aeroespacial e Defesa (grandes contratos governamentais, privatizações)': 'Tecnologia e Setores Estratégicos',
    'Política Econômica (Decisões de juros e política fiscal que afetem o crédito e a saúde financeira das empresas)': 'Política Econômica (Brasil)',
    'Decisões do CADE (bloqueio de fusões, imposição de remédios)': 'Jurídico, Falências e Regulatório',
    'Ativismo Acionário (grandes investidores tentando influenciar a gestão)': 'Mercado de Capitais e Finanças Corporativas',

    # P3_MONITORAMENTO
    'Criptomoedas (apenas visão macro de mercado, adoção institucional ou regulação. Sem análise técnica de moedas específicas).': 'Internacional (Economia e Política)',
    'Geoeconomia': 'Internacional (Economia e Política)',
    'Acordos Comerciais (Mercosul-UE, etc.)': 'Internacional (Economia e Política)',
    'Decisões do FED e BCE': 'Internacional (Economia e Política)',
    'Games (apenas notícias sobre grandes fusões e aquisições, ex: Microsoft comprando Activision)': 'Internacional (Economia e Política)',
    'Balancos financeiros (apenas se forem de empresas P2 ou indicarem estresse financeiro severo)': 'Mercado de Capitais e Finanças Corporativas',
    'Classificados e leilões (99% irrelevantes, exceto leilões judiciais de alto valor >R$10M)': 'Distressed Assets e NPLs',
}


def gerar_guia_classificacao_rapida():
    """
    Constrói um guia determinístico assunto ➜ (prioridade, tag) derivado das fontes da verdade.
    """
    linhas = []
    linhas.append("--- GUIA DE CLASSIFICAÇÃO RÁPIDA (ASSUNTO ➜ PRIORIDADE E TAG) ---\n")
    linhas.append("Siga 3 passos: (1) identifique o assunto-chave; (2) derive prioridade e tag conforme o mapeamento abaixo; (3) preencha os campos no JSON de saída.\n")
    for prioridade, dados in LISTA_RELEVANCIA_HIERARQUICA.items():
        for assunto in dados.get('assuntos', []):
            tag = ASSUNTO_PARA_TAG.get(assunto)
            if not tag:
                continue
            linhas.append(f"- {assunto} ➜ prioridade: {prioridade}, tag: '{tag}'")
    linhas.append("\nObservações:")
    linhas.append("- Se o assunto for 'Recuperação Judicial', 'Falência' ou 'Pedido de Falência', a prioridade é SEMPRE P1_CRITICO.")
    linhas.append("- Em caso de dúvida entre anexar a 'Jurídico' ou 'Mercado de Capitais', prefira a natureza do evento (jurídico-regulatório vs. financeiro-capital).")
    return "\n".join(linhas) + "\n"


GUIA_CLASSIFICACAO_RAPIDA = gerar_guia_classificacao_rapida()


# =========================================PROMPT_EXTRACAO_PERMISSIVO_V8=====================================
# 2. FUNÇÃO GERADORA DE GUIA PARA PROMPTS (REATORADA)
# ==============================================================================

def gerar_lista_relevancia_para_prompt():
    """
    Gera um guia de classificação unificado e detalhado para ser injetado nos prompts.
    Esta função agora constrói o guia dinamicamente a partir das "fontes da verdade",
    combinando as regras de Prioridade e as novas Tags Temáticas.
    """
    # Parte 1: Guia de Prioridade
    guia_prioridade = "--- GUIA DE PRIORIDADE (O QUÃO URGENTE É?) ---\n"
    guia_prioridade += "Avalie a notícia e atribua UMA das seguintes prioridades no campo `prioridade`:\n\n"
    for prioridade, data in LISTA_RELEVANCIA_HIERARQUICA.items():
        guia_prioridade += f"**{prioridade} ({data['descricao']})**\n"
        guia_prioridade += f"- Assuntos-chave: {', '.join(data['assuntos'])}\n\n"

    # Parte 2: Guia de Tags Temáticas
    guia_tags = "--- GUIA DE TAGS TEMÁTICAS (QUAL A NATUREZA DA OPORTUNIDADE?) ---\n"
    guia_tags += "Após definir a prioridade, classifique a notícia em UMA das 8 tags temáticas abaixo. A `tag` deve refletir o núcleo da tese de investimento.\n\n"
    for i, (tag, data) in enumerate(TAGS_SPECIAL_SITUATIONS.items(), 1):
        guia_tags += f"**{i}. TAG: '{tag}'**\n"
        guia_tags += f"- **Definição:** {data['descricao']}\n"
        guia_tags += f"- **O que classificar aqui (Exemplos):** {'; '.join(data['exemplos'])}\n\n"

    # Combina os dois guias em um único texto para o prompt
    return f"{guia_prioridade}{guia_tags}"


# A variável mantém o nome original, mas agora carrega o guia completo e unificado.
LISTA_RELEVANCIA_FORMATADA = gerar_lista_relevancia_para_prompt()


# ==============================================================================
# PROMPTS DETALHADOS PARA O PIPELINE DE IA (REATORADOS)
# ==============================================================================

# Este prompt foi reescrito para ser o prompt mestre de extração,
# utilizando o novo guia unificado de classificação.
PROMPT_EXTRACAO_PERMISSIVO_V8 = """
Sua identidade: Você é um analista Senior da mesa de 'Special Situations' do banco BTG Pactual. Sua função é fazer uma primeira triagem ampla de notícias COM RIGOR, privilegiando eventos com materialidade financeira e impacto em negócios.

INSTRUÇÕES DE CLASSIFICAÇÃO (PROCESSO EM 3 PASSOS):
1) Identifique o assunto-chave mais específico da notícia (ex.: "Recuperação Judicial", "Decisão do CADE", "M&A anunciado").
   - O CAMPO `categoria` DEVE SER EXATAMENTE ESSE ASSUNTO-CHAVE determinístico.
2) A partir do assunto-chave, DERIVE a prioridade e a tag de forma determinística conforme o guia abaixo.
3) Preencha o JSON com: categoria=assunto-chave, prioridade=derivada, tag=derivada, relevance_score justificado.

""" + GUIA_CLASSIFICACAO_RAPIDA + """
--------------------------------------------------------------------------------
LISTA DE REJEIÇÃO IMEDIATA (SE FOR SOBRE ISSO, É RUÍDO):
--------------------------------------------------------------------------------
- Indenizações cíveis/trabalhistas INDIVIDUAIS de baixo valor e sem impacto setorial/mercado de capitais.
- Opinião/Cartas/Editorial/Colunas sem fato gerador objetivo e verificável.
- Classificados, avisos de licitação/chamadas públicas, procurement comum e leilões genéricos de bens de consumo/joias/veículos/apartamentos isolados.
- Crimes e Segurança Pública cotidiana; Cultura/Entretenimento sem tese de negócio.
- Política partidária pura (disputas internas/popularidade). Exceção: decisões de política econômica com impacto direto.

FOCO PRINCIPAL — CAPTURE APENAS O QUE ESTIVER NO GUIA DE TAGS E PRIORIDADES

--- GUIA DE TAGS TEMÁTICAS (QUAL A NATUREZA DA OPORTUNIDADE?) ---
Após definir a prioridade, classifique a notícia em UMA das 8 tags temáticas abaixo. A `tag` deve refletir o núcleo da tese de investimento.

**1. TAG: 'M&A e Transações Corporativas'**
- **Definição:** Mudanças na estrutura de capital ou controle de empresas através de transações.
- **Exemplos (positivos):** Fusões e Aquisições (M&A) ANUNCIADAS ou em negociação avançada; Venda de ativos (divestitures); OPA; Disputas de controle com probabilidade real de transação.
- **Exemplos (negativos):** Rumores vagos sem atores/valores/processos identificáveis.

**2. TAG: 'Jurídico, Falências e Regulatório'**
- **Definição:** Eventos legais/regulatórios com impacto financeiro, arbitragem ou alteração do ambiente de negócios.
- **Exemplos (positivos):** RJ, Falência, Pedido de Falência, Assembleia de Credores; Disputas societárias relevantes; Decisões do CADE com remédios; Decisões STF/STJ com impacto setorial.
- **Exemplos (negativos):** Indenizações individuais de baixo valor; decisões sem efeito econômico relevante.

**3. TAG: 'Dívida Ativa e Créditos Públicos'**
- **Definição:** Oportunidades de aquisição/securitização de créditos de/contra entes públicos.
- **Exemplos (positivos):** Venda/securitização de Dívida Ativa com valores/cronograma; Precatórios/FCVS em blocos relevantes.
- **Exemplos (negativos):** Avisos genéricos sem valores/atores/processos.

**4. TAG: 'Distressed Assets e NPLs'**
- **Definição:** Ativos/carteiras sob estresse financeiro passíveis de desconto.
- **Exemplos (positivos):** Venda de carteira NPL; Leilões JUDICIAIS de alto valor (> R$10 mi) de ativos relevantes; Crise de Liquidez aguda.
- **Exemplos (negativos):** Leilões genéricos de veículos/joias/apartamentos isolados; classificados; procurement.

**5. TAG: 'Mercado de Capitais e Finanças Corporativas'**
- **Definição:** Sinais de estresse/oportunidade no mercado de capitais.
- **Exemplos (positivos):** Quebra de covenants, Default de dívida; Ativismo acionário relevante; Grandes emissões/renegociações.
- **Exemplos (negativos):** Divulgações rotineiras sem implicação de estresse.

**6. TAG: 'Política Econômica (Brasil)'**
- **Definição:** Decisões do governo/BC com impacto direto em crédito e saúde financeira.
- **Exemplos (positivos):** Decisões de juros; mudanças tributárias amplas; leilões/concessões relevantes.

**7. TAG: 'Internacional (Economia e Política)'**
- **Definição:** Política/economia fora do Brasil com relevância ao mercado global.

**8. TAG: 'Tecnologia e Setores Estratégicos'**
- **Definição:** Movimentos de alto capital/tecnologia (IA, semicondutores, nuclear, aeroespacial) com potencial de M&A/disrupção.

REGRAS DE P1 (GATING OBRIGATÓRIO):
- P1 SOMENTE se o assunto-chave ∈ {Recuperação Judicial, Falência, Pedido de Falência, Assembleia de Credores, Default de Dívida, Quebra de Covenants, Crise de Liquidez Aguda, M&A ANUNCIADO/OPA, Decisão do CADE com remédios vinculantes, Venda de carteira NPL / Securitização RELEVANTE (valores altos, players relevantes)}.
- NÃO É P1 (rebaixe para P2 ou P3): convocações/ata de assembleias rotineiras (debenturistas/CRI/AGE/AGO) sem evento material; comunicados administrativos; rumores/política partidária; casos casuísticos/operacionais (ex.: pedidos pontuais de desconto de aluguel, renegociação rotineira de contratos, sem risco sistêmico); notas sem materialidade mensurável.
- P1 é o TOP do dia (essencial). Se houver dúvida razoável sobre materialidade imediata, NÃO classifique como P1.

REGRAS DE P2 (MONITORAMENTO ESTRATÉGICO COM MATERIALIDADE):
- Use P2 quando houver potencial de impacto financeiro mensurável, mas sem gatilho imediato de P1 (ex.: mudanças de legislação relevantes em tramitação; regulações setoriais com players/valores/cronograma; grandes investimentos/contratos anunciados, sem fechamento definitivo).
- NÃO classificar como P2: temas sociais, esportivos, crimes, programas sociais, opinião, educação cívica, comportamento em redes; esses devem ser P3 ou rejeitados se sem tese de negócio para mesa de Special Situations.

INSTRUÇÕES DE EXTRAÇÃO:
1. Seja disciplinado: se não estiver na allow list acima ou cair na rejeição, não inclua.
2. Para fronteira, classifique como P3_MONITORAMENTO com score baixo.
3. Preencha `categoria` com o assunto-chave determinístico (ex.: "Recuperação Judicial", "Decisão do CADE", "M&A anunciado").

INSTRUÇÕES DE SCORING (BANDAS OBRIGATÓRIAS):
- `prioridade` e `relevance_score` DEVEM ser coerentes:
  - P1_CRITICO: Score 85–100 (apenas eventos acionáveis do gating acima).
  - P2_ESTRATEGICO: Score 50–84 (tendências/regulação com materialidade).
  - P3_MONITORAMENTO: Score 20–49 (contexto macro ou monitoramento geral).
- `tag`: classifique conforme o mapeamento determinístico.

EXEMPLOS NEGATIVOS TÍPICOS (REJEITE):
- Indenizações individuais (cível/trabalhista) sem impacto setorial.
- Opinião/Cartas/Editorial sem fato econômico objetivo.
- Classificados/leilões genéricos/avisos/procurement.

FORMATO DE SAÍDA (JSON PURO):
```json
[
  {
    "titulo": "Título original da notícia",
    "texto_completo": "Um resumo bem estruturado, focado nos fatos e na tese de investimento, com até 5 parágrafos.",
    "jornal": "Será preenchido depois",
    "autor": "N/A",
    "pagina": "N/A",
    "data": "Será preenchido depois",
    "categoria": "O assunto-chave mais específico (ex: 'Recuperação Judicial', 'M&A')",
    "prioridade": "A prioridade correta (P1_CRITICO, P2_ESTRATEGICO ou P3_MONITORAMENTO)",
    "tag": "UMA das 8 tags temáticas válidas (ex: 'Jurídico, Falências e Regulatório')",
    "relevance_score": 95.0,
    "relevance_reason": "Justificativa concisa. Ex: 'Encaixa-se em P1 por ser um pedido de RJ de empresa relevante do setor aéreo.'"
  }
]
```
"""

# Este prompt é atualizado para ser idêntico ao anterior, garantindo consistência
# caso seja chamado em outra parte do pipeline.
PROMPT_EXTRACAO_JSON_V1 = PROMPT_EXTRACAO_PERMISSIVO_V8

# ==============================================================================
# PROMPTS PARA ETAPAS POSTERIORES (MANTIDOS INTACTOS)
# ==============================================================================

# Os prompts abaixo não lidam com a classificação inicial e, portanto,
# não precisam ser alterados. Eles operam em dados já classificados.

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

PROMPT_RADAR_MONITORAMENTO_V1 = """
Você está criando um "Radar de Monitoramento" para executivos. Sua tarefa é transformar as notícias do cluster abaixo em UM ÚNICO bullet point de UMA LINHA, começando com a ENTIDADE/ATOR principal.

REGRAS:
- Apenas 1 linha. Comece com "Entidade: ...". Seja preciso e informativo.
- Evite listas de classificados/leilões/avisos genéricos. Se mantidos excepcionalmente, foque em materialidade (valor, atores, data/próximo marco).

Exemplos:
- "iFood: em negociações para adquirir a Alelo por R$ 5 bilhões"
- "Mercado de Carbono: governo adia a criação de agência reguladora para o setor"

DADOS DO CLUSTER PARA TRANSFORMAR EM BULLET POINT:
{DADOS_DO_GRUPO}

FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):
```json
{{
  "bullet_point": "Entidade: resumo consolidado das notícias do cluster em uma linha"
}}
```
"""

PROMPT_AGRUPAMENTO_V1 = """
Você é um especialista em análise de conteúdo focado em granularidade. Sua tarefa é agrupar notícias de uma lista JSON que se referem ao MESMO FATO GERADOR. Diferentes jornais cobrem o mesmo fato com títulos distintos; sua missão é identificar o núcleo semântico e consolidar em grupos.

**DIRETRIZES DE AGRUPAMENTO:**
1.  **INTEGRIDADE TOTAL:** TODAS as notícias DEVEM ser alocadas a um grupo. Notícias sem par formam grupo de 1 item. NENHUMA notícia pode ser descartada.

2.  **FOCO NO NÚCLEO SEMÂNTICO:** O que realmente aconteceu? Qual a decisão/anúncio/evento objetivo?
    - **EXEMPLO (MESMO FATO):**
      - Notícia 1: "Moraes decide não prender X, mas mantém cautelares."
      - Notícia 2: "Ministro do STF não decreta prisão de X e esclarece cautelares."
      - **Análise:** Núcleo idêntico → MESMO GRUPO.

3.  **ESTÁGIOS DO MESMO PROCESSO (MESMO DIA):** anúncio → reação imediata → análises → desfecho parcial → **MESMO GRUPO**.

4.  **AÇÃO ⇄ CONSEQUÊNCIA DIRETA (MESMO PERÍODO):**
    - "CADE aprova fusão A+B com remédios" e "Ações da C sobem 5% após decisão" → **MESMO GRUPO**.

5.  **TEMA PRINCIPAL PRECISO:** `tema_principal` descreve o fato gerador consolidado de forma neutra e específica.

6.  **MAPEAMENTO POR ID:** Use os `ids_originais` para garantir correspondência.

7.  **EM CASO DE DÚVIDA RAZOÁVEL, PREFIRA AGRUPAR (NÃO criar novo grupo).**

**FORMATO DE ENTRADA (EXEMPLO):**
[
 {{"id": 0, "titulo": "Apple lança iPhone 20", "jornal": "Jornal Tech"}},
 {{"id": 1, "titulo": "Novo iPhone 20 da Apple chega ao mercado", "jornal": "Jornal Varejo"}},
 {{"id": 2, "titulo": "Tesla anuncia novo carro elétrico", "jornal": "Jornal Auto"}}
]

**FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):**
```json
[
 {{
  "tema_principal": "Apple lança o novo iPhone 20",
  "ids_originais": [0, 1]
 }},
 {{
  "tema_principal": "Tesla anuncia novo modelo de carro elétrico",
  "ids_originais": [2]
 }}
]
```
"""

PROMPT_RESUMO_FINAL_V3 = """
Você é um analista de inteligência criando um resumo sobre um evento específico, baseado em um CLUSTER de notícias relacionadas. A profundidade do seu resumo deve variar conforme o **Nível de Detalhe** solicitado.

**IMPORTANTE:** Você está resumindo um CLUSTER DE NOTÍCIAS sobre o mesmo fato gerador. Combine todas as informações das notícias do cluster em um resumo coerente e abrangente.

**NÍVEIS DE DETALHE:**
-   **Executivo (P1_CRITICO):** Um resumo de 4 a 7 linhas em um unico paragrafo. Detalhe o contexto, os principais dados (valores, percentuais), os players envolvidos e as implicações estratégicas (riscos/oportunidades).
-   **Padrão (P2_ESTRATEGICO):** Um único parágrafo denso e informativo que sintetiza os fatos mais importantes do evento, de 2 a 5 linhas.
-   **Conciso (P3_MONITORAMENTO):** Uma ou duas frases que capturam a essência do evento (de 1 a no maximo 2 linhas).

**MISSÃO:**
Baseado no CLUSTER de notícias fornecido e no **Nível de Detalhe** `{NIVEL_DE_DETALHE}` solicitado, produza um resumo consolidado.

**FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):**
```json
{{
  "titulo_final": "Use exatamente o tema_principal fornecido no cluster.",
  "resumo_final": "O resumo consolidado de todas as notícias do cluster conforme o Nível de Detalhe especificado."
}}
```

**DADOS DO CLUSTER PARA ANÁLISE:**
{DADOS_DO_GRUPO}
"""

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
# PROMPT PARA AGRUPAMENTO INCREMENTAL
# ==============================================================================

PROMPT_AGRUPAMENTO_INCREMENTAL_V1 = """
Você é um especialista em análise de conteúdo focado em granularidade. Sua tarefa é classificar novas notícias em relação a clusters existentes do mesmo dia.

**CONTEXTO IMPORTANTE:**
- Você receberá NOTÍCIAS NOVAS que precisam ser classificadas (título e, se disponível, início do texto)
- Você receberá CLUSTERS EXISTENTES do mesmo dia (inclua `tema_principal` e, se disponível, um breve resumo)
- Sua missão é decidir se cada notícia nova deve ser ANEXADA a um cluster existente ou criar um NOVO cluster somente se tratar de evento distinto

**REGRAS CRÍTICAS:**
1. **PRIORIZE ANEXAR:** Em caso de dúvida razoável (desdobramento, reação ou análise do mesmo evento), prefira ANEXAR ao cluster existente.
2. **MESMO FATO GERADOR:** Se a notícia nova se refere ao mesmo evento, decisão ou anúncio de um cluster existente, ANEXE ao cluster.
3. **FATO DIFERENTE:** Crie um novo cluster somente se a notícia tratar de um evento claramente distinto e independente.
4. **INTEGRIDADE TOTAL:** TODAS as notícias novas DEVEM ser classificadas (anexadas ou em novos clusters).

**FORMATO DE ENTRADA:**
- **NOTÍCIAS NOVAS:** Lista de notícias com ID, título e opcionalmente um breve início do texto
- **CLUSTERS EXISTENTES:** Lista de clusters com `cluster_id`, `tema_principal` e opcionalmente um breve resumo

**FORMATO DE SAÍDA OBRIGATÓRIO (JSON PURO):**
```json
[
  {{
    "tipo": "anexar",
    "noticia_id": 0,
    "cluster_id_existente": 1,
    "justificativa": "A notícia se refere ao mesmo evento do cluster existente"
  }},
  {{
    "tipo": "novo_cluster",
    "noticia_id": 1,
    "tema_principal": "Novo evento específico",
    "justificativa": "A notícia se refere a um fato gerador diferente"
  }}
]
```

**EXEMPLO:**
Se você tem:
- Notícia nova: "Apple anuncia novo iPhone"
- Cluster existente: "Apple lança iPhone 20" (com outras notícias sobre o mesmo lançamento)

**RESULTADO:** Anexar a notícia nova ao cluster existente, pois se refere ao mesmo evento.

**DADOS PARA ANÁLISE:**
**NOTÍCIAS NOVAS:**
{NOVAS_NOTICIAS}

**CLUSTERS EXISTENTES:**
{CLUSTERS_EXISTENTES}

**CLASSIFIQUE:** Cada notícia nova deve ser anexada a um cluster existente ou criar um novo cluster.
"""

# ============================================================================
# PROMPT DE SANITIZAÇÃO (GATEKEEPER) — REMOVER CLUSTERS IRRELEVANTES
# ============================================================================

PROMPT_SANITIZACAO_CLUSTER_V1 = """
Você é um porteiro (gatekeeper) para a mesa de 'Special Situations'. Decida se um CLUSTER de notícias é RELEVANTE ou IRRELEVANTE para análise financeira.

REJEIÇÃO IMEDIATA (IRRELEVANTE):
- Indenizações cíveis/trabalhistas individuais de baixo valor.
- Opinião/Cartas/Editorial sem fato econômico objetivo.
- Classificados/avisos/procurement/leilões genéricos (veículos/joias/apartamentos isolados).
- Esportes, Cultura/Entretenimento (sem tese de negócio), Crimes cotidianos, Política partidária pura.

EXCEÇÕES (RELEVANTE quando houver materialidade):
- Leilão JUDICIAL de alto valor (> R$10 mi) de ativo relevante; Venda de carteira NPL; Securitização de Dívida Ativa com valores/processos.
- M&A anunciado/OPA; Decisão do CADE com remédios; RJ/Falência/Default/Quebra de Covenants/Crise de Liquidez.

DADOS DO CLUSTER:
- Título do Cluster: {TITULO_CLUSTER}
- Amostra de Títulos: {TITULOS_ARTIGOS}

FORMATO DE SAÍDA (JSON PURO):
```json
{
  "decisao": "RELEVANTE" ou "IRRELEVANTE",
  "justificativa": "Motivo conciso"
}
```
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
