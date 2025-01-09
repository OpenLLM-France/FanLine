@app.get("/queue/timers/{user_id}")
async def get_timers(user_id: str):
    """Récupère les timers actifs pour un utilisateur."""
    timers = await queue_manager.get_timers(user_id)
    if not timers:
        return {"timer_type": None}
    return timers 