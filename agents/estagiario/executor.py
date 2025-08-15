import json
from typing import List

try:
    import google.generativeai as genai  # type: ignore
except Exception:
    genai = None  # type: ignore

from .tools.executor import ToolExecutor
from .prompts import REACT_PROMPT_TEMPLATE


class EstagiarioExecutor:
    def __init__(self):
        self.tools = ToolExecutor()
        self.model = None
        if genai:
            from os import getenv
            api_key = getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel('gemini-2.0-flash')

    def run(self, user_input: str, chat_history: List[str] = None) -> dict:
        chat_history = chat_history or []
        agent_scratchpad = ""
        trace = []

        if not self.model:
            return {"final": "LLM indisponível no executor.", "trace": trace}

        max_loops = 4
        for _ in range(max_loops):
            prompt = REACT_PROMPT_TEMPLATE.format(
                tools=self.tools.get_tool_definitions_for_llm(),
                chat_history="\n".join(chat_history),
                input=user_input,
                agent_scratchpad=agent_scratchpad,
            )
            resp = self.model.generate_content(prompt, generation_config={'temperature': 0.2, 'top_p': 0.8, 'max_output_tokens': 512})
            output = (resp.text or "").strip()

            thought, action = self._parse_llm_output(output)
            trace.append({"thought": thought, "action": action})
            agent_scratchpad += f"\nThought: {thought}\n"

            if action and action.get("action") == "Final Answer":
                return {"final": action.get("action_input", {}).get("answer", ""), "trace": trace}

            if action and action.get("action"):
                observation = self.tools.execute(action.get("action"), action.get("action_input", {}))
                trace.append({"observation": observation})
                agent_scratchpad += f"Observation: {json.dumps(observation)[:800]}\n"
            else:
                # Se não veio nenhuma ação válida, tenta novamente com o contexto atualizado
                agent_scratchpad += "Observation: nenhuma ação válida.\n"

        return {"final": "Não foi possível chegar a uma resposta final.", "trace": trace}

    def _parse_llm_output(self, text: str):
        # Extrai primeiro bloco JSON dentro de ```json ... ```
        import re
        thought = re.sub(r"```json[\s\S]*?```", "", text).strip()
        m = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        action = None
        if m:
            try:
                action = json.loads(m.group(1))
            except Exception:
                action = None
        return thought, action


