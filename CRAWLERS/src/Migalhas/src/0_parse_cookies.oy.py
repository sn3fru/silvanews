import json

def parse_cookie_txt(path_txt, target_domains=None):
    cookies = []
    with open(path_txt, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            # Divide por TAB
            fields = line.strip().split('\t')
            if len(fields) < 4:
                continue  # Linha inválida

            name = fields[0]
            value = fields[1]
            domain = fields[2]
            path = fields[3]

            # Filtra por domínio se desejado
            if target_domains and not any(domain.endswith(d) for d in target_domains):
                continue

            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path
            }
            cookies.append(cookie)
    return cookies

if __name__ == "__main__":
    # Altere para o nome do seu arquivo
    txt_path = "../data/cookies.txt"
    # Ajuste os domínios que quer considerar:
    doms = [".migalhas.com.br"]

    cookies = parse_cookie_txt(txt_path, doms)
    estrutura = {
        "jota": {
            "cookies": cookies
        }
    }
    with open("../credentials.json", "w", encoding="utf-8") as f:
        json.dump(estrutura, f, ensure_ascii=False, indent=2)
    print(f"{len(cookies)} cookies exportados para credentials.json!")
