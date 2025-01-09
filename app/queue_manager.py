import os
from redis.asyncio import Redis
from redis import Redis as SyncRedis
from celery import Celery
import json
import asyncio
import time
import logging
from typing import Dict, Any, List
import datetime
# Configuration de Celery
celery = Celery('queue_manager')

logger = logging.getLogger('test_logger')

# Récupération des variables d'environnement Redis
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))

# Configuration de base
celery.conf.update(
    broker_url=f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}',
    result_backend=f'redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}',
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

    def __init__(self, redis):
        self.redis = redis
        self.max_active_users = int(os.getenv('MAX_ACTIVE_USERS', 50))
        self.session_duration = int(os.getenv('SESSION_DURATION', 1200))
        self.draft_duration = int(os.getenv('DRAFT_DURATION', 300))
        self._slot_check_task = None
        self._stop_slot_check = False
        self.connection_manager = None
        logger.debug(f"QueueManager initialisé avec max_active_users={self.max_active_users}")

    def set_connection_manager(self, manager):
        """Définit le gestionnaire de connexions WebSocket."""
        self.connection_manager = manager

    async def _send_timer_update(self, user_id: str, timer_type: str, ttl: int):
        """Envoie une mise à jour de timer via WebSocket."""
        if self.connection_manager:
            await self.connection_manager.send_timer_update(user_id, {
                "timer_type": timer_type,
                "ttl": ttl,
                "updates_left": 3  # Pour compatibilité avec l'ancien format
            })

    async def _verify_queue_state(self, user_id: str, expected_states) -> bool:
        """Vérifie l'état de la file d'attente pour un utilisateur.
        
        Args:
            user_id: L'identifiant de l'utilisateur
            expected_states: Soit un dictionnaire d'états attendus, soit une liste de dictionnaires d'états possibles.
                Chaque état peut contenir soit un booléen soit une liste de booléens.
                Par exemple: 
                - {'in_queue': True} 
                - {'in_queue': [True, False]}
                - [{'in_queue': True, 'in_draft': False}, {'in_queue': False, 'in_draft': True}]
        """
        try:
            logger.debug(f"Vérification de l'état pour {user_id} avec attentes: {expected_states}")
            
            # Convertir en liste si c'est un dictionnaire unique
            if isinstance(expected_states, dict):
                expected_states = [expected_states]
                
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('queued_users', user_id)
                pipe.lrange('waiting_queue', 0, -1)  # Récupérer toute la liste
                pipe.sismember('draft_users', user_id)
                pipe.sismember('active_users', user_id)
                results = await pipe.execute()
                
                is_queued = bool(results[0])
                waiting_list = results[1]
                is_draft = bool(results[2])
                is_active = bool(results[3])
                
                actual_state = {
                    'in_queue': is_queued,
                    'in_waiting': user_id in waiting_list,
                    'in_draft': is_draft,
                    'in_active': is_active
                }
                
                logger.debug(f"État actuel pour {user_id}: {actual_state}")
                
                # Vérifier si l'état actuel correspond à l'un des états attendus
                for expected_state in expected_states:
                    matches = True
                    for key, expected in expected_state.items():
                        if isinstance(expected, (list, tuple)):
                            if actual_state[key] not in expected:
                                matches = False
                                break
                        elif actual_state[key] != expected:
                            matches = False
                            break
                    
                    if matches:
                        logger.debug(f"État vérifié avec succès pour {user_id} (correspond à {expected_state})")
                        return True
                
                # Si aucun état attendu ne correspond
                logger.warning(f"État invalide pour {user_id} - actuel={actual_state}, attendu l'un de {expected_states}")
                return False
                
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

    async def add_to_queue(self, user_id: str, check_slots: bool = True) -> Dict:
        """Ajoute un utilisateur à la file d'attente principale."""
        try:
            logger.info(f"Tentative d'ajout de l'utilisateur {user_id}")
            
            # Obtenir le statut actuel
            last_status = await self.get_user_status(user_id, check_slots=check_slots)
            logger.info(f"Statut actuel: {last_status}")
            
            # Si l'utilisateur n'existe pas dans Redis
            if await self._verify_queue_state(user_id, {
                'in_queue': False,
                'in_waiting': False,
                'in_draft': False,
                'in_active': False
            }):
                logger.debug(f"Nouvel utilisateur détecté")
                last_status = {"status": None, "position": None}
            
            # Si l'utilisateur est déconnecté ou n'a pas de statut
            if last_status["status"] in [None, 'disconnected']:
                logger.info(f"Tentative d'ajout à la file d'attente pour {user_id} avec statut {last_status['status']}")
                async with self.redis.pipeline(transaction=True) as pipe:
                    logger.debug("Début transaction Redis")
                    # Ajouter à la file d'attente
                    pipe.rpush('waiting_queue', user_id)
                    pipe.sadd('queued_users', user_id)
                    pipe.llen('waiting_queue')
                    results = await pipe.execute()
                    logger.info(f"Résultats de la transaction Redis pour {user_id}: {results}")
                    position = results[-1]
                    logger.debug(f"Position: {position}")
                    
                    # Vérification immédiate post-transaction
                    is_queued = await self.redis.sismember('queued_users', user_id)
                    is_in_waiting = await self.redis.lpos('waiting_queue', user_id) is not None
                    logger.info(f"Vérification post-transaction pour {user_id}: queued={is_queued}, in_waiting={is_in_waiting}")

                    if not (is_queued and is_in_waiting):
                        logger.error(f"❌ Échec de l'ajout à la file d'attente pour {user_id}")
                        raise Exception("Échec de l'ajout à la file d'attente")
                    
                    # Vérifier l'état après l'ajout - permettre plusieurs états possibles
                    expected_states = [
                        # État 1: En attente dans la file
                        {
                            'in_queue': True,
                            'in_waiting': True,
                            'in_draft': False,
                            'in_active': False
                        }
                    ]
                    if not await self._verify_queue_state(user_id, expected_states):
                        logger.error("État incohérent après l'ajout")
                        raise Exception("État incohérent après l'ajout à la file")
                    
                    # Obtenir le nouveau statut après l'ajout
                    new_status = await self.get_user_status(user_id, check_slots=check_slots)
                    
                    # Vérifier les slots disponibles si demandé
                    if check_slots:
                        await self._check_slots_after_add()
                    
                    # Retourner la position réelle dans la file
                    waiting_pos = await self.redis.lpos('waiting_queue', user_id)
                    if waiting_pos is not None:
                        position = waiting_pos + 1
                    else:
                        position = new_status.get("position", None)
                    
                    return {
                        "last_status": last_status["status"],
                        "last_position": last_status.get("position", None),
                        "commit_status": new_status["status"],
                        "commit_position": position
                    }
            
            # Pour tous les autres cas, retourner le statut actuel
            return {
                "last_status": last_status["status"],
                "last_position": last_status.get("position", None),
                "commit_status": last_status["status"],
                "commit_position": last_status.get("position", None)
            }
                
        except Exception as e:
            logger.error(f"Erreur lors de l'ajout à la file : {str(e)}")
            
            # Nettoyage en cas d'erreur
            async with self.redis.pipeline(transaction=True) as pipe:
                logger.debug("Nettoyage après erreur")
                pipe.lrem('waiting_queue', 0, user_id)
                pipe.srem('queued_users', user_id)
                await pipe.execute()
                
            return {
                "last_status": None,
                "last_position": None,
                "commit_status": None,
                "commit_position": None
            }

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
                    
                    # Vérifier les slots disponibles
                    await self._check_slots_after_add()
                    
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
            
            # Vérifier l'état actuel en une seule transaction
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('queued_users', user_id)
                pipe.lpos('waiting_queue', user_id)
                pipe.sismember('draft_users', user_id)
                pipe.sismember('active_users', user_id)
                results = await pipe.execute()
                
                is_queued, position, is_draft, is_active = results
                if is_draft or is_active:
                    logger.info(f"État invalide pour {user_id}: déjà en draft ou actif")
                    return False
                
                if not is_queued or position is None:
                    logger.warning(f"Utilisateur {user_id} non éligible pour un slot (queued={is_queued}, pos={position})")
                    return False
                    

                # Effectuer la transition en une seule transaction
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.lrem('waiting_queue', 0, user_id)
                    pipe.srem('queued_users', user_id)
                    pipe.sadd('draft_users', user_id)
                    pipe.setex(f'draft:{user_id}', self.draft_duration, '1')
                    await pipe.execute()
                    
                # Vérifier l'état après la transition
                expected_state = {
                    'in_queue': False,
                    'in_waiting': False,
                    'in_draft': True,
                    'in_active': False
                }
                if not await self._verify_queue_state(user_id, expected_state):
                    raise Exception("État incohérent après l'offre du slot")
                
                # Publier la notification
                await self.redis.publish(f'queue_status:{user_id}', 
                    json.dumps({
                        "status": "draft",
                        "duration": self.draft_duration
                    })
                )
                # Ajouter le nouveau statut dans l'historique
                await self.redis.rpush(f'status_history:{user_id}', json.dumps({
                    "status": "draft",
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }))
                
                # Mettre à jour le dernier statut
                await self.redis.set(f'last_status:{user_id}', "draft")
                logger.info(f"Slot offert avec succès à {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur lors de l'offre du slot à {user_id}: {str(e)}")
            # Nettoyage en cas d'erreur
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.srem('draft_users', user_id)
                pipe.delete(f'draft:{user_id}')
                await pipe.execute()
            return False

    async def confirm_connection(self, user_id: str) -> bool:
        """Confirme la connexion d'un utilisateur."""
        try:
            # Vérifier l'état actuel en une seule transaction
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('draft_users', user_id)
                pipe.exists(f'draft:{user_id}')
                pipe.sismember('active_users', user_id)
                pipe.sismember('queued_users', user_id)
                results = await pipe.execute()
                
                is_draft, has_draft, is_active, is_queued = results
                
                if not (is_draft and has_draft) or is_active or is_queued:
                    logger.warning(f"État invalide pour confirmation: draft={is_draft}, has_draft={has_draft}, active={is_active}, queued={is_queued}")
                    return False
                
                # Effectuer la transition en une seule transaction
                async with self.redis.pipeline(transaction=True) as pipe:
                    pipe.srem('draft_users', user_id)
                    pipe.sadd('active_users', user_id)
                    pipe.delete(f'draft:{user_id}')
                    pipe.setex(f'session:{user_id}', self.session_duration, '1')
                    await pipe.execute()
                    
                # Vérifier l'état après la transition
                expected_state = {
                    'in_queue': False,
                    'in_waiting': False,
                    'in_draft': False,
                    'in_active': True
                }
                if not await self._verify_queue_state(user_id, expected_state):
                    raise Exception("État incohérent après la confirmation")
                
                # Publier la notification
                await self.redis.publish(f'queue_status:{user_id}', 
                    json.dumps({
                        "status": "connected",
                        "session_duration": self.session_duration
                    })
                )
                logger.info(f"Connexion confirmée pour {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Erreur lors de la confirmation pour {user_id}: {str(e)}")
            # Nettoyage en cas d'erreur
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.srem('active_users', user_id)
                pipe.delete(f'session:{user_id}')
                await pipe.execute()
            return False

    async def extend_session(self, user_id: str) -> bool:
        """Prolonge la session d'un utilisateur actif."""
        try:
            # Vérifier l'état en une seule transaction
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('active_users', user_id)
                pipe.exists(f'session:{user_id}')
                results = await pipe.execute()
                
                is_active, has_session = results
                
                if not (is_active and has_session):
                    logger.warning(f"Session invalide pour {user_id}: active={is_active}, has_session={has_session}")
                    return False
                
                # Prolonger la session
                await self.redis.setex(f'session:{user_id}', self.session_duration, '1')
                logger.info(f"Session prolongée pour {user_id}")
                
                # Publier la notification
                await self.redis.publish(f'queue_status:{user_id}', 
                    json.dumps({
                        "status": "extended",
                        "session_duration": self.session_duration
                    })
                )
                return True
                
        except Exception as e:
            logger.error(f"Erreur lors de la prolongation de session pour {user_id}: {str(e)}")
            return False

    async def get_user_status(self, user_id: str, check_slots: bool = True) -> Dict:
        """Récupère le statut actuel d'un utilisateur."""
        try:
            # Vérifier si l'utilisateur existe dans un des états possibles
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.sismember('active_users', user_id)
                pipe.sismember('draft_users', user_id)
                pipe.lpos('waiting_queue', user_id)
                pipe.sismember('queued_users', user_id)
                is_active, is_draft, waiting_pos, is_queued = await pipe.execute()

            # Si l'utilisateur n'existe dans aucun état, retourner None
            if not any([is_active, is_draft, waiting_pos is not None, is_queued]):
                return {"status": None}

            # Déterminer le statut en fonction des flags
            if is_active:
                status_info = {
                    "status": "connected",
                    "position": -2
                }
                
                # Vérifier le TTL de la session
                session_ttl = await self.redis.ttl(f'session:{user_id}')
                if session_ttl > 0:
                    status_info["remaining_time"] = session_ttl
                    
            elif is_draft:
                status_info = {
                    "status": "draft",
                    "position": -1
                }
                
                # Vérifier le TTL du draft
                draft_ttl = await self.redis.ttl(f'draft:{user_id}')
                if draft_ttl > 0:
                    status_info["remaining_time"] = draft_ttl
                    
            elif waiting_pos is not None:
                status_info = {
                    "status": "waiting",
                    "position": waiting_pos + 1
                }
                
            else:
                status_info = {
                    "status": "disconnected",
                    "position": None
                }

            # Ajouter un timestamp au statut
            status_info["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Stocker le statut dans la liste et publier
            status_json = json.dumps(status_info)
            last_status = None
            
            # Vérifier si l'historique des statuts existe déjà
            if exist:=(await self.redis.exists(f'status_history:{user_id}') == 0):
                logger.info(f"Aucun historique de statuts trouvé pour {user_id}")
            else:
                # Récupérer le dernier statut stocké
                last_status_json = await self.redis.lindex(f'status_history:{user_id}', -1)
                if last_status_json:
                    try:
                        last_status = json.loads(last_status_json)
                        logger.info(f"Dernier statut récupéré pour {user_id}: {last_status}")
                        
                        # Vérifier si on doit checker les slots
                        if check_slots and (status_info["status"] == "waiting" or (last_status.get("status") == "connected" and status_info["status"] != "connected")):
                            await self._check_slots_after_add()
                    except json.JSONDecodeError:
                        logger.error(f"Erreur lors du décodage du dernier statut pour {user_id}")
                else:
                    logger.info(f"Aucun statut trouvé pour {user_id}")
            
            # Ajouter le nouveau statut à l'historique
            if not last_status or (last_status["status"] != status_info["status"]):
                await self.redis.rpush(f'status_history:{user_id}', status_json)
                await self.redis.publish(f'queue_status:{user_id}', status_json)
            
                # Garder seulement les 100 derniers statuts
                if not exist:
                    await self.redis.ltrim(f'status_history:{user_id}', -100, -1)
            
            return status_info
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du statut pour {user_id}: {str(e)}")
            error_status = {
                "status": "error",
                "position": None,
                "message": str(e),
                "timestamp": int(time.time())
            }
            error_json = json.dumps(error_status)
            await self.redis.rpush(f'status_history:{user_id}', error_json)
            await self.redis.publish(f'queue_status:{user_id}', error_json)
            return error_status

    async def get_status_messages(self, user_id: str, limit: int = None) -> List[Dict]:
        """Récupère l'historique des messages de statut pour un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur dont on veut récupérer l'historique des statuts.
            limit: Nombre maximum de messages à récupérer (par défaut, tous les messages)
        
        Returns:
            List[Dict]: Liste des messages de statut, du plus récent au plus ancien
        """
        try:
            # Récupérer tous les statuts stockés
            if limit is not None:
                messages = await self.redis.lrange(f'status_history:{user_id}', -limit, -1)
            else:
                messages = await self.redis.lrange(f'status_history:{user_id}', 0, -1)
            
            if messages:
                try:
                    # Décoder les messages JSON
                    status_list = [json.loads(msg) for msg in messages]
                    logger.info(f"{len(status_list)} messages récupérés pour {user_id}")
                    return status_list
                except Exception as e:
                    logger.error(f"Erreur lors du décodage des messages: {str(e)}")
            
            logger.info(f"Aucun message trouvé pour {user_id}")
            return []
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des messages: {str(e)}")
            return []

    async def get_all_user_statuses(self) -> List[Dict]:
        """Récupère le statut de tous les utilisateurs dans le système.
        
        Returns:
            List[Dict]: Une liste de dictionnaires contenant les statuts de tous les utilisateurs.
            Chaque dictionnaire contient:
                - user_id: L'identifiant de l'utilisateur
                - status: Le statut actuel ('waiting', 'draft', 'connected', etc.)
                - position: La position actuelle
                - remaining_time: Le temps restant (pour les statuts draft et connected)
        """
        try:
            all_statuses = []
            
            async with self.redis.pipeline(transaction=True) as pipe:
                # Récupérer tous les utilisateurs de chaque état
                pipe.smembers('active_users')
                pipe.smembers('draft_users')
                pipe.lrange('waiting_queue', 0, -1)
                active_users, draft_users, waiting_users = await pipe.execute()
                
                # Convertir les sets en listes pour les utilisateurs actifs et en draft
                active_users = list(active_users)
                draft_users = list(draft_users)
                
                logger.debug(f"Utilisateurs trouvés - actifs: {len(active_users)}, draft: {len(draft_users)}, en attente: {len(waiting_users)}")
                
                # Récupérer le statut de chaque utilisateur
                for user_id in active_users:
                    status = await self.get_user_status(user_id)
                    all_statuses.append({
                        "user_id": user_id,
                        **status
                    })
                
                for user_id in draft_users:
                    status = await self.get_user_status(user_id)
                    all_statuses.append({
                        "user_id": user_id,
                        **status
                    })
                
                for user_id in waiting_users:
                    status = await self.get_user_status(user_id)
                    all_statuses.append({
                        "user_id": user_id,
                        **status
                    })
                
            logger.info(f"Total des statuts récupérés: {len(all_statuses)}")
            return all_statuses
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des statuts: {str(e)}")
            return []

    async def get_timers(self, user_id: str) -> Dict[str, Any]:
        """Récupère les timers actifs pour un utilisateur."""
        try:
            logger.info(f"Récupération des timers pour {user_id}")
            
            # Utiliser une pipeline pour les vérifications atomiques
            async with self.redis.pipeline() as pipe:
                pipe.sismember('active_users', user_id)
                pipe.sismember('draft_users', user_id)
                pipe.ttl(f'session:{user_id}')
                pipe.ttl(f'draft:{user_id}')
                is_active, is_draft, session_ttl, draft_ttl = await pipe.execute()

            logger.debug(
                f"État des timers pour {user_id} - actif: {is_active}, draft: {is_draft}, "
                f"session_ttl: {session_ttl}, draft_ttl: {draft_ttl}"
            )

            if not is_active and not is_draft:
                logger.warning(f"Aucun timer actif pour {user_id}")
                return {}

            if is_active and session_ttl > 0:
                # Démarrer la tâche de mise à jour du timer de session
                celery.send_task(
                    'app.tasks.update_timer_channel',
                    args=[user_id, 'session', session_ttl],
                    countdown=1
                )
                return {
                    'timer_type': 'session',
                    'ttl': session_ttl,
                    'channel': f'timer:channel:{user_id}'
                }

            if is_draft and draft_ttl > 0:
                # Démarrer la tâche de mise à jour du timer de draft
                celery.send_task(
                    'app.tasks.update_timer_channel',
                    args=[user_id, 'draft', draft_ttl],
                    countdown=1
                )
                return {
                    'timer_type': 'draft',
                    'ttl': draft_ttl,
                    'channel': f'timer:channel:{user_id}'
                }

            return {}

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des timers pour {user_id}: {str(e)}")
            return {}

    async def _cleanup_inconsistent_state(self, user_id: str):
        """Nettoie un état incohérent."""
        try:
            logger.warning(f"Nettoyage de l'état incohérent pour {user_id}")
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.srem('queued_users', user_id)
                pipe.lrem('waiting_queue', 0, user_id)
                pipe.srem('active_users', user_id)
                pipe.srem('draft_users', user_id)
                pipe.delete(f'draft:{user_id}')
                pipe.delete(f'session:{user_id}')
                pipe.delete(f'status_history:{user_id}')
                pipe.delete(f'last_status:{user_id}')
                await pipe.execute()
                logger.info(f"État nettoyé pour {user_id}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage de l'état pour {user_id}: {str(e)}")

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

@celery.task
async def handle_draft_expiration(user_id: str):
    """Gère l'expiration du draft d'un utilisateur."""
    logger.info(f"Début de la tâche d'expiration de draft pour {user_id}")
    redis = None
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        # Vérifier l'état actuel
        async with redis.pipeline(transaction=True) as pipe:
            pipe.sismember('draft_users', user_id)
            pipe.exists(f'draft:{user_id}')
            pipe.sismember('queued_users', user_id)
            results = await pipe.execute()
            
            is_draft, has_draft, is_queued = results
            
            if not (is_draft and has_draft) or is_queued:
                logger.warning(f"État invalide pour expiration: draft={is_draft}, has_draft={has_draft}, queued={is_queued}")
                return
        
        # Effectuer la transition
        async with redis.pipeline(transaction=True) as pipe:
            pipe.srem('draft_users', user_id)
            pipe.delete(f'draft:{user_id}')
            await pipe.execute()
            
        # Publier la notification
        await redis.publish(f'queue_status:{user_id}', 
            json.dumps({
                "status": "expired",
                "message": "Draft expiré"
            })
        )
        logger.info(f"Draft expiré avec succès pour {user_id}")
        
    except Exception as e:
        logger.error(f"Erreur lors de l'expiration du draft de {user_id}: {str(e)}")
    finally:
        if redis:
            await redis.aclose()
            logger.debug(f"Connexion Redis fermée pour {user_id}")

@celery.task
async def cleanup_session(user_id: str):
    """Nettoie la session d'un utilisateur."""
    logger.info(f"Début de la tâche de nettoyage de session pour {user_id}")
    redis = None
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        # Vérifier l'état actuel
        async with redis.pipeline(transaction=True) as pipe:
            pipe.sismember('active_users', user_id)
            pipe.exists(f'session:{user_id}')
            results = await pipe.execute()
            
            is_active, has_session = results
            
            if not (is_active and has_session):
                logger.warning(f"État invalide pour nettoyage: active={is_active}, has_session={has_session}")
                return
        
        # Effectuer le nettoyage
        async with redis.pipeline(transaction=True) as pipe:
            pipe.srem('active_users', user_id)
            pipe.delete(f'session:{user_id}')
            await pipe.execute()
            
        # Publier la notification
        await redis.publish(f'queue_status:{user_id}', 
            json.dumps({
                "status": "disconnected",
                "reason": "session_timeout"
            })
        )
        logger.info(f"Session nettoyée avec succès pour {user_id}")
        
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage de la session de {user_id}: {str(e)}")
    finally:
        if redis:
            await redis.aclose()
            logger.debug(f"Connexion Redis fermée pour {user_id}")

@celery.task(name='app.queue_manager.update_timer_channel')
def update_timer_channel(channel: str, initial_ttl: int, timer_type: str, max_updates: int = 3):
    """Met à jour le canal de timer avec le TTL restant."""
    logger.info(f"Début de la tâche de mise à jour du timer pour {channel} (TTL initial: {initial_ttl})")
    redis_client = None
    
    try:
        # Utiliser un client Redis synchrone avec les variables d'environnement
        redis_client = SyncRedis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        
        updates_left = max_updates
        current_ttl = initial_ttl
        user_id = channel.split(':')[-1]
        key = f"{timer_type}:{user_id}"
        
        while updates_left > 0 and current_ttl > 0:
            try:
                # Vérifier l'état et le TTL en une seule transaction
                pipe = redis_client.pipeline(transaction=True)
                if timer_type == 'session':
                    pipe.sismember('active_users', user_id)
                else:
                    pipe.sismember('draft_users', user_id)
                pipe.ttl(key)
                results = pipe.execute()
                
                is_valid_state, current_ttl = results
                
                if not is_valid_state or current_ttl <= 0:
                    logger.info(f"Timer invalide pour {user_id} (état={is_valid_state}, ttl={current_ttl})")
                    break
                    
                # Publier la mise à jour
                message = {
                    'timer_type': timer_type,
                    'ttl': current_ttl,
                    'updates_left': updates_left
                }
                redis_client.publish(channel, json.dumps(message))
                logger.debug(f"Mise à jour du timer pour {channel} (TTL: {current_ttl}, updates: {updates_left})")
                
                updates_left -= 1
                if updates_left > 0:
                    time.sleep(1)  # Attendre 1 seconde avant la prochaine mise à jour
                    
            except Exception as e:
                logger.error(f"Erreur lors de la mise à jour du timer pour {user_id}: {str(e)}")
                break
                
        return {
            'status': 'success',
            'ttl': current_ttl,
            'updates_left': updates_left
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du timer: {str(e)}")
        return {
            'status': 'error',
            'error': str(e)
        }
    finally:
        if redis_client:
            redis_client.close()  # Utiliser close() car c'est un client synchrone 