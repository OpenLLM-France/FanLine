import asyncio
import logging
import os
import requests
import time
from datetime import datetime
from redis.asyncio import Redis
# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = "http://localhost:8000"  # Ajustez selon votre configuration
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def test_auto_expiration_flow():
    """Test le flux complet d'auto-expiration avec des requêtes HTTP."""
    try:
        user_id = "test_auto_expiration"
        
        # Nettoyage initial via l'API
        logger.info("🧹 Nettoyage initial de la file...")
        response = requests.post(
            f"{API_BASE_URL}/queue/cleanup_all",
            headers=HEADERS
        )
        assert response.status_code == 200, "Erreur lors du nettoyage initial"
        
        # Vérification de l'état initial
        response = requests.get(
            f"{API_BASE_URL}/queue/get_users",
            headers=HEADERS
        )
        assert response.status_code == 200
        response = response.json()
        assert response["active_users"] == [], "La file active devrait être vide"
        assert response["draft_users"] == [], "La file draft devrait être vide"
        
        # Test du premier utilisateur
        logger.info("🔄 Ajout de l'utilisateur à la file...")
        response = requests.post(
            f"{API_BASE_URL}/queue/join",
            json={"user_id": user_id},
            headers=HEADERS
        )
        assert response.status_code == 200
        
        # Vérification du statut initial
        response = requests.get(
            f"{API_BASE_URL}/queue/status/{user_id}",
            headers=HEADERS
        )
        assert response.status_code == 200, f"Erreur lors de la vérification du statut: {response.text}"
        logger.info(f"Status initial: {response.json()}")
        


        # Vérification du statut après draft
        response = requests.get(
            f"{API_BASE_URL}/queue/status/{user_id}",
            headers=HEADERS
        )
        assert response.status_code == 200, f"Erreur lors de la vérification du statut: {response.text}"
        logger.info(f"Status après draft: {response.json()}")
        
        # Confirmation de la connexion
        logger.info("🔄 Confirmation de la connexion...")
        response = requests.post(
            f"{API_BASE_URL}/queue/confirm/",
            json={"user_id": user_id},
            headers=HEADERS
        )
        assert response.status_code == 200, f"Erreur lors de la confirmation: {response.text}"
        
        # Vérification du statut après connexion
        response = requests.get(
            f"{API_BASE_URL}/queue/status/{user_id}",
            headers=HEADERS
        )
        assert response.status_code == 200, f"Erreur lors de la vérification du statut: {response.text}"
        logger.info(f"Status après connexion: {response.json()}")
        
        # Test d'expiration (attendre 2 secondes)
        logger.info("Test d'expiration...")
        time.sleep(3)
        
        # Vérification du statut final
        response = requests.get(
            f"{API_BASE_URL}/queue/status/{user_id}",
            headers=HEADERS
        )
        assert response.status_code == 200, f"Erreur lors de la vérification du statut final: {response.text}"
        final_status = response.json()
        logger.info(f"Status final: {final_status}")
        
        # Vérification que l'utilisateur est bien déconnecté
        assert final_status["status"] == "disconnected", f"Statut incorrect: {final_status}"
        
        return True

    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_auto_expiration_flow()
    if success:
        logger.info("✅ Test terminé avec succès")
        exit(0)
    else:
        logger.error("❌ Test échoué")
        exit(1)