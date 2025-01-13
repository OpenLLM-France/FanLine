from fastapi import FastAPI, HTTPException, WebSocket, Depends, WebSocketDisconnect
from app.queue_manager import QueueManager
from typing import Dict, Optional
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
    await app.state.queue_manager.start_slot_checker()
    
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

# Configuration Redis
async def get_redis():
    redis = Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=True
    )
    try:
        yield redis
    finally:
        await redis.aclose()

async def get_queue_manager(redis: Redis = Depends(get_redis)) -> QueueManager:
    return QueueManager(redis)

@app.get("/health")
async def health_check():
    """Endpoint de vérification de santé."""
    return {"status": "ok"}

@app.post("/queue/join/{user_id}")
async def join_queue(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)):
    """Ajoute un utilisateur à la file d'attente."""
    try:
        result = await queue_manager.add_to_queue(user_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/queue/leave/{user_id}")
async def leave_queue(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Permet à un utilisateur de quitter la file d'attente ou sa session active."""
    try:
        # Vérifier l'état actuel de l'utilisateur
        current_status = await queue_manager.get_user_status(user_id)
        
        # Si l'utilisateur n'existe pas ou n'a jamais été dans le système
        if current_status["status"] is None:
            raise HTTPException(
                status_code=404,
                detail="Utilisateur non trouvé dans le système"
            )
        
        # Gérer selon l'état actuel
        if current_status["status"] == "waiting":
            # Retirer de la file d'attente mais garder dans accounts_queue
            success = await queue_manager.remove_from_queue(user_id)
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="Erreur lors de la sortie de la file d'attente"
                )
        elif current_status["status"] == "draft":
            # Retirer du draft mais garder dans accounts_queue
            async with queue_manager.redis.pipeline(transaction=True) as pipe:
                pipe.srem('draft_users', user_id)
                pipe.delete(f'draft:{user_id}')
                await pipe.execute()
        elif current_status["status"] == "connected":
            # Retirer de la session active mais garder dans accounts_queue
            async with queue_manager.redis.pipeline(transaction=True) as pipe:
                pipe.srem('active_users', user_id)
                pipe.delete(f'session:{user_id}')
                await pipe.execute()
        elif current_status["status"] == "disconnected":
            # Déjà déconnecté, rien à faire
            return {
                "previous_status": "disconnected",
                "new_status": "disconnected",
                "user_id": user_id,
                "in_accounts_queue": True
            }
        
        # Récupérer le nouveau statut (devrait être "disconnected" car dans accounts_queue)
        new_status = await queue_manager.get_user_status(user_id)
        
        return {
            "previous_status": current_status["status"],
            "new_status": new_status["status"],
            "user_id": user_id,
            "in_accounts_queue": await queue_manager.redis.sismember('accounts_queue', user_id)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/queue/confirm/{user_id}")
async def confirm_queue_connection(
    user_id: str,
    queue_manager: QueueManager = Depends(get_queue_manager)
) -> Dict:
    """Confirme la connexion d'un utilisateur."""
    try:
        result = await queue_manager.confirm_connection(user_id)
        if result:
            logger.info(f"✅ Confirmation réussie pour {user_id}, résultat: {result}")
            return {"status": "success", "message": "Connexion confirmée", "result": result}
        else:
            logger.info(f"ℹ️ Confirmation impossible pour {user_id} - Pas de slot draft disponible, résultat: {result}")
            raise HTTPException(
                status_code=400,
                detail=f"No draft slot available, result: {result}"
            )
    except HTTPException as he:
        logger.error(f"❌ Erreur HTTP lors de la confirmation pour {user_id}: {str(he)}")
        raise he
    except Exception as e:
        logger.error(f"❌ Erreur inattendue lors de la confirmation pour {user_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.get("/queue/status/{user_id}")
async def get_status(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)):
    """Récupère le statut d'un utilisateur."""
    try:
        status = await queue_manager.get_user_status(user_id)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/queue/heartbeat")
async def heartbeat(request: UserRequest, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour maintenir la session active."""
    success = await queue_manager.extend_session(request.user_id)
    if not success:
        raise HTTPException(status_code=404, detail="No active session found")
    
    # Vérifier que l'utilisateur est toujours dans active_users
    is_active = await queue_manager.redis.sismember("active_users", request.user_id)
    if not is_active:
        raise HTTPException(status_code=404, detail="User not in active users")
    
    # Étendre la session
    await queue_manager.redis.setex(f"session:{request.user_id}", queue_manager.session_duration, "1")
    
    return {"success": True}

@app.get("/queue/metrics")
async def get_metrics(queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour obtenir les métriques de la file d'attente."""
    metrics = await queue_manager.get_metrics()
    return metrics

@app.get("/queue/get_users")
async def get_users(queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Récupère les listes d'utilisateurs en attente, en draft et actifs."""
    try:
        # Récupérer les utilisateurs en attente
        waiting_users = await queue_manager.redis.lrange('waiting_queue', 0, -1)
        waiting_users = [user.decode('utf-8') for user in waiting_users]
        
        # Récupérer les utilisateurs en draft
        draft_users = await queue_manager.redis.smembers('draft_users')
        draft_users = [user.decode('utf-8') for user in draft_users]
        
        # Récupérer les utilisateurs actifs
        active_users = await queue_manager.redis.smembers('active_users')
        active_users = [user.decode('utf-8') for user in active_users]
        
        return {
            "waiting_users": waiting_users,
            "draft_users": draft_users,
            "active_users": active_users
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/queue/timers/{user_id}")
async def get_timers(user_id: str, queue_manager: QueueManager = Depends(get_queue_manager)) -> Dict:
    """Endpoint pour obtenir les timers actifs d'un utilisateur."""
    timers = await queue_manager.get_timers(user_id)

    # Nettoyer la réponse pour la rendre sérialisable
    if "task" in timers and timers["task"] is not None:
        # Supprimer l'objet Task ou le convertir en données simples
        task_info = await timers["task"]
        if hasattr(task_info, 'result'):
            timers["task_result"] = task_info.result
    if "task" in timers:
        del timers["task"]

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