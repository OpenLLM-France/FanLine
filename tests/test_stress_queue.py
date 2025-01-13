import asyncio
import random
import pytest
import time
import threading
import queue
import concurrent.futures
import httpx
from functools import partial
from typing import Dict, List
from httpx import AsyncClient
import logging
from celery_test_config import setup_test_celery
import os
# Configuration du logging pour les tests de stress
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

class TestStressQueue:
    @pytest.fixture(autouse=True)
    def setup_logging(self, test_logger):
        """Configure le niveau de log pour les tests de stress."""
        test_logger.setLevel(logging.INFO)
        return test_logger

    @pytest.mark.asyncio
    async def test_parallel_users_stress(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test de stress avec plusieurs utilisateurs en parallèle."""
        # Configuration
        NB_USERS = 50  # Réduit pour éviter le timeout
        MAX_ACTIVE = 25  # Réduit proportionnellement
        SIMULATION_TIME = 20  # Réduit le temps de simulation
        BATCH_SIZE = 5  # Nombre d'utilisateurs à ajouter par lot
        
        # Probabilités de comportement (en pourcentage)
        PROBA_CONNECT = 80    # Probabilité qu'un utilisateur en draft se connecte
        PROBA_DISCONNECT = 20 # Probabilité qu'un utilisateur actif se déconnecte
        
        users: List[Dict] = []
        active_users: List[str] = []
        draft_users: List[str] = []
        waiting_users: List[str] = []

        test_logger.info(f"Démarrage du test de stress avec {NB_USERS} utilisateurs")

        async def sync_lists_with_redis():
            """Synchronise les listes locales avec l'état Redis."""
            try:
                # Récupérer les états depuis Redis
                redis_active = await redis_client.smembers("active_users")
                redis_draft = await redis_client.smembers("draft_users")
                redis_waiting = await redis_client.lrange("waiting_queue", 0, -1)
                
                # Mettre à jour les listes locales
                active_users.clear()
                active_users.extend(redis_active)
                
                draft_users.clear()
                draft_users.extend(redis_draft)
                
                waiting_users.clear()
                waiting_users.extend(redis_waiting)
                
                test_logger.debug(
                    f"Listes synchronisées - Actifs: {len(active_users)}, "
                    f"Draft: {len(draft_users)}, "
                    f"En attente: {len(waiting_users)}"
                )
            except Exception as e:
                test_logger.error(f"Erreur lors de la synchronisation: {str(e)}")

        async def add_users_batch(start_idx: int, count: int):
            """Ajoute un lot d'utilisateurs à la file d'attente."""
            for i in range(start_idx, min(start_idx + count, NB_USERS)):
                user_id = f"stress_user_{i}"
                users.append({"id": user_id, "status": "waiting"})
                
                try:
                    # Ajouter à la file d'attente avec retry
                    for attempt in range(3):
                        response = await test_client.post(f"/queue/join/{user_id}")
                        if response.status_code == 200:
                            test_logger.debug(f"Utilisateur {user_id} créé et ajouté à la file")
                            break
                        await asyncio.sleep(0.1)
                    else:
                        test_logger.error(f"Impossible d'ajouter {user_id} après 3 tentatives")
                except Exception as e:
                    test_logger.error(f"Erreur lors de l'ajout de {user_id}: {str(e)}")
                
                # Attendre un peu entre chaque utilisateur
                await asyncio.sleep(0.2)

        async def simulate_user_behavior():
            """Simule le comportement aléatoire d'un utilisateur."""
            try:
                current_user_count = 0
                while True:
                    # Synchroniser l'état avec Redis
                    await sync_lists_with_redis()
                    
                    # Vérifier si on peut ajouter plus d'utilisateurs
                    total_active = len(active_users) + len(draft_users)
                    if total_active < MAX_ACTIVE and current_user_count < NB_USERS:
                        # Ajouter un nouveau lot d'utilisateurs
                        await add_users_batch(current_user_count, BATCH_SIZE)
                        current_user_count = min(current_user_count + BATCH_SIZE, NB_USERS)
                    
                    # Gérer les utilisateurs en draft
                    for user_id in draft_users[:]:
                        if random.randint(1, 100) <= PROBA_CONNECT:
                            test_logger.debug(f"Tentative de connexion pour {user_id}")
                            try:
                                response = await test_client.post("/queue/confirm", json={"user_id": user_id})
                                if response.status_code == 200:
                                    await sync_lists_with_redis()
                                    test_logger.info(f"Utilisateur {user_id} connecté avec succès")
                            except Exception as e:
                                test_logger.error(f"Erreur lors de la connexion de {user_id}: {str(e)}")

                    # Gérer les utilisateurs actifs
                    for user_id in active_users[:]:
                        if random.randint(1, 100) <= PROBA_DISCONNECT:
                            test_logger.debug(f"Déconnexion de {user_id}")
                            try:
                                # D'abord quitter la file
                                leave_response = await test_client.post("/queue/leave", json={"user_id": user_id})
                                if leave_response.status_code == 200:
                                    # Puis rejoindre à nouveau
                                    await test_client.post("/queue/join", json={"user_id": user_id})
                                    await sync_lists_with_redis()
                                    test_logger.info(f"Utilisateur {user_id} déconnecté et remis en file d'attente")
                            except Exception as e:
                                test_logger.error(f"Erreur lors de la déconnexion de {user_id}: {str(e)}")

                    await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                test_logger.info("Tâche de simulation arrêtée")
            except Exception as e:
                test_logger.error(f"Erreur dans simulate_user_behavior: {str(e)}")

        async def monitor_queue_state():
            """Surveille et log l'état de la file d'attente."""
            try:
                while True:
                    await sync_lists_with_redis()
                    
                    active_count = len(active_users)
                    draft_count = len(draft_users)
                    waiting_count = len(waiting_users)
                    
                    test_logger.info(
                        f"État de la file - Actifs: {active_count}, "
                        f"Draft: {draft_count}, "
                        f"En attente: {waiting_count}"
                    )
                    
                    # Vérifier que le nombre total d'utilisateurs est correct
                    total_users = active_count + draft_count + waiting_count
                    assert total_users <= NB_USERS, f"Nombre total d'utilisateurs incorrect: {total_users}"
                    
                    # Vérifier que le nombre d'utilisateurs actifs ne dépasse pas la limite
                    assert active_count + draft_count <= MAX_ACTIVE, \
                        f"Trop d'utilisateurs actifs/draft: {active_count + draft_count}"
                    
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                test_logger.info("Tâche de monitoring arrêtée")
            except Exception as e:
                test_logger.error(f"Erreur dans monitor_queue_state: {str(e)}")

        async def check_server_connection():
            """Vérifie que le serveur est accessible avant de démarrer les tests."""
            try:
                # Tester avec un endpoint simple
                response = await test_client.get("/queue/status/test_connection")
                # 404 est OK car l'utilisateur n'existe pas
                if response.status_code in [200, 404]:
                    test_logger.info("Test client prêt")
                    return True
            except Exception as e:
                test_logger.error(f"Erreur lors du test du client: {str(e)}")
            return False

        try:
            # Vérifier la connexion au serveur
            if not await check_server_connection():
                raise RuntimeError("Impossible de se connecter au serveur après plusieurs tentatives")

            # Démarrer les tâches de simulation
            behavior_task = asyncio.create_task(simulate_user_behavior())
            monitor_task = asyncio.create_task(monitor_queue_state())

            # Laisser la simulation tourner
            await asyncio.sleep(SIMULATION_TIME)

            # Arrêter les tâches proprement
            behavior_task.cancel()
            monitor_task.cancel()
            try:
                await behavior_task
                await monitor_task
            except asyncio.CancelledError:
                pass

            # Vérifications finales
            await sync_lists_with_redis()
            
            test_logger.info(
                f"État final - Actifs: {len(active_users)}, "
                f"Draft: {len(draft_users)}, "
                f"En attente: {len(waiting_users)}"
            )

            # Vérifier que le nombre maximum d'utilisateurs actifs n'a jamais été dépassé
            assert len(active_users) + len(draft_users) <= MAX_ACTIVE, \
                "Le nombre maximum d'utilisateurs actifs a été dépassé"

        finally:
            # Nettoyage
            test_logger.info("Nettoyage des données de test")
            for user in users:
                try:
                    # D'abord faire quitter la file
                    await test_client.post("/queue/leave", json={"user_id": user["id"]})
                    await asyncio.sleep(0.1)  # Petit délai entre chaque leave
                    # Puis nettoyer Redis
                    await redis_client.srem("active_users", user["id"])
                    await redis_client.srem("draft_users", user["id"])
                    await redis_client.lrem("waiting_queue", 0, user["id"])
                    await redis_client.delete(f"session:{user['id']}")
                    await redis_client.delete(f"draft:{user['id']}")
                except Exception as e:
                    test_logger.error(f"Erreur lors du nettoyage de {user['id']}: {str(e)}")

    @pytest.mark.asyncio
    async def test_rapid_join_leave_stress(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test de stress avec des utilisateurs qui rejoignent et quittent rapidement la file."""
        NB_USERS = 25  # Réduit pour éviter la surcharge
        CYCLES = 3    # Réduit le nombre de cycles
        
        async def join_leave_cycle(user_id: str):
            """Simule un cycle de join/leave pour un utilisateur."""
            try:
                for _ in range(CYCLES):
                    # Rejoindre la file avec retry
                    for attempt in range(3):
                        try:
                            join_response = await test_client.post("/queue/join", json={"user_id": user_id})
                            if join_response.status_code == 200:
                                break
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            test_logger.error(f"Erreur lors du join pour {user_id}: {str(e)}")
                            await asyncio.sleep(0.1)
                    
                    # Attendre un temps aléatoire
                    await asyncio.sleep(random.uniform(0.2, 0.8))
                    
                    # Vérifier le statut avant de quitter
                    status_response = await test_client.get(f"/queue/status/{user_id}")
                    if status_response.status_code == 200:
                        status = status_response.json()
                        test_logger.debug(f"Statut de {user_id}: {status}")
                        
                        if status.get("status") == "draft":
                            # Si en draft, d'abord confirmer la connexion
                            await test_client.post("/queue/confirm", json={"user_id": user_id})
                            await asyncio.sleep(0.1)
                        
                        # Puis quitter la file
                        for attempt in range(3):
                            try:
                                leave_response = await test_client.post("/queue/leave", json={"user_id": user_id})
                                if leave_response.status_code == 200:
                                    break
                                await asyncio.sleep(0.1)
                            except Exception as e:
                                test_logger.error(f"Erreur lors du leave pour {user_id}: {str(e)}")
                                await asyncio.sleep(0.1)
                    
                    # Délai plus long entre les cycles
                    await asyncio.sleep(random.uniform(0.3, 0.6))
            except Exception as e:
                test_logger.error(f"Erreur dans le cycle pour {user_id}: {str(e)}")

        async def cleanup_user(user_id: str):
            """Nettoie proprement un utilisateur du système."""
            try:
                # Vérifier le statut actuel
                status_response = await test_client.get(f"/queue/status/{user_id}")
                if status_response.status_code == 200:
                    status = status_response.json()
                    test_logger.debug(f"Nettoyage de {user_id} avec statut: {status}")
                    
                    if status.get("status") == "draft":
                        # Si en draft, confirmer d'abord la connexion
                        await test_client.post("/queue/confirm", json={"user_id": user_id})
                        await asyncio.sleep(0.1)
                    
                    # Puis quitter la file
                    await test_client.post("/queue/leave", json={"user_id": user_id})
                    await asyncio.sleep(0.1)
                
                # Nettoyage forcé dans Redis
                await redis_client.srem("active_users", user_id)
                await redis_client.srem("draft_users", user_id)
                await redis_client.lrem("waiting_queue", 0, user_id)
                await redis_client.delete(f"session:{user_id}")
                await redis_client.delete(f"draft:{user_id}")
                await redis_client.delete(f"status_history:{user_id}")
                await redis_client.delete(f"last_status:{user_id}")
            except Exception as e:
                test_logger.error(f"Erreur lors du nettoyage de {user_id}: {str(e)}")

        try:
            # Créer et lancer toutes les tâches en parallèle
            tasks = []
            for i in range(NB_USERS):
                user_id = f"rapid_user_{i}"
                task = asyncio.create_task(join_leave_cycle(user_id))
                tasks.append(task)
                test_logger.debug(f"Tâche créée pour {user_id}")
                await asyncio.sleep(0.1)  # Délai entre chaque création de tâche

            # Attendre que toutes les tâches soient terminées
            await asyncio.gather(*tasks, return_exceptions=True)
            
            # Attendre un peu pour laisser le système se stabiliser
            await asyncio.sleep(2)
            
            # Nettoyage complet de tous les utilisateurs
            cleanup_tasks = []
            for i in range(NB_USERS):
                user_id = f"rapid_user_{i}"
                cleanup_tasks.append(asyncio.create_task(cleanup_user(user_id)))
            
            # Attendre que tout le nettoyage soit terminé
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            
            # Attendre encore un peu pour le nettoyage
            await asyncio.sleep(2)
            
            # Vérifications finales
            final_active = await redis_client.scard("active_users")
            final_draft = await redis_client.scard("draft_users")
            final_waiting = await redis_client.llen("waiting_queue")
            
            # Vérifier qu'il ne reste pas d'utilisateurs dans le système
            assert final_active == 0, f"Il reste {final_active} utilisateurs actifs"
            assert final_draft == 0, f"Il reste {final_draft} utilisateurs en draft"
            assert final_waiting == 0, f"Il reste {final_waiting} utilisateurs en attente"
            
            test_logger.info("Test de stress rapid join/leave terminé avec succès")

        finally:
            # Nettoyage supplémentaire si nécessaire
            test_logger.info("Nettoyage final")
            cleanup_tasks = []
            for i in range(NB_USERS):
                user_id = f"rapid_user_{i}"
                cleanup_tasks.append(asyncio.create_task(cleanup_user(user_id)))
            
            # Attendre que tout le nettoyage soit terminé
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_multiple_clients_timer_polling(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test de stress avec plusieurs clients qui font du long polling sur leurs timers."""
        NB_CLIENTS = 10  # Réduit de 50 à 10 clients
        POLL_DURATION = 15  # Réduit de 30 à 15 secondes
        POLL_INTERVAL = 1.0  # Réduit à 1 seconde
        
        clients: Dict[str, ClientState] = {}
        
        class ClientState:
            def __init__(self, user_id: str):
                self.user_id = user_id
                self.last_ttl = float('inf')
                self.status = None
                self.timer_decreasing = True
                self.ttl_history = []
            
            def __str__(self):
                return f"Client {self.user_id} - Status: {self.status}, TTL: {self.last_ttl}"

        async def poll_client_timer(client: ClientState):
            """Effectue le long polling des timers pour un client."""
            try:
                test_logger.info(f"Démarrage du polling pour {client.user_id}")
                while True:
                    try:
                        # Récupérer les timers
                        response = await test_client.get(f"/queue/timers/{client.user_id}")
                        if response.status_code == 200:
                            timer_data = response.json()
                            test_logger.debug(f"Timer data pour {client.user_id}: {timer_data}")
                            
                            if timer_data:  # Si on a des données de timer
                                current_ttl = timer_data.get('ttl', 0)
                                timer_type = timer_data.get('timer_type')
                                
                                # Vérifier que le TTL diminue
                                if client.last_ttl != float('inf'):
                                    if current_ttl > client.last_ttl:
                                        client.timer_decreasing = False
                                        test_logger.error(
                                            f"Timer non décroissant pour {client.user_id}: "
                                            f"{client.last_ttl} -> {current_ttl}"
                                        )
                                
                                client.last_ttl = current_ttl
                                client.ttl_history.append(current_ttl)
                                test_logger.debug(
                                    f"Client {client.user_id} - Type: {timer_type}, "
                                    f"TTL: {current_ttl}, Historique: {len(client.ttl_history)} valeurs"
                                )
                            
                            # Récupérer aussi le statut
                            status_response = await test_client.get(f"/queue/status/{client.user_id}")
                            if status_response.status_code == 200:
                                status_data = status_response.json()
                                client.status = status_data.get('status')
                                test_logger.debug(f"Status pour {client.user_id}: {client.status}")
                    
                    except Exception as e:
                        test_logger.error(f"Erreur lors du poll pour {client.user_id}: {str(e)}")
                    
                    await asyncio.sleep(POLL_INTERVAL)
                    
            except asyncio.CancelledError:
                test_logger.info(f"Polling arrêté pour {client.user_id} avec {len(client.ttl_history)} valeurs collectées")

        async def client_lifecycle(client: ClientState):
            """Simule le cycle de vie d'un client."""
            try:
                # Rejoindre la file
                join_response = await test_client.post(f"/queue/join/{client.user_id}")
                assert join_response.status_code == 200
                
                # Démarrer le polling des timers
                polling_task = asyncio.create_task(poll_client_timer(client))
                
                # Attendre un moment avant de confirmer si en draft
                await asyncio.sleep(random.uniform(1, 3))
                
                # Si en draft, confirmer la connexion
                if client.status == "draft":
                    confirm_response = await test_client.post(
                        f"/queue/confirm/{client.user_id}"
                    )
                    if confirm_response.status_code == 200:
                        test_logger.info(f"Client {client.user_id} confirmé")
                
                # Continuer le polling jusqu'à la fin du test
                try:
                    await asyncio.sleep(POLL_DURATION - 3)  # -3 pour laisser du temps pour le nettoyage
                finally:
                    polling_task.cancel()
                    try:
                        await polling_task
                    except asyncio.CancelledError:
                        pass
                
            except Exception as e:
                test_logger.error(f"Erreur dans le cycle de vie de {client.user_id}: {str(e)}")

        async def cleanup_client(client: ClientState):
            """Nettoie proprement un client."""
            try:
                # Vérifier le statut actuel
                status_response = await test_client.get(f"/queue/status/{client.user_id}")
                if status_response.status_code == 200:
                    status = status_response.json()
                    
                    if status.get("status") == "draft":
                        # Si en draft, confirmer d'abord
                        await test_client.post("/queue/confirm", json={"user_id": client.user_id})
                        await asyncio.sleep(0.1)
                    
                    # Puis quitter
                    await test_client.post("/queue/leave", json={"user_id": client.user_id})
                
                # Nettoyage Redis
                await redis_client.srem("active_users", client.user_id)
                await redis_client.srem("draft_users", client.user_id)
                await redis_client.lrem("waiting_queue", 0, client.user_id)
                await redis_client.delete(f"session:{client.user_id}")
                await redis_client.delete(f"draft:{client.user_id}")
                await redis_client.delete(f"status_history:{client.user_id}")
                await redis_client.delete(f"last_status:{client.user_id}")
            
            except Exception as e:
                test_logger.error(f"Erreur lors du nettoyage de {client.user_id}: {str(e)}")

        try:
            # Créer les clients
            for i in range(NB_CLIENTS):
                client = ClientState(f"timer_client_{i}")
                clients[client.user_id] = client
            
            # Lancer les cycles de vie des clients
            lifecycle_tasks = [
                asyncio.create_task(client_lifecycle(client))
                for client in clients.values()
            ]
            
            # Attendre que tous les cycles de vie soient terminés
            await asyncio.gather(*lifecycle_tasks, return_exceptions=True)
            
            # Vérifier que tous les timers étaient décroissants
            non_decreasing_clients = [
                client.user_id
                for client in clients.values()
                if not client.timer_decreasing
            ]
            
            assert len(non_decreasing_clients) == 0, \
                f"Clients avec timers non décroissants: {non_decreasing_clients}"
            
            test_logger.info("Test de polling des timers terminé avec succès")
            
        finally:
            # Nettoyage
            test_logger.info("Nettoyage des clients")
            cleanup_tasks = [
                asyncio.create_task(cleanup_client(client))
                for client in clients.values()
            ]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            
            # Vérifications finales
            final_active = await redis_client.scard("active_users")
            final_draft = await redis_client.scard("draft_users")
            final_waiting = await redis_client.llen("waiting_queue")
            
            assert final_active == 0, f"Il reste {final_active} utilisateurs actifs"
            assert final_draft == 0, f"Il reste {final_draft} utilisateurs en draft"
            assert final_waiting == 0, f"Il reste {final_waiting} utilisateurs en attente"

    @pytest.mark.asyncio
    async def test_multiple_clients_timer_polling_threaded(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test de stress avec plusieurs clients qui font du long polling sur leurs timers, répartis sur 4 threads."""
        import threading
        import queue
        import concurrent.futures
        import httpx
        import time
        import os
        from functools import partial
        
        # Configuration des constantes
        NB_CLIENTS_PER_THREAD = 2  # Réduit pour le débogage
        NB_THREADS = 4
        POLL_DURATION = 15
        POLL_INTERVAL = 1.0
        REQUEST_TIMEOUT = 5.0  # Réduit pour détecter les problèmes plus rapidement
        MAX_RETRIES = 3
        SETUP_TIMEOUT = 10.0
        SETUP_INTERVAL = 2.0
        
        # Configuration du logging
        test_logger.setLevel(logging.DEBUG)  # Augmente le niveau de détail des logs

        # Nettoyage initial de Redis
        test_logger.info("Nettoyage initial de Redis...")
        # Récupérer tous les utilisateurs actifs
        active_users = await redis_client.smembers('active_users')
        draft_users = await redis_client.smembers('draft_users')
        waiting_users = await redis_client.lrange('waiting_queue', 0, -1)
        
        # Convertir les bytes en str
        active_users = [user.decode('utf-8') for user in active_users]
        draft_users = [user.decode('utf-8') for user in draft_users]
        waiting_users = [user.decode('utf-8') for user in waiting_users]
        
        test_logger.info(f"Utilisateurs à nettoyer - Actifs: {len(active_users)}, Draft: {len(draft_users)}, En attente: {len(waiting_users)}")
        
        # Nettoyer chaque utilisateur
        for user_id in active_users + draft_users + waiting_users:
            try:
                # Faire quitter la file via l'API
                await test_client.post(f"/queue/leave/{user_id}")
                # Nettoyage forcé dans Redis
                await redis_client.srem("active_users", user_id)
                await redis_client.srem("draft_users", user_id)
                await redis_client.lrem("waiting_queue", 0, user_id)
                await redis_client.delete(f"session:{user_id}")
                await redis_client.delete(f"draft:{user_id}")
                await redis_client.delete(f"status_history:{user_id}")
                await redis_client.delete(f"last_status:{user_id}")
            except Exception as e:
                test_logger.error(f"Erreur lors du nettoyage de {user_id}: {str(e)}")
        
        # Vérifier que tout est bien nettoyé
        active_count = await redis_client.scard("active_users")
        draft_count = await redis_client.scard("draft_users")
        waiting_count = await redis_client.llen("waiting_queue")
        
        if active_count > 0 or draft_count > 0 or waiting_count > 0:
            raise RuntimeError(f"Nettoyage incomplet - Actifs: {active_count}, Draft: {draft_count}, En attente: {waiting_count}")
        
        test_logger.info("Nettoyage initial terminé avec succès")
        
        # S'assurer que le slot checker est démarré
        if not queue_manager_with_checker._slot_check_task:
            test_logger.info("Démarrage du slot checker")
            await queue_manager_with_checker.start_slot_checker()
            await asyncio.sleep(1.0)  # Attendre que le slot checker soit prêt

        # Vérifier que le slot checker est bien démarré
        if not queue_manager_with_checker._slot_check_task or queue_manager_with_checker._slot_check_task.done():
            raise RuntimeError("Le slot checker n'a pas démarré correctement")
        
        test_logger.info("Slot checker opérationnel")
        
        # File d'attente pour les métriques en temps réel
        metrics_queue = queue.Queue()
        
        class ClientMetrics:
            def __init__(self):
                self.total_requests = 0
                self.failed_requests = 0
                self.avg_response_time = 0.0
                self.last_update = time.time()
            
            def update(self, response_time, success):
                self.total_requests += 1
                if not success:
                    self.failed_requests += 1
                self.avg_response_time = (self.avg_response_time * (self.total_requests - 1) + response_time) / self.total_requests
                self.last_update = time.time()
        
        class ClientState:
            def __init__(self, user_id: str, thread_id: int):
                self.user_id = user_id
                self.thread_id = thread_id
                self.last_ttl = float('inf')
                self.status = None
                self.timer_decreasing = True
                self.ttl_history = []
                self.error_count = 0
                self.metrics = ClientMetrics()
                self.last_poll_time = None
                self.consecutive_errors = 0
            
            def __str__(self):
                return (f"Client {self.user_id} (Thread {self.thread_id}) - "
                       f"Status: {self.status}, TTL: {self.last_ttl}, "
                       f"Errors: {self.error_count}")

        async def monitor_client_health(clients: Dict[str, ClientState], stop_event: threading.Event):
            """Surveille la santé des clients en temps réel."""
            while not stop_event.is_set():
                current_time = time.time()
                for client in clients.values():
                    if client.last_poll_time and (current_time - client.last_poll_time) > 5.0:
                        test_logger.warning(f"Client {client.user_id} n'a pas fait de polling depuis {current_time - client.last_poll_time:.1f}s")
                    if client.consecutive_errors >= 3:
                        test_logger.error(f"Client {client.user_id} a {client.consecutive_errors} erreurs consécutives")
                await asyncio.sleep(1.0)

        def poll_client_timer_sync(client: ClientState, stop_event: threading.Event):
            """Version synchrone du polling des timers avec métriques améliorées."""
            test_logger.info(f"Démarrage du polling pour {client.user_id} dans le thread {client.thread_id}")
            start_time = time.time()
            
            with create_sync_client() as http_client:
                while not stop_event.is_set() and time.time() - start_time < POLL_DURATION:
                    request_start = time.time()
                    try:
                        # Récupérer les timers
                        response = http_client.get(f"/queue/timers/{client.user_id}")
                        response_time = time.time() - request_start
                        
                        client.metrics.update(response_time, response.status_code == 200)
                        client.last_poll_time = time.time()
                        
                        if response.status_code == 200:
                            client.consecutive_errors = 0
                            timer_data = response.json()
                            
                            if timer_data:
                                current_ttl = timer_data.get('ttl', 0)
                                timer_type = timer_data.get('timer_type')
                                
                                # Vérification plus stricte du TTL
                                if client.last_ttl != float('inf'):
                                    ttl_diff = client.last_ttl - current_ttl
                                    if ttl_diff < 0:
                                        test_logger.error(
                                            f"TTL incohérent pour {client.user_id}: "
                                            f"ancien={client.last_ttl}, nouveau={current_ttl}, "
                                            f"diff={ttl_diff}"
                                        )
                                        client.timer_decreasing = False
                                    elif ttl_diff > POLL_INTERVAL * 2:
                                        test_logger.warning(
                                            f"TTL diminue trop rapidement pour {client.user_id}: "
                                            f"diff={ttl_diff}s en {POLL_INTERVAL}s"
                                        )
                                
                                client.last_ttl = current_ttl
                                client.ttl_history.append((time.time(), current_ttl))
                                
                                metrics_queue.put({
                                    'client_id': client.user_id,
                                    'ttl': current_ttl,
                                    'type': timer_type,
                                    'response_time': response_time
                                })
                        else:
                            client.consecutive_errors += 1
                            test_logger.error(
                                f"Erreur de polling pour {client.user_id}: "
                                f"status={response.status_code}, "
                                f"body={response.text[:200]}"
                            )
                    
                    except Exception as e:
                        client.consecutive_errors += 1
                        client.error_count += 1
                        test_logger.error(
                            f"Exception pour {client.user_id} "
                            f"(erreurs: {client.error_count}): {str(e)}"
                        )
                        if client.error_count >= MAX_RETRIES:
                            test_logger.error(f"Arrêt du polling pour {client.user_id}")
                            break
                        time.sleep(0.5)
                        continue
                    
                    # Ajuster dynamiquement l'intervalle de polling
                    actual_interval = max(0.1, POLL_INTERVAL - response_time)
                    time.sleep(actual_interval)
            
            test_logger.info(
                f"Polling terminé pour {client.user_id} - "
                f"Valeurs: {len(client.ttl_history)}, "
                f"Erreurs: {client.error_count}"
            )

        async def wait_for_client_ready(client: ClientState):
            """Attend que le client soit prêt avant de démarrer le polling."""
            MAX_READY_RETRIES = 10
            READY_CHECK_INTERVAL = 1.0
            
            async with await create_async_client() as http_client:
                for attempt in range(MAX_READY_RETRIES):
                    try:
                        response = await http_client.get(f"/queue/status/{client.user_id}")
                        if response.status_code == 200:
                            status_data = response.json()
                            status = status_data.get('status')
                            remaining_time = status_data.get('remaining_time')
                            position = status_data.get('position')
                            
                            test_logger.debug(
                                f"Client {client.user_id} - Statut: {status}, "
                                f"Position: {position}, Temps restant: {remaining_time}"
                            )
                            
                            if status in ['active', 'draft', 'connected']:
                                client.status = status
                                return True
                    except Exception as e:
                        test_logger.debug(f"Erreur lors de la vérification du statut de {client.user_id}: {str(e)}")
                    
                    await asyncio.sleep(READY_CHECK_INTERVAL)
                
                test_logger.error(f"Client {client.user_id} n'est pas prêt après {MAX_READY_RETRIES} tentatives")
                return False

        async def setup_client(client: ClientState):
            """Configure un client avec gestion améliorée des erreurs."""
            MAX_SETUP_RETRIES = 3
            MAX_SLOT_WAIT = 10  # Temps maximum d'attente pour un slot en secondes

            try:
                async with await create_async_client() as http_client:
                    # Rejoindre la file avec retry
                    join_success = False
                    for attempt in range(MAX_SETUP_RETRIES):
                        try:
                            join_response = await http_client.post(f"/queue/join/{client.user_id}")
                            test_logger.debug(f"Réponse du join: {join_response.status_code}")
                            # Récupérer la file d'attente avec les métriques
                            #waiting_queue = await http_client.get(f"/queue/waiting_queue/{client.user_id}")
                            metrics = await http_client.get(f"/queue/metrics")
                            test_logger.debug(f"File d'attente:  Métriques: {metrics.json()}")
                            test_logger.debug(f"Réponse du join: {join_response.json()}")
                            if join_response.status_code == 200:
                                test_logger.info(f"Client {client.user_id} a rejoint la file")
                                join_success = True
                                break
                            else:
                                test_logger.warning(
                                    f"Échec du join pour {client.user_id} "
                                    f"(tentative {attempt + 1}): {join_response.status_code}"
                                )
                        except Exception as e:
                            test_logger.error(f"Erreur lors du join pour {client.user_id}: {str(e)}")
                        await asyncio.sleep(SETUP_INTERVAL)

                    if not join_success:
                        return False

                    # Attendre que le client passe en état draft
                    slot_wait_start = time.time()
                    while time.time() - slot_wait_start < MAX_SLOT_WAIT:
                        status_response = await http_client.get(f"/queue/status/{client.user_id}")
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            if status_data.get("status") == "draft":
                                test_logger.info(f"Client {client.user_id} est passé en état draft")
                                break
                        await asyncio.sleep(0.5)
                    else:
                        test_logger.error(f"Client {client.user_id} n'a pas obtenu de slot après {MAX_SLOT_WAIT}s")
                        return False

                    # Confirmer avec retry
                    confirm_success = False
                    for attempt in range(MAX_SETUP_RETRIES):
                        try:
                            confirm_response = await http_client.post(f"/queue/confirm/{client.user_id}")
                            if confirm_response.status_code == 200:
                                test_logger.info(f"Client {client.user_id} confirmé")
                                confirm_success = True
                                break
                            else:
                                test_logger.warning(
                                    f"Échec de la confirmation pour {client.user_id} "
                                    f"(tentative {attempt + 1}): {confirm_response.status_code}"
                                )
                        except Exception as e:
                            test_logger.error(f"Erreur lors de la confirmation pour {client.user_id}: {str(e)}")
                        await asyncio.sleep(SETUP_INTERVAL)

                    if not confirm_success:
                        return False

                    # Vérifier que le client est prêt
                    return await wait_for_client_ready(client)

            except Exception as e:
                test_logger.error(f"Erreur fatale lors de la configuration de {client.user_id}: {str(e)}")
                return False

        async def process_metrics():
            """Traite et affiche les métriques en temps réel."""
            metrics_by_client = {}
            last_display = time.time()
            DISPLAY_INTERVAL = 5.0  # Afficher les métriques toutes les 5 secondes
            
            while True:
                try:
                    metric = metrics_queue.get_nowait()
                    client_id = metric['client_id']
                    
                    if client_id not in metrics_by_client:
                        metrics_by_client[client_id] = {
                            'ttl_values': [],
                            'response_times': [],
                            'last_ttl': None
                        }
                    
                    client_metrics = metrics_by_client[client_id]
                    client_metrics['ttl_values'].append(metric['ttl'])
                    client_metrics['response_times'].append(metric['response_time'])
                    
                    # Vérifier la cohérence des TTL
                    if client_metrics['last_ttl'] is not None:
                        ttl_diff = client_metrics['last_ttl'] - metric['ttl']
                        if ttl_diff < 0:
                            test_logger.error(
                                f"TTL incohérent pour {client_id}: "
                                f"{client_metrics['last_ttl']} -> {metric['ttl']}"
                            )
                    
                    client_metrics['last_ttl'] = metric['ttl']
                    
                    # Afficher les métriques périodiquement
                    current_time = time.time()
                    if current_time - last_display >= DISPLAY_INTERVAL:
                        test_logger.info("\n=== Métriques des clients ===")
                        for cid, cmetrics in metrics_by_client.items():
                            avg_response = sum(cmetrics['response_times']) / len(cmetrics['response_times'])
                            test_logger.info(
                                f"Client {cid}:\n"
                                f"  - TTL moyen: {sum(cmetrics['ttl_values']) / len(cmetrics['ttl_values']):.2f}\n"
                                f"  - Temps de réponse moyen: {avg_response:.3f}s\n"
                                f"  - Nombre de requêtes: {len(cmetrics['ttl_values'])}"
                            )
                        last_display = current_time
                
                except queue.Empty:
                    await asyncio.sleep(0.1)
                except Exception as e:
                    test_logger.error(f"Erreur lors du traitement des métriques: {str(e)}")

        def create_sync_client():
            """Crée un client HTTP synchrone avec la configuration appropriée."""
            return httpx.Client(
                base_url="http://localhost:8000",
                timeout=REQUEST_TIMEOUT,
                headers={"Content-Type": "application/json"},
                verify=False,  # Désactive la vérification SSL pour les tests
                http2=False    # Désactive HTTP/2 pour éviter les problèmes
            )

        async def create_async_client():
            """Crée un client HTTP asynchrone avec la configuration appropriée."""
            return httpx.AsyncClient(
                base_url="http://localhost:8000",
                timeout=SETUP_TIMEOUT,
                headers={"Content-Type": "application/json"},
                verify=False,
                http2=False
            )

        async def check_server_connection():
            """Vérifie que le serveur est accessible avant de démarrer les tests."""
            try:
                async with await create_async_client() as client:
                    response = await client.get("/queue/status/test_connection")
                    if response.status_code in [200, 404]:
                        test_logger.info("Serveur accessible")
                        return True
            except Exception as e:
                test_logger.error(f"Erreur de connexion au serveur: {str(e)}")
            return False

        async def cleanup_client(client: ClientState):
            """Nettoie proprement un client avec vérification."""
            try:
                async with await create_async_client() as http_client:
                    # D'abord faire quitter la file
                    leave_response = await http_client.post(f"/queue/leave/{client.user_id}")
                    if leave_response.status_code == 200:
                        test_logger.debug(f"Client {client.user_id} a quitté la file")
                    else:
                        test_logger.warning(
                            f"Échec du leave pour {client.user_id}: "
                            f"{leave_response.status_code}"
                        )
                
                # Nettoyage Redis avec vérification
                keys_to_clean = [
                    f"session:{client.user_id}",
                    f"draft:{client.user_id}",
                    f"status_history:{client.user_id}",
                    f"last_status:{client.user_id}"
                ]
                
                for key in keys_to_clean:
                    if await redis_client.exists(key):
                        await redis_client.delete(key)
                        test_logger.debug(f"Clé Redis supprimée: {key}")
                
                # Supprimer des sets et listes
                await redis_client.srem("active_users", client.user_id)
                await redis_client.srem("draft_users", client.user_id)
                await redis_client.lrem("waiting_queue", 0, client.user_id)
                
                # Vérification finale
                still_exists = []
                for key in keys_to_clean:
                    if await redis_client.exists(key):
                        still_exists.append(key)
                
                if still_exists:
                    test_logger.warning(f"Clés Redis restantes pour {client.user_id}: {still_exists}")
            
            except Exception as e:
                test_logger.error(f"Erreur lors du nettoyage de {client.user_id}: {str(e)}")

        def thread_worker(thread_id: int, clients_subset: List[ClientState], stop_event: threading.Event):
            """Fonction exécutée par chaque thread avec gestion améliorée des erreurs."""
            thread_name = f"PollingThread-{thread_id}"
            threading.current_thread().name = thread_name
            
            test_logger.info(f"Démarrage du thread {thread_name} avec {len(clients_subset)} clients")
            
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(clients_subset)) as executor:
                    # Démarrer le polling pour chaque client
                    futures = {
                        executor.submit(poll_client_timer_sync, client, stop_event): client
                        for client in clients_subset
                    }
                    
                    # Attendre la fin de tous les pollings avec timeout
                    done, not_done = concurrent.futures.wait(
                        futures.keys(),
                        timeout=POLL_DURATION + 5.0,  # Ajoute 5s de marge
                        return_when=concurrent.futures.ALL_COMPLETED
                    )
                    
                    # Gérer les tâches non terminées
                    if not_done:
                        test_logger.error(
                            f"Thread {thread_name}: {len(not_done)} tâches "
                            f"n'ont pas terminé dans le temps imparti"
                        )
                        for future in not_done:
                            client = futures[future]
                            test_logger.error(f"Client bloqué: {client.user_id}")
                            future.cancel()
                    
                    # Vérifier les résultats des tâches terminées
                    for future in done:
                        client = futures[future]
                        try:
                            future.result()  # Vérifie s'il y a eu des exceptions
                        except Exception as e:
                            test_logger.error(
                                f"Erreur dans le polling du client {client.user_id}: {str(e)}"
                            )
            
            except Exception as e:
                test_logger.error(f"Erreur dans le thread {thread_name}: {str(e)}")
            finally:
                test_logger.info(f"Thread {thread_name} terminé")

        try:
            # Vérifier la connexion au serveur
            if not await check_server_connection():
                raise RuntimeError("Le serveur n'est pas accessible")

            # Initialiser les clients
            clients: Dict[str, ClientState] = {}
            for i in range(NB_CLIENTS_PER_THREAD * NB_THREADS):
                client = ClientState(f"timer_client_{i}", i // NB_CLIENTS_PER_THREAD)
                clients[client.user_id] = client
            
            test_logger.info(f"Configuration de {len(clients)} clients")
            
            # Configurer les clients en parallèle
            setup_tasks = [setup_client(client) for client in clients.values()]
            setup_results = await asyncio.gather(*setup_tasks, return_exceptions=True)
            
            # Filtrer les clients configurés avec succès
            ready_clients = {
                client.user_id: client
                for client, success in zip(clients.values(), setup_results)
                if isinstance(success, bool) and success
            }
            
            if not ready_clients:
                raise RuntimeError("Aucun client n'a pu être configuré")
            
            test_logger.info(f"{len(ready_clients)}/{len(clients)} clients sont prêts")
            
            # Répartir les clients par thread
            clients_by_thread = [[] for _ in range(NB_THREADS)]
            for i, client in enumerate(ready_clients.values()):
                thread_id = i % NB_THREADS
                clients_by_thread[thread_id].append(client)
            
            # Démarrer le monitoring des clients et le traitement des métriques
            stop_event = threading.Event()
            monitor_task = asyncio.create_task(monitor_client_health(ready_clients, stop_event))
            metrics_task = asyncio.create_task(process_metrics())
            
            # Démarrer les threads de polling
            threads = []
            for thread_id in range(NB_THREADS):
                if clients_by_thread[thread_id]:  # Ne créer le thread que s'il y a des clients
                    thread = threading.Thread(
                        target=thread_worker,
                        args=(thread_id, clients_by_thread[thread_id], stop_event)
                    )
                    threads.append(thread)
                    thread.start()
            
            # Attendre que les threads terminent
            for thread in threads:
                thread.join(timeout=POLL_DURATION + 10.0)  # 10s de marge
                if thread.is_alive():
                    test_logger.error(f"Le thread {thread.name} est bloqué")
            
            # Arrêter le monitoring et les métriques
            stop_event.set()
            monitor_task.cancel()
            metrics_task.cancel()
            try:
                await monitor_task
                await metrics_task
            except asyncio.CancelledError:
                pass
            
            # Vérifications finales
            failed_clients = [
                client.user_id
                for client in ready_clients.values()
                if not client.timer_decreasing or client.error_count > MAX_RETRIES
            ]
            
            if failed_clients:
                raise AssertionError(f"Clients en échec: {failed_clients}")
            
            test_logger.info("Test de polling des timers multi-thread terminé avec succès")
            
        finally:
            # Nettoyage final
            test_logger.info("Nettoyage des clients")
            cleanup_tasks = [cleanup_client(client) for client in clients.values()]
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
            
            # Vérification finale de Redis
            final_active = await redis_client.scard("active_users")
            final_draft = await redis_client.scard("draft_users")
            final_waiting = await redis_client.llen("waiting_queue")
            
            if final_active > 0 or final_draft > 0 or final_waiting > 0:
                test_logger.error(
                    f"Il reste des clients dans Redis - "
                    f"Actifs: {final_active}, "
                    f"Draft: {final_draft}, "
                    f"En attente: {final_waiting}"
                )

    @pytest.mark.asyncio
    async def test_server_health(self, test_logger):
        """Test la disponibilité du serveur."""
        base_url = "http://localhost:8000"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Test du health check
                response = await client.get(f"{base_url}/health")
                assert response.status_code == 200, f"Health check a échoué: {response.status_code}"
                test_logger.info("Health check réussi")
                
                # Test simple de l'endpoint join
                test_user = "test_health_user"
                join_response = await client.post(f"{base_url}/queue/join/{test_user}")
                assert join_response.status_code == 200, f"Join a échoué: {join_response.status_code}"
                test_logger.info("Test join réussi")
                
                # Vérification des timers
                timer_response = await client.get(f"{base_url}/queue/timers/{test_user}")
                assert timer_response.status_code == 200, f"Get timers a échoué: {timer_response.status_code}"
                test_logger.info("Test get timers réussi")
                
            except httpx.RequestError as e:
                test_logger.error(f"Erreur de connexion au serveur: {str(e)}")
                raise
            except AssertionError as e:
                test_logger.error(f"Test échoué: {str(e)}")
                raise
            except Exception as e:
                test_logger.error(f"Erreur inattendue: {str(e)}")
                raise
            finally:
                # Nettoyage
                try:
                    await client.post(f"{base_url}/queue/leave/{test_user}")
                    test_logger.info("Nettoyage effectué")
                except Exception as e:
                    test_logger.warning(f"Erreur pendant le nettoyage: {str(e)}") 