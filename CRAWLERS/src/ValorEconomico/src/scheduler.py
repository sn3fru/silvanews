import time
import subprocess
import sys
import locale

while True:
    qtd_minutos: int = 10
    encoding = sys.stdout.encoding or locale.getpreferredencoding(False)
    result = subprocess.run(['python', '3_run_main_update.py'], capture_output=True, text=True, encoding=encoding)
    print(f"Aguardando {qtd_minutos} minutos...")
    time.sleep(qtd_minutos * 60)  # qtd_minutos
    # Garante que prints usem encoding correto
    try:
        print(f"Saída:\n{result.stdout}")
    except UnicodeEncodeError:
        print(
            f"Saída (ajustada):\n{result.stdout.encode('utf-8', errors='replace').decode(encoding, errors='replace')}")
    if result.stderr:
        print(f"Erros:\n{result.stderr}")