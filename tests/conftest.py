import pytest
from redis import Redis
from fastapi.testclient import TestClient
from app.main import app
from app.queue_manager import QueueManager

@pytest.fixture(autouse=True)
async def clean_redis():
    """Fixture pour nettoyer Redis avant et après chaque test."""
    redis = Redis(host='redis-test', port=6379, db=1)
    redis.flushdb()
    yield redis
    redis.flushdb()

@pytest.fixture
def queue_manager(clean_redis):
    """Fixture pour le QueueManager configuré pour les tests."""
    manager = QueueManager()
    manager.redis = clean_redis
    return manager

@pytest.fixture
def test_client():
    """Fixture pour le client FastAPI de test."""
    return TestClient(app) 