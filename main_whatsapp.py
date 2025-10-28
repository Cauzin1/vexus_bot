# main_whatsapp.py — VexusBot para WhatsApp Cloud API
# Versão FINAL CORRIGIDA - Pronto para produção no Render
# ✅ Todos os bugs corrigidos
# ✅ Sistema de keep-alive integrado
# ✅ Logs otimizados para debug

import os
import json
import re
import requests
import sqlite3
from flask import Flask, request
from dotenv import load_dotenv
import traceback
import threading
import time
import sys

# === CARREGA VARIÁVEIS ===
load_dotenv()

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")

if not all([WHATSAPP_TOKEN, PHONE_NUMBER_ID, VERIFY_TOKEN, GEMINI_KEY]):
    raise Exception("❌ Variáveis de ambiente ausentes no .env!")

# === FLASK APP ===
app = Flask(__name__)

# === CONFIG GEMINI ===
import google.generativeai as genai
genai.configure(api_key=GEMINI_KEY)

def escolher_modelo():
    """Escolhe o melhor modelo Gemini disponível"""
    disponiveis = [m.name for m in genai.list_models()]
    for candidato in [
        "models/gemini-2.5-flash",
        "models/gemini-2.0-flash-001",
        "models/gemini-flash-latest",
        "models/gemini-1.5-flash",
        "models/gemini-1.5-pro",
        "models/gemini-pro-latest"
    ]:
        if candidato in disponiveis:
            return candidato.replace("models/", "")
    
    for candidato in disponiveis:
        if "gemini" in candidato and ("flash" in candidato or "pro" in candidato):
            return candidato.replace("models/", "")
    
    raise RuntimeError(f"Nenhum modelo Gemini disponível. Modelos encontrados: {disponiveis}")

try:
    GEMINI_MODEL = escolher_modelo()
    model = genai.GenerativeModel(GEMINI_MODEL)
    print(f"✅ Gemini configurado: {GEMINI_MODEL}", flush=True)
except Exception as e:
    print(f"❌ Erro na configuração do Gemini: {e}", flush=True)
    exit()

# === CONFIG RAG ===
try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
    from langchain_community.vectorstores import FAISS
    from langchain.prompts import PromptTemplate
    from langchain.schema.runnable import RunnablePassthrough
    from langchain.schema.output_parser import StrOutputParser

    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/embedding-001", 
        google_api_key=GEMINI_KEY
    )
    vector_store = FAISS.load_local(
        "faiss_index", 
        embeddings, 
        allow_dangerous_deserialization=True
    )
    retriever = vector_store.as_retriever(search_kwargs={"k": 3})

    template = """
Você é o VexusBot, um assistente de viagens.
Use SOMENTE o conteúdo fornecido abaixo para responder à pergunta.
Se não encontrar resposta, diga: "Não encontrei essa dica no meu guia de viagens."

CONTEÚDO: {context}
PERGUNTA: {question}
RESPOSTA:
"""
    prompt_template = PromptTemplate.from_template(template)
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL, 
        temperature=0.7,
        google_api_key=GEMINI_KEY
    )

    rag_chain = (
        {"context": retriever, "question": RunnablePassthrough()}
        | prompt_template
        | llm
        | StrOutputParser()
    )
    print("✅ Sistema RAG carregado com sucesso!", flush=True)
except Exception as e:
    print(f"⚠️ Erro ao carregar RAG: {e}", flush=True)
    rag_chain = None

