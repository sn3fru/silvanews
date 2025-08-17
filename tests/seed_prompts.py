#!/usr/bin/env python3
"""
Script para popular o banco de dados com os dados iniciais dos prompts.
Este script deve ser executado uma vez após a criação das tabelas para inserir
os dados padrão que estavam hardcoded no arquivo prompts.py.
"""

import os
import sys
from datetime import datetime, timezone

# Adiciona o diretório atual ao path para importar os módulos
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.database import SessionLocal, PromptTag, PromptPrioridadeItem, PromptTemplate

# Valores hardcoded originais (evitando import problemático)
TAGS_SPECIAL_SITUATIONS_ORIGINAL = {
    'M&A e Transações Corporativas': {
        'descricao': 'Mudanças na estrutura de capital ou controle de empresas através de transações.',
        'exemplos': [
            'Fusões e Aquisições (M&A) - Apenas quando o fato gerador for um anúncio oficial de transação, um acordo assinado ou uma negociação formal e exclusiva em andamento. Intenções genéricas de "buscar aquisições" devem ser P3 ou rejeitadas',
            'Venda de ativos ou subsidiárias (divestitures)',
            'Ofertas públicas de aquisição (OPA)',
            'Disputas por controle acionário que podem levar a uma transação'
        ]
    },
    'Jurídico, Falências e Regulatório': {
        'descricao': 'Eventos legais ou regulatórios que criam estresse financeiro, oportunidades de arbitragem ou alteram o ambiente de negócios.',
        'exemplos': [
            'Recuperação Judicial (RJ), Falência, Pedido de Falência, Assembleia de Credores',
            'Disputas societárias relevantes ENTRE SÓCIOS, ACIONISTAS ou CONSELHO de uma EMPRESA, com impacto em controle ou governança. (Ex: NÃO se aplica a disputas entre partidos políticos ou investigações de agentes públicos por crimes comuns)',
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
            'EnergIA Nuclear e Aeroespacial (grandes projetos, concessões)'
        ]
    },
    'Divulgação de Resultados': {
        'descricao': 'Publicações oficiais de resultados trimestrais/anuais (earnings) de empresas.',
        'exemplos': [
            'Divulgação de resultados trimestrais (ex.: 2T24, 3T24, 4T24)',
            'Conference call de resultados/press release de earnings',
            'Atualização de guidance vinculada ao release de resultados',
            'Observação: Resultados com sinais de estresse severo (impairment, write-down, quebra de covenants) podem ser elevados para P2.'
        ]
    },
    'IRRELEVANTE': {
        'descricao': 'Estamos na mesa de Special Situations do BTG Pactual. Vamos classificar tudo que que não tem contato conosco como IRRELEVANTE.',
        'exemplos': [
            'Noticias sobre crimes comuns, politica, opiniÕes que nao tem contato com o banco',
            'Fofocas, entretenimento, esportes, programas sociais, etc.',
            'Eventos esportivos, culturais, musicas, shows, teatrosetc.',
            'Programas publicos e do governo sociais, ambientes, bolsa familia, desemprego, etc que nao impactem a economia de forma abrangente'
        ]
    }
}

P1_ITENS_ORIGINAL = [
    "Anúncio de Falência ou Recuperação Judicial (RJ) de empresas Médias e Grandes",
    "Default de Dívida ou Quebra de Covenants anunciado oficialmente.",
    "Crise de Liquidez Aguda em empresa relevante ou crise soberana em país vizinho.",
    "M&A ou Venda de Ativo RELEVANTE (> R$ 100 milhões) — ANUNCIADO OFICIALMENTE. Intenções genéricas como 'buscar aquisições' NÃO são P1.",
    "Leilões de Ativos/Concessões inclusive NPL (> R$ 50 Milhões) com data marcada.",
    "Venda de carteiras de NPLs / Créditos Podres incluindo a venda e ou securitização de blocos de dívida ativa de estados e municípios.",
    "Notícia Crítica sobre Empresas-Foco (BTG Pactual, Banco Pan, Caixa Econômica Federal, Banco Master, PREVIC, IRB Brasil RE) que se enquadre como P1.",
    "Mudanças em Legislação com votação marcada no plenário e impacto setorial bilionário.",
    'Política Econômica (Decisões de juros, política fiscal e outras variáveis que afetem diretamente e de forma intensa o crédito e a saúde financeira das empresas)',
    'Decisões Grandes/Relevantes do CADE (bloqueio de fusões, imposição de remédios)',
    "Decisão de Tribunal Superior (STF/STJ) com precedente VINCULANTE que altera significativamente regras de Recuperação de Crédito, Direito Falimentar, Tributário ou Societário.",
    "Mudança em legislação ou regulamentação com APLICAÇÃO IMEDIATA e impacto setorial bilionário."
]

