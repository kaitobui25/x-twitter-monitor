
import sys
import logging
from src.notifiers.telegram import TelegramNotifier, TelegramMessage

def test_send(token, chat_id):
    # Setup logging to see what's happening
    logging.basicConfig(level=logging.INFO)
    
    print(f"Initializing TelegramNotifier with token: {token[:10]}...")
    try:
        TelegramNotifier.init(token=token, logger_name='test-telegram')
        
        message_text = "🚀 Test message from X-Twitter-Monitor (httpx version)\nIf you see this, the notification system is working perfectly!"
        print(f"Sending test message to chat_id: {chat_id}...")
        
        # Test direct send_message (through queue)
        msg = TelegramMessage(chat_id_list=[int(chat_id)], text=message_text)
        TelegramNotifier.put_message_into_queue(msg)
        
        print("Message put into queue. Waiting a few seconds for worker to process...")
        import time
        time.sleep(5)
        print("Done. Check your Telegram!")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_telegram.py <BOT_TOKEN> <CHAT_ID>")
    else:
        test_send(sys.argv[1], sys.argv[2])
