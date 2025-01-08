from celery import Celery
import os
import logging
from app.queue_manager import update_timer_channel, handle_draft_expiration, cleanup_session

logger = logging.getLogger('test_logger')

def setup_celery_worker():
    """Configure le worker Celery pour les tests."""
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
        'task_always_eager': False,
        'task_eager_propagates': False,
        'worker_prefetch_multiplier': 1,
        'task_acks_late': False,
        'task_track_started': True,
        'task_send_sent_event': True,
        'task_remote_tracebacks': True,
        'task_store_errors_even_if_ignored': True,
        'task_ignore_result': False,
        'worker_concurrency': 1
    })
    
    # Enregistrer les tâches
    celery_app.task(name='app.queue_manager.update_timer_channel')(update_timer_channel)
    celery_app.task(name='app.queue_manager.handle_draft_expiration')(handle_draft_expiration)
    celery_app.task(name='app.queue_manager.cleanup_session')(cleanup_session)
    
    return celery_app

if __name__ == '__main__':
    celery_app = setup_celery_worker()
    celery_app.worker_main(['worker', '--loglevel=INFO']) 