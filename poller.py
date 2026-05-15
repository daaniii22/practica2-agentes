import os
import time
import requests

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN no definido.")
    exit(1)

N8N_WEBHOOK_URL = "http://n8n:5678/webhook/chat"
OFFSET = 0

print(f"Iniciando Telegram Poller...")
print(f"Reenviando mensajes a: {N8N_WEBHOOK_URL}")

# Delete any existing webhook to enable getUpdates
requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")

while True:
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={OFFSET}&timeout=30"
        resp = requests.get(url, timeout=35).json()
        
        if resp.get("ok"):
            for update in resp.get("result", []):
                OFFSET = update["update_id"] + 1
                
                if "message" in update and "text" in update["message"]:
                    print(f"Mensaje recibido de {update['message']['chat']['id']}: {update['message']['text']}")
                    
                    # Forward to n8n
                    try:
                        n8n_resp = requests.post("http://n8n:5678/webhook-test/chat", json=update, timeout=10)
                        if n8n_resp.status_code == 404:
                            n8n_resp = requests.post("http://n8n:5678/webhook/chat", json=update, timeout=10)
                        print(f"Reenviado a n8n. Status: {n8n_resp.status_code}")
                    except Exception as e:
                        print(f"Error reenviando a n8n: {e}")
                        
    except Exception as e:
        print(f"Error en el poller: {e}")
        time.sleep(5)
    
    time.sleep(1)
