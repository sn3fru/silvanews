import subprocess
import time
import sys
import locale

def run_script(path):
    print(f"Executando: {path}")
    # Força UTF-8 no output, mas tenta detectar encoding do terminal
    encoding = sys.stdout.encoding or locale.getpreferredencoding(False)
    result = subprocess.run(['python', path], capture_output=True, text=True, encoding=encoding)
    # Garante que prints usem encoding correto
    try:
        print(f"Saída de {path}:\n{result.stdout}")
    except UnicodeEncodeError:
        print(f"Saída de {path} (ajustada):\n{result.stdout.encode('utf-8', errors='replace').decode(encoding, errors='replace')}")
    if result.stderr:
        print(f"Erros em {path}:\n{result.stderr}")

def main():
    run_script("1_main_latest.py")
    print("Aguardando 15 segundos antes de executar o próximo script...")
    time.sleep(15)
    run_script("2_atualizar_banco_valor.py")

if __name__ == "__main__":
    main()
