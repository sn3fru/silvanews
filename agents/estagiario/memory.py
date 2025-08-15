from typing import List


class SimpleMemory:
    """Memória simples em processo para o executor ReAct."""

    def __init__(self) -> None:
        self.lines: List[str] = []

    def add(self, role: str, content: str) -> None:
        self.lines.append(f"{role}: {content}")

    def dump(self) -> List[str]:
        return self.lines[-20:]