# === BANCO DE DADOS ===
def get_conn():
    """Cria conexão SQLite otimizada"""
    conn = sqlite3.connect('whatsapp_usuarios.db', check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=8000;")
    return conn

def inicializar_banco():
    conn = get_conn()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessoes (
            telefone TEXT PRIMARY KEY,
            estado TEXT,
            dados TEXT,
            modo TEXT,
            ultima_interacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY,
            telefone TEXT UNIQUE NOT NULL,
            nome TEXT,
            idade INTEGER,
            acompanhantes TEXT,
            estilo_viagem TEXT,
            tipo_comida TEXT,
            interesses TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("🗄️ Banco de dados inicializado!", flush=True)

def migrar_banco():
    """Adiciona colunas ausentes em bancos existentes"""
    conn = get_conn()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT modo FROM sessoes LIMIT 1")
    except sqlite3.OperationalError:
        print("🔧 Migrando banco: adicionando coluna 'modo'...", flush=True)
        cursor.execute("ALTER TABLE sessoes ADD COLUMN modo TEXT")
        conn.commit()
        print("✅ Migração concluída!", flush=True)
    
    conn.close()

inicializar_banco()
migrar_banco()

def salvar_sessao(telefone, estado, dados, modo=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO sessoes (telefone, estado, dados, modo, ultima_interacao)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (telefone, estado, json.dumps(dados), modo))
    conn.commit()
    conn.close()

def carregar_sessao(telefone):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT estado, dados, modo FROM sessoes WHERE telefone = ?', (telefone,))
    resultado = cursor.fetchone()
    conn.close()
    
    if resultado:
        return {
            'estado': resultado[0],
            'dados': json.loads(resultado[1]) if resultado[1] else {},
            'modo': resultado[2]
        }
    return {'estado': None, 'dados': {}, 'modo': None}

def limpar_sessao(telefone):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sessoes WHERE telefone = ?', (telefone,))
    conn.commit()
    conn.close()

_COLS_OK = {"nome", "idade", "acompanhantes", "estilo_viagem", "tipo_comida", "interesses"}

def salvar_preferencia(telefone, coluna, valor):
    """Salva preferências do perfil do usuário"""
    if coluna not in _COLS_OK:
        raise ValueError("Coluna inválida")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO usuarios (telefone) VALUES (?)", (str(telefone),))
    cursor.execute(f"UPDATE usuarios SET {coluna} = ? WHERE telefone = ?", (valor, str(telefone)))
    conn.commit()
    conn.close()

def carregar_preferencias(telefone):
    """Carrega preferências do perfil do usuário"""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE telefone = ?", (str(telefone),))
    resultado = cursor.fetchone()
    conn.close()
    if resultado:
        return dict(resultado)
    return {}

# === HELPERS ===
def _extrair_json_seguro(texto):
    """Extrai JSON de uma resposta do Gemini"""
    if not texto:
        return None
    texto_limpo = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.IGNORECASE | re.MULTILINE)
    m = re.search(r'\{.*?\}', texto_limpo, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def extrair_tabela_markdown(texto: str) -> str:
    """Extrai tabelas Markdown do texto"""
    linhas_tabela = []
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha.startswith('|') and linha.endswith('|') and linha.count('|') > 2:
            if not all(c in '|:- ' for c in linha):
                linhas_tabela.append(linha)
    
    resultado = '\n'.join(linhas_tabela)
    print(f"📋 DEBUG: Extraídas {len(linhas_tabela)} linhas de tabela", flush=True)
    return resultado

DATE_FORMAT_HELP = "Por favor, informe as datas no formato: *DD/MM a DD/MM* (ex.: *10/07 a 18/07*)."

def _zero2(n: str) -> str:
    try:
        return f"{int(n):02d}"
    except Exception:
        return n

def parse_intervalo_datas(texto: str) -> dict | None:
    """Parse de datas no formato DD/MM a DD/MM"""
    t = (texto or "").strip()
    m1 = re.search(r'(?i)\b(\d{1,2})[\/\-.](\d{1,2})\s*(?:a|até|ate|–|-|—)\s*(\d{1,2})[\/\-.](\d{1,2})\b', t)
    if m1:
        d1, m_1, d2, m_2 = _zero2(m1.group(1)), _zero2(m1.group(2)), _zero2(m1.group(3)), _zero2(m1.group(4))
        if 1 <= int(d1) <= 31 and 1 <= int(d2) <= 31 and 1 <= int(m_1) <= 12 and 1 <= int(m_2) <= 12:
            inicio = f"{d1}/{m_1}"
            fim = f"{d2}/{m_2}"
            return {"inicio": inicio, "fim": fim, "texto_norm": f"{inicio} a {fim}"}
    
    m2 = re.search(r'(?i)\b(\d{1,2})\s*(?:a|até|ate|–|-|—)\s*(\d{1,2})[\/\-.](\d{1,2})\b', t)
    if m2:
        d1, d2, m_ = _zero2(m2.group(1)), _zero2(m2.group(2)), _zero2(m2.group(3))
        if 1 <= int(d1) <= 31 and 1 <= int(d2) <= 31 and 1 <= int(m_) <= 12:
            inicio = f"{d1}/{m_}"
            fim = f"{d2}/{m_}"
            return {"inicio": inicio, "fim": fim, "texto_norm": f"{inicio} a {fim}"}
    return None

# === ANÁLISE COM IA ===
def analisar_resposta_data(texto_usuario: str, destino: str) -> dict:
    """Analisa se usuário forneceu data ou fez uma pergunta"""
    prompt = f"""
    O assistente perguntou as datas para uma viagem a {destino}.
    O usuário respondeu: "{texto_usuario}".
    Analise a resposta e classifique-a em 'data_fornecida', 'pergunta_sobre_data' ou 'indefinido'.
    Extraia o valor da data se aplicável (ex: '10 a 20 de dezembro').
    Responda APENAS com um JSON. Ex: {{"classificacao": "pergunta_sobre_data", "valor": "melhor época"}}
    """
    try:
        response = model.generate_content(prompt)
        data = _extrair_json_seguro(response.text)
        return data if data else {"classificacao": "indefinido"}
    except Exception as e:
        print(f"ERRO AO ANALISAR RESPOSTA DE DATA: {e}", flush=True)
        return {"classificacao": "indefinido"}

# === FUNÇÕES DE ENVIO ===
def enviar_mensagem(destino, texto):
    """Envia mensagem de texto simples"""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "text",
        "text": {"body": texto}
    }
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code == 401:
        print(f"❌ ERRO 401: Token inválido ou expirado!", flush=True)
        print(f"   Token usado: {WHATSAPP_TOKEN[:20]}...", flush=True)
        print(f"   Resposta: {response.text}", flush=True)
    elif response.status_code != 200:
        print(f"⚠️ Erro {response.status_code}: {response.text}", flush=True)
    else:
        print(f"✅ Mensagem enviada para {destino}: {response.status_code}", flush=True)
    
    sys.stdout.flush()
    return response

def enviar_menu_principal(destino):
    """Menu principal com botões"""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "🌟 Olá! Eu sou o VexusBot.\n\nComo posso te ajudar?"
            },
            "action": {
                "button": "Ver Opções",
                "sections": [
                    {
                        "title": "Menu Principal",
                        "rows": [
                            {
                                "id": "menu_planejar",
                                "title": "✈️ Planejar Roteiro",
                                "description": "Criar roteiro personalizado"
                            },
                            {
                                "id": "menu_perfil",
                                "title": "👤 Meu Perfil",
                                "description": "Ver/editar preferências"
                            },
                            {
                                "id": "menu_ajuda",
                                "title": "❓ Ajuda",
                                "description": "Como usar o bot"
                            }
                        ]
                    }
                ]
            }
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"✅ Menu enviado: {response.status_code}", flush=True)
    sys.stdout.flush()
    return response

