import pytest
from redis.asyncio import Redis
from fastapi.testclient import TestClient
from httpx import AsyncClient
from app.main import app
from app.queue_manager import QueueManager
import os

@pytest.fixture
async def redis_client():
    """Fixture pour Redis en mode test."""
    client = Redis(
        host='redis-test',  
        port=6379,  
        db=1,  
        decode_responses=True
    )
    await client.flushdb() 
    yield client
    await client.aclose()  
    

@pytest.fixture
async def test_client():
    """Fixture pour le client de test FastAPI."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
async def queue_manager(redis_client):
    """Fixture pour le QueueManager."""
    manager = QueueManager(redis_client)
    await manager.start_slot_checker(check_interval=0.1)  # Intervalle court pour les tests
    yield manager
    await manager.stop_slot_checker()

@pytest.fixture(autouse=True)
async def setup_queue_manager(redis_client):
    """Configure le QueueManager pour les tests."""
    app.state.redis = redis_client
    app.state.queue_manager = QueueManager(redis_client)
    await app.state.queue_manager.start_slot_checker(check_interval=0.1)
    yield 
    await app.state.queue_manager.stop_slot_checker() 