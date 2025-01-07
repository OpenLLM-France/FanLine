import redis
import json
import asyncio

class QueueClient:
    def __init__(self, user_id: str):
        print(f"Initialisation du client pour l'utilisateur {user_id}")
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
        self.pubsub = self.redis.pubsub()
        self.user_id = user_id
        print(f"Abonnement au canal queue_status:{user_id}")
        self.pubsub.subscribe(f'queue_status:{user_id}')

    async def listen_for_updates(self):
        print("Démarrage de l'écoute des messages...")
        while True:
            message = self.pubsub.get_message()
            if message:
                print(f"Message reçu: {message}")
                if message['type'] == 'message':
                    status = json.loads(message['data'])
                    if status.get('status') == 'connected':
                        print(f"Connecté ! Session de {status['session_duration']} secondes")
                    else:
                        print(f"Position dans la file: {status['position']}")
                        print(f"Slots actifs: {status['active_slots']}/{status['total_slots']}")
            await asyncio.sleep(0.1)

async def main():
    client = QueueClient("user123")
    await client.listen_for_updates()

if __name__ == "__main__":
    print("Démarrage du client...")
    asyncio.run(main()) 