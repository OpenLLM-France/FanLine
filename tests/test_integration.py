import pytest
import asyncio
from app.queue_manager import QueueManager
from redis.exceptions import RedisError

class TestIntegration:
    @pytest.mark.asyncio
    async def test_concurrent_users(self, redis_client):
        try:
            queue_manager = QueueManager(redis_client)
            users = [f"user_{i}" for i in range(5)]
            
            # Add users concurrently
            tasks = [queue_manager.add_to_queue(user) for user in users]
            await asyncio.gather(*tasks)
            
            # check queue size
            queue_size = await redis_client.llen("waiting_queue")
            assert queue_size == 5
            
            # check queue order
            queue_list = await redis_client.lrange("waiting_queue", 0, -1)
            assert len(queue_list) == 5
            assert all(user in users for user in queue_list)
        except RedisError as e:
            pytest.fail(f"Redis error: {str(e)}")
        finally:
            # cleanup
            await redis_client.delete("waiting_queue")
            for user in users:
                await redis_client.srem("queued_users", user)

    @pytest.mark.asyncio
    async def test_requeue_mechanism(self, redis_client):
        try:
            queue_manager = QueueManager(redis_client)
            user_id = "test_user_requeue"
            
            # init queue
            await queue_manager.add_to_queue(user_id)
            assert await redis_client.sismember("queued_users", user_id)
            
            # offer slot
            await queue_manager.offer_slot(user_id)
            assert await redis_client.sismember("draft_users", user_id)
            assert not await redis_client.sismember("queued_users", user_id)
            
            # let draft expire
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.srem("draft_users", user_id)
            
            # requeue
            await queue_manager.add_to_queue(user_id)
            assert await redis_client.sismember("queued_users", user_id)
            assert not await redis_client.sismember("draft_users", user_id)
        except RedisError as e:
            pytest.fail(f"Redis error: {str(e)}")
        finally:
            # Cleanup
            await redis_client.delete("waiting_queue")
            await redis_client.srem("queued_users", user_id)
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.srem("draft_users", user_id) 