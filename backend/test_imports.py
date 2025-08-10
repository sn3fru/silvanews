"""
Teste de importações do pacote 'backend'.
Execute com: python -m backend.test_imports
"""

print("--- (1/6) Testando import de 'database' ---")
from . import database
print("✅ OK: 'database' importado.")

print("--- (2/6) Testando import de 'models' ---")
from . import models
print("✅ OK: 'models' importado.")

print("--- (3/6) Testando import de 'crud' ---")
from . import crud
print("✅ OK: 'crud' importado.")

print("--- (4/6) Testando import de 'processing' ---")
from . import processing
print("✅ OK: 'processing' importado.")

print("--- (5/6) Testando import de 'collectors.file_loader' ---")
from .collectors import file_loader
print("✅ OK: 'collectors.file_loader' importado.")

print("--- (6/6) Testando import de 'main' ---")
from . import main
print("✅ OK: 'main' importado.")

print("\n🎉 SUCESSO! Importações internas do pacote 'backend' funcionando.")

