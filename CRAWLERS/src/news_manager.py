import subprocess
import time
import sys
import locale
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

def run_script(path):
    print(f"\n🚀 Executando: {path}")
    try:
        # Executar sem tentar decodificar automaticamente para evitar erros de Unicode
        result = subprocess.run(['python', path], capture_output=True, text=False)

        # Tentar decodificar stdout com diferentes encodings
        stdout_text = ""
        if result.stdout:
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    stdout_text = result.stdout.decode(encoding, errors='replace')
                    break
                except UnicodeDecodeError:
                    continue

        # Tentar decodificar stderr com diferentes encodings
        stderr_text = ""
        if result.stderr:
            for encoding in ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    stderr_text = result.stderr.decode(encoding, errors='replace')
                    break
                except UnicodeDecodeError:
                    continue

        # Exibir saída apenas se houver conteúdo relevante
        if stdout_text.strip():
            print(f"📝 Saída de {path}:\n{stdout_text}")

        if stderr_text.strip():
            print(f"⚠️ Erros em {path}:\n{stderr_text}")

        if result.returncode != 0:
            print(f"❌ Falha na execução de: {path} (código: {result.returncode})")
        else:
            print(f"✅ Finalizado com sucesso: {path}")
    except Exception as e:
        print(f"❌ Erro ao executar {path}: {e}")

def gerar_dump_global():
    base_dir = Path(__file__).parent
    output_dir = base_dir.parent / "output"
    dump_dir = base_dir.parent / "dump"
    dump_dir.mkdir(parents=True, exist_ok=True)

    noticias = []

    for file_path in output_dir.glob("*.json"):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                dados = json.load(f)
                if isinstance(dados, list):
                    noticias.extend(dados)
                else:
                    print(f"[AVISO] Arquivo ignorado por não conter uma lista: {file_path.name}")
        except Exception as e:
            print(f"[ERRO] Falha ao ler {file_path.name}: {e}")

    def extrair_data(noticia):
        valor = noticia.get("data_publicacao", "")
        try:
            if "+" not in valor and "-" not in valor[10:]:
                dt = datetime.fromisoformat(valor)
                return dt.replace(tzinfo=timezone.utc)
            else:
                return datetime.fromisoformat(valor)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    if noticias:
        noticias.sort(key=extrair_data, reverse=True)
        data_str = datetime.today().strftime("%Y%m%d")
        nome_arquivo = f"dump_crawlers_{data_str}.json"
        caminho_dump = dump_dir / nome_arquivo

        with caminho_dump.open("w", encoding="utf-8") as f:
            json.dump(noticias, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Dump global gerado com sucesso: {caminho_dump} ({len(noticias)} registros)\n")
    else:
        print("\n⚠️ Nenhuma notícia encontrada para gerar o dump global.\n")

def main():
    base_dir = Path(__file__).parent
    output_dir = base_dir.parent / "output"

    # Cria o diretório se não existir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Limpa todos os arquivos dentro de output_dir
    for item in output_dir.iterdir():
        if item.is_file():
            item.unlink()  # apaga arquivo
        elif item.is_dir():
            shutil.rmtree(item)  # apaga diretório e todo o conteúdo dele

    ################################################################################

    scripts = {
        # "Estadão": "./Estadao/src/1_main_paginated.py",
        "Valor Econômico": "./ValorEconomico/src/1_main_paginated.py",
        "Jota": "./Jota/src/1_main_paginated.py",
        "Conjur": "./Conjur/main_conjur.py",
        "Brazil Journal": "./BrazilJournal/main_brazil_journal.py",
        "Migalhas": "./Migalhas/src/1_main_paginated.py"
    }

    for nome, caminho in scripts.items():
        try:
            run_script(caminho)
        except Exception as e:
            print(f"❌ Erro inesperado ao executar {nome}: {e}")
        print(f"\n[{nome}]")
        print("Aguardando 5 segundos antes de executar o próximo script...")
        time.sleep(5)

    try:
        gerar_dump_global()
    except Exception as e:
        print(f"\n❌ Erro ao gerar dump global: {e}\n")

if __name__ == "__main__":
    main()
