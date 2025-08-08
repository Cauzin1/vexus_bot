# app.py - TESTE FINAL: BOT ECO

import os
import traceback
from flask import Flask, request
from dotenv import load_dotenv

import telegram
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# --- Configuração ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
app = Flask(__name__)

# --- Lógica do Bot Eco ---
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN não foi encontrado nas variáveis de ambiente!")

# Constrói a aplicação do bot com o token
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Esta é a única função do bot: responder com a mesma mensagem
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_id = str(update.message.chat_id)
    texto_recebido = update.message.text
    
    # Imprime no log para sabermos que a mensagem chegou
    print(f"--- MENSAGEM RECEBIDA --- Chat ID: {session_id}, Texto: '{texto_recebido}'")
    
    try:
        # Tenta enviar a mensagem de volta
        await context.bot.send_message(
            chat_id=session_id,
            text=f"Eco: {texto_recebido}" # Simplesmente responde com a mensagem recebida
        )
        print(f"--- RESPOSTA ECO ENVIADA COM SUCESSO ---")
    except Exception as e:
        # Se falhar ao enviar, o erro aparecerá aqui
        print(f"!!!!!!!!!! ERRO AO ENVIAR MENSAGEM DE ECO: {e} !!!!!!!!!!")
        traceback.print_exc()

# Adiciona o gerenciador de mensagens à aplicação
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))


# --- Rotas Flask ---
@app.route('/telegram_webhook', methods=['POST'])
async def telegram_webhook():
    # Processa a atualização recebida do Telegram
    await application.update_queue.put(Update.de_json(request.get_json(force=True), application.bot))
    return "ok", 200

# Rota para configurar o webhook (você chama uma vez após o deploy)
@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    if WEBHOOK_URL:
        webhook_full_url = f"{WEBHOOK_URL}/telegram_webhook"
        await application.bot.set_webhook(webhook_full_url)
        return f"Webhook configurado para: {webhook_full_url}"
    return "WEBHOOK_URL não configurado.", 500

@app.route('/')
def index():
    # Uma página simples para sabermos que o servidor está no ar
    return "Servidor do Bot Eco está no ar!", 200