import pytest
import json
from app.queue_manager import QueueManager

class TestQueueManager:
    @pytest.mark.asyncio
    async def test_add_to_queue(self, queue_manager):
        """Test l'ajout d'un utilisateur à la file d'attente."""
        position = await queue_manager.add_to_queue("user1")
        assert position == 1
        assert queue_manager.redis.llen('waiting_queue') == 1

    @pytest.mark.asyncio
    async def test_draft_flow(self, queue_manager):
        """Test le flux complet du système de draft."""
        await queue_manager.add_to_queue("user1")
        await queue_manager.offer_slot("user1")
        assert queue_manager.redis.sismember('draft_users', "user1")
        
        success = await queue_manager.confirm_connection("user1")
        assert success
        assert queue_manager.redis.sismember('active_users', "user1")

    @pytest.mark.asyncio
    async def test_draft_expiration(self, queue_manager):
        """Test l'expiration d'un draft."""
        await queue_manager.add_to_queue("user1")
        await queue_manager.offer_slot("user1")
        queue_manager.redis.delete(f'draft:user1')
        
        success = await queue_manager.confirm_connection("user1")
        assert not success 