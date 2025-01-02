import pytest
from fastapi.testclient import TestClient

class TestAPI:
    def test_join_queue_flow(self, test_client, queue_manager):
        """Test le flux complet d'un utilisateur via l'API."""
        response = test_client.post("/queue/join/test_user")
        assert response.status_code == 200
        assert response.json()["position"] == 1

        response = test_client.get("/queue/status/test_user")
        assert response.status_code == 200
        assert response.json()["status"] == "waiting"

        queue_manager.redis.sadd('draft_users', "test_user")
        queue_manager.redis.setex('draft:test_user', 300, '1')

        response = test_client.post("/queue/confirm/test_user")
        assert response.status_code == 200 