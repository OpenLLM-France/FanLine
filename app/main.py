from fastapi import FastAPI, HTTPException, WebSocket, Depends
from app.queue_manager import QueueManager
from typing import Dict
import os
from redis.asyncio import Redis
from fastapi import WebSocketDisconnect
from pydantic import BaseModel
from contextlib import asynccontextmanager

class UserRequest(BaseModel):
    user_id: str

buffer ={}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie de l'application."""
    # Initialisation
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    app.state.redis = redis
    app.state.queue_manager = QueueManager(redis)
    
    # Démarrer le slot checker
    await app.state.queue_manager.start_slot_checker(check_interval=0.1)
    
    yield
    
    # Nettoyage
    await app.state.queue_manager.stop_slot_checker()
    await redis.aclose()

app = FastAPI(lifespan=lifespan)

async def get_queue_manager():
    """Dépendance pour obtenir le QueueManager."""
    return app.state.queue_manager

@app.post("/queue/join")
async def join_queue(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour rejoindre la file d'attente."""
    position = await queue_manager.add_to_queue(request.user_id)
    if position == 0:
        raise HTTPException(status_code=400, detail="Already in queue or active")
    return {"position": position}

@app.post("/queue/leave")
async def leave_queue(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour quitter la file d'attente."""
    success = await queue_manager.remove_from_queue(request.user_id)
    if not success:
        raise HTTPException(status_code=400, detail="Not in queue")
    return {"success": True}

@app.post("/queue/confirm")
async def confirm_connection(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour confirmer la connexion après l'obtention d'un slot."""
    success = await queue_manager.confirm_connection(request.user_id)
    if not success:
        raise HTTPException(status_code=400, detail="No draft slot available")
    return {"session_duration": queue_manager.session_duration}

@app.get("/queue/status/{user_id}")
async def get_status(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour obtenir le statut d'un utilisateur."""
    status = await queue_manager.get_user_status(user_id)
    if status is None:
        raise HTTPException(status_code=404, detail="User not found")
    return status

@app.post("/queue/heartbeat")
async def heartbeat(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour maintenir la session active."""
    success = await queue_manager.extend_session(request.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="No active session found")
    return {"success": True}

@app.get("/queue/metrics")
async def get_metrics(queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour obtenir les métriques de la file d'attente."""
    metrics = await queue_manager.get_metrics()
    return metrics

@app.get("/queue/timers/{user_id}")
async def get_timers(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour obtenir les timers actifs d'un utilisateur."""
    timers = await queue_manager.get_timers(user_id)
    return timers 