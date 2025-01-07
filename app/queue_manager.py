import os
from redis.asyncio import Redis
from celery import Celery
import json
import asyncio
import time
import logging

# Configuration de Celery
celery = Celery('queue_manager')

logger = logging.getLogger('test_logger')

# Configuration de base
celery.conf.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/0',
    broker_connection_retry=False,
    broker_connection_max_retries=0,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    worker_max_tasks_per_child=1000,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True
)

# Forcer le mode eager si en test
if os.environ.get('TESTING') == 'true':
    logger.info("Mode TEST détecté, activation du mode EAGER")
    celery.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
        worker_prefetch_multiplier=1,
        task_acks_late=False,
        task_track_started=True,
        task_send_sent_event=True,
        task_remote_tracebacks=True,
        task_store_errors_even_if_ignored=True,
        task_ignore_result=False
    )
    logger.info(f"Configuration Celery en mode EAGER: {celery.conf.task_always_eager}")

logger.info(f"Mode Celery au démarrage: EAGER={celery.conf.task_always_eager}")

class QueueManager:
    """Gestionnaire de file d'attente avec Redis."""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.max_active_users = int(os.getenv('MAX_ACTIVE_USERS', 50))
        self.session_duration = int(os.getenv('SESSION_DURATION', 1200))
        self.draft_duration = int(os.getenv('DRAFT_DURATION', 300))
        self._slot_check_task = None
        self._stop_slot_check = False
        logger.debug(f"QueueManager initialisé avec max_active_users={self.max_active_users}")

    async def _verify_queue_state(self, user_id: str, expected_state: dict) -> bool:
        """Vérifie l'état de la file d'attente pour un utilisateur."""
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
                        logger.warning(f"Incohérence détectée pour {user_id} - {key}: attendu={expected}, actuel={actual_state[key]}")
                        return False
                        
                logger.debug(f"État vérifié pour {user_id} - {actual_state}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur lors de la vérification pour {user_id}: {str(e)}")
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
            logger.info(f"Tentative d'offre de slot à {user_id}")
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.lpop('waiting_queue')
                pipe.srem('queued_users', user_id)
                pipe.sadd('draft_users', user_id)
                pipe.setex(f'draft:{user_id}', self.draft_duration, '1')
                await pipe.execute()
                logger.debug(f"Slot offert à {user_id}, durée de draft: {self.draft_duration}s")

                expected_state = {
                    'in_queue': False,
                    'in_waiting': False,
                    'in_draft': True,
                    'in_active': False
                }
                if not await self._verify_queue_state(user_id, expected_state):
                    raise Exception("État incohérent après l'offre du slot")

            await self.redis.publish(f'queue_status:{user_id}', 
                json.dumps({
                    "status": "draft",
                    "duration": self.draft_duration
                })
            )
            logger.info(f"Notification de draft envoyée à {user_id}")
            
        except Exception as e:
            logger.error(f"Erreur lors de l'offre du slot à {user_id}: {str(e)}")
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.srem('draft_users', user_id)
                pipe.delete(f'draft:{user_id}')
                await pipe.execute()
                logger.debug(f"Nettoyage effectué pour {user_id} après erreur")

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

    async def get_timers(self, user_id: str, max_updates: int = 3) -> dict:
        """Obtient les timers actifs et démarre la tâche de mise à jour"""
        try:
            logger.info(f"Récupération des timers pour {user_id}")
            timers = {}
            
            # check session active
            is_active = await self.redis.sismember('active_users', user_id)
            is_draft = await self.redis.sismember('draft_users', user_id)
            logger.debug(f"État de {user_id} - actif: {is_active}, draft: {is_draft}")
            
            # Vérifier le mode Celery
            is_eager = celery.conf.task_always_eager
            logger.info(f"Mode Celery: {'EAGER/TEST' if is_eager else 'PRODUCTION'} (task_always_eager={is_eager})")
            
            if is_active and not is_draft:
                session_ttl = await self.redis.ttl(f'session:{user_id}')
                logger.debug(f"TTL de session pour {user_id}: {session_ttl}")
                if session_ttl > 0:
                    timers = {
                        'ttl': session_ttl,
                        'channel': f'timer:channel:{user_id}',
                        'timer_type': 'session'
                    }
                    logger.info(f"Démarrage du timer de session pour {user_id} (max_updates: {max_updates})")
                    
                    try:
                        if is_eager:
                            logger.debug("Mode EAGER: exécution synchrone de update_timer_channel")
                            await update_timer_channel(
                                timers['channel'], 
                                timers['ttl'], 
                                timers['timer_type'], 
                                max_updates
                            )
                            logger.debug("Tâche update_timer_channel exécutée avec succès")
                        else:
                            logger.debug("Mode PRODUCTION: planification asynchrone de update_timer_channel")
                            update_timer_channel.apply_async(
                                args=[timers['channel'], timers['ttl'], timers['timer_type'], max_updates],
                                countdown=1
                            )
                    except Exception as e:
                        logger.error(f"Erreur lors du démarrage de la tâche timer: {str(e)}")
                        logger.exception(e)
                        # On continue pour retourner les timers même si la tâche échoue
                    
            # check draft active
            elif is_draft and not is_active:
                draft_ttl = await self.redis.ttl(f'draft:{user_id}')
                logger.debug(f"TTL de draft pour {user_id}: {draft_ttl}")
                if draft_ttl > 0:
                    timers = {
                        'ttl': draft_ttl,
                        'channel': f'timer:channel:{user_id}',
                        'timer_type': 'draft'
                    }
                    logger.info(f"Démarrage du timer de draft pour {user_id} (max_updates: {max_updates})")
                    
                    try:
                        if is_eager:
                            logger.debug("Mode EAGER: exécution synchrone de update_timer_channel")
                            await update_timer_channel(
                                timers['channel'], 
                                timers['ttl'], 
                                timers['timer_type'], 
                                max_updates
                            )
                            logger.debug("Tâche update_timer_channel exécutée avec succès")
                        else:
                            logger.debug("Mode PRODUCTION: planification asynchrone de update_timer_channel")
                            update_timer_channel.apply_async(
                                args=[timers['channel'], timers['ttl'], timers['timer_type'], max_updates],
                                countdown=1
                            )
                    except Exception as e:
                        logger.error(f"Erreur lors du démarrage de la tâche timer: {str(e)}")
                        logger.exception(e)
                        # On continue pour retourner les timers même si la tâche échoue
            else:
                logger.warning(f"Utilisateur {user_id} n'est ni en draft ni actif")
                    
            return timers
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des timers pour {user_id}: {str(e)}")
            logger.exception(e)
            return {}