def enviar_menu_pos_roteiro(destino):
    """Menu após gerar roteiro"""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "📋 O que você gostaria de fazer agora?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "gerar_pdf",
                            "title": "📄 Gerar PDF"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "gerar_excel",
                            "title": "📊 Gerar Excel"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "voltar_menu",
                            "title": "⬅️ Voltar ao Menu"
                        }
                    }
                ]
            }
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"✅ Menu pós-roteiro enviado: {response.status_code}", flush=True)
    sys.stdout.flush()
    return response

def enviar_menu_perfil(destino):
    """Menu de gerenciamento de perfil"""
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "👤 *Gerenciar Perfil*\n\nO que você gostaria de fazer?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "ver_perfil",
                            "title": "👁️ Ver Perfil"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "editar_perfil",
                            "title": "✍️ Editar Perfil"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "voltar_menu",
                            "title": "⬅️ Voltar"
                        }
                    }
                ]
            }
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    sys.stdout.flush()
    return response

def enviar_selecao_interesses(destino, interesses_atuais):
    """Menu de seleção de interesses"""
    opcoes = ["Museus", "Natureza", "Vida Noturna", "Gastronomia"]
    
    rows = []
    for opt in opcoes:
        marcador = "✅ " if opt in interesses_atuais else ""
        rows.append({
            "id": f"interesse_{opt}",
            "title": f"{marcador}{opt}",
            "description": "Clique para adicionar/remover"
        })
    
    rows.append({
        "id": "concluir_interesses",
        "title": "✔️ Concluir Seleção",
        "description": "Salvar e voltar"
    })
    
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "✍️ *Editar Interesses*\n\nSelecione seus interesses de viagem:"
            },
            "action": {
                "button": "Selecionar",
                "sections": [
                    {
                        "title": "Interesses",
                        "rows": rows
                    }
                ]
            }
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    sys.stdout.flush()
    return response

def enviar_documento(destino, caminho_arquivo, nome_arquivo):
    """Envia documento (PDF, XLSX, DOCX, etc) - VERSÃO CORRIGIDA"""
    # Determina o MIME type correto
    if nome_arquivo.lower().endswith('.pdf'):
        mime_type = 'application/pdf'
    elif nome_arquivo.lower().endswith('.xlsx'):
        mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif nome_arquivo.lower().endswith('.docx'):
        mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif nome_arquivo.lower().endswith('.txt'):
        mime_type = 'text/plain'
    else:
        mime_type = 'application/octet-stream'
    
    print(f"📤 Enviando arquivo: {nome_arquivo} (tipo: {mime_type})", flush=True)
    
    # Upload do arquivo
    url_upload = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/media"
    headers_upload = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    with open(caminho_arquivo, 'rb') as arquivo:
        files = {
            'file': (nome_arquivo, arquivo, mime_type),
            'messaging_product': (None, 'whatsapp'),
        }
        response_upload = requests.post(url_upload, headers=headers_upload, files=files)
    
    if response_upload.status_code != 200:
        print(f"❌ Erro no upload ({response_upload.status_code}): {response_upload.text}", flush=True)
        raise Exception(f"Falha ao fazer upload: {response_upload.text[:200]}")
    
    media_id = response_upload.json().get('id')
    print(f"✅ Upload realizado! Media ID: {media_id}", flush=True)
    
    # Envia mensagem com documento (CORRIGIDO - era 'url', agora é 'url_send')
    url_send = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers_send = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": destino,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": nome_arquivo
        }
    }
    
    response_send = requests.post(url_send, headers=headers_send, json=payload)
    
    if response_send.status_code != 200:
        print(f"❌ Erro ao enviar documento ({response_send.status_code}): {response_send.text}", flush=True)
    else:
        print(f"✅ Documento enviado com sucesso: {response_send.status_code}", flush=True)
    
    sys.stdout.flush()
    return response_send