P2_ITENS_ORIGINAL = [
    "Venda e/ou securitização de Dívida Ativa / Precatórios / FCVS.",
    "Discussões sobre mudança na legilasção que afetem diretamente a cobrança das dividas das empresas",
    "Decisões judiciais de outras instâncias (ex: TRFs, TJs) com precedente setorial relevante.",
    "Denúncia de gestão temerária em instituição financeira junto ao Banco Central.",
    "Suspensão judicial de um M&A ou da execução de dívidas de uma empresa relevante.",
    "Notícias importantes sobre o Mercado Imobiliário com impacto setorial amplo.",
    "Resultados com sinais graves de estresse (impairment >10% PL, alavancagem >4x, risco de quebra de covenants).",
    "Investimento/CAPEX de grande porte anunciado (> R$ 1 bilhão).",
    "Grandes disputas societárias em empresas relevantes.",
    "M&A ou Investimento de grande porte (> R$ 1 bilhão) nos setores de Tecnologia, IA, Energia ou Defesa.",
    "Operação de Corrupção de GRANDE ESCALA com impacto direto em empresas listadas/relevantes (ex.: Operação Ícaro).",
    'Ativismo Acionário (grandes investidores tentando influenciar a gestão)',
    "Mudança de jurisprudência consolidada em tribunais (TRF, TST) com impacto setorial amplo (ex: Direito do Trabalho para um setor específico, teses tributárias).",
    "Publicação de acórdão ou tese de repercussão geral com impacto direto em passivos/ativos de empresas."
]

P3_ITENS_ORIGINAL = [
    "Tecnologia e mercados adjacentes: avanços gerais em IA, exploração espacial, setor de defesa, gaming e criptomoedas.",
    "Acompanhamento de Empresas (Radar, essa é 1:1 com uma TAG): notícias gerais ou divulgação de resultados de Meta, Google, Alphabet, Apple, Constellation Energy, Tesla, AMD, Intel, Microsoft, Intuitive Machines, Netflix, Micron, Siemens Energy AG, e outras grandes empresas listadas.",
    "Contexto macro e político: inflação/juros/câmbio, política econômica, discussões sobre projetos de lei (sem votação marcada), eventos geopolíticos.",
    "Atos institucionais de rotina: decisões judiciais de menor impacto, aprovações de licenças, indicações para agências, atas de assembleias."         
]


