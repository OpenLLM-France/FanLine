import pytest
import logging
import asyncio
import pdb

logger = logging.getLogger(__name__)

class TestDebugGetUsersEndpoint:
    @pytest.mark.asyncio
    async def test_get_users_endpoint_debug(self, test_client, queue_manager, test_logger):
        """Test l'endpoint /queue/get_users en mode débogage."""
        test_logger.info("Démarrage du test de l'endpoint get_users en mode débogage")
        
        # Nettoyer Redis et désactiver le vérificateur automatique
        await queue_manager.redis.flushdb()
        await queue_manager.stop_slot_checker()
        test_logger.info("Redis nettoyé et vérificateur automatique arrêté")
        
        # Vérifier l'état initial des files
        response = await test_client.get("/queue/get_users")
        assert response.status_code == 200
        initial_data = response.json()
        test_logger.info(f"État initial des files: {initial_data}")
        assert len(initial_data["waiting_users"]) == 0
        assert len(initial_data["draft_users"]) == 0
        assert len(initial_data["active_users"]) == 0
        
        # 1. Ajouter le premier utilisateur
        user_active = "user_active_1"
        response = await test_client.post("/queue/join", json={"user_id": user_active})
        assert response.status_code == 200
        test_logger.info(f"Utilisateur {user_active} ajouté")
        
        # Vérifier l'état après ajout
        response = await test_client.get("/queue/get_users")
        assert response.status_code == 200
        data = response.json()
        test_logger.info(f"État après ajout du premier utilisateur: {data}")
        assert len(data["waiting_users"]) == 1, "Devrait avoir 1 utilisateur en attente"
        
        # 2. Ajouter 5 utilisateurs en attente
        waiting_users = []
        for i in range(5):
            user_id = f"user_wait_{i}"
            waiting_users.append(user_id)
            response = await test_client.post("/queue/join", json={"user_id": user_id})
            assert response.status_code == 200
            test_logger.info(f"Utilisateur {user_id} ajouté à la file d'attente")
            await asyncio.sleep(0.1)  # Petit délai entre chaque ajout
        
        # Vérifier l'état après ajout des utilisateurs en attente
        response = await test_client.get("/queue/get_users")
        assert response.status_code == 200
        data = response.json()
        test_logger.info(f"État des files après ajout des utilisateurs en attente: {data}")
        assert len(data["waiting_users"]) == 6, "Devrait avoir 6 utilisateurs en attente"
        
        # 3. Activer manuellement le check des slots pour le premier utilisateur
        test_logger.info("Activation manuelle du check des slots")
        await queue_manager.check_available_slots()
        
        # Vérifier l'état après le check des slots
        response = await test_client.get("/queue/get_users")
        assert response.status_code == 200
        data = response.json()
        test_logger.info(f"État après check des slots: {data}")
        assert len(data["draft_users"]) == 1, "Devrait avoir 1 utilisateur en draft"
        assert len(data["waiting_users"]) == 5, "Devrait avoir 5 utilisateurs en attente"
        
        # 4. Confirmer la connexion du premier utilisateur
        response = await test_client.post("/queue/confirm", json={"user_id": user_active})
        assert response.status_code == 200
        test_logger.info(f"Connexion confirmée pour {user_active}")
        
        # Vérifier l'état final
        response = await test_client.get("/queue/get_users")
        assert response.status_code == 200
        final_data = response.json()
        test_logger.info(f"État final des files: {final_data}")
        assert len(final_data["active_users"]) == 1, "Devrait avoir 1 utilisateur actif"
        assert len(final_data["waiting_users"]) == 5, "Devrait avoir 5 utilisateurs en attente"
        assert len(final_data["draft_users"]) == 0, "Ne devrait plus avoir d'utilisateur en draft"
        
        # Nettoyer Redis à la fin du test
        await queue_manager.redis.flushdb()
        test_logger.info("Base Redis nettoyée") 