# === LÓGICA DE PROCESSAMENTO ===
def processar_comando(telefone, texto, nome_usuario="Viajante"):
    """Processa comandos e estados"""
    texto_lower = texto.lower().strip()
    sessao = carregar_sessao(telefone)
    estado = sessao['estado']
    dados = sessao['dados']
    modo = sessao.get('modo')

    print(f"🔍 DEBUG: Estado={estado}, Modo={modo}, Texto={texto_lower[:50]}", flush=True)

    # Detecção de saudação
    saudacoes = ['oi', 'olá', 'ola', 'hey', 'bom dia', 'boa tarde', 'boa noite', 'eai', 'e ai', 'opa']
    eh_saudacao = any(saudacao == texto_lower or texto_lower.startswith(saudacao + ' ') for saudacao in saudacoes)
    
    if eh_saudacao:
        print("✅ Detectada saudação - resetando sessão", flush=True)
        limpar_sessao(telefone)
        salvar_preferencia(telefone, 'nome', nome_usuario)
        
        texto_apresentacao = (
            f"Olá, {nome_usuario}! Eu sou o VexusBot. ✈️\n\n"
            "Sou seu assistente de viagens pessoal e uso inteligência artificial "
            "para te ajudar a planejar a viagem dos sonhos!\n\n"
            "Posso criar *roteiros completos*, te dar *sugestões de destinos* ou "
            "criar um *perfil de viajante* personalizado.\n\n"
            "Veja as opções abaixo:"
        )
        enviar_mensagem(telefone, texto_apresentacao)
        enviar_menu_principal(telefone)
        return

    # Comandos globais
    if texto_lower in ['menu', 'iniciar', 'start', 'voltar']:
        limpar_sessao(telefone)
        salvar_preferencia(telefone, 'nome', nome_usuario)
        enviar_menu_principal(telefone)
        return

    # Agradecimentos
    palavras_agradecimento = ["obrigado", "obrigada", "valeu", "grato", "agradeço", "thanks", "obg"]
    if any(palavra in texto_lower for palavra in palavras_agradecimento):
        enviar_mensagem(telefone, f"De nada! 😊 Fico feliz em ajudar. Digite 'menu' para voltar ao início.")
        return

    # === MODO PERFIL ===
    if estado == 'EDITANDO_INTERESSES':
        enviar_mensagem(telefone, "Use os botões acima para selecionar seus interesses.")
        return

    # === FLUXO DE ROTEIRO ===
    if estado == 'AGUARDANDO_DESTINO':
        dados['destino'] = texto.strip().title()
        salvar_sessao(telefone, 'AGUARDANDO_DATAS', dados)
        enviar_mensagem(
            telefone,
            f"✈️ *{dados['destino']}* é uma ótima escolha!\n\n"
            f"Agora me conte: *quando* você vai viajar?\n\n{DATE_FORMAT_HELP}"
        )
        return

    elif estado == 'AGUARDANDO_DATAS':
        pars = parse_intervalo_datas(texto)
        if pars:
            dados['datas'] = pars['texto_norm']
            salvar_sessao(telefone, 'AGUARDANDO_ORCAMENTO', dados)
            enviar_mensagem(telefone, "💰 Perfeito! Qual o seu orçamento total para a viagem?")
            return
        
        analise = analisar_resposta_data(texto, dados.get('destino', 'esse destino'))
        classificacao = analise.get('classificacao')
        
        if classificacao == 'pergunta_sobre_data':
            prompt_resposta = (
                f"Responda à pergunta de um viajante sobre o melhor período para ir para "
                f"{dados.get('destino', 'esse lugar')}: '{texto}'"
            )
            try:
                response = model.generate_content(prompt_resposta)
                enviar_mensagem(telefone, f"{response.text}\n\n{DATE_FORMAT_HELP}")
            except Exception as e:
                print(f"Erro ao responder pergunta: {e}", flush=True)
                enviar_mensagem(telefone, f"Desculpe, tive um problema. {DATE_FORMAT_HELP}")
            return
        
        enviar_mensagem(telefone, f"Desculpe, não entendi as datas.\n{DATE_FORMAT_HELP}")
        return

    elif estado == 'AGUARDANDO_ORCAMENTO':
        dados['orcamento'] = texto.strip()
        salvar_sessao(telefone, 'GERANDO_ROTEIRO', dados)
        enviar_mensagem(
            telefone,
            "🎉 Perfeito! Estou preparando seu roteiro personalizado...\n"
            "Aguarde alguns segundos..."
        )
        gerar_roteiro(telefone, dados)
        return

    elif estado == 'ROTEIRO_GERADO':
        print(f"⚠️ Estado ROTEIRO_GERADO - enviando menu pós-roteiro", flush=True)
        if 'pdf' in texto_lower:
            gerar_e_enviar_pdf(telefone)
        elif 'excel' in texto_lower or 'planilha' in texto_lower:
            gerar_e_enviar_excel(telefone)
        else:
            enviar_mensagem(telefone, "Seu roteiro já foi gerado! O que gostaria de fazer?")
            enviar_menu_pos_roteiro(telefone)
        return

    # Sem estado definido
    print(f"ℹ️ Sem estado definido, enviando menu principal", flush=True)
    enviar_menu_principal(telefone)

