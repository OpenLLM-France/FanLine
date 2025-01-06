import pytest
from httpx import AsyncClient
from app.main import app
from app.queue_manager import QueueManager
import asyncio
import os

@pytest.fixture
def queue_manager(redis_client):
    return QueueManager(redis_client)

class TestTimers:
    @pytest.mark.asyncio
    async def test_draft_timer_redis(self, queue_manager, redis_client):
        user_id = "test_user_draft"
        
        await queue_manager.offer_slot(user_id)
        exists = await redis_client.exists(f"draft:{user_id}")
        assert exists
        
        ttl = await redis_client.ttl(f"draft:{user_id}")
        assert 0 < ttl <= queue_manager.draft_duration
        
        await asyncio.sleep(2)
        
        new_ttl = await redis_client.ttl(f"draft:{user_id}")
        assert new_ttl < ttl
        
        await redis_client.delete(f"draft:{user_id}")
        await redis_client.srem("draft_users", user_id)

    @pytest.mark.asyncio
    async def test_session_timer_redis(self, queue_manager, redis_client):
        user_id = "test_user_session"
        
        # Setup: ajouter l'utilisateur en draft d'abord
        await redis_client.sadd("draft_users", user_id)
        await redis_client.setex(f"draft:{user_id}", queue_manager.draft_duration, "1")
        
        # Confirmer la connexion
        success = await queue_manager.confirm_connection(user_id)
        assert success, "La confirmation de connexion a échoué"
        
        exists = await redis_client.exists(f"session:{user_id}")
        assert exists, "La session n'existe pas"
        
        ttl = await redis_client.ttl(f"session:{user_id}")
        assert 0 < ttl <= queue_manager.session_duration
        
        await asyncio.sleep(2)
        
        new_ttl = await redis_client.ttl(f"session:{user_id}")
        assert new_ttl < ttl
        
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_draft(self, test_client, redis_client):
        user_id = "test_user_api_draft"
        
        await redis_client.sadd("draft_users", user_id)
        await redis_client.setex(f"draft:{user_id}", 300, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        
        timers = response.json()
        assert "draft" in timers
        assert 0 < timers["draft"] <= 300
        
        await redis_client.delete(f"draft:{user_id}")
        await redis_client.srem("draft_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_session(self, test_client, redis_client):
        user_id = "test_user_api_session"
        
        # Setup: ajouter l'utilisateur en tant qu'utilisateur actif
        await redis_client.sadd("active_users", user_id)
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        
        timers = response.json()
        assert "session" in timers
        assert 0 < timers["session"] <= 1200
        
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_both(self, test_client, redis_client):
        user_id = "test_user_api_both"
        
        await redis_client.sadd("draft_users", user_id)
        await redis_client.sadd("active_users", user_id)
        await redis_client.setex(f"draft:{user_id}", 300, "1")
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        
        timers = response.json()
        assert "draft" in timers
        assert "session" in timers
        assert 0 < timers["draft"] <= 300
        assert 0 < timers["session"] <= 1200
        
        await redis_client.delete(f"draft:{user_id}")
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("draft_users", user_id)
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_no_timers(self, test_client, redis_client):
        user_id = "test_user_api_none"
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        timers = response.json()
        assert timers == {} 