from fastapi import FastAPI, HTTPException
from app.queue_manager import QueueManager
from typing import Dict

app = FastAPI()
queue_manager = QueueManager()

@app.post("/queue/join/{user_id}")
async def join_queue(user_id: str) -> Dict:
    """Endpoint pour rejoindre la file d'attente."""
    position = await queue_manager.add_to_queue(user_id)
    if position == 0:
        raise HTTPException(status_code=400, detail="Already in queue or active")
    return {"position": position}

@app.post("/queue/confirm/{user_id}")
async def confirm_connection(user_id: str) -> Dict:
    """Endpoint pour confirmer la connexion après l'obtention d'un slot."""
    success = await queue_manager.confirm_connection(user_id)
    if not success:
        raise HTTPException(status_code=400, detail="No draft slot available")
    return {"session_duration": queue_manager.session_duration}

@app.get("/queue/status/{user_id}")
async def get_status(user_id: str) -> Dict:
    """Endpoint pour obtenir le statut d'un utilisateur."""
    if queue_manager.redis.sismember('active_users', user_id):
        return {"status": "active"}
    if queue_manager.redis.sismember('draft_users', user_id):
        return {"status": "draft"}
    position = queue_manager.redis.lpos('waiting_queue', user_id)
    if position is not None:
        return {"status": "waiting", "position": position + 1}
    return {"status": "disconnected"}

@app.get("/queue/metrics")
async def get_metrics() -> Dict:
    """Endpoint pour obtenir les métriques de la file d'attente."""
    return {
        "active_users": queue_manager.redis.scard('active_users'),
        "waiting_users": queue_manager.redis.llen('waiting_queue'),
        "total_slots": queue_manager.max_active_users
    } 