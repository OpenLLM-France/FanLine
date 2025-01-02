import pytest
import asyncio

@pytest.mark.asyncio
class TestIntegration:
    async def test_concurrent_users(self, queue_manager):
        """Test le comportement avec plusieurs utilisateurs simultanés."""
        users = [f"user{i}" for i in range(60)]
        await asyncio.gather(*[queue_manager.add_to_queue(user) for user in users])
        
        active_count = queue_manager.redis.scard('active_users')
        draft_count = queue_manager.redis.scard('draft_users')
        assert active_count + draft_count <= queue_manager.max_active_users

    async def test_requeue_mechanism(self, queue_manager):
        """Test le mécanisme de remise en file d'attente."""
        for i in range(10):
            await queue_manager.add_to_queue(f"user{i}")
        
        await queue_manager.offer_slot("user0")
        await queue_manager.requeue_user("user0")
        
        position = queue_manager.redis.lpos('waiting_queue', "user0")
        assert position == 2 