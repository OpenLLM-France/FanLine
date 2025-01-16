import pytest
import logging
import asyncio
from app.queue_manager import QueueManager

logger = logging.getLogger(__name__)

class TestAutoExpiration:
    @pytest.mark.asyncio
    async def test_auto_expiration_flow(self, test_client, queue_manager, test_logger):
        """Test le flux complet d'auto-expiration (draft -> connected -> expired)."""
        user_id = "test_auto_expiration"
        
        # 1. Ajouter l'utilisateur à la file
        response = await test_client.post("/queue/join", json={"user_id": user_id})
        assert response.status_code == 200
        test_logger.info("Utilisateur ajouté à la file")
        status = await queue_manager.get_user_status(user_id)

        # 2. Forcer le passage en draft
        await queue_manager.check_available_slots()
        test_logger.info("Vérification des slots forcée")

        # Vérifier que l'utilisateur est en draft
        status = await queue_manager.get_user_status(user_id)
        assert status["status"] == "draft"
        test_logger.info(f"Statut initial: {status}")
        assert "remaining_time" in status, "Le TTL du draft devrait être présent"
        draft_ttl = status["remaining_time"]
        test_logger.info(f"TTL du draft: {draft_ttl}")

        # 3. Confirmer la connexion avec un TTL court
        await redis_client.setex(f"session:{user_id}", 2, "1")  # TTL de 2 secondes pour le test
        response = await test_client.post("/queue/confirm", json={"user_id": user_id})
        assert response.status_code == 200
        test_logger.info("Connexion confirmée")

        # Vérifier que l'utilisateur est connecté
        status = await queue_manager.get_user_status(user_id)
        assert status["status"] == "connected"
        test_logger.info(f"Statut après confirmation: {status}")
        assert "remaining_time" in status, "Le TTL de la session devrait être présent"
        session_ttl = status["remaining_time"]
        test_logger.info(f"TTL de la session: {session_ttl}")

        # 4. Attendre que la session expire
        await asyncio.sleep(3)  # Attendre 3 secondes pour s'assurer que le TTL de 2 secondes est expiré

        # 5. Vérifier que l'utilisateur est déconnecté
        status = await queue_manager.get_user_status(user_id)
        test_logger.info(f"Statut final: {status}")
        assert status["status"] == "disconnected", "L'utilisateur devrait être déconnecté après expiration"

        # Vérifier que l'utilisateur n'est plus dans les ensembles actifs
        is_active = await queue_manager.redis.sismember("active_users", user_id)
        assert not is_active, "L'utilisateur ne devrait plus être dans active_users"
        
        session_exists = await queue_manager.redis.exists(f"session:{user_id}")
        assert not session_exists, "La clé de session ne devrait plus exister" 