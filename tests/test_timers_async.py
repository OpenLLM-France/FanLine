import pytest
from app.queue_manager import QueueManager
from httpx import AsyncClient
import logging
import asyncio
from celery import current_app as celery_app
import time

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestTimersAsync:
    @pytest.fixture(autouse=True)
    async def cleanup(self, redis_client):
        self.redis = redis_client
        yield
        # Nettoyage après chaque test
        await self.redis.flushall()
        if hasattr(self, 'queue_manager'):
            await self.queue_manager.stop_slot_checker()

    @pytest.mark.asyncio
    async def test_timers_async(self, redis_client, test_client, test_logger):
        """Test le fonctionnement asynchrone des timers."""
        # Configuration de Celery
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True,
            broker_connection_retry=False,
            broker_connection_max_retries=0,
            result_backend='redis://localhost:6379',
            broker_url='redis://localhost:6379'
        )
        test_logger.info(f"Mode Celery configuré: EAGER={celery_app.conf.task_always_eager}")
        
        # Nettoyage complet de Redis avant le test
        async with redis_client.pipeline(transaction=True) as pipe:
            pipe.delete("waiting_queue", "active_users", "draft_users", "queued_users", "accounts_queue")
            pipe.delete("available_slots")
            await pipe.execute()
        
        # Initialiser les slots disponibles
        await redis_client.set("available_slots", "2")
        test_logger.info("Redis nettoyé et slots initialisés")
        
        user_id = "test_user_timers"
        
        try:
            # Ajouter l'utilisateur à la file
            test_logger.info("🔄 Tentative d'ajout de l'utilisateur")
            join_response = await test_client.post(f"/queue/join/{user_id}")
            assert join_response.status_code == 200
            test_logger.info("Utilisateur ajouté à la file")
            
            # Vérifier les timers initiaux (devrait avoir un timer draft)
            timers_response = await test_client.get(f"/queue/timers/{user_id}")
            assert timers_response.status_code == 200
            initial_timers = timers_response.json()
            assert initial_timers.get('timer_type') == 'draft'
            assert initial_timers.get('ttl') == 300
            assert initial_timers.get('channel') == f'timer:channel:{user_id}'
            test_logger.info("Vérification des timers initiaux OK")
            
            # Attendre que l'utilisateur soit en draft
            max_wait = 5
            start_time = time.time()
            is_draft = False
            
            while not is_draft and (time.time() - start_time) < max_wait:
                status_response = await test_client.get(f"/queue/status/{user_id}")
                if status_response.json().get('status') == 'draft':
                    is_draft = True
                    break
                await asyncio.sleep(0.1)
            
            assert is_draft, "L'utilisateur n'a pas été placé en draft"
            test_logger.info("Utilisateur placé en draft")
            
            # Vérifier les timers après le draft
            timers_response = await test_client.get(f"/queue/timers/{user_id}")
            assert timers_response.status_code == 200
            draft_timers = timers_response.json()
            assert draft_timers.get('timer_type') == 'draft'
            assert draft_timers.get('ttl') > 0
            test_logger.info(f"Timers en draft vérifiés: {draft_timers}")
            
            # Attendre quelques mises à jour du timer
            await asyncio.sleep(2)
            
            # Vérifier que le TTL a diminué
            timers_response = await test_client.get(f"/queue/timers/{user_id}")
            assert timers_response.status_code == 200
            updated_timers = timers_response.json()
            assert updated_timers.get('ttl') < draft_timers.get('ttl'), f"Le TTL n'a pas diminué: {updated_timers.get('ttl')} >= {draft_timers.get('ttl')}"
            test_logger.info(f"Timer décroissant vérifié: {updated_timers.get('ttl')} < {draft_timers.get('ttl')}")
            
        finally:
            # Nettoyage complet
            test_logger.info("Nettoyage final")
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.delete("waiting_queue", "active_users", "draft_users", "queued_users", "accounts_queue")
                pipe.delete("available_slots")
                pipe.delete(f"draft:{user_id}", f"session:{user_id}", f"timer:channel:{user_id}")
                pipe.delete(f"last_status:{user_id}", f"status_history:{user_id}")
                await pipe.execute()
            test_logger.info("Test terminé, nettoyage effectué") 