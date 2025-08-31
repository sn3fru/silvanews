#!/usr/bin/env python3
"""
Script de teste para o endpoint de expansão de resumo
"""

import requests
import json
import time
from datetime import datetime

def testar_endpoint_expandir_resumo():
    """Testa o endpoint de expansão de resumo com dados controlados"""

    # URL do endpoint
    base_url = "http://localhost:8000"
    endpoint = "/api/clusters/17978/expandir-resumo"

    print("🧪 TESTANDO ENDPOINT DE EXPANSÃO DE RESUMO")
    print("=" * 60)

    # Verificar se o servidor está rodando
    try:
        health_response = requests.get(f"{base_url}/api/health", timeout=5)
        if health_response.status_code == 200:
            print("✅ Servidor está rodando")
        else:
            print("❌ Servidor não está respondendo corretamente")
            return
    except Exception as e:
        print(f"❌ Erro ao conectar com o servidor: {e}")
        return

    # Fazer a requisição de expansão
    print("
📤 Fazendo requisição para expandir resumo..."    print(f"🔗 URL: {base_url}{endpoint}")

    start_time = time.time()

    try:
        response = requests.post(f"{base_url}{endpoint}", timeout=60)
        end_time = time.time()

        print(".2f"
        print(f"📊 Status Code: {response.status_code}")

        if response.status_code == 200:
            print("✅ Requisição bem-sucedida!")
            try:
                data = response.json()
                if 'resumo_expandido' in data:
                    resumo = data['resumo_expandido']
                    print(f"📝 Resumo gerado ({len(resumo)} caracteres)")
                    print("-" * 40)
                    print(resumo[:300] + "..." if len(resumo) > 300 else resumo)
                    print("-" * 40)
                else:
                    print("⚠️ Resposta não contém 'resumo_expandido'")
                    print(f"📋 Resposta completa: {data}")
            except json.JSONDecodeError:
                print("❌ Resposta não é JSON válido")
                print(f"📋 Conteúdo da resposta: {response.text[:500]}")

        else:
            print("❌ Erro na requisição"            print(f"📋 Resposta de erro: {response.text}")

    except requests.exceptions.Timeout:
        print("⏰ Timeout: A requisição excedeu o tempo limite")
    except requests.exceptions.ConnectionError:
        print("🔌 Erro de conexão: Não foi possível conectar ao servidor")
    except Exception as e:
        print(f"💥 Erro inesperado: {e}")

    print("\n" + "=" * 60)
    print("🏁 Teste concluído")

if __name__ == "__main__":
    testar_endpoint_expandir_resumo()
