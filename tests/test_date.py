#!/usr/bin/env python3
"""
Script para testar a data do backend
"""

import sys
from pathlib import Path

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from backend.utils import get_date_brasil, get_datetime_brasil
from datetime import datetime

print("=== TESTE DE DATA ===")
print(f"Data atual (sistema): {datetime.now().date()}")
print(f"Data Brasil (backend): {get_date_brasil()}")
print(f"DateTime Brasil: {get_datetime_brasil()}")
print("===================") 