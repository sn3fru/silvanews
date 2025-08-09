"""
Exemplo de coletor para o BTG AlphaFeed.
Demonstra como criar um coletor que envia dados para a API.
"""

import requests
import hashlib
import time
from typing import Dict, Any, List
from datetime import datetime


class ExemploColetor:
    """
    Exemplo de coletor que simula a coleta de notícias.
    Em um cenário real, este seria um coletor de Telegram, RSS, ou web scraping.
    """
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self.session = requests.Session()
    
    def gerar_hash_artigo(self, texto: str, url: str = "") -> str:
        """Gera hash único para o artigo."""
        conteudo = f"{texto}{url}"
        return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()
    
    def enviar_artigo(self, texto_bruto: str, url_original: str = None, metadados: Dict[str, Any] = None) -> bool:
        """
        Envia um artigo para a API para processamento.
        
        Args:
            texto_bruto: Texto completo do artigo
            url_original: URL original (opcional)
            metadados: Metadados adicionais (opcional)
            
        Returns:
            True se enviado com sucesso, False caso contrário
        """
        try:
            # Gera hash único
            hash_unico = self.gerar_hash_artigo(texto_bruto, url_original or "")
            
            # Prepara dados
            dados_artigo = {
                "hash_unico": hash_unico,
                "texto_bruto": texto_bruto,
                "url_original": url_original,
                "fonte_coleta": "exemplo_coletor",
                "metadados": metadados or {}
            }
            
            # Envia para API
            response = self.session.post(
                f"{self.api_base_url}/internal/novo-artigo",
                json=dados_artigo,
                timeout=30
            )
            
            if response.status_code == 200:
                resultado = response.json()
                print(f"✅ Artigo enviado: {resultado['message']}")
                return True
            else:
                print(f"❌ Erro ao enviar artigo: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Erro de conexão: {e}")
            return False
    
    def coletar_noticias_exemplo(self) -> List[Dict[str, Any]]:
        """
        Simula a coleta de notícias.
        Em um cenário real, esta função faria scraping, consultaria APIs, etc.
        """
        noticias_exemplo = [
            {
                "texto": """
                BTG Pactual anuncia aquisição de fintech de crédito
                
                O BTG Pactual anunciou hoje a aquisição da fintech de crédito TechCredit por R$ 500 milhões. 
                A operação faz parte da estratégia do banco de expandir sua atuação no segmento de tecnologia 
                financeira e democratizar o acesso ao crédito.
                
                Segundo Roberto Sallouti, CEO do BTG, a aquisição permitirá ao banco oferecer soluções mais 
                inovadoras e ágeis para clientes corporativos e pessoas físicas. A TechCredit possui uma 
                carteira de crédito de R$ 2 bilhões e atende mais de 100 mil clientes.
                
                A transação ainda depende de aprovação do Banco Central e deve ser concluída no primeiro 
                trimestre de 2025.
                """,
                "url": "https://exemplo.com/btg-aquisicao-fintech",
                "metadados": {
                    "fonte_original": "Valor Econômico",
                    "data_coleta": datetime.now().isoformat(),
                    "palavras_chave": ["BTG Pactual", "aquisição", "fintech", "crédito"]
                }
            },
            {
                "texto": """
                Americanas obtém aprovação para novo plano de recuperação judicial
                
                A Americanas S.A. teve seu novo plano de recuperação judicial aprovado pela 4ª Vara Empresarial 
                do Rio de Janeiro. O plano prevê a conversão de R$ 15 bilhões em dívidas para capital e um 
                aporte de R$ 8 bilhões dos acionistas controladores.
                
                O juiz responsável destacou que o plano apresenta viabilidade econômica e garante a manutenção 
                de empregos. A empresa deverá vender suas operações de marketplace e focar no varejo físico.
                
                As ações da empresa subiram 12% na B3 após o anúncio da aprovação.
                """,
                "url": "https://exemplo.com/americanas-recuperacao-aprovada",
                "metadados": {
                    "fonte_original": "Estadão",
                    "data_coleta": datetime.now().isoformat(),
                    "palavras_chave": ["Americanas", "recuperação judicial", "aprovação"]
                }
            },
            {
                "texto": """
                Banco Central mantém Selic em 10,75% e sinaliza pausa
                
                O Comitê de Política Monetária (Copom) do Banco Central decidiu manter a taxa Selic em 10,75% 
                ao ano, conforme esperado pelo mercado. A decisão foi unânime e marca a terceira reunião 
                consecutiva sem alteração na taxa básica de juros.
                
                Em comunicado, o BC sinalizou que deve manter a taxa estável nas próximas reuniões, dependendo 
                da evolução dos dados de inflação e atividade econômica. O IPCA acumulado em 12 meses está 
                em 4,2%, dentro da meta de inflação.
                
                O mercado reagiu positivamente, com o dólar fechando em queda de 0,8%.
                """,
                "url": "https://exemplo.com/bc-mantem-selic",
                "metadados": {
                    "fonte_original": "Folha de S.Paulo",
                    "data_coleta": datetime.now().isoformat(),
                    "palavras_chave": ["Banco Central", "Selic", "juros", "inflação"]
                }
            }
        ]
        
        return noticias_exemplo
    
    def executar_coleta(self):
        """Executa um ciclo completo de coleta."""
        print("🔄 Iniciando coleta de exemplo...")
        
        # Simula coleta de notícias
        noticias = self.coletar_noticias_exemplo()
        
        # Envia cada notícia para a API
        sucessos = 0
        for i, noticia in enumerate(noticias, 1):
            print(f"\n📰 Enviando notícia {i}/{len(noticias)}...")
            
            if self.enviar_artigo(
                texto_bruto=noticia["texto"],
                url_original=noticia["url"],
                metadados=noticia["metadados"]
            ):
                sucessos += 1
                # Aguarda um pouco entre envios
                time.sleep(1)
        
        print(f"\n✅ Coleta finalizada: {sucessos}/{len(noticias)} notícias enviadas com sucesso")
    
    def verificar_api_status(self) -> bool:
        """Verifica se a API está funcionando."""
        try:
            response = self.session.get(f"{self.api_base_url}/health", timeout=10)
            if response.status_code == 200:
                status = response.json()
                print(f"✅ API Status: {status['status']}")
                return True
            else:
                print(f"❌ API não está saudável: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Erro ao verificar API: {e}")
            return False


def main():
    """Função principal para teste do coletor."""
    print("=" * 60)
    print("📡 BTG AlphaFeed - Exemplo de Coletor")
    print("=" * 60)
    
    # Cria instância do coletor
    coletor = ExemploColetor()
    
    # Verifica status da API
    if not coletor.verificar_api_status():
        print("\n❌ API não está disponível. Verifique se o backend está rodando.")
        return
    
    # Pergunta se deve executar a coleta
    executar = input("\n🚀 Executar coleta de exemplo? (s/N): ").lower().strip()
    if executar in ['s', 'sim', 'yes', 'y']:
        coletor.executar_coleta()
    else:
        print("Coleta cancelada pelo usuário.")
    
    print("\n" + "=" * 60)
    print("💡 Este é apenas um exemplo. Em produção, você implementaria:")
    print("   - Conexão com fontes reais (Telegram, RSS, etc.)")
    print("   - Tratamento de erros robusto")
    print("   - Agendamento automático (cron, APScheduler)")
    print("   - Monitoramento e logs detalhados")
    print("=" * 60)


if __name__ == "__main__":
    main()