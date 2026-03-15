# TELEGRAM_LISTENER/config.py
"""Configurações e constantes do listener."""

import re
from pathlib import Path

# Diretório do projeto principal (btg_alphafeed)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Pasta onde o load_news.py espera encontrar PDFs (mesma do run_complete_workflow)
PDFS_DIR = PROJECT_ROOT.parent / "pdfs"

# Padrões para identificar jornais/arquivos de interesse
JOURNAL_PATTERNS = [
    r"(?i)valor\s*(econ[oô]mico)?",
    r"(?i)folha\s*(de?\s*s\.?\s*paulo)?",
    r"(?i)estado\s*(de?\s*s\.?\s*paulo)?",
    r"(?i)estadao",
    r"(?i)gazeta",
    r"(?i)correio\s*braziliense",
    r"(?i)o\s*globo",
    r"(?i)jornal",
    r"(?i)broadcast",
    r"(?i)infomoney",
    r"(?i)capital\s*aberto",
    r"(?i)brazil\s*journal",
    r"(?i)pipeline",
    r"(?i)reset",
    r"(?i)neofeed",
    r"(?i)bloomberg",
    r"(?i)reuters",
    r"(?i)financial\s*times",
    r"(?i)\.pdf$",
]


def is_journal(filename: str, message_text: str = "") -> bool:
    """Verifica se o arquivo parece ser um jornal de interesse."""
    combined = f"{filename} {message_text}"
    for pattern in JOURNAL_PATTERNS:
        if re.search(pattern, combined):
            return True
    if filename.lower().endswith(".pdf"):
        return True
    return False


def safe_filename(name: str) -> str:
    """Normaliza nome do arquivo para salvar."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip()
