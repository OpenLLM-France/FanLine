from celery import Celery
import os

def setup_test_celery():
    """Configure Celery pour les tests en mode asynchrone."""
    # Récupération des variables d'environnement Redis
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_db = int(os.getenv('REDIS_DB', 0))
    
    celery_app = Celery(
        'test_app',
        broker=f'redis://{redis_host}:{redis_port}/{redis_db}',
        backend=f'redis://{redis_host}:{redis_port}/{redis_db}'
    )
    
    celery_app.conf.update({
        'broker_url': f'redis://{redis_host}:{redis_port}/{redis_db}',
        'result_backend': f'redis://{redis_host}:{redis_port}/{redis_db}',
        'task_always_eager': False,  # Désactiver le mode eager
        'task_eager_propagates': False,
        'worker_prefetch_multiplier': 1,
        'task_acks_late': False,
        'task_track_started': True,
        'task_send_sent_event': True,
        'task_remote_tracebacks': True,
        'task_store_errors_even_if_ignored': True,
        'task_ignore_result': False,
        'worker_concurrency': 1,  # Un seul worker pour les tests
    })
    
    return celery_app 