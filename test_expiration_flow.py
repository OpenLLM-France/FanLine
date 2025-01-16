import asyncio
import logging
import os
from redis.asyncio import Redis
from app.queue_manager import QueueManager, DEBUG, auto_expiration
from app.celery_app import celery

# Configuration Celery
celery.conf.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/0',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    task_always_eager=True,
    task_eager_propagates=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=False,
    imports=['app.queue_manager'],
    worker_pool='solo'
)

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def sync_get_task_result(task_result, timeout=None):
    """Version synchrone de get_task_result."""
    return task_result.get(timeout=timeout)

async def test_auto_expiration_flow():
    """Test le flux complet d'auto-expiration."""
    redis_client = None
    try:
        redis_client = Redis(
            host='localhost',
            port=6379,
            decode_responses=True
        )
        await redis_client.flushdb()
        queue_manager = QueueManager(redis_client)
        user_id = "test_auto_expiration"
        user_id2 = "test_auto_expiration2"

        # Test du premier utilisateur
        logger.info("🔄 Ajout de l'utilisateur à la file...")
        await queue_manager.add_to_queue(user_id)
        status = await queue_manager.get_user_status(user_id)
        
        logger.info("🔄 Passage en draft...")
        await queue_manager.check_available_slots()
        status = await queue_manager.get_user_status(user_id)
        
        logger.info("🔄 Confirmation de la connexion...")
        confirm = await queue_manager.confirm_connection(user_id)
        status = await queue_manager.get_user_status(user_id)
        
        # Test d'expiration
        logger.info("Test d'expiration...")
        session_ttl = 2
        await redis_client.setex(f"session:{user_id}", session_ttl, "1")
        status = await queue_manager.get_user_status(user_id)
    
        
        # Attente synchrone
        await asyncio.sleep(3)
        status = await queue_manager.get_user_status(user_id)
        
        # Test du deuxième utilisateur
        logger.info("🔄 Test du deuxième utilisateur...")
        await queue_manager.add_to_queue(user_id)
        status = await queue_manager.get_user_status(user_id)
        await redis_client.setex(f"draft:{user_id}", session_ttl, "1")
        await asyncio.sleep(3)
        status = await queue_manager.get_user_status(user_id)
        
        return True

    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {str(e)}")
        return False
    finally:
        if redis_client:
            try:
                await redis_client.delete(f"session:{user_id}")
                await redis_client.delete(f"draft:{user_id}")
                await redis_client.delete(f"status_history:{user_id}")
                await redis_client.srem("active_users", user_id)
                await redis_client.srem("draft_users", user_id)
                await redis_client.aclose()
            except Exception as e:
                logger.error(f"Erreur pendant le nettoyage: {str(e)}")

def run_test():
    """Fonction wrapper pour exécuter le test."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(test_auto_expiration_flow())
        loop.close()
        return result
    except Exception as e:
        logger.error(f"Erreur dans run_test: {e}")
        return False

if __name__ == "__main__":
    success = run_test()
    if success:
        logger.info("✅ Test terminé avec succès")
        exit(0)
    else:
        logger.error("❌ Test échoué")
        exit(1)