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

def pytest_addoption(parser):
    """Ajoute des options personnalisées pour le débogage."""
    parser.addoption(
        "--debug-user",
        action="store",
        default="test_user",
        help="ID de l'utilisateur pour les tests de débogage"
    )
    parser.addoption(
        "--debug-mode",
        action="store_true",
        default=False,
        help="Active le mode débogage détaillé"
    )
    parser.addoption(
        "--redis-debug",
        action="store_true",
        default=False,
        help="Active le débogage des opérations Redis"
    )

@pytest.fixture
def debug_config(request):
    """Fixture pour la configuration de débogage."""
    return {
        "user_id": request.config.getoption("--debug-user"),
        "debug_mode": request.config.getoption("--debug-mode"),
        "redis_debug": request.config.getoption("--redis-debug")
    }

@pytest.fixture
def test_logger():
    """Configure le logger pour les tests."""
    logger = logging.getLogger('test_logger')
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if os.environ.get('PYTEST_DEBUG') else logging.INFO)
    return logger

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
def celery_logger():
    """Configure le logger pour les tests Celery."""
    logger = logging.getLogger('celery_test_logger')
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if os.environ.get('PYTEST_DEBUG') else logging.INFO)
    return logger

@pytest.fixture(scope="session")
def celery_app(celery_config, celery_logger):
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
    
    celery_logger.info("Configuration Celery appliquée")
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