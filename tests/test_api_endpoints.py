import pytest
from app.queue_manager import QueueManager
from httpx import AsyncClient
import logging
import asyncio
from celery import current_app as celery_app, Celery
import time

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
    async def test_join_queue_flow(self, test_client, test_logger):
        """Test le flux complet d'ajout à la file."""
        user_id = "test_user_flow"
        
        # Ajouter l'utilisateur à la file
        response = await test_client.post(f"/queue/join/{user_id}")
        assert response.status_code == 200
        test_logger.info("Utilisateur ajouté à la file")
        
        # Vérifier le statut initial
        status_response = await test_client.get(f"/queue/status/{user_id}")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["status"] in ["queued", "in_waiting", "draft"]
        test_logger.info(f"Statut initial vérifié: {status}")

    @pytest.mark.asyncio
    async def test_join_queue_flow_when_full(self, test_client, test_logger):
        """Test le flux d'ajout à la file quand elle est pleine."""
        # Ajouter le premier utilisateur
        user_id_1 = "test_user_0"
        response = await test_client.post(f"/queue/join/{user_id_1}")
        assert response.status_code == 200
        test_logger.info("Premier utilisateur ajouté")
        
        # Ajouter le deuxième utilisateur
        user_id_2 = "test_user_1"
        response = await test_client.post(f"/queue/join/{user_id_2}")
        assert response.status_code == 200
        test_logger.info("Deuxième utilisateur ajouté")
        
        # Vérifier les statuts
        for user_id in [user_id_1, user_id_2]:
            status_response = await test_client.get(f"/queue/status/{user_id}")
            assert status_response.status_code == 200
            status = status_response.json()
            assert status["status"] in ["queued", "in_waiting", "draft"]
            test_logger.info(f"Statut vérifié pour {user_id}: {status}")

    @pytest.mark.asyncio
    async def test_leave_queue(self, test_client, test_logger):
        """Test le départ de la file d'attente."""
        user_id = "test_user_leave"
        
        # Ajouter l'utilisateur à la file
        join_response = await test_client.post(f"/queue/join/{user_id}")
        assert join_response.status_code == 200
        test_logger.info("Utilisateur ajouté à la file")
        
        # Faire partir l'utilisateur
        leave_response = await test_client.post(f"/queue/leave/{user_id}")
        assert leave_response.status_code == 200
        test_logger.info("Utilisateur retiré de la file")
        
        # Vérifier que l'utilisateur n'est plus dans la file
        status_response = await test_client.get(f"/queue/status/{user_id}")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["status"] == "disconnected"
        test_logger.info("Statut vérifié après départ")

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, test_client):
        """Test la récupération du statut pour un utilisateur inexistant."""
        response = await test_client.get("/queue/status/nonexistent_user")
        assert response.status_code == 200
        status = response.json()
        assert status["status"] is None

    @pytest.mark.asyncio
    async def test_heartbeat(self, test_client, test_logger):
        """Test le heartbeat pour maintenir la session active."""
        user_id = "test_user_heartbeat"
        
        # Ajouter l'utilisateur à la file
        join_response = await test_client.post(f"/queue/join/{user_id}")
        assert join_response.status_code == 200
        test_logger.info("Utilisateur ajouté à la file")
        
        # Confirmer la connexion
        confirm_response = await test_client.post(f"/queue/confirm/{user_id}")
        assert confirm_response.status_code == 200
        test_logger.info("Connexion confirmée")
        
        # Envoyer un heartbeat
        heartbeat_response = await test_client.post(f"/queue/heartbeat/{user_id}")
        assert heartbeat_response.status_code == 200
        test_logger.info("Heartbeat envoyé avec succès")
        
        # Vérifier que la session est toujours active
        status_response = await test_client.get(f"/queue/status/{user_id}")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["status"] != "disconnected"
        test_logger.info("Session toujours active après heartbeat")

    @pytest.mark.asyncio
    async def test_heartbeat_invalid(self, test_client):
        """Test le heartbeat pour un utilisateur invalide."""
        response = await test_client.post("/queue/heartbeat/invalid_user")
        assert response.status_code == 404  