def seed_prompts():
    """Popula o banco de dados com os dados iniciais dos prompts"""
    db = SessionLocal()
    
    try:
        print("🌱 Populando banco de dados com prompts iniciais...")
        
        # Verifica se já existem dados
        if db.query(PromptTag).count() > 0:
            print("⚠️ Tabela de tags já possui dados. Pulando...")
        else:
            print("📝 Inserindo tags temáticas...")
            for i, (tag_name, tag_data) in enumerate(TAGS_SPECIAL_SITUATIONS_ORIGINAL.items(), 1):
                tag = PromptTag(
                    nome=tag_name,
                    descricao=tag_data['descricao'],
                    exemplos=tag_data['exemplos'],
                    ordem=i + 1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(tag)
            print(f"✅ {len(TAGS_SPECIAL_SITUATIONS_ORIGINAL)} tags inseridas")
        
        # Verifica se já existem dados de prioridade
        if db.query(PromptPrioridadeItem).count() > 0:
            print("⚠️ Tabela de prioridades já possui dados. Pulando...")
        else:
            print("🎯 Inserindo itens de prioridade...")
            
            # P1 - CRÍTICO
            for i, item in enumerate(P1_ITENS_ORIGINAL):
                prioridade = PromptPrioridadeItem(
                    nivel='P1_CRITICO',
                    texto=item,
                    ordem=i + 1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(prioridade)
            
            # P2 - ESTRATÉGICO
            for i, item in enumerate(P2_ITENS_ORIGINAL):
                prioridade = PromptPrioridadeItem(
                    nivel='P2_ESTRATEGICO',
                    texto=item,
                    ordem=i + 1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(prioridade)
            
            # P3 - MONITORAMENTO
            for i, item in enumerate(P3_ITENS_ORIGINAL):
                prioridade = PromptPrioridadeItem(
                    nivel='P3_MONITORAMENTO',
                    texto=item,
                    ordem=i + 1,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(prioridade)
            
            total_prioridades = len(P1_ITENS_ORIGINAL) + len(P2_ITENS_ORIGINAL) + len(P3_ITENS_ORIGINAL)
            print(f"✅ {total_prioridades} itens de prioridade inseridos")
        
        # Verifica se já existem templates
        if db.query(PromptTemplate).count() > 0:
            print("⚠️ Tabela de templates já possui dados. Pulando...")
        else:
            print("📋 Inserindo templates padrão...")
            
            # Template de resumo/clusterização
            template_resumo = PromptTemplate(
                chave='resumo',
                descricao='Prompt principal para resumo e clusterização de notícias',
                conteudo='''Você é um assistente especializado em análise de notícias financeiras e econômicas.

ANALISE a notícia fornecida e:

1. **DEFINA A PRIORIDADE** (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO):
   - P1_CRITICO: Notícias que podem impactar significativamente o mercado ou empresas específicas
   - P2_ESTRATEGICO: Notícias importantes para estratégias de investimento de médio prazo
   - P3_MONITORAMENTO: Notícias relevantes para acompanhamento e análise

2. **CLASSIFIQUE A TAG TEMÁTICA** (escolha UMA das opções abaixo):
   - M&A e Transações Corporativas
   - Jurídico, Falências e Regulatório
   - Dívida Ativa e Créditos Públicos
   - Distressed Assets e NPLs
   - Mercado de Capitais e Finanças Corporativas
   - Política Econômica (Brasil)
   - Internacional (Economia e Política)
   - Tecnologia e Setores Estratégicos

3. **GERE UM RESUMO EXECUTIVO** (máximo 200 palavras):
   - Principais pontos da notícia
   - Impacto potencial no mercado
   - Empresas/entidades envolvidas
   - Recomendações ou observações relevantes

4. **IDENTIFIQUE CLUSTERS SIMILARES** (se houver):
   - Sugira agrupamento com notícias relacionadas
   - Justifique a relação temática

NOTÍCIA: {texto_noticia}

RESPONDA NO FORMATO:
PRIORIDADE: [P1_CRITICO/P2_ESTRATEGICO/P3_MONITORAMENTO]
TAG: [tag_tematica]
RESUMO: [resumo_executivo]
CLUSTER: [sugestao_agrupamento_ou_none]''',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(template_resumo)
            
            # Template de relevância
            template_relevancia = PromptTemplate(
                chave='relevancia',
                descricao='Prompt para análise de relevância de notícias',
                conteudo='''Analise se a notícia é RELEVANTE para investidores e analistas financeiros.

CRITÉRIOS DE RELEVÂNCIA:
- Impacto potencial no mercado de capitais
- Relevância para estratégias de investimento
- Notícias sobre empresas listadas ou setores importantes
- Desenvolvimentos regulatórios significativos
- Mudanças na política econômica
- Eventos internacionais que afetam o Brasil

NOTÍCIA: {texto_noticia}

RESPONDA APENAS:
RELEVANTE: [SIM/NÃO]
JUSTIFICATIVA: [breve explicação]''',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(template_relevancia)
            
            # Template de extração
            template_extracao = PromptTemplate(
                chave='extracao',
                descricao='Prompt para extração de dados estruturados de notícias',
                conteudo='''Extraia as seguintes informações da notícia:

ENTIDADES:
- Empresas mencionadas
- Pessoas importantes
- Órgãos governamentais
- Instituições financeiras

VALORES:
- Valores monetários
- Percentuais
- Datas importantes
- Prazos

SETORES:
- Setor econômico principal
- Setores relacionados

NOTÍCIA: {texto_noticia}

RESPONDA EM JSON:
{
  "entidades": ["lista", "de", "entidades"],
  "valores": ["lista", "de", "valores"],
  "setores": ["lista", "de", "setores"]
}''',
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            db.add(template_extracao)
            
            print("✅ 3 templates padrão inseridos")
        
        db.commit()
        print("🎉 População do banco concluída com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro ao popular banco: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_prompts()
