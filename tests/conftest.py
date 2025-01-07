import pytest
from redis.asyncio import Redis
import os
from app.queue_manager import QueueManager
from app.main import app
from httpx import AsyncClient
from celery import Celery
import logging
import sys
import atexit
import asyncio
import weakref

# Configuration du logging pour les tests
def setup_test_logging():
    logger = logging.getLogger('test_logger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = True
    
    # Supprimer les handlers existants de manière sécurisée
    handlers = logger.handlers[:]
    for handler in handlers:
        try:
            handler.flush()
            handler.close()
        except Exception:
            pass
        if handler in logger.handlers:
            logger.removeHandler(handler)
    
    # Handler pour la console avec buffer
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler pour le fichier avec buffer
    log_file = 'tests/test.log'
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8', delay=True)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Stocker les handlers dans un attribut du logger pour le nettoyage
    logger._test_handlers = [console_handler, file_handler]
    
    return logger

@pytest.fixture(scope="session")
def test_logger():
    logger = setup_test_logging()
    yield logger
    # Nettoyage sécurisé après les tests
    if hasattr(logger, '_test_handlers'):
        for handler in logger._test_handlers:
            try:
                handler.flush()
                handler.close()
            except Exception:
                pass
            if handler in logger.handlers:
                logger.removeHandler(handler)

# Définir la variable d'environnement TESTING
os.environ['TESTING'] = 'true'

@pytest.fixture(scope="session", autouse=True)
def celery_config():
    """Configure Celery pour les tests."""
    config = {
        'broker_url': 'redis://localhost:6379/0',
        'result_backend': 'redis://localhost:6379/0',
        'task_always_eager': True,  # Forcer le mode eager pour les tests
        'task_eager_propagates': True,
        'worker_prefetch_multiplier': 1,
        'task_acks_late': False,
        'task_track_started': True,
        'task_send_sent_event': True,
        'task_remote_tracebacks': True,
        'task_store_errors_even_if_ignored': True,
        'task_ignore_result': False
    }
    
    # Appliquer la configuration immédiatement
    from app.queue_manager import celery as app
    app.conf.update(config)
    
    return config

@pytest.fixture(scope="session")
def celery_app(celery_config, test_logger):
    from app.queue_manager import celery as app
    
    # Forcer la configuration
    app.conf.update(celery_config)
    app.conf.update(
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
    
    # Vérification du mode eager
    test_logger.info(f"Mode Celery configuré dans fixture - task_always_eager: {app.conf.task_always_eager}")
    
    # Handlers de tâches pour le logging
    from celery.signals import task_prerun, task_postrun, task_failure
    
    @task_prerun.connect
    def task_prerun_handler(task_id, task, *args, **kwargs):
        test_logger.info(f"Démarrage de la tâche Celery: {task.name} (ID: {task_id})")
        test_logger.debug(f"Arguments de la tâche: args={args}, kwargs={kwargs}")
        test_logger.debug(f"Mode eager actuel: {app.conf.task_always_eager}")

    @task_postrun.connect
    def task_postrun_handler(task_id, task, retval, state, *args, **kwargs):
        test_logger.info(f"Fin de la tâche Celery: {task.name} (ID: {task_id})")
        test_logger.debug(f"État final: {state}, Résultat: {retval}")

    @task_failure.connect
    def task_failure_handler(task_id, exception, traceback, *args, **kwargs):
        test_logger.error(f"Échec de la tâche Celery (ID: {task_id})")
        test_logger.error(f"Exception: {exception}")
        test_logger.debug(f"Traceback: {traceback}")

    return app

@pytest.fixture
async def redis_client(test_logger):
    test_logger.debug("Initialisation du client Redis pour les tests")
    try:
        redis = Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 0)),
            decode_responses=True
        )
        await redis.ping()  # Vérifier la connexion
        test_logger.info("Connexion Redis établie avec succès")
        
        await redis.flushdb()  # Nettoyer la base avant chaque test
        test_logger.debug("Base de données Redis nettoyée")
        
        yield redis
        
        test_logger.debug("Fermeture de la connexion Redis")
        await redis.aclose()
        
    except Exception as e:
        test_logger.error(f"Erreur lors de l'initialisation Redis: {str(e)}")
        raise

@pytest.fixture
async def queue_manager(redis_client, test_logger):
    test_logger.debug("Initialisation du QueueManager")
    try:
        manager = QueueManager(redis_client)
        # Vérifier si initialize existe, sinon on retourne directement le manager
        if hasattr(manager, 'initialize'):
            test_logger.debug("Appel de la méthode initialize")
            await manager.initialize()
        test_logger.info("QueueManager initialisé avec succès")
        yield manager  # Utiliser yield au lieu de return pour les fixtures async
    except Exception as e:
        test_logger.error(f"Erreur lors de l'initialisation du QueueManager: {str(e)}")
        raise

@pytest.fixture
async def test_client(redis_client, queue_manager, test_logger):
    test_logger.debug("Initialisation du client de test")
    try:
        app.state.redis = redis_client
        app.state.queue_manager = queue_manager
        async with AsyncClient(app=app, base_url="http://test") as client:
            test_logger.info("Client de test initialisé avec succès")
            yield client
    except Exception as e:
        test_logger.error(f"Erreur lors de l'initialisation du client de test: {str(e)}")
        raise

@pytest.fixture
async def queue_manager_with_checker(queue_manager, test_logger):
    test_logger.debug("Démarrage du slot checker")
    try:
        await queue_manager.start_slot_checker()
        test_logger.info("Slot checker démarré avec succès")
        yield queue_manager
    except Exception as e:
        test_logger.error(f"Erreur avec le slot checker: {str(e)}")
        raise
    finally:
        test_logger.debug("Arrêt du slot checker")
        try:
            await asyncio.wait_for(queue_manager.stop_slot_checker(), timeout=5.0)
            # Attendre que toutes les tâches en cours se terminent avec un timeout
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            if tasks:
                test_logger.debug(f"Attente de la fin de {len(tasks)} tâches")
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
        except asyncio.TimeoutError:
            test_logger.warning("Timeout lors de l'arrêt du slot checker")
        except Exception as e:
            test_logger.error(f"Erreur lors de l'arrêt du slot checker: {str(e)}")
        # Ne pas relever l'exception pendant le nettoyage 