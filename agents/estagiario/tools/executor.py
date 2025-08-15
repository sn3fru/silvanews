from . import definitions


class ToolExecutor:
    def __init__(self):
        self.tools = {
            "query_clusters": definitions.query_clusters,
            "get_cluster_details": definitions.get_cluster_details,
            "update_cluster_priority": definitions.update_cluster_priority,
        }
        self.tool_schemas = {
            "query_clusters": definitions.QueryClustersInput,
            "get_cluster_details": definitions.GetClusterDetailsInput,
            "update_cluster_priority": definitions.UpdateClusterPriorityInput,
        }

    def get_tool_names(self) -> list:
        return list(self.tools.keys())

    def get_tool_definitions_for_llm(self) -> str:
        # descrição curta manual para não depender de libs extras
        desc = []
        desc.append("- query_clusters(data?: YYYY-MM-DD, prioridade?: P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO, palavras_chave?: string[], limite?: int): lista clusters do dia.")
        desc.append("- get_cluster_details(cluster_id: int): detalhes do cluster, incluindo artigos originais.")
        desc.append("- update_cluster_priority(cluster_id: int, nova_prioridade: P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO|IRRELEVANTE): atualização unitária e segura.")
        return "\n".join(desc)

    def execute(self, tool_name: str, tool_input: dict):
        if tool_name not in self.tools:
            return {"error": f"Ferramenta '{tool_name}' não encontrada"}
        try:
            model = self.tool_schemas[tool_name]
            validated = model(**tool_input)
            return self.tools[tool_name](validated)
        except Exception as e:
            return {"error": str(e)}


