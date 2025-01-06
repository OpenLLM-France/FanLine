import pytest
from fastapi.testclient import TestClient

class TestAPI:
    def test_join_queue_flow_with_available_slots(self, test_client, queue_manager):
        """Test le flux quand des slots sont disponibles."""
        
        response = test_client.post("/queue/join/test_user")
        assert response.status_code == 200
        assert response.json()["position"] == 1

        response = test_client.get("/queue/status/test_user")
        assert response.status_code == 200
        assert response.json()["status"] == "draft"  

        response = test_client.post("/queue/confirm/test_user")
        assert response.status_code == 200

    def test_join_queue_flow_when_full(self, test_client, queue_manager):
        """Test le flux quand la file est pleine."""
       
        queue_manager.redis.sadd('active_users', *[f"existing_user_{i}" for i in range(queue_manager.max_active_users)])

        
        response = test_client.post("/queue/join/test_user")
        assert response.status_code == 200
        assert response.json()["position"] == 1

        response = test_client.get("/queue/status/test_user")
        assert response.status_code == 200
        assert response.json()["status"] == "waiting"  