# -*- coding: utf-8 -*-

import os
import asyncio
import logging
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError
from pathlib import Path

# --- CONFIGURAÇÕES OBRIGATÓRIAS ---
# Preencha com as suas credenciais obtidas em my.telegram.org
API_ID = 17882453  # Substitua pelo seu API_ID
API_HASH = 'fbca1324f45f308de6525256d489cbc5'  # Substitua pelo seu API_HASH

# Seu número de telefone no formato internacional (ex: +5511999998888)
PHONE_NUMBER = '+5511985432150' # Substitua pelo seu número

# ID numérico do grupo alvo. Veja o guia para instruções de como obter.
TARGET_GROUP_ID = -1002342403724 # id do grupo JBL

# --- CONFIGURAÇÕES OPCIONAIS ---
# Nome do arquivo de sessão que será criado para salvar seu login.
SESSION_NAME = 'telegram_user'

# Palavras-chave para filtrar quais PDFs baixar.
# O script vai baixar arquivos se o nome contiver QUALQUER uma dessas palavras.
# A verificação não diferencia maiúsculas de minúsculas.
# Exemplo: ['Estadão', 'Globo', 'Valor']
KEYWORDS_TO_DOWNLOAD = ['Estadão', 'O Globo', 'Valor Econômico', 'Folha']

# Diretório para salvar os arquivos baixados.
DOWNLOAD_PATH = Path('./downloads')

# Número de mensagens recentes para verificar no grupo.
MESSAGE_LIMIT = 20

# Configuração do logging para exibir informações no terminal.
logging.basicConfig(
    format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',
    level=logging.INFO
)

# Garante que o diretório de download exista.
DOWNLOAD_PATH.mkdir(exist_ok=True)

async def main():
    """
    Função principal que orquestra a conexão, autenticação e download dos PDFs.
    """
    logging.info("Iniciando o cliente Telegram...")
    # O bloco 'async with' gerencia a conexão e desconexão automaticamente.
    async with TelegramClient(SESSION_NAME, API_ID, API_HASH) as client:
        
        # Verifica se o usuário já está logado (se o arquivo .session existe e é válido)
        is_authorized = await client.is_user_authorized()
        
        if not is_authorized:
            logging.warning("Sessão não encontrada ou inválida. Iniciando login interativo.")
            try:
                # Inicia o processo de login
                await client.send_code_request(PHONE_NUMBER)
                await client.sign_in(PHONE_NUMBER, input('Por favor, digite o código recebido: '))
            except SessionPasswordNeededError:
                # Se a conta tiver senha de duas etapas (2FA), pede a senha.
                await client.sign_in(password=input('Sua senha de duas etapas (2FA): '))
            except Exception as e:
                logging.error(f"Ocorreu um erro durante o login: {e}")
                return

        user = await client.get_me()
        logging.info(f"Login bem-sucedido como: {user.first_name} {user.last_name}")

        try:
            # Busca a entidade (grupo/canal) pelo ID fornecido.
            target_group = await client.get_entity(TARGET_GROUP_ID)
            logging.info(f"Acessando o grupo: '{target_group.title}'")
        except (ValueError, TypeError) as e:
            logging.error(f"Não foi possível encontrar o grupo com o ID '{TARGET_GROUP_ID}'. Verifique se o ID está correto e se você é membro do grupo. Erro: {e}")
            return
            
        logging.info(f"Procurando por PDFs com as palavras-chave: {KEYWORDS_TO_DOWNLOAD} nas últimas {MESSAGE_LIMIT} mensagens...")
        
        files_downloaded = 0
        # Converte as palavras-chave para minúsculas para comparação.
        lower_keywords = [key.lower() for key in KEYWORDS_TO_DOWNLOAD]

        # Itera sobre as mensagens do grupo.
        async for message in client.iter_messages(target_group, limit=MESSAGE_LIMIT):
            # Verifica se a mensagem contém um arquivo e se é um PDF.
            if message.file and message.file.mime_type == 'application/pdf':
                file_name = message.file.name if message.file.name else f"telegram_doc_{message.id}.pdf"
                
                # Verifica se o nome do arquivo contém alguma das palavras-chave.
                if any(keyword in file_name.lower() for keyword in lower_keywords):
                    file_path = DOWNLOAD_PATH / file_name
                    
                    if file_path.exists():
                        logging.info(f"Arquivo '{file_name}' já existe. Pulando.")
                        continue
                        
                    logging.info(f"Baixando '{file_name}'...")
                    try:
                        # Baixa o arquivo para o diretório especificado.
                        await message.download_media(file=file_path)
                        logging.info(f"Download de '{file_name}' concluído com sucesso.")
                        files_downloaded += 1
                    except Exception as e:
                        logging.error(f"Falha ao baixar o arquivo '{file_name}'. Erro: {e}")

        if files_downloaded == 0:
            logging.warning("Nenhum PDF novo correspondente aos critérios foi encontrado.")
        else:
            logging.info(f"Processo concluído. Total de {files_downloaded} novos arquivos baixados.")

if __name__ == "__main__":
    # Executa a função principal assíncrona.
    # No Windows, pode ser necessário configurar a política de eventos do asyncio.
    # Se encontrar um erro 'RuntimeError: This event loop is already running',
    # descomente as 3 linhas abaixo e comente a última.
    # import asyncio
    # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # asyncio.run(main())
    asyncio.run(main())
