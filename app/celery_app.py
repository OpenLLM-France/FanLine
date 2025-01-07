from celery import Celery
import os

celery = Celery('queue_system')

# Configuration de base
celery.conf.update(
    broker_url='redis://localhost:6379/0',
    result_backend='redis://localhost:6379/0',
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Configuration pour les tests
if os.environ.get('TESTING') == 'true':
    celery.conf.update(
        task_always_eager=True,  # Exécuter les tâches de manière synchrone
        task_eager_propagates=True,  # Propager les exceptions en mode eager
    ) 