import unicodedata

def norm(s):
    s = s.lower()
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))

question = 'Escreva um panorama geral utilizando todas as mensagens p1, p2 e p3 de hoje'
nq = norm(question)
print(f'Original: {question}')
print(f'Normalizada: {nq}')

tag_map = {
    'autos': ['carro', 'veiculo', 'automovel', 'montadora', 'concessionaria', 'ev', 'eletrico'],
}
tags = set()
for tag, keys in tag_map.items():
    if any(k in nq for k in keys):
        tags.add(tag)
        print(f'Tag {tag} adicionada por palavras: {[k for k in keys if k in nq]}')

print(f'Tags inferidas: {list(tags)}')
