import asyncio
import logging
import os
from redis.asyncio import Redis
from app.queue_manager import QueueManager, DEBUG, auto_expiration, cleanup_session
from app.celery_app import celery

# Configuration pour les tests
celery.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=False,
    result_backend='redis://localhost:6379/0'
)

# Désactiver le mode asynchrone de Celery pour les tests
celery.conf.task_always_eager = True
os.environ['TESTING'] = 'true'
os.environ['DEBUG'] = 'true'  # Activer le mode debug

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,  # Niveau DEBUG pour plus de détails
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_auto_expiration_flow():
    """Test le flux complet d'auto-expiration (draft -> connected -> expired)."""
    try:
        # Initialisation
        redis_client = Redis(
            host='localhost',
            port=6379,
            decode_responses=True
        )
        await redis_client.flushdb()
        queue_manager = QueueManager(redis_client)
        user_id = "test_auto_expiration"
        
        # 1. Ajouter l'utilisateur à la file
        logger.info("🔄 Ajout de l'utilisateur à la file...")
        await queue_manager.add_to_queue(user_id)
        status = await queue_manager.get_user_status(user_id)
        logger.info(f"Status initial: {status}")

        # 2. Forcer le passage en draft
        logger.info("🔄 Passage en draft...")
        await queue_manager.check_available_slots()
        status = await queue_manager.get_user_status(user_id)
        assert status["status"] == "draft", f"Statut incorrect: {status}"
        logger.info(f"Status après draft: {status}")
        
        # 3. Confirmer la connexion avec un TTL court
        logger.info("🔄 Confirmation de la connexion...")
        await queue_manager.confirm_connection(user_id)
        status = await queue_manager.get_user_status(user_id)
        
        # Point de debug : Tester directement la tâche auto_expiration
        logger.info("Test direct de auto_expiration...")
        session_ttl = 2  # TTL court pour le test
        await redis_client.setex(f"session:{user_id}", session_ttl, "1")
        
        # Vous pouvez mettre un point d'arrêt ici
        #result = await auto_expiration(session_ttl, "active", user_id)
        #logger.info(f"Résultat auto_expiration: {result}")
        # 4. Attendre l'expiration
        logger.info("⏳ Attente de l'expiration...")
        await asyncio.sleep(3)    
        status = await queue_manager.get_user_status(user_id)
        assert status["status"] == "disconnected", f"Statut incorrect: {status}"
        logger.info(f"Status après connexion: {status}")



        # Point de debug : Tester directement cleanup_session
        logger.info("Test direct de cleanup_session...")
        # Vous pouvez mettre un point d'arrêt ici
        #result = await cleanup_session(user_id)
        #logger.info(f"Résultat cleanup_session: {result}")

        # 5. Vérifier l'état final
        status = await queue_manager.get_user_status(user_id)
        logger.info(f"Status final: {status}")
        assert status["status"] == "disconnected", f"Statut incorrect: {status}"

        # Vérifications finales
        is_active = await redis_client.sismember("active_users", user_id)
        session_exists = await redis_client.exists(f"session:{user_id}")
        assert not is_active and not session_exists, "Nettoyage incomplet"
        
        logger.info("✅ Test réussi!")
        return True

    except AssertionError as e:
        logger.error(f"❌ Test échoué: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {str(e)}")
        return False
    finally:
        # Nettoyage
        try:
            await redis_client.delete(f"session:{user_id}")
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.delete(f"status_history:{user_id}")
            await redis_client.srem("active_users", user_id)
            await redis_client.srem("draft_users", user_id)
            await redis_client.close()
        except Exception as e:
            logger.error(f"Erreur pendant le nettoyage: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_auto_expiration_flow())