import pytest
from app.queue_manager import QueueManager
from httpx import AsyncClient
import logging
import asyncio
from celery import current_app as celery_app

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestAPI:
    @pytest.fixture(autouse=True)
    async def cleanup(self, redis_client):
        self.redis = redis_client
        yield
        # Nettoyage après chaque test
        await self.redis.flushall()
        if hasattr(self, 'queue_manager'):
            await self.queue_manager.stop_slot_checker()

    @pytest.mark.asyncio
    @pytest.mark.timeout(30)
    async def test_join_queue_flow(self, test_client, redis_client):
        # Configuration de Celery en mode EAGER pour les tests
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            task_store_eager_result=True,
            result_backend='cache',
            broker_url='memory://'  # Utiliser un broker en mémoire pour les tests
        )
        
        user_id = "test_user_flow"
        queue_manager = QueueManager(redis_client)
        
        try:
            logger.debug("État initial de Redis:")
            logger.debug(f"Queued users: {await redis_client.smembers('queued_users')}")
            logger.debug(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
            
            # Join queue
            response = await test_client.post(f"/queue/join/{user_id}")
            assert response.status_code == 200
            response_data = response.json()
            logger.debug(f"Join queue response: {response_data}")
            
            # Vérifier immédiatement le statut
            status_response = await test_client.get(f"/queue/status/{user_id}")
            assert status_response.status_code == 200
            status_data = status_response.json()
            logger.debug(f"Status response: {status_data}")
            
            # Attendre que la tâche soit traitée avec plusieurs tentatives
            for attempt in range(5):
                logger.debug(f"Tentative {attempt + 1} de vérification du statut")
                
                # Vérifier l'état Redis directement
                in_queue = await redis_client.sismember("queued_users", user_id)
                in_draft = await redis_client.sismember("draft_users", user_id)
                queue_position = await redis_client.lpos("waiting_queue", user_id)
                last_status = await redis_client.get(f"last_status:{user_id}")
                
                logger.debug(f"État Redis: queue={in_queue}, draft={in_draft}, position={queue_position}, status={last_status}")
                
                if in_draft or (in_queue and queue_position is not None):
                    break
                    
                await asyncio.sleep(0.5)
            else:
                pytest.fail("L'utilisateur n'a pas été correctement ajouté à la file")
                
            # Vérification finale
            final_status = await test_client.get(f"/queue/status/{user_id}")
            assert final_status.status_code == 200
            final_data = final_status.json()
            assert final_data["status"] in ["waiting", "draft"]
                
        except asyncio.TimeoutError:
            logger.error("Test timeout - opération trop longue")
            # Log l'état complet
            status = await redis_client.get(f"last_status:{user_id}")
            queue_pos = await redis_client.lpos("waiting_queue", user_id)
            in_queue = await redis_client.sismember("queued_users", user_id)
            in_draft = await redis_client.sismember("draft_users", user_id)
            logger.error(f"État final: status={status}, position={queue_pos}, in_queue={in_queue}, in_draft={in_draft}")
            raise
        finally:
            # Nettoyage complet
            await redis_client.delete("waiting_queue")
            await redis_client.srem("queued_users", user_id)
            await redis_client.srem("draft_users", user_id)
            await redis_client.srem("active_users", user_id)
            await redis_client.delete(f"session:{user_id}")
            await redis_client.delete(f"last_status:{user_id}")
            await redis_client.delete(f"status_history:{user_id}")
            await queue_manager._cleanup_inconsistent_state(user_id)

    @pytest.mark.asyncio
    async def test_join_queue_flow_when_full(self, test_client, redis_client):
        queue_manager = QueueManager(redis_client)
        max_users = queue_manager.max_active_users
        users = [f"test_user_{i}" for i in range(max_users + 1)]
        
        logger.debug(f"Testing with {max_users} users")
        
        try:
            # Fill queue
            for i in range(max_users):
                logger.debug(f"Adding user {users[i]}")
                await queue_manager.add_to_queue(users[i])
                await queue_manager.offer_slot(users[i])
                await queue_manager.confirm_connection(users[i])
                
            # Vérifier l'état après remplissage
            logger.debug("État après remplissage:")
            logger.debug(f"Active users: {await redis_client.smembers('active_users')}")
            logger.debug(f"Active count: {await redis_client.scard('active_users')}")
            
            # Try to join full queue
            response = await test_client.post(f"/queue/join/{users[-1]}")
            logger.debug(f"Join full queue response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert data["commit_position"] > 0
            
            # Vérifier le statut après avoir rejoint
            response = await test_client.get(f"/queue/status/{users[-1]}")
            assert response.status_code == 200
            status = response.json()
            # Quand la file est pleine, l'utilisateur doit être en waiting
            assert status["status"] == "waiting"
            assert status["position"] > 0
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}")
            logger.error("État final:")
            logger.error(f"Active users: {await redis_client.smembers('active_users')}")
            logger.error(f"Queued users: {await redis_client.smembers('queued_users')}")
            logger.error(f"Draft users: {await redis_client.smembers('draft_users')}")
            raise
            
        finally:
            # Cleanup
            await redis_client.delete("waiting_queue")
            for user in users:
                await redis_client.srem("queued_users", user)
                await redis_client.srem("active_users", user)
                await redis_client.srem("draft_users", user)
                await redis_client.delete(f"session:{user}")
                await redis_client.delete(f"draft:{user}")
                await redis_client.delete(f"status_history:{user}")
                await redis_client.delete(f"last_status:{user}")

    @pytest.mark.asyncio
    async def test_leave_queue(self, test_client, redis_client):
        # Configuration de Celery en mode EAGER pour les tests
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            task_store_eager_result=True,
            result_backend='cache',
            broker_url='memory://'
        )
        
        user_id = "test_user_leave"
        logger.info(f"=== Démarrage du test leave_queue pour {user_id} ===")
        
        try:
            # État initial
            logger.info("--- Vérification de l'état initial Redis ---")
            initial_in_queue = await redis_client.sismember("queued_users", user_id)
            initial_queue_list = await redis_client.lrange("waiting_queue", 0, -1)
            initial_draft = await redis_client.sismember("draft_users", user_id)
            initial_active = await redis_client.sismember("active_users", user_id)
            initial_status = await redis_client.get(f"last_status:{user_id}")
            initial_in_accounts_queue = await redis_client.sismember('accounts_queue', user_id)
            
            logger.info(f"État initial:")
            logger.info(f"- In queue: {initial_in_queue}")
            logger.info(f"- Queue list: {initial_queue_list}")
            logger.info(f"- In draft: {initial_draft}")
            logger.info(f"- In active: {initial_active}")
            logger.info(f"- Status: {initial_status}")
            logger.info(f"- In accounts queue: {initial_in_accounts_queue}")
            # Ajouter à la file d'attente avec un timeout court
            logger.info("--- Ajout de l'utilisateur à la file d'attente ---")
            async with asyncio.timeout(2):
                add_queue_result = await redis_client.rpush("waiting_queue", user_id)
                add_set_result = await redis_client.sadd("queued_users", user_id)
                add_in_accounts_queue_result = await redis_client.sadd('accounts_queue', user_id)
                logger.info(f"Résultats de l'ajout: queue={add_queue_result}, set={add_set_result}")
            
            # Vérifier l'ajout avec un timeout court
            async with asyncio.timeout(2):
                after_add_in_queue = await redis_client.sismember("queued_users", user_id)
                after_add_queue_list = await redis_client.lrange("waiting_queue", 0, -1)
                after_add_position = await redis_client.lpos("waiting_queue", user_id)
                after_add_in_accounts_queue = await redis_client.sismember('accounts_queue', user_id)
                
                logger.info(f"Après ajout:")
                logger.info(f"- In queue: {after_add_in_queue}")
                logger.info(f"- Queue list: {after_add_queue_list}")
                logger.info(f"- Position: {after_add_position}")
                logger.info(f"- In accounts queue: {after_add_in_accounts_queue}")
            # Quitter la file d'attente avec un timeout court
            logger.info("--- Tentative de quitter la file d'attente ---")
            async with asyncio.timeout(2):
                response = await test_client.post(f"/queue/leave/{user_id}")
                assert response.status_code == 200
                response_data = response.json()
                logger.info(f"Réponse leave queue: {response_data}")
            
            # Attendre que la tâche Celery soit traitée
            for attempt in range(5):
                logger.info(f"Vérification du statut - tentative {attempt + 1}")
                async with asyncio.timeout(1):
                    status_response = await test_client.get(f"/queue/status/{user_id}")
                    status = status_response.json()
                    if status["status"] == "disconnected":
                        break
                    await asyncio.sleep(0.2)
            
            # Vérifications finales
            logger.info("--- Vérification finale de l'état Redis ---")
            final_state = await self._get_redis_state(redis_client, user_id)
            logger.info("État final:")
            for key, value in final_state.items():
                logger.info(f"- {key}: {value}")
            
            assert status["status"] == "disconnected", f"Statut incorrect: {status['status']}"
            assert not final_state["in_queue"], "L'utilisateur devrait être retiré de queued_users"
            assert user_id not in final_state["queue_list"], "L'utilisateur devrait être retiré de la waiting_queue"
            
        except Exception as e:
            logger.error(f"!!! Erreur pendant le test leave_queue: {str(e)}")
            error_state = await self._get_redis_state(redis_client, user_id)
            logger.error("État en erreur:")
            for key, value in error_state.items():
                logger.error(f"- {key}: {value}")
            raise
        finally:
            logger.info("--- Nettoyage des données de test ---")
            await self._cleanup_redis(redis_client, user_id)
            logger.info("=== Fin du test leave_queue ===")

    async def _get_redis_state(self, redis_client, user_id):
        """Helper pour récupérer l'état complet Redis"""
        return {
            "in_queue": await redis_client.sismember("queued_users", user_id),
            "queue_list": await redis_client.lrange("waiting_queue", 0, -1),
            "in_draft": await redis_client.sismember("draft_users", user_id),
            "in_active": await redis_client.sismember("active_users", user_id),
            "status": await redis_client.get(f"last_status:{user_id}"),
            "position": await redis_client.lpos("waiting_queue", user_id),
            "history": await redis_client.lrange(f"status_history:{user_id}", 0, -1)
        }

    async def _cleanup_redis(self, redis_client, user_id):
        """Helper pour le nettoyage Redis"""
        cleanup_keys = [
            "waiting_queue",
            f"last_status:{user_id}",
            f"status_history:{user_id}",
            f"session:{user_id}"
        ]
        cleanup_sets = ["queued_users", "draft_users", "active_users"]
        
        for key in cleanup_keys:
            await redis_client.delete(key)
        for set_name in cleanup_sets:
            await redis_client.srem(set_name, user_id)

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, test_client):
        """Test la récupération du statut d'un utilisateur inexistant."""
        response = await test_client.get("/queue/status/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data == {"status": None}

    @pytest.mark.asyncio
    async def test_heartbeat(self, test_client, redis_client):
        user_id = "test_user_heartbeat"
        
        # Setup active user
        await redis_client.sadd("active_users", user_id)
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        # Send heartbeat
        response = await test_client.post("/queue/heartbeat", json={"user_id": user_id})
        assert response.status_code == 200
        
        # Verify session is extended
        ttl = await redis_client.ttl(f"session:{user_id}")
        assert 0 < ttl <= 1200
        
        # Wait a bit and verify auto-expiration
        await asyncio.sleep(2)
        is_active = await redis_client.sismember("active_users", user_id)
        assert is_active, "L'utilisateur devrait toujours être actif"
        
        # Cleanup
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_heartbeat_invalid(self, test_client, redis_client):
        """Test le heartbeat avec un utilisateur invalide."""
        response = await test_client.post("/queue/heartbeat", json={"user_id": "nonexistent_user"})
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_timers_async(self, test_client, redis_client, test_logger):
        """Test le comportement asynchrone des timers."""
        from celery_test_config import setup_test_celery
        
        # Configuration de Celery
        celery_app = setup_test_celery()
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            task_store_eager_result=True,
            result_backend='cache'
        )
        test_logger.info(f"Mode Celery configuré: EAGER={celery_app.conf.task_always_eager}")
        
        user_id = "test_user_timers"
        queue_manager = QueueManager(redis_client)
        
        try:
            # Remplir la file active d'abord pour éviter le draft immédiat
            for i in range(queue_manager.max_active_users):
                active_user = f"active_user_{i}"
                await redis_client.sadd("active_users", active_user)
                await redis_client.setex(f"session:{active_user}", queue_manager.session_duration, "1")
            test_logger.info("File active remplie")
            
            # Ajouter l'utilisateur à la file
            response = await test_client.post(f"/queue/join/{user_id}")
            assert response.status_code == 200
            test_logger.info(f"Utilisateur {user_id} ajouté à la file")
            
            # Vérifier les timers initiaux (devrait être en waiting, donc pas de timer)
            response = await test_client.get(f"/queue/timers/{user_id}")
            assert response.status_code == 200
            initial_timers = response.json()
            assert "error" in initial_timers, f"Aucun timer ne devrait être actif en waiting, reçu: {initial_timers}"
            test_logger.info("Vérification des timers initiaux OK")
            
            # Libérer un slot et offrir le slot à l'utilisateur
            first_active = await redis_client.srandmember("active_users")
            await redis_client.srem("active_users", first_active)
            await redis_client.delete(f"session:{first_active}")
            test_logger.info("Slot libéré")
            
            # Offrir un slot pour activer le timer de draft
            await queue_manager.offer_slot(user_id)
            test_logger.info("Slot offert à l'utilisateur")
            
            # Vérifier les timers après l'offre de slot
            response = await test_client.get(f"/queue/timers/{user_id}")
            assert response.status_code == 200
            timer_data = response.json()

            # Vérifier les données du timer
            assert "channel" in timer_data, f"Channel manquant dans la réponse: {timer_data}"
            assert timer_data["timer_type"] == "draft", f"Type de timer incorrect: {timer_data}"
            assert "ttl" in timer_data, f"TTL manquant dans la réponse: {timer_data}"
            assert timer_data["ttl"] <= queue_manager.draft_duration, "Le TTL devrait être inférieur ou égal à la durée du draft"
            if "task_result" in timer_data:
                assert isinstance(timer_data["task_result"], dict), "Le résultat de la tâche devrait être un dictionnaire"
            test_logger.info("Vérification des timers draft OK")
            
            # Confirmer la connexion pour passer au timer de session
            await queue_manager.confirm_connection(user_id)
            test_logger.info("Connexion confirmée")
            
            # Vérifier les timers après la confirmation
            response = await test_client.get(f"/queue/timers/{user_id}")
            assert response.status_code == 200
            session_timers = response.json()
            assert session_timers["timer_type"] == "session", "Le timer devrait être de type session"
            assert session_timers["ttl"] <= queue_manager.session_duration, "Le TTL devrait être inférieur ou égal à la durée de session"
            test_logger.info("Vérification des timers session OK")
            
        finally:
            # Nettoyage
            test_logger.debug("Début du nettoyage")
            await redis_client.delete("waiting_queue")
            await redis_client.srem("queued_users", user_id)
            await redis_client.srem("draft_users", user_id)
            await redis_client.srem("active_users", user_id)
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.delete(f"session:{user_id}")
            await redis_client.delete(f"status_history:{user_id}")
            await redis_client.delete(f"last_status:{user_id}")
            
            # Nettoyer les utilisateurs actifs de test
            for i in range(queue_manager.max_active_users):
                active_user = f"active_user_{i}"
                await redis_client.srem("active_users", active_user)
                await redis_client.delete(f"session:{active_user}")
            
            await queue_manager._cleanup_inconsistent_state(user_id)
            test_logger.info("Nettoyage terminé")  