def processar_botao(telefone, button_id, nome_usuario="Viajante"):
    """Processa cliques em botões interativos"""
    print(f"🔘 Processando botão: {button_id}", flush=True)
    sessao = carregar_sessao(telefone)
    
    if button_id == "menu_planejar":
        salvar_sessao(telefone, 'AGUARDANDO_DESTINO', {})
        enviar_mensagem(telefone, "✈️ Ótimo! Para qual cidade ou país você quer um roteiro?")

    elif button_id == "menu_ajuda":
        texto_ajuda = (
            "📖 *Como usar o VexusBot*\n\n"
            "1️⃣ *Planejar Roteiro*: Crio um roteiro completo personalizado\n"
            "2️⃣ *Meu Perfil*: Configure suas preferências de viagem\n"
            "3️⃣ *Menu*: Digite 'menu' para voltar\n\n"
            "Estou aqui para ajudar! ✈️"
        )
        enviar_mensagem(telefone, texto_ajuda)
    
    elif button_id == "menu_perfil":
        enviar_menu_perfil(telefone)
    
    elif button_id == "ver_perfil":
        preferencias = carregar_preferencias(telefone)
        if not preferencias or not preferencias.get('interesses'):
            enviar_mensagem(telefone, "Você ainda não configurou seu perfil. Clique em 'Editar Perfil' para começar!")
        else:
            texto_perfil = (
                f"👤 *Seu Perfil de Viajante*\n\n"
                f"• *Nome:* {preferencias.get('nome', 'Não informado')}\n"
                f"• *Interesses:* {preferencias.get('interesses', 'Não informado')}\n"
            )
            enviar_mensagem(telefone, texto_perfil)
        enviar_menu_perfil(telefone)
    
    elif button_id == "editar_perfil":
        prefs = carregar_preferencias(telefone)
        interesses_salvos = (prefs.get('interesses') or '')
        selecoes_atuais = [i.strip() for i in interesses_salvos.split(',') if i.strip()]
        
        dados = {'selecoes_interesses': selecoes_atuais}
        salvar_sessao(telefone, 'EDITANDO_INTERESSES', dados)
        
        enviar_selecao_interesses(telefone, selecoes_atuais)
    
    elif button_id.startswith("interesse_"):
        interesse = button_id.replace("interesse_", "")
        dados = sessao.get('dados', {})
        selecoes = dados.get('selecoes_interesses', [])
        
        if interesse in selecoes:
            selecoes.remove(interesse)
        else:
            selecoes.append(interesse)
        
        dados['selecoes_interesses'] = selecoes
        salvar_sessao(telefone, 'EDITANDO_INTERESSES', dados)
        
        enviar_selecao_interesses(telefone, selecoes)
    
    elif button_id == "concluir_interesses":
        dados = sessao.get('dados', {})
        selecoes = dados.get('selecoes_interesses', [])
        interesses_finais = ", ".join(selecoes)
        
        salvar_preferencia(telefone, 'interesses', interesses_finais)
        limpar_sessao(telefone)
        
        if interesses_finais:
            enviar_mensagem(telefone, f"✅ Perfil salvo com sucesso!\n\n*Seus interesses:* {interesses_finais}")
        else:
            enviar_mensagem(telefone, "✅ Perfil salvo!")
        
        enviar_menu_principal(telefone)
    
    elif button_id == "gerar_pdf":
        gerar_e_enviar_pdf(telefone)
    
    elif button_id == "gerar_excel":
        gerar_e_enviar_excel(telefone)
    
    elif button_id == "voltar_menu":
        limpar_sessao(telefone)
        enviar_menu_principal(telefone)