@celery.task
async def handle_draft_expiration(user_id: str):
    """Gère l'expiration du draft d'un utilisateur."""
    logger.info(f"Début de la tâche d'expiration de draft pour {user_id}")
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        async with redis.pipeline(transaction=True) as pipe:
            pipe.srem('draft_users', user_id)
            pipe.delete(f'draft:{user_id}')
            await pipe.execute()
            logger.debug(f"Draft expiré pour {user_id}, utilisateur retiré du draft")
            
        await redis.publish(f'queue_status:{user_id}', 
            json.dumps({
                "status": "expired",
                "message": "Draft expiré"
            })
        )
        logger.info(f"Notification d'expiration envoyée à {user_id}")
        
    except Exception as e:
        logger.error(f"Erreur lors de l'expiration du draft de {user_id}: {str(e)}")
    finally:
        await redis.aclose()
        logger.debug(f"Connexion Redis fermée pour {user_id}")

@celery.task
async def cleanup_session(user_id: str):
    """Nettoie la session d'un utilisateur."""
    logger.info(f"Début de la tâche de nettoyage de session pour {user_id}")
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        async with redis.pipeline(transaction=True) as pipe:
            pipe.srem('active_users', user_id)
            pipe.delete(f'session:{user_id}')
            await pipe.execute()
            logger.debug(f"Session terminée pour {user_id}, utilisateur retiré des actifs")
            
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage de la session de {user_id}: {str(e)}")
    finally:
        await redis.aclose()
        logger.debug(f"Connexion Redis fermée pour {user_id}")

