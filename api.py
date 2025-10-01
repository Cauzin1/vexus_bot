# api.py

from flask import Flask, jsonify, abort
from flask_cors import CORS # <-- Nova importação
import sqlite3
import os

app = Flask(__name__)
CORS(app) # <-- Habilita o CORS para toda a aplicação

# --- Funções de Acesso ao Banco de Dados ---
def get_db_connection():
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(os.path.abspath('usuarios.db'))
    conn.row_factory = sqlite3.Row
    return conn

# --- Rotas da API (Endpoints) ---

@app.route('/api/viajantes', methods=['GET'])
def get_viajantes():
    """Endpoint que retorna a lista de todos os usuários que têm roteiros."""
    conn = get_db_connection()
    usuarios = conn.execute("""
        SELECT DISTINCT u.chat_id, u.nome
        FROM usuarios u JOIN roteiros r ON u.chat_id = r.chat_id
        ORDER BY u.nome
    """).fetchall()
    conn.close()
    # Converte os resultados para uma lista de dicionários e retorna como JSON
    return jsonify([dict(row) for row in usuarios])

@app.route('/api/viajante/<chat_id>', methods=['GET'])
def get_painel_viajante(chat_id):
    """Endpoint que retorna o perfil e todos os roteiros de um viajante."""
    conn = get_db_connection()
    usuario = conn.execute('SELECT * FROM usuarios WHERE chat_id = ?', (chat_id,)).fetchone()
    roteiros = conn.execute('SELECT * FROM roteiros WHERE chat_id = ? ORDER BY data_criacao DESC', (chat_id,)).fetchall()
    conn.close()
    
    if usuario is None:
        abort(404)

    # Monta um único objeto JSON com todas as informações
    return jsonify({
        'usuario': dict(usuario),
        'roteiros': [dict(row) for row in roteiros]
    })

if __name__ == '__main__':
    # Para rodar localmente: python api.py
    app.run(debug=True, port=5001)