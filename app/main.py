from fastapi import FastAPI, HTTPException, WebSocket, Depends, WebSocketDisconnect
from app.queue_manager import QueueManager
from typing import Dict
import os
from redis.asyncio import Redis
from pydantic import BaseModel
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import json
import logging

logger = logging.getLogger(__name__)

class UserRequest(BaseModel):
    user_id: str

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: str):
        if user_id in self.active_connections:
            del self.active_connections[user_id]

    async def send_timer_update(self, user_id: str, timer_data: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json({
                    "type": "timer",
                    **timer_data
                })
            except Exception as e:
                print(f"Erreur lors de l'envoi du message à {user_id}: {str(e)}")
                self.disconnect(user_id)

manager = ConnectionManager()

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
    app.state.connection_manager = manager
    
    # Configurer le gestionnaire de connexions
    app.state.queue_manager.set_connection_manager(manager)
    
    # Démarrer le slot checker
    await app.state.queue_manager.start_slot_checker(check_interval=0.1)
    
    yield
    
    # Nettoyage
    await app.state.queue_manager.stop_slot_checker()
    await redis.aclose()

app = FastAPI(lifespan=lifespan)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_queue_manager() -> QueueManager:
    """Dépendance pour obtenir le gestionnaire de file d'attente."""
    return app.state.queue_manager

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé."""
    return {"status": "ok"}

@app.post("/queue/join")
async def join_queue(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour rejoindre la file d'attente."""
    result = await queue_manager.add_to_queue(request.user_id)
    logger.debug(f"Join queue result: {result}")
    if  result["commit_status"] in ["draft","connected"]:
        raise HTTPException(status_code=400, detail="Utilisateur déjà dans la file d'attente")
    return result

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

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            # Attendre les messages du client
            data = await websocket.receive_text()
            # Pour l'instant, nous ne faisons rien avec les messages reçus
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        print(f"Erreur WebSocket pour {user_id}: {str(e)}")
        manager.disconnect(user_id) 