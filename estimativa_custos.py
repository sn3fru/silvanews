import json
from pathlib import Path
from typing import Dict, Any

# Supondo que os prompts e o acesso ao DB estejam configurados como em process_articles.py
# Para este exemplo, vamos usar placeholders para os prompts e simular os dados do DB.
from backend.prompts import PROMPT_AGRUPAMENTO_V1, PROMPT_EXTRACAO_PERMISSIVO_V8, PROMPT_RESUMO_FINAL_V3
from backend.database import SessionLocal, ArtigoBruto




def carregar_precos(caminho_arquivo: str = "precos_modelos.json") -> Dict[str, Any]:
    """Carrega a estrutura de preços do arquivo JSON."""
    try:
        with open(caminho_arquivo, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERRO: Arquivo de preços '{caminho_arquivo}' não encontrado.")
        return None

def chars_to_tokens(num_chars: int) -> int:
    """
    Estima o número de tokens a partir do número de caracteres.
    Aproximação: 1 token ~ 4 caracteres.
    """
    return num_chars / 4

def estimar_custos_pipeline(db_session, modelos_config: Dict[str, str], precos: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simula o fluxo do pipeline e estima os custos de input e output para cada etapa.

    Args:
        db_session: A sessão do banco de dados para consultar os artigos.
        modelos_config: Dicionário indicando qual modelo usar para cada tarefa.
                        Ex: {'agrupamento': 'gemini-2.5-flash-lite', ...}
        precos: Dicionário com os preços dos modelos.

    Returns:
        Um dicionário com a análise detalhada dos custos.
    """
    resultados = {
        'cenario': modelos_config,
        'custos': {},
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'custo_total': 0.0
    }

    # --- SIMULAÇÃO DA ETAPA 2: AGRUPAMENTO ---
    print("Simulando ETAPA 2: Agrupamento...")
    artigos_para_agrupar = db_session.query(ArtigoBruto).filter(
        ArtigoBruto.status == "pronto_agrupar",
        ArtigoBruto.cluster_id.is_(None)
    ).all()
    
    if not artigos_para_agrupar:
        print("Nenhum artigo para agrupar.")
        return resultados

    # Simulação do input
    noticias_json_str = json.dumps(
        [{"id": i, "titulo": a.titulo_extraido or "", "trecho": (a.texto_processado or "")[:150]} for i, a in enumerate(artigos_para_agrupar)]
    )
    input_chars_agrupamento = len(PROMPT_AGRUPAMENTO_V1) + len(noticias_json_str)
    input_tokens_agrupamento = chars_to_tokens(input_chars_agrupamento)
    
    # Simulação do output (heurística: output é ~15% do tamanho dos títulos enviados)
    output_chars_agrupamento = len(json.dumps([{"tema_principal": a.titulo_extraido or "", "ids_originais": [i]} for i, a in enumerate(artigos_para_agrupar)])) * 0.15
    output_tokens_agrupamento = chars_to_tokens(output_chars_agrupamento)
    
    modelo_agrupamento = modelos_config['agrupamento']
    custo_input_agrupamento = (input_tokens_agrupamento / 1_000_000) * precos[modelo_agrupamento]['input']
    custo_output_agrupamento = (output_tokens_agrupamento / 1_000_000) * precos[modelo_agrupamento]['output']
    
    resultados['custos']['agrupamento'] = {
        'modelo': modelo_agrupamento,
        'input_tokens': input_tokens_agrupamento,
        'output_tokens': output_tokens_agrupamento,
        'custo': custo_input_agrupamento + custo_output_agrupamento
    }
    resultados['total_input_tokens'] += input_tokens_agrupamento
    resultados['total_output_tokens'] += output_tokens_agrupamento
    
    # --- SIMULAÇÃO DA ETAPA 3: CLASSIFICAÇÃO E RESUMO ---
    print("Simulando ETAPA 3: Classificação e Resumo...")
    # Heurística: Assumir que cada artigo se torna um cluster, o pior caso em termos de chamadas.
    num_clusters = len(artigos_para_agrupar)
    
    # Calcular o tamanho médio do texto de um artigo para usar na simulação
    tamanho_medio_texto_artigo = sum(len(a.texto_processado or "") for a in artigos_para_agrupar) / num_clusters if num_clusters > 0 else 0

    # Classificação
    input_chars_classificacao_por_cluster = len(PROMPT_EXTRACAO_PERMISSIVO_V8) + tamanho_medio_texto_artigo
    input_tokens_classificacao = num_clusters * chars_to_tokens(input_chars_classificacao_por_cluster)
    output_tokens_classificacao = num_clusters * chars_to_tokens(1500) # Saída JSON é relativamente fixa
    
    modelo_classificacao = modelos_config['classificacao']
    custo_input_classificacao = (input_tokens_classificacao / 1_000_000) * precos[modelo_classificacao]['input']
    custo_output_classificacao = (output_tokens_classificacao / 1_000_000) * precos[modelo_classificacao]['output']

    resultados['custos']['classificacao'] = {
        'modelo': modelo_classificacao,
        'input_tokens': input_tokens_classificacao,
        'output_tokens': output_tokens_classificacao,
        'custo': custo_input_classificacao + custo_output_classificacao
    }
    resultados['total_input_tokens'] += input_tokens_classificacao
    resultados['total_output_tokens'] += output_tokens_classificacao
    
    # Resumo
    input_chars_resumo_por_cluster = len(PROMPT_RESUMO_FINAL_V3) + tamanho_medio_texto_artigo
    input_tokens_resumo = num_clusters * chars_to_tokens(input_chars_resumo_por_cluster)
    output_tokens_resumo = num_clusters * chars_to_tokens(1000) # Média entre P1, P2 e P3
    
    modelo_resumo = modelos_config['resumo']
    custo_input_resumo = (input_tokens_resumo / 1_000_000) * precos[modelo_resumo]['input']
    custo_output_resumo = (output_tokens_resumo / 1_000_000) * precos[modelo_resumo]['output']
    
    resultados['custos']['resumo'] = {
        'modelo': modelo_resumo,
        'input_tokens': input_tokens_resumo,
        'output_tokens': output_tokens_resumo,
        'custo': custo_input_resumo + custo_output_resumo
    }
    resultados['total_input_tokens'] += input_tokens_resumo
    resultados['total_output_tokens'] += output_tokens_resumo

    # --- TOTAIS ---
    resultados['custo_total'] = sum(etapa['custo'] for etapa in resultados['custos'].values())
    
    return resultados

def imprimir_analise(analise: Dict[str, Any]):
    """Formata e imprime a análise de custos."""
    print("\n" + "="*80)
    print("📊 ANÁLISE DE CUSTO-BENEFÍCIO DO PIPELINE")
    print("="*80)
    
    print("\nCenário de Modelos:")
    for etapa, modelo in analise['cenario'].items():
        print(f"  - {etapa.capitalize():<15}: {modelo}")
        
    print("\nEstimativa de Custos por Etapa:")
    for etapa, dados in analise['custos'].items():
        print(f"  - {etapa.capitalize():<15}: ${dados['custo']:.6f} (Input: {int(dados['input_tokens'])} tokens, Output: {int(dados['output_tokens'])} tokens)")
        
    print("\n" + "-"*40)
    print(f"  TOTAL DE TOKENS INPUT : {int(analise['total_input_tokens'])}")
    print(f"  TOTAL DE TOKENS OUTPUT: {int(analise['total_output_tokens'])}")
    print(f"  CUSTO TOTAL ESTIMADO  : ${analise['custo_total']:.6f}")
    print("-"*40)

if __name__ == "__main__":
    precos_modelos = carregar_precos()
    
    if precos_modelos:
        db = SessionLocal()
        
        # Cenário 1: Estratégia Atual (usando o modelo antigo para tudo)
        cenario_atual = {
            "agrupamento": "gemini-2.5-flash",
            "classificacao": "gemini-2.5-flash",
            "resumo": "gemini-2.5-flash"
        }
        
        # Cenário 2: Estratégia Proposta (multi-modelo otimizado)
        cenario_proposto = {
            "agrupamento": "gemini-2.5-flash-lite",
            "classificacao": "gemini-2.5-flash-ga",
            "resumo": "gemini-2.5-flash-ga"
        }
        
        print("Executando simulação para o cenário ATUAL...")
        analise_atual = estimar_custos_pipeline(db, cenario_atual, precos_modelos)
        imprimir_analise(analise_atual)
        
        print("\n\nExecutando simulação para o cenário PROPOSTO...")
        analise_proposta = estimar_custos_pipeline(db, cenario_proposto, precos_modelos)
        imprimir_analise(analise_proposta)
        
        db.close()

        # Comparativo final
        if analise_atual and analise_proposta:
            economia = analise_atual['custo_total'] - analise_proposta['custo_total']
            reducao_percentual = (economia / analise_atual['custo_total']) * 100 if analise_atual['custo_total'] > 0 else 0
            print("\n" + "="*80)
            print("📈 COMPARATIVO FINAL")
            print("="*80)
            print(f"Custo Cenário Atual   : ${analise_atual['custo_total']:.6f}")
            print(f"Custo Cenário Proposto: ${analise_proposta['custo_total']:.6f}")
            print(f"Economia Estimada     : ${economia:.6f} ({reducao_percentual:.2f}% de redução)")
            print("="*80)