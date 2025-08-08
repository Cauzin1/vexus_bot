# app.py - Versão final completa

import os
import re
import traceback
import asyncio
from flask import Flask, request, send_from_directory
from dotenv import load_dotenv
import google.generativeai as genai

import telegram
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- UTILS (Copiado para dentro do app.py para simplificar) ---
def validar_destino(texto: str) -> bool:
    paises = ["italia", "franca", "espanha", "portugal", "alemanha"]
    return texto.lower().strip() in paises

def validar_data(texto: str) -> bool:
    return re.match(r"^\d{1,2}/\d{1,2}\s*a\s*\d{1,2}/\d{1,2}$", texto.strip()) is not None

def validar_orcamento(texto: str) -> bool:
    return any(char.isdigit() for char in texto)

# --- Configuração ---
load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
app = Flask(__name__)
sessoes = {}

# --- Inicialização dos Serviços ---
try:
    if not GEMINI_KEY: raise ValueError("GEMINI_KEY não encontrada!")
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini configurado com sucesso!")
except Exception as e:
    model = None
    print(f"❌ Erro na configuração do Gemini: {e}")

if not TELEGRAM_TOKEN: raise ValueError("TELEGRAM_TOKEN não encontrado!")
application = Application.builder().token(TELEGRAM_TOKEN).build()


# --- Lógica do Bot (Cérebro) ---
def processar_mensagem(session_id: str, texto: str) -> str:
    # Lógica de estados simplificada para garantir funcionamento
    if session_id not in sessoes:
        sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO'}
    
    estado = sessoes[session_id].get('estado')
    texto_normalizado = texto.strip().lower()

    if texto_normalizado == "reiniciar":
        sessoes[session_id]['estado'] = 'AGUARDANDO_DESTINO'
        return "🔄 Certo! Vamos recomeçar. Para qual país da Europa você quer viajar?"

    if estado == 'AGUARDANDO_DESTINO':
        if validar_destino(texto_normalizado):
            sessoes[session_id]['estado'] = 'FEITO'
            return f"Ótima escolha! O roteiro para {texto.title()} seria gerado aqui. Para reiniciar, digite 'reiniciar'."
        else:
            return "❌ País não reconhecido. Tente Itália, França, Espanha, Portugal ou Alemanha."
    
    return "Seu roteiro foi gerado. Para começar um novo, digite 'reiniciar'."


# --- Gerenciador de Mensagens do Telegram ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = str(update.message.chat_id)
    texto_recebido = update.message.text
    
    try:
        # Primeiro, um "eco" para garantir que o bot está vivo
        await context.bot.send_message(chat_id=session_id, text=f"Eco: {texto_recebido}")
        
        # Agora, a lógica real
        if session_id not in sessoes:
            sessoes[session_id] = {'estado': 'AGUARDANDO_DESTINO'}
            resposta = ("🌟 Olá! Eu sou o vIAjante.\n\nPara começar, para qual país você quer viajar?")
        else:
            resposta = processar_mensagem(session_id, texto_recebido)

        await context.bot.send_message(
            chat_id=session_id, text=resposta, parse_mode=telegram.constants.ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"!!!!!!!!!! ERRO NO HANDLE: {e} !!!!!!!!!!"); traceback.print_exc()
        await context.bot.send_message(chat_id=session_id, text="Ocorreu um erro interno.")

application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# --- Rotas Flask ---
@app.route('/telegram_webhook', methods=['POST'])
async def telegram_webhook():
    await application.update_queue.put(Update.de_json(request.get_json(force=True), application.bot))
    return "ok", 200

@app.route('/')
def index(): return "Servidor do vIAjante está no ar!"