@celery.task
async def update_timer_channel(channel: str, initial_ttl: int, timer_type: str, max_updates: int = 10):
    """Met à jour le canal de timer pour un utilisateur de manière récursive."""
    logger.info(f"Début de la tâche de mise à jour du timer pour {channel} (TTL initial: {initial_ttl})")
    
    # Forcer le mode EAGER en test
    if os.environ.get('TESTING') == 'true':
        celery.conf.update(task_always_eager=True)
    
    logger.debug(f"Mode Celery actuel dans la tâche: EAGER={celery.conf.task_always_eager}")
    
    redis = None
    result = {"status": "error", "ttl": initial_ttl, "updates_left": max_updates}
    
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        # Extraire l'ID utilisateur et le type de timer de la clé
        await asyncio.sleep(1)
        user_id = channel.replace('timer:channel:', '')
        key = f"{timer_type}:{user_id}"  # session:user_id ou draft:user_id
        
        # Vérifier que la clé existe et obtenir son TTL réel
        ttl = await redis.ttl(key)
        logger.debug(f"TTL actuel pour {key}: {ttl}")
        if ttl <= 0:
            logger.info(f"La clé {key} n'existe plus ou a expiré (TTL={ttl})")
            result["status"] = "expired"
            result["ttl"] = ttl
            return result
            
        logger.debug(f"TTL réel pour {key}: {ttl}")
        result["ttl"] = ttl
        
        # Vérifier si l'utilisateur est connecté
        is_active = await redis.sismember('active_users', user_id)
        is_draft = await redis.sismember('draft_users', user_id)
        
        # Ajuster max_updates en fonction de l'état
        if timer_type == 'session' and not is_active:
            logger.debug(f"Utilisateur {user_id} pas encore actif, pas de décompte des updates")
            effective_max_updates = max_updates  # On ne décrémente pas
        elif timer_type == 'draft' and not is_draft:
            logger.debug(f"Utilisateur {user_id} pas encore en draft, pas de décompte des updates")
            effective_max_updates = max_updates  # On ne décrémente pas
        else:
            effective_max_updates = max_updates - 1  # On décrémente normalement
            
        if ttl > 0 and max_updates > 0:
            # Publier la mise à jour
            message = {
                "ttl": ttl,
                "timer_type": timer_type
            }
            await redis.publish(channel, json.dumps(message))
            logger.debug(f"Timer publié pour {channel}: {message}")
            
            # En mode eager, on attend un peu et on rappelle directement
            if celery.conf.task_always_eager:
                logger.debug("Mode EAGER: exécution synchrone de la prochaine mise à jour")
                await asyncio.sleep(0.1)  # Délai réduit en mode test
                try:
                    next_result = await update_timer_channel(channel, ttl, timer_type, effective_max_updates)
                    logger.debug(f"Appel récursif réussi en mode eager: {next_result}")
                    result.update(next_result)
                except Exception as e:
                    logger.error(f"Erreur lors de l'appel récursif en mode eager: {str(e)}")
                    result["error"] = str(e)
            else:
                # En mode production, on planifie la prochaine mise à jour
                logger.debug("Mode PRODUCTION: planification de la prochaine mise à jour")
                update_timer_channel.apply_async(
                    args=[channel, ttl, timer_type, effective_max_updates],
                    countdown=1
                )
            
            result["status"] = "success"
            result["updates_left"] = effective_max_updates
            
        else:
            if ttl <= 0:
                logger.info(f"Timer expiré pour {channel} ({key})")
                result["status"] = "expired"
            else:
                logger.info(f"Nombre maximum de mises à jour atteint pour {channel}")
                result["status"] = "max_updates"
            
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du timer pour {channel}: {str(e)}")
        logger.exception(e)
        result["error"] = str(e)
    finally:
        if redis:
            try:
                await redis.aclose()
                logger.debug(f"Connexion Redis fermée pour {channel}")
            except Exception as e:
                logger.error(f"Erreur lors de la fermeture de la connexion Redis: {str(e)}")
    
    return result 