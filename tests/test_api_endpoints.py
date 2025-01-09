import pytest
from app.queue_manager import QueueManager
from httpx import AsyncClient
import logging
import debugpy

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestAPI:
    @pytest.mark.asyncio
    async def test_join_queue_flow(self, test_client, redis_client):
        user_id = "test_user_flow"
        queue_manager = QueueManager(redis_client)
        # Log l'état initial
        logger.debug("État initial de Redis:")
        logger.debug(f"Queued users: {await redis_client.smembers('queued_users')}")
        logger.debug(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
        
        try:
            # Join queue
            response = await test_client.post("/queue/join", json={"user_id": user_id})
            logger.debug(f"Join queue response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert "commit_position" in data
            
            # Check status
            response = await test_client.get(f"/queue/status/{user_id}")
            logger.debug(f"Status response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            
            # L'utilisateur peut être soit en waiting soit en draft selon la disponibilité des slots
            assert data["status"] in ["waiting", "draft"], f"Status devrait être 'waiting' ou 'draft', reçu: {data['status']}"
            if data["status"] == "waiting":
                assert data["position"] > 0, f"Position devrait être > 0, reçu: {data['position']}"
                
                # Essayer de rejoindre à nouveau - devrait échouer
                response = await test_client.post("/queue/join", json={"user_id": user_id})
                assert response.status_code == 400
                assert response.json()["detail"] == "Utilisateur déjà dans la file d'attente"
            else:  # draft
                assert data["position"] == -1, f"Position en draft devrait être -1, reçu: {data['position']}"
                assert await redis_client.sismember("draft_users", user_id), "L'utilisateur devrait être dans draft_users"
                
                # Essayer de rejoindre à nouveau - devrait échouer car déjà en draft
                response = await test_client.post("/queue/join", json={"user_id": user_id})
                logger.debug(f"Join draft response: {response.json()}")
                assert response.status_code == 400
                assert response.json()["detail"] == "Utilisateur déjà dans la file d'attente"
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}")
            # Log l'état final en cas d'erreur
            logger.error("État final de Redis:")
            logger.error(f"Queued users: {await redis_client.smembers('queued_users')}")
            logger.error(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
            logger.error(f"Draft users: {await redis_client.smembers('draft_users')}")
            raise
            
        finally:
            # Cleanup
            await redis_client.delete("waiting_queue")
            await redis_client.srem("queued_users", user_id)
            await redis_client.srem("draft_users", user_id)
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.delete(f"status_history:{user_id}")
            await redis_client.delete(f"last_status:{user_id}")
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
            response = await test_client.post("/queue/join", json={"user_id": users[-1]})
            logger.debug(f"Join full queue response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert data["position"] > 0
            
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
        user_id = "test_user_leave"
        
        # Add to queue first
        await redis_client.rpush("waiting_queue", user_id)
        await redis_client.sadd("queued_users", user_id)
        
        # Leave queue
        response = await test_client.post("/queue/leave", json={"user_id": user_id})
        assert response.status_code == 200
        
        # Verify user is removed
        assert not await redis_client.sismember("queued_users", user_id)
        queue_list = await redis_client.lrange("waiting_queue", 0, -1)
        assert user_id not in queue_list
        
        # Cleanup
        await redis_client.delete("waiting_queue")

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
        
        # Cleanup
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_heartbeat_invalid(self, test_client, redis_client):
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
            response = await test_client.post("/queue/join", json={"user_id": user_id})
            assert response.status_code == 200
            test_logger.info(f"Utilisateur {user_id} ajouté à la file")
            
            # Vérifier les timers initiaux (devrait être en waiting, donc pas de timer)
            response = await test_client.get(f"/queue/timers/{user_id}")
            assert response.status_code == 200
            initial_timers = response.json()
            assert initial_timers["timer_type"] is None, f"Aucun timer ne devrait être actif en waiting, reçu: {initial_timers}"
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
            draft_timers = response.json()
            assert draft_timers["timer_type"] == "draft", "Le timer devrait être de type draft"
            assert draft_timers["ttl"] <= queue_manager.draft_duration, "Le TTL devrait être inférieur ou égal à la durée du draft"
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