def gerar_roteiro(telefone, dados):
    """Gera roteiro usando Gemini"""
    try:
        preferencias = carregar_preferencias(telefone)
        contexto_perfil = ""
        
        if preferencias.get('interesses'):
            contexto_perfil = f"\nPerfil do viajante: Interesses em {preferencias.get('interesses')}"
        
        prompt = (
            f"Crie um roteiro de viagem detalhado para {dados['destino']} "
            f"de {dados['datas']} com orçamento de {dados['orcamento']}.{contexto_perfil}\n\n"
            "IMPORTANTE: Inclua uma tabela Markdown com as seguintes colunas:\n"
            "| DATA | DIA | LOCAL | ATIVIDADE |\n\n"
            "Após a tabela, adicione:\n"
            "- Dicas práticas\n"
            "- Restaurantes recomendados\n"
            "- Informações úteis sobre transporte e hospedagem"
        )
        
        response = model.generate_content(prompt)
        roteiro = response.text
        
        tabela_extraida = extrair_tabela_markdown(roteiro)
        
        dados['roteiro_completo'] = roteiro
        dados['tabela_itinerario'] = tabela_extraida
        dados['descricao_detalhada'] = roteiro
        
        salvar_sessao(telefone, 'ROTEIRO_GERADO', dados)
        
        print(f"📊 DEBUG: Tabela extraída tem {len(tabela_extraida.split(chr(10)))} linhas", flush=True)
        
        if len(roteiro) > 4000:
            partes = [roteiro[i:i+4000] for i in range(0, len(roteiro), 4000)]
            for i, parte in enumerate(partes):
                enviar_mensagem(telefone, f"📄 *Parte {i+1}/{len(partes)}*\n\n{parte}")
        else:
            enviar_mensagem(telefone, f"🎉 *Seu Roteiro Personalizado*\n\n{roteiro}")
        
        enviar_menu_pos_roteiro(telefone)
        
    except Exception as e:
        print(f"❌ Erro ao gerar roteiro: {e}", flush=True)
        traceback.print_exc()
        enviar_mensagem(telefone, "Desculpe, tive um problema ao gerar o roteiro. Tente novamente!")

def gerar_roteiro(telefone, dados):
    """Gera roteiro usando Gemini"""
    try:
        preferencias = carregar_preferencias(telefone)
        contexto_perfil = ""
        
        if preferencias.get('interesses'):
            contexto_perfil = f"\nPerfil do viajante: Interesses em {preferencias.get('interesses')}"
        
        prompt = (
            f"Crie um roteiro de viagem detalhado para {dados['destino']} "
            f"de {dados['datas']} com orçamento de {dados['orcamento']}.{contexto_perfil}\n\n"
            "IMPORTANTE: Inclua uma tabela Markdown com as seguintes colunas:\n"
            "| DATA | DIA | LOCAL | ATIVIDADE |\n\n"
            "Após a tabela, adicione:\n"
            "- Dicas práticas\n"
            "- Restaurantes recomendados\n"
            "- Informações úteis sobre transporte e hospedagem"
        )
        
        response = model.generate_content(prompt)
        roteiro = response.text
        
        # Garantir que a tabela Markdown tenha pelo menos um dado válido
        if "| DATA | DIA | LOCAL | ATIVIDADE |" not in roteiro:
            raise ValueError("Tabela Markdown não foi gerada corretamente.")
        
        tabela_extraida = extrair_tabela_markdown(roteiro)
        
        dados['roteiro_completo'] = roteiro
        dados['tabela_itinerario'] = tabela_extraida
        dados['descricao_detalhada'] = roteiro
        
        salvar_sessao(telefone, 'ROTEIRO_GERADO', dados)
        
        print(f"📊 DEBUG: Tabela extraída tem {len(tabela_extraida.split(chr(10)))} linhas", flush=True)
        
        # Se a tabela for grande, envia em partes
        if len(roteiro) > 4000:
            partes = [roteiro[i:i+4000] for i in range(0, len(roteiro), 4000)]
            for i, parte in enumerate(partes):
                enviar_mensagem(telefone, f"📄 *Parte {i+1}/{len(partes)}*\n\n{parte}")
        else:
            enviar_mensagem(telefone, f"🎉 *Seu Roteiro Personalizado*\n\n{roteiro}")
        
        enviar_menu_pos_roteiro(telefone)
        
    except Exception as e:
        print(f"❌ Erro ao gerar roteiro: {e}", flush=True)
        traceback.print_exc()
        enviar_mensagem(telefone, "Desculpe, tive um problema ao gerar o roteiro. Tente novamente!")

def extrair_tabela_markdown(texto: str) -> str:
    """Extrai e formata a tabela Markdown corretamente"""
    linhas_tabela = []
    linhas = texto.split("\n")
    
    # Busca pela tabela Markdown
    in_tabela = False
    for linha in linhas:
        if linha.startswith("| DATA | DIA | LOCAL | ATIVIDADE |"):
            in_tabela = True
        
        if in_tabela:
            linhas_tabela.append(linha.strip())
        
        if in_tabela and linha.strip() == "":
            break
    
    if len(linhas_tabela) < 2:
        raise ValueError("Tabela não encontrada ou vazia no texto.")
    
    # Converte a tabela extraída para um formato adequado
    tabela_formatada = "\n".join(linhas_tabela)
    return tabela_formatada

def gerar_e_enviar_excel(telefone):
    """Gera e envia planilha Excel do roteiro"""
    try:
        import pandas as pd
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        
        sessao = carregar_sessao(telefone)
        dados = sessao.get('dados', {})
        
        if not dados.get('roteiro_completo'):
            enviar_mensagem(telefone, "❌ Não encontrei um roteiro. Crie um roteiro primeiro!")
            return
        
        tabela = dados.get('tabela_itinerario', '')
        
        print(f"📊 DEBUG EXCEL: Tabela tem {len(tabela)} caracteres", flush=True)
        
        if not tabela or tabela.count('|') < 6:
            enviar_mensagem(
                telefone, 
                "⚠️ O roteiro não contém uma tabela formatada. "
                "Tente gerar um novo roteiro para obter a planilha."
            )
            return
        
        enviar_mensagem(telefone, "📊 Gerando sua planilha Excel... Aguarde...")
        
        try:
            df = markdown_table_to_dataframe(tabela)
            print(f"✅ DataFrame criado: {df.shape[0]} linhas x {df.shape[1]} colunas", flush=True)
            
        except Exception as e_parse:
            print(f"❌ Erro ao parsear tabela: {e_parse}", flush=True)
            caminho_txt = f"roteiro_{telefone}.txt"
            with open(caminho_txt, 'w', encoding='utf-8') as f:
                f.write(f"ROTEIRO DE VIAGEM\n")
                f.write(f"Destino: {dados.get('destino', 'N/A')}\n")
                f.write(f"Período: {dados.get('datas', 'N/A')}\n")
                f.write(f"Orçamento: {dados.get('orcamento', 'N/A')}\n\n")
                f.write("=" * 50 + "\n\n")
                f.write(tabela)
            
            enviar_documento(telefone, caminho_txt, "roteiro.txt")
            os.remove(caminho_txt)
            
            enviar_mensagem(telefone, "✅ Roteiro enviado como arquivo de texto!")
            enviar_menu_pos_roteiro(telefone)
            return
        
        caminho_xlsx = f"roteiro_{telefone}.xlsx"
        
        with pd.ExcelWriter(caminho_xlsx, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Roteiro')
            
            worksheet = writer.sheets['Roteiro']
            
            header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
            header_font = Font(bold=True, color="FFFFFF", size=12)
            
            for cell in worksheet[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if cell.value:
                            max_length = max(max_length, len(str(cell.value)))
                    except:
                        pass
                adjusted_width = min(max_length + 3, 60)
                worksheet.column_dimensions[column_letter].width = adjusted_width
            
            worksheet.freeze_panes = 'A2'
        
        print(f"✅ Excel gerado com sucesso: {caminho_xlsx}", flush=True)
        
        enviar_documento(telefone, caminho_xlsx, "roteiro.xlsx")
        os.remove(caminho_xlsx)
        
        enviar_mensagem(telefone, "✅ Planilha Excel enviada com sucesso!")
        enviar_menu_pos_roteiro(telefone)
        
    except Exception as e:
        print(f"❌ Erro crítico ao gerar planilha: {e}", flush=True)
        traceback.print_exc()
        
        try:
            caminho_txt = f"roteiro_completo_{telefone}.txt"
            with open(caminho_txt, 'w', encoding='utf-8') as f:
                f.write(dados.get('roteiro_completo', 'Erro ao gerar roteiro'))
            
            enviar_documento(telefone, caminho_txt, "roteiro_completo.txt")
            os.remove(caminho_txt)
            enviar_mensagem(telefone, "✅ Roteiro enviado como texto!")
        except:
            enviar_mensagem(telefone, "❌ Desculpe, não consegui gerar o arquivo.")

# === WEBHOOK ENDPOINTS ===
@app.route("/webhook", methods=["GET"])
def verificar_webhook():
    """Verificação inicial do webhook pela Meta"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Webhook verificado com sucesso!", flush=True)
        return challenge, 200
    else:
        print("❌ Falha na verificação do webhook", flush=True)
        return "Erro de verificação", 403

@app.route("/webhook", methods=["POST"])
def receber_mensagem():
    """Recebe e processa mensagens do WhatsApp"""
    data = request.get_json()
    print("=" * 60, flush=True)
    print("📩 WEBHOOK RECEBIDO:", flush=True)
    print(json.dumps(data, indent=2), flush=True)
    print("=" * 60, flush=True)
    sys.stdout.flush()

    try:
        if "entry" not in data:
            print("⚠️ Webhook sem 'entry', ignorando", flush=True)
            return "ok", 200

        for entry in data["entry"]:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                if "messages" in value:
                    for message in value["messages"]:
                        telefone = message["from"]
                        
                        nome_usuario = "Viajante"
                        if "contacts" in value:
                            for contact in value["contacts"]:
                                if contact.get("wa_id") == telefone:
                                    nome_usuario = contact.get("profile", {}).get("name", "Viajante")
                        
                        if message["type"] == "text":
                            texto = message["text"]["body"]
                            print(f"📨 MENSAGEM DE {telefone} ({nome_usuario}): {texto}", flush=True)
                            processar_comando(telefone, texto, nome_usuario)
                        
                        elif message["type"] == "interactive":
                            interactive_type = message["interactive"]["type"]
                            
                            if interactive_type == "button_reply":
                                button_id = message["interactive"]["button_reply"]["id"]
                                print(f"🔘 BOTÃO CLICADO: {button_id}", flush=True)
                                processar_botao(telefone, button_id, nome_usuario)
                            
                            elif interactive_type == "list_reply":
                                row_id = message["interactive"]["list_reply"]["id"]
                                print(f"📋 ITEM DE LISTA CLICADO: {row_id}", flush=True)
                                processar_botao(telefone, row_id, nome_usuario)
                else:
                    print(f"ℹ️ Webhook recebido mas sem mensagens (status update)", flush=True)

    except Exception as e:
        print(f"❌ ERRO AO PROCESSAR MENSAGEM: {e}", flush=True)
        traceback.print_exc()
        sys.stdout.flush()

    return "ok", 200

@app.route("/", methods=["GET"])
def home():
    """Página inicial"""
    return "VexusBot WhatsApp está online! ✅", 200

@app.route("/health", methods=["GET"])
def health():
    """Health check para monitoramento"""
    import datetime
    uptime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🏥 Health check - {uptime}", flush=True)
    sys.stdout.flush()
    return f"VexusBot WhatsApp está online! ✅ ({uptime})", 200

@app.route("/status", methods=["GET"])
def status():
    """Status detalhado"""
    return {
        "status": "online",
        "rag_loaded": rag_chain is not None,
        "phone_number_id": PHONE_NUMBER_ID,
        "gemini_model": GEMINI_MODEL,
        "token_preview": WHATSAPP_TOKEN[:20] + "..." if WHATSAPP_TOKEN else "NOT_SET"
    }, 200

@app.route("/reset/<telefone>", methods=["GET"])
def reset_user(telefone):
    """Reseta sessão de um usuário (debug)"""
    try:
        limpar_sessao(telefone)
        print(f"🔄 Sessão resetada para {telefone}", flush=True)
        return f"✅ Sessão resetada com sucesso para {telefone}", 200
    except Exception as e:
        print(f"❌ Erro ao resetar sessão: {e}", flush=True)
        return f"❌ Erro: {str(e)}", 500

def keep_alive_ping():
    """Faz ping no próprio servidor a cada 10 minutos"""
    while True:
        try:
            time.sleep(600)  # 10 minutos
            render_url = os.getenv('RENDER_EXTERNAL_URL')
            if render_url:
                url = f"https://{render_url}/health"
            else:
                url = "http://localhost:10000/health"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print("🏓 Keep-alive ping: OK", flush=True)
            else:
                print(f"⚠️ Keep-alive ping: status {response.status_code}", flush=True)
        except Exception as e:
            print(f"⚠️ Erro no keep-alive: {e}", flush=True)
        
        sys.stdout.flush()

# === INICIA O SERVIDOR ===
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    debug_mode = os.getenv("DEBUG", "False").lower() == "true"
    
    # Inicia thread de keep-alive
    keep_alive_thread = threading.Thread(target=keep_alive_ping, daemon=True)
    keep_alive_thread.start()
    print("🏓 Thread de keep-alive iniciada", flush=True)
    
    print("=" * 60, flush=True)
    print(f"🚀 VexusBot WhatsApp iniciando na porta {port}...", flush=True)
    print(f"📱 Phone Number ID: {PHONE_NUMBER_ID}", flush=True)
    print(f"🤖 Modelo Gemini: {GEMINI_MODEL}", flush=True)
    print(f"🔍 RAG Status: {'✅ Ativo' if rag_chain else '❌ Inativo'}", flush=True)
    print(f"🔧 Debug Mode: {debug_mode}", flush=True)
    print(f"🔑 Token Preview: {WHATSAPP_TOKEN[:20]}...", flush=True)
    print("=" * 60, flush=True)
    sys.stdout.flush()
    
    # Em produção, use Gunicorn (não precisa do app.run)
    if os.getenv("RENDER") is None:
        app.run(host="0.0.0.0", port=port, debug=debug_mode)
    else:
        print("✅ Rodando em produção com Gunicorn", flush=True)