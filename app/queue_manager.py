import os
from redis import Redis
from celery import Celery
import json
import asyncio

celery_app = Celery('queue_tasks',
                    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
                    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'))

class QueueManager:
    """Gestionnaire de file d'attente avec Redis."""

    def __init__(self):
        self.redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        self.pubsub = self.redis.pubsub()
        self.max_active_users = int(os.getenv('MAX_ACTIVE_USERS', 50))
        self.session_duration = int(os.getenv('SESSION_DURATION', 1200))
        self.draft_duration = int(os.getenv('DRAFT_DURATION', 300))

    async def publish_status(self, user_id: str, position: int, status: str = "waiting"):
        """Publie le statut de l'utilisateur dans la file d'attente."""
        message = {
            "user_id": user_id,
            "status": status,
            "position": position
        }
        self.redis.publish(f'queue_status:{user_id}', json.dumps(message))

    async def add_to_queue(self, user_id: str) -> int:
        """Ajoute un utilisateur à la file d'attente principale."""
        if not self.redis.sismember('active_users', user_id) and not self.redis.sismember('draft_users', user_id):
            with self.redis.pipeline() as pipe:
                pipe.rpush('waiting_queue', user_id)
                pipe.llen('waiting_queue')
                results = pipe.execute()
                position = results[1]

            await self.publish_status(user_id, position)
            
            # Vérifie les slots disponibles de manière asynchrone
            asyncio.create_task(self.check_available_slots())
            return position
        return 0

    async def check_available_slots(self):
        """Vérifie et attribue les slots disponibles."""
        active_count = self.redis.scard('active_users')
        draft_count = self.redis.scard('draft_users')
        available_slots = self.max_active_users - (active_count + draft_count)

        if available_slots > 0:
            for _ in range(available_slots):
                user_id = self.redis.lindex('waiting_queue', 0)
                if user_id:
                    await self.offer_slot(user_id)

    async def offer_slot(self, user_id: str):
        """Offre un slot à un utilisateur."""
        with self.redis.pipeline() as pipe:
            pipe.lpop('waiting_queue')
            pipe.sadd('draft_users', user_id)
            pipe.setex(f'draft:{user_id}', self.draft_duration, '1')
            pipe.execute()

        handle_draft_expiration.apply_async(args=[user_id], countdown=self.draft_duration)
        await self.publish_status(user_id, 0, status="slot_available")

    async def confirm_connection(self, user_id: str) -> bool:
        """Confirme la connexion d'un utilisateur."""
        if self.redis.sismember('draft_users', user_id) and self.redis.exists(f'draft:{user_id}'):
            with self.redis.pipeline() as pipe:
                pipe.srem('draft_users', user_id)
                pipe.sadd('active_users', user_id)
                pipe.delete(f'draft:{user_id}')
                pipe.setex(f'session:{user_id}', self.session_duration, '1')
                pipe.execute()

            cleanup_session.apply_async(args=[user_id], countdown=self.session_duration)
            
            status = {
                "user_id": user_id,
                "status": "connected",
                "session_duration": self.session_duration
            }
            self.redis.publish(f'queue_status:{user_id}', json.dumps(status))
            return True
        return False

    async def requeue_user(self, user_id: str):
        """Remet l'utilisateur dans la file d'attente."""
        queue_length = self.redis.llen('waiting_queue')
        new_position = max(1, int(queue_length * 0.25))
        
        temp_list = self.redis.lrange('waiting_queue', 0, -1)
        temp_list.insert(new_position, user_id)
        
        with self.redis.pipeline() as pipe:
            pipe.delete('waiting_queue')
            pipe.rpush('waiting_queue', *temp_list)
            pipe.srem('draft_users', user_id)
            pipe.delete(f'draft:{user_id}')
            pipe.execute()

        await self.publish_status(user_id, new_position)

@celery_app.task
def handle_draft_expiration(user_id: str):
    """Gère l'expiration d'un draft."""
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    if redis.sismember('draft_users', user_id):
        queue_manager = QueueManager()
        asyncio.run(queue_manager.requeue_user(user_id))

@celery_app.task
def cleanup_session(user_id: str):
    """Nettoie la session expirée."""
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    redis.srem('active_users', user_id)
    redis.delete(f'session:{user_id}') 