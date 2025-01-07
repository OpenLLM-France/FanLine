import os
from redis.asyncio import Redis
from celery import Celery
import json
import asyncio
import time

celery_app = Celery('queue_tasks',
                    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
                    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'))

class QueueManager:
    """Gestionnaire de file d'attente avec Redis."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.max_active_users = int(os.getenv('MAX_ACTIVE_USERS', 50))
        self.session_duration = int(os.getenv('SESSION_DURATION', 1200))
        self.draft_duration = int(os.getenv('DRAFT_DURATION', 300))
        self._slot_check_task = None
        self._stop_slot_check = False

    async def _verify_queue_state(self, user_id: str, expected_state: dict) -> bool:
        """Vérifie l'état de la file d'attente pour un utilisateur.
        
        Args:
            user_id: L'identifiant de l'utilisateur
            expected_state: Dictionnaire contenant les états attendus:
                - in_queue: bool - Si l'utilisateur doit être dans queued_users
                - in_waiting: bool - Si l'utilisateur doit être dans waiting_queue
                - in_draft: bool - Si l'utilisateur doit être dans draft_users
                - in_active: bool - Si l'utilisateur doit être dans active_users
        """
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('queued_users', user_id)
                pipe.lpos('waiting_queue', user_id)
                pipe.sismember('draft_users', user_id)
                pipe.sismember('active_users', user_id)
                results = await pipe.execute()
                
                actual_state = {
                    'in_queue': bool(results[0]),
                    'in_waiting': results[1] is not None,
                    'in_draft': bool(results[2]),
                    'in_active': bool(results[3])
                }
                

                for key, expected in expected_state.items():
                    if actual_state[key] != expected:
                        print(f"❌ Incohérence détectée - {key}: attendu={expected}, actuel={actual_state[key]}")
                        return False
                        
                print(f"✅ État vérifié - {actual_state}")
                return True
                
        except Exception as e:
            print(f"❌ Erreur lors de la vérification: {str(e)}")
            return False

    async def _check_slots_after_add(self):
        """Vérifie les slots disponibles de manière asynchrone."""
        try:

            active_count = await self.redis.scard('active_users')
            draft_count = await self.redis.scard('draft_users')
            available_slots = self.max_active_users - (active_count + draft_count)

            if available_slots > 0:

                users = await self.redis.lrange('waiting_queue', 0, available_slots - 1)
                for user_id in users:

                    is_queued = await self.redis.sismember('queued_users', user_id)
                    if is_queued:
                        await self.offer_slot(user_id)
            return True
        except Exception as e:
            print(f"❌ Erreur lors de la vérification des slots : {str(e)}")
            return False

    async def start_slot_checker(self, check_interval: float = 1.0):
        """Démarre la vérification périodique des slots disponibles."""
        if self._slot_check_task is None:
            self._stop_slot_check = False
            self._slot_check_task = asyncio.create_task(self._periodic_slot_check(check_interval))

    async def stop_slot_checker(self):
        """Arrête la vérification périodique des slots."""
        if self._slot_check_task is not None:
            self._stop_slot_check = True
            await self._slot_check_task
            self._slot_check_task = None

    async def _periodic_slot_check(self, interval: float):
        """Vérifie périodiquement les slots disponibles."""
        while not self._stop_slot_check:
            try:
                await self._check_slots_after_add()
                await asyncio.sleep(interval)
            except Exception as e:
                print(f"❌ Erreur dans la vérification périodique des slots : {str(e)}")
                await asyncio.sleep(interval)  # Continuer malgré l'erreur

    async def add_to_queue(self, user_id: str) -> int:
        """Ajoute un utilisateur à la file d'attente principale."""
        try:

            async with self.redis.pipeline(transaction=True) as pipe:

                pipe.sismember('queued_users', user_id)
                pipe.sismember('active_users', user_id)
                pipe.sismember('draft_users', user_id)
                results = await pipe.execute()
                is_queued, is_active, is_draft = results
                
                print(f"État initial - is_queued: {is_queued}, is_active: {is_active}, is_draft: {is_draft}")
                
                # Si l'utilisateur n'est ni dans la file d'attente ni actif
                if not (is_queued or is_active):
                    # Nouvelle transaction pour l'ajout
                    pipe.multi()
                    # Ajouter à la file d'attente et au set des utilisateurs en attente
                    pipe.rpush('waiting_queue', user_id)
                    pipe.sadd('queued_users', user_id)
                    
                    # Si l'utilisateur était en draft, le retirer
                    if is_draft:
                        pipe.srem('draft_users', user_id)
                        pipe.delete(f'draft:{user_id}')
                    
                    # Obtenir la position dans la file
                    pipe.llen('waiting_queue')
                    
                    # Exécuter la transaction
                    results = await pipe.execute()
                    print(f"Résultats de la transaction: {results}")
                    
                    # La dernière valeur est la longueur de la file = position
                    position = results[-1]
                    
                    # Vérifier l'état après l'opération
                    expected_state = {
                        'in_queue': True,
                        'in_waiting': True,
                        'in_draft': False,
                        'in_active': False
                    }
                    if not await self._verify_queue_state(user_id, expected_state):
                        raise Exception("État incohérent après l'ajout à la file")
                    
                    return position
                
            return 0
                
        except Exception as e:
            print(f"Erreur lors de l'ajout à la file : {str(e)}")

            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lrem('waiting_queue', 0, user_id)
                pipe.srem('queued_users', user_id)
                await pipe.execute()
                
                # Vérifier le nettoyage
                expected_state = {
                    'in_queue': False,
                    'in_waiting': False,
                    'in_draft': False,
                    'in_active': False
                }
                await self._verify_queue_state(user_id, expected_state)
            return 0

    async def remove_from_queue(self, user_id: str) -> bool:
        """Retire un utilisateur de la file d'attente."""
        try:
            is_queued = await self.redis.sismember('queued_users', user_id)
            if is_queued:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.lrem('waiting_queue', 0, user_id)
                    pipe.srem('queued_users', user_id)
                    await pipe.execute()
                    
                    # Vérifier l'état après suppression
                    expected_state = {
                        'in_queue': False,
                        'in_waiting': False,
                        'in_draft': False,
                        'in_active': False
                    }
                    if not await self._verify_queue_state(user_id, expected_state):
                        raise Exception("État incohérent après la suppression")
                    
                return True
            return False
        except Exception as e:
            print(f"Erreur lors de la suppression : {str(e)}")
            return False

    async def check_available_slots(self):
        """Vérifie et attribue les slots disponibles."""
        active_count = await self.redis.scard('active_users')
        draft_count = await self.redis.scard('draft_users')
        available_slots = self.max_active_users - (active_count + draft_count)

        if available_slots > 0:
            for _ in range(available_slots):
                user_id = await self.redis.lindex('waiting_queue', 0)
                if user_id:
                    await self.offer_slot(user_id)

    async def offer_slot(self, user_id: str):
        """Offre un slot à un utilisateur."""
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpop('waiting_queue')
                pipe.srem('queued_users', user_id)
                pipe.sadd('draft_users', user_id)
                pipe.setex(f'draft:{user_id}', self.draft_duration, '1')
                await pipe.execute()

                # Vérifier l'état après l'offre du slot
                expected_state = {
                    'in_queue': False,
                    'in_waiting': False,
                    'in_draft': True,
                    'in_active': False
                }
                if not await self._verify_queue_state(user_id, expected_state):
                    raise Exception("État incohérent après l'offre du slot")

            # Publier la notification de draft disponible
            await self.redis.publish(f'queue_status:{user_id}', 
                json.dumps({
                    "status": "draft",
                    "duration": self.draft_duration
                })
            )
        except Exception as e:
            print(f"Erreur lors de l'offre du slot : {str(e)}")
            # Nettoyage en cas d'erreur
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.srem('draft_users', user_id)
                pipe.delete(f'draft:{user_id}')
                await pipe.execute()

    async def confirm_connection(self, user_id: str) -> bool:
        """Confirme la connexion d'un utilisateur."""
        try:
            is_draft = await self.redis.sismember('draft_users', user_id)
            has_draft = await self.redis.exists(f'draft:{user_id}')
            
            if is_draft and has_draft:
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.srem('draft_users', user_id)
                    pipe.sadd('active_users', user_id)
                    pipe.delete(f'draft:{user_id}')
                    pipe.setex(f'session:{user_id}', self.session_duration, '1')
                    await pipe.execute()

                    # Vérifier l'état après confirmation
                    expected_state = {
                        'in_queue': False,
                        'in_waiting': False,
                        'in_draft': False,
                        'in_active': True
                    }
                    if not await self._verify_queue_state(user_id, expected_state):
                        raise Exception("État incohérent après la confirmation")

                # Publier la notification de connexion confirmée
                await self.redis.publish(f'queue_status:{user_id}', 
                    json.dumps({
                        "status": "connected",
                        "session_duration": self.session_duration
                    })
                )
                return True
            return False
        except Exception as e:
            print(f"Erreur lors de la confirmation : {str(e)}")
            return False

    async def extend_session(self, user_id: str) -> bool:
        """Prolonge la session d'un utilisateur actif."""
        is_active = await self.redis.sismember('active_users', user_id)
        if is_active:
            await self.redis.setex(f'session:{user_id}', self.session_duration, '1')
            return True
        return False

    async def get_user_status(self, user_id: str) -> dict:
        """Obtient le statut d'un utilisateur."""
        is_queued = await self.redis.sismember('queued_users', user_id)
        if is_queued:
            position = await self.redis.lpos('waiting_queue', user_id)
            return {"status": "waiting", "position": position + 1 if position is not None else 0}
        
        is_active = await self.redis.sismember('active_users', user_id)
        if is_active:
            return {"status": "connected"}
        
        is_draft = await self.redis.sismember('draft_users', user_id)
        if is_draft:
            #@-> ADD POSITION DATA
            return {"status": "draft"}
        
        return None

    async def get_metrics(self) -> dict:
        """Obtient les métriques de la file d'attente."""
        #@-> ADD draft information
        async with self.redis.pipeline(transaction=True) as pipe:
            await pipe.scard('active_users')
            await pipe.llen('waiting_queue')
            results = await pipe.execute()
            
        return {
            "active_users": results[0],
            "waiting_users": results[1],
            "total_slots": self.max_active_users
        }

    async def get_timers(self, user_id: str) -> dict:
        """Obtient les timers actifs et démarre la tâche de mise à jour"""
        try:
            timers = {}
            
            # check session active
            is_active = await self.redis.sismember('active_users', user_id)
            if is_active:
                session_ttl = await self.redis.ttl(f'session:{user_id}')
                if session_ttl > 0:
                    timers['session'] = {
                        'ttl': session_ttl,
                        'channel': f'timer:session:{user_id}'
                    }
                    # start update session timer
                    update_timer_channel.delay(
                        timers['session']['channel'], 
                        session_ttl,
                        'session'
                    )
                    
            # check draft active
            is_draft = await self.redis.sismember('draft_users', user_id)
            if is_draft:
                draft_ttl = await self.redis.ttl(f'draft:{user_id}')
                if draft_ttl > 0:
                    timers['draft'] = {
                        'ttl': draft_ttl,
                        'channel': f'timer:draft:{user_id}'
                    }
                    # start update draft timer
                    update_timer_channel.delay(
                        timers['draft']['channel'], 
                        draft_ttl,
                        'draft'
                    )
                    
            return timers
            
        except Exception as e:
            print(f"Erreur lors de la récupération des timers: {str(e)}")
            return {}

@celery_app.task
async def handle_draft_expiration(user_id: str):
    """Gère l'expiration d'un draft."""
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    is_draft = await redis.sismember('draft_users', user_id)
    if is_draft:
        queue_manager = QueueManager(redis)
        await queue_manager.add_to_queue(user_id)
    await redis.aclose()

@celery_app.task
async def cleanup_session(user_id: str):
    """Nettoie la session expirée."""
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    await redis.srem('active_users', user_id)
    await redis.delete(f'session:{user_id}')
    await redis.aclose() 

@celery_app.task
async def update_timer_channel(channel: str, initial_ttl: int, timer_type: str):
    """Tâche Celery qui met à jour le timer sur un canal"""
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    
    try:
        # check if subscribers listen to channel
        subscribers = await redis.pubsub_numsub(channel)
        if subscribers[0][1] == 0:  # if no one listen
            return
            
        # publish timer update
        await redis.publish(
            channel,
            json.dumps({
                "type": "timer_update",
                "timer_type": timer_type,  # draft or session
                "ttl": initial_ttl
            })
        )
        
        # recursif  ttl-1
        if initial_ttl > 0:
            update_timer_channel.apply_async(
                args=[channel, initial_ttl - 1, timer_type],
                countdown=1
            )
            
    except Exception as e:
        print(f"Erreur dans la mise à jour du timer: {str(e)}")
    finally:
        await redis.aclose() 