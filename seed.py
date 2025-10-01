import sqlite3

# Conexão com o banco de dados
conn = sqlite3.connect('usuarios.db')
cursor = conn.cursor()

# Apaga tabelas existentes (opcional, para recriar do zero)
cursor.execute("DROP TABLE IF EXISTS usuarios")
cursor.execute("DROP TABLE IF EXISTS roteiros")

# Cria tabela de usuários
cursor.execute('''
CREATE TABLE usuarios (
    chat_id TEXT PRIMARY KEY,
    nome TEXT NOT NULL
)
''')

# Cria tabela de roteiros com os campos completos
cursor.execute('''
CREATE TABLE roteiros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    nome TEXT NOT NULL,
    destino TEXT,
    datas TEXT,
    orcamento TEXT,
    roteiro_completo TEXT,
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES usuarios (chat_id)
)
''')

# Insere usuários
usuarios = [
    ('12345', 'João'),
    ('67890', 'Maria')
]
cursor.executemany("INSERT INTO usuarios (chat_id, nome) VALUES (?, ?)", usuarios)

# Insere roteiros
roteiros = [
    ('12345', 'João', 'Paris', '10 a 15 de setembro', 'R$ 5.000', '''Dia 1: Chegada em Paris
Dia 2: Torre Eiffel
Dia 3: Museu do Louvre
Dia 4: Passeio de barco
Dia 5: Retorno'''),

    ('67890', 'Maria', 'Roma', '5 a 12 de outubro', '€ 4.000', '''Dia 1: Chegada em Roma
Dia 2: Coliseu
Dia 3: Vaticano
Dia 4: Fontana di Trevi
Dia 5: Retorno''')
]
cursor.executemany("""
    INSERT INTO roteiros (chat_id, nome, destino, datas, orcamento, roteiro_completo)
    VALUES (?, ?, ?, ?, ?, ?)
""", roteiros)

# Salva e fecha
conn.commit()
conn.close()

print("Banco de dados criado e populado com sucesso.")
