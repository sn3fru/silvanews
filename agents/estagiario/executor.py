import json
import re
from typing import List, Optional, Callable

try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # type: ignore

from .tools.executor import ToolExecutor
from .prompts import REACT_PROMPT_TEMPLATE


class EstagiarioExecutor:
    MAX_LOOPS = 10
    MAX_PARSE_RETRIES = 2

    def __init__(self):
        self.tools = ToolExecutor()
        self.model = None
        if genai:
            from os import getenv
            api_key = getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel('gemini-3-flash-preview')

    def run(
        self,
        user_input: str,
        chat_history: List[str] = None,
        data_referencia: str = "",
        on_step: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        ReAct agent loop with up to MAX_LOOPS iterations.
        on_step(text) is called after each intermediate step for streaming UX.
        """
        chat_history = chat_history or []
        agent_scratchpad = ""
        trace = []

        if not self.model:
            return {"final": "LLM indisponível no executor.", "trace": trace}

        for iteration in range(self.MAX_LOOPS):
            prompt = REACT_PROMPT_TEMPLATE.format(
                tools=self.tools.get_tool_definitions_for_llm(),
                chat_history="\n".join(chat_history),
                input=user_input,
                agent_scratchpad=agent_scratchpad,
                data_referencia=data_referencia or "hoje",
            )

            resp = self.model.generate_content(
                prompt,
                generation_config={'temperature': 0.2, 'top_p': 0.8, 'max_output_tokens': 2048},
            )
            output = (resp.text or "").strip()

            thought, action = self._parse_llm_output(output)
            trace.append({"iteration": iteration + 1, "thought": thought, "action": action})

            if thought:
                agent_scratchpad += f"\nThought: {thought}\n"

            if action and action.get("action") == "Final Answer":
                answer = action.get("action_input", {})
                if isinstance(answer, dict):
                    answer = answer.get("answer", "")
                return {"final": str(answer), "trace": trace}

            if action and action.get("action"):
                tool_name = action["action"]
                tool_input = action.get("action_input", {})

                if on_step:
                    step_label = self._step_label(tool_name, tool_input)
                    on_step(step_label)

                observation = self.tools.execute(tool_name, tool_input)
                obs_str = json.dumps(observation, ensure_ascii=False, default=str)
                if len(obs_str) > 3000:
                    obs_str = obs_str[:3000] + "... (truncado)"
                trace.append({"observation_tool": tool_name, "observation": obs_str[:500]})
                agent_scratchpad += f"Action: {tool_name}({json.dumps(tool_input, ensure_ascii=False)})\nObservation: {obs_str}\n"
            else:
                agent_scratchpad += "Observation: Formato inválido. Responda com um bloco ```json com action e action_input.\n"
                if on_step:
                    on_step("Corrigindo formato...")

        return {
            "final": "Desculpe, não consegui chegar a uma resposta definitiva. Tente reformular a pergunta.",
            "trace": trace,
        }

    def _parse_llm_output(self, text: str):
        thought = re.sub(r"```json[\s\S]*?```", "", text).strip()
        m = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        action = None
        if m:
            raw_json = m.group(1).strip()
            for attempt in range(self.MAX_PARSE_RETRIES + 1):
                try:
                    action = json.loads(raw_json)
                    break
                except json.JSONDecodeError:
                    raw_json = re.sub(r",\s*}", "}", raw_json)
                    raw_json = re.sub(r",\s*]", "]", raw_json)
        if not action:
            m2 = re.search(r'\{[^{}]*"action"\s*:', text)
            if m2:
                brace_start = m2.start()
                depth, end = 0, brace_start
                for i in range(brace_start, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                try:
                    action = json.loads(text[brace_start:end])
                except Exception:
                    pass
        return thought, action

    @staticmethod
    def _step_label(tool_name: str, tool_input: dict) -> str:
        labels = {
            "list_cluster_titles": "Lendo títulos das notícias...",
            "query_clusters": "Buscando clusters...",
            "get_cluster_details": f"Aprofundando notícia #{tool_input.get('cluster_id', '')}...",
            "semantic_search": f"Busca semântica: {tool_input.get('consulta', '')[:40]}...",
            "update_cluster_priority": "Atualizando prioridade...",
        }
        return labels.get(tool_name, f"Executando {tool_name}...")
