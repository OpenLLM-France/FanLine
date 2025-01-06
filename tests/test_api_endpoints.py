import pytest
from app.queue_manager import QueueManager
from httpx import AsyncClient
import logging
import debugpy

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestAPI:
    @pytest.mark.asyncio
    async def test_join_queue_flow(self, test_client, redis_client):
        user_id = "test_user_flow"
        
        # Point d'arrêt manuel si nécessaire
        # debugpy.breakpoint()
        
        # Log l'état initial
        logger.debug("État initial de Redis:")
        logger.debug(f"Queued users: {await redis_client.smembers('queued_users')}")
        logger.debug(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
        
        try:
            # Join queue
            response = await test_client.post("/queue/join", json={"user_id": user_id})
            logger.debug(f"Join queue response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert "position" in data
            assert data["position"] == 1
            
            # Vérifier l'état après join
            logger.debug("État après join:")
            logger.debug(f"Queued users: {await redis_client.smembers('queued_users')}")
            logger.debug(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
            assert await redis_client.sismember("queued_users", user_id)
            
            # Check status
            response = await test_client.get(f"/queue/status/{user_id}")
            logger.debug(f"Status response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "waiting"
            assert data["position"] == 1
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}")
            # Log l'état final en cas d'erreur
            logger.error("État final de Redis:")
            logger.error(f"Queued users: {await redis_client.smembers('queued_users')}")
            logger.error(f"Waiting queue: {await redis_client.lrange('waiting_queue', 0, -1)}")
            raise
            
        finally:
            # Cleanup
            await redis_client.delete("waiting_queue")
            await redis_client.srem("queued_users", user_id)

    @pytest.mark.asyncio
    async def test_join_queue_flow_when_full(self, test_client, redis_client):
        queue_manager = QueueManager(redis_client)
        max_users = queue_manager.max_active_users
        users = [f"test_user_{i}" for i in range(max_users + 1)]
        
        logger.debug(f"Testing with {max_users} users")
        
        try:
            # Fill queue
            for i in range(max_users):
                logger.debug(f"Adding user {users[i]}")
                await queue_manager.add_to_queue(users[i])
                await queue_manager.offer_slot(users[i])
                await queue_manager.confirm_connection(users[i])
                
            # Vérifier l'état après remplissage
            logger.debug("État après remplissage:")
            logger.debug(f"Active users: {await redis_client.smembers('active_users')}")
            logger.debug(f"Active count: {await redis_client.scard('active_users')}")
            
            # Try to join full queue
            response = await test_client.post("/queue/join", json={"user_id": users[-1]})
            logger.debug(f"Join full queue response: {response.json()}")
            assert response.status_code == 200
            data = response.json()
            assert data["position"] > 0
            
        except Exception as e:
            logger.error(f"Test failed with error: {str(e)}")
            logger.error("État final:")
            logger.error(f"Active users: {await redis_client.smembers('active_users')}")
            logger.error(f"Queued users: {await redis_client.smembers('queued_users')}")
            raise
            
        finally:
            # Cleanup
            await redis_client.delete("waiting_queue")
            for user in users:
                await redis_client.srem("queued_users", user)
                await redis_client.srem("active_users", user)
                await redis_client.delete(f"session:{user}")

    @pytest.mark.asyncio
    async def test_leave_queue(self, test_client, redis_client):
        user_id = "test_user_leave"
        
        # Add to queue first
        await redis_client.rpush("waiting_queue", user_id)
        await redis_client.sadd("queued_users", user_id)
        
        # Leave queue
        response = await test_client.post("/queue/leave", json={"user_id": user_id})
        assert response.status_code == 200
        
        # Verify user is removed
        assert not await redis_client.sismember("queued_users", user_id)
        queue_list = await redis_client.lrange("waiting_queue", 0, -1)
        assert user_id not in queue_list
        
        # Cleanup
        await redis_client.delete("waiting_queue")

    @pytest.mark.asyncio
    async def test_get_status_nonexistent(self, test_client, redis_client):
        response = await test_client.get("/queue/status/nonexistent_user")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_heartbeat(self, test_client, redis_client):
        user_id = "test_user_heartbeat"
        
        # Setup active user
        await redis_client.sadd("active_users", user_id)
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        # Send heartbeat
        response = await test_client.post("/queue/heartbeat", json={"user_id": user_id})
        assert response.status_code == 200
        
        # Verify session is extended
        ttl = await redis_client.ttl(f"session:{user_id}")
        assert 0 < ttl <= 1200
        
        # Cleanup
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_heartbeat_invalid(self, test_client, redis_client):
        response = await test_client.post("/queue/heartbeat", json={"user_id": "nonexistent_user"})
        assert response.status_code == 404  