from . import definitions


class ToolExecutor:
    def __init__(self):
        self.tools = {
            "list_cluster_titles": definitions.list_cluster_titles,
            "query_clusters": definitions.query_clusters,
            "get_cluster_details": definitions.get_cluster_details,
            "update_cluster_priority": definitions.update_cluster_priority,
            "semantic_search": definitions.semantic_search,
        }
        self.tool_schemas = {
            "list_cluster_titles": definitions.ListClusterTitlesInput,
            "query_clusters": definitions.QueryClustersInput,
            "get_cluster_details": definitions.GetClusterDetailsInput,
            "update_cluster_priority": definitions.UpdateClusterPriorityInput,
            "semantic_search": definitions.SemanticSearchInput,
        }

    def get_tool_names(self) -> list:
        return list(self.tools.keys())

    def get_tool_definitions_for_llm(self) -> str:
        desc = [
            "- list_cluster_titles(data?: YYYY-MM-DD): lista TODOS os clusters do dia (id, titulo, tags, prioridade, fontes). Leve — use PRIMEIRO para planejar quais clusters aprofundar.",
            "- query_clusters(data?: YYYY-MM-DD, prioridade?: P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO, palavras_chave?: string[], limite?: int): busca clusters com filtros.",
            "- get_cluster_details(cluster_id: int): detalhes COMPLETOS de um cluster (artigos originais, resumo, fontes). Use para aprofundar clusters específicos.",
            "- update_cluster_priority(cluster_id: int, nova_prioridade: P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO|IRRELEVANTE): altera prioridade (unitário, cuidado).",
            "- semantic_search(consulta: string, limite?: int=5): busca semântica por artigos similares à consulta.",
        ]
        return "\n".join(desc)

    def execute(self, tool_name: str, tool_input: dict):
        if tool_name not in self.tools:
            return {"error": f"Ferramenta '{tool_name}' não encontrada. Ferramentas: {list(self.tools.keys())}"}
        try:
            model = self.tool_schemas[tool_name]
            validated = model(**tool_input)
            return self.tools[tool_name](validated)
        except Exception as e:
            return {"error": str(e)}


