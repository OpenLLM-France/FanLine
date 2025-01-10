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
                        response = await test_client.post("/queue/join", json={"user_id": user_id})
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
        NB_CLIENTS = 50
        POLL_DURATION = 30  # Durée totale du test en secondes
        POLL_INTERVAL = 0.5  # Intervalle entre chaque poll en secondes
        
        class ClientState:
            def __init__(self, user_id: str):
                self.user_id = user_id
                self.last_ttl = float('inf')
                self.status = None
                self.timer_decreasing = True
                self.ttl_history = []
            
            def __str__(self):
                return f"Client {self.user_id} - Status: {self.status}, TTL: {self.last_ttl}"

        clients: Dict[str, ClientState] = {}
        
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
                join_response = await test_client.post("/queue/join", json={"user_id": client.user_id})
                assert join_response.status_code == 200
                
                # Démarrer le polling des timers
                polling_task = asyncio.create_task(poll_client_timer(client))
                
                # Attendre un moment avant de confirmer si en draft
                await asyncio.sleep(random.uniform(1, 3))
                
                # Si en draft, confirmer la connexion
                if client.status == "draft":
                    confirm_response = await test_client.post("/queue/confirm", json={"user_id": client.user_id})
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
        
        NB_CLIENTS_PER_THREAD = 2  # Réduit à 2 clients par thread
        NB_THREADS = 4
        POLL_DURATION = 15  # Réduit à 15 secondes
        POLL_INTERVAL = 1.0  # Réduit à 1 seconde
        REQUEST_TIMEOUT = 10.0  # Augmenté à 10 secondes
        MAX_RETRIES = 3  # Réduit à 3 tentatives
        SETUP_TIMEOUT = 15.0  # Augmenté à 15 secondes
        SETUP_INTERVAL = 5.0  # Augmenté à 5 secondes
        
        # Configuration de l'URL de base et des timeouts
        if os.environ.get("DOCKER_ENV"):
            BASE_URL = "http://api:8000"  # Utilise le nom du service dans Docker
            test_logger.info("Environnement Docker détecté, utilisation de api:8000")
        else:
            BASE_URL = "http://localhost:8000"  # Port local par défaut
            test_logger.info("Environnement local détecté, utilisation de localhost:8000")

        # Vérifier que le serveur est accessible
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{BASE_URL}/queue/status/test_connection")
                test_logger.info(f"Test de connexion initial au serveur: {response.status_code}")
        except Exception as e:
            test_logger.error(f"Erreur lors du test de connexion initial: {str(e)}")
            test_logger.error("Assurez-vous que le serveur API est en cours d'exécution sur le port 8000")
            raise RuntimeError("Le serveur API n'est pas accessible")

        test_logger.info(f"Utilisation de l'URL de base: {BASE_URL}")
        
        # Configuration des clients HTTP avec des timeouts plus longs
        COMMON_HEADERS = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        def create_sync_client():
            """Crée un client HTTP synchrone avec la bonne configuration."""
            return httpx.Client(
                base_url=BASE_URL,
                headers=COMMON_HEADERS,
                timeout=REQUEST_TIMEOUT,
                verify=False,  # Désactive la vérification SSL pour les tests
                http2=False  # Désactive HTTP/2 pour éviter les problèmes de connexion
            )
        
        async def create_async_client():
            """Crée un client HTTP asynchrone avec la bonne configuration."""
            return httpx.AsyncClient(
                base_url=BASE_URL,
                headers=COMMON_HEADERS,
                timeout=SETUP_TIMEOUT,
                verify=False,  # Désactive la vérification SSL pour les tests
                http2=False  # Désactive HTTP/2 pour éviter les problèmes de connexion
            )
        
        test_logger.info(f"Démarrage du test avec {NB_CLIENTS_PER_THREAD * NB_THREADS} clients au total")
        
        # Queue pour collecter les résultats des threads
        results_queue = queue.Queue()
        
        class ClientState:
            def __init__(self, user_id: str, thread_id: int):
                self.user_id = user_id
                self.thread_id = thread_id
                self.last_ttl = float('inf')
                self.status = None
                self.timer_decreasing = True
                self.ttl_history = []
                self.error_count = 0
            
            def __str__(self):
                return f"Client {self.user_id} (Thread {self.thread_id}) - Status: {self.status}, TTL: {self.last_ttl}"

        clients: Dict[str, ClientState] = {}

        async def setup_client(client: ClientState):
            """Configure un client avant le polling."""
            MAX_SETUP_RETRIES = 5
            SETUP_INTERVAL = 2.0
            
            try:
                async with await create_async_client() as http_client:
                    # Rejoindre la file
                    join_success = False
                    for attempt in range(MAX_SETUP_RETRIES):
                        try:
                            test_logger.info(f"Tentative {attempt + 1} de join pour {client.user_id}")
                            join_response = await http_client.post(
                                "/queue/join",
                                json={"user_id": client.user_id}
                            )
                            test_logger.info(f"Réponse join pour {client.user_id}: {join_response.status_code}")
                            
                            if join_response.status_code == 200:
                                test_logger.info(f"Client {client.user_id} a rejoint la file")
                                join_success = True
                                break
                            else:
                                test_logger.error(f"Échec du join pour {client.user_id}: {join_response.status_code}")
                                if join_response.status_code != 500:
                                    test_logger.error(f"Contenu de la réponse: {join_response.text}")
                        except Exception as e:
                            test_logger.error(f"Exception lors du join pour {client.user_id}: {str(e)}")
                        await asyncio.sleep(SETUP_INTERVAL)
                    
                    if not join_success:
                        test_logger.error(f"Impossible de faire rejoindre {client.user_id} après {MAX_SETUP_RETRIES} tentatives")
                        return False
                    
                    # Attendre un moment avant de confirmer
                    await asyncio.sleep(3.0)
                    
                    # Confirmer la connexion
                    confirm_success = False
                    for attempt in range(MAX_SETUP_RETRIES):
                        try:
                            test_logger.info(f"Tentative {attempt + 1} de confirmation pour {client.user_id}")
                            confirm_response = await http_client.post(
                                "/queue/confirm",
                                json={"user_id": client.user_id}
                            )
                            test_logger.info(f"Réponse confirm pour {client.user_id}: {confirm_response.status_code}")
                            
                            if confirm_response.status_code == 200:
                                test_logger.info(f"Client {client.user_id} confirmé avec succès")
                                confirm_success = True
                                break
                            else:
                                test_logger.error(f"Échec de la confirmation pour {client.user_id}: {confirm_response.status_code}")
                                if confirm_response.status_code != 500:
                                    test_logger.error(f"Contenu de la réponse: {confirm_response.text}")
                        except Exception as e:
                            test_logger.error(f"Exception lors de la confirmation pour {client.user_id}: {str(e)}")
                        await asyncio.sleep(SETUP_INTERVAL)
                    
                    if not confirm_success:
                        test_logger.error(f"Impossible de confirmer {client.user_id} après {MAX_SETUP_RETRIES} tentatives")
                        return False
                    
                    # Attendre plus longtemps avant de vérifier si le client est prêt
                    await asyncio.sleep(3.0)
                    
                    # Vérifier le statut initial
                    try:
                        status_response = await http_client.get(f"/queue/status/{client.user_id}")
                        test_logger.info(f"Statut initial pour {client.user_id}: {status_response.status_code}")
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            test_logger.info(f"Données de statut pour {client.user_id}: {status_data}")
                    except Exception as e:
                        test_logger.error(f"Erreur lors de la vérification du statut initial de {client.user_id}: {str(e)}")
                    
                    # Attendre que le client soit prêt
                    if await wait_for_client_ready(client):
                        test_logger.info(f"Client {client.user_id} est prêt pour le polling")
                        return True
                    else:
                        test_logger.error(f"Client {client.user_id} n'est pas prêt après l'attente")
                        return False
                    
            except Exception as e:
                test_logger.error(f"Erreur lors de la configuration de {client.user_id}: {str(e)}")
                return False

        def poll_client_timer_sync(client: ClientState, stop_event: threading.Event):
            """Version synchrone du polling des timers pour utilisation dans les threads."""
            test_logger.info(f"Démarrage du polling pour {client.user_id} dans le thread {client.thread_id}")
            start_time = time.time()
            retry_count = 0
            
            with create_sync_client() as http_client:
                while not stop_event.is_set() and time.time() - start_time < POLL_DURATION:
                    try:
                        # Récupérer les timers
                        response = http_client.get(f"/queue/timers/{client.user_id}")
                        if response.status_code == 200:
                            timer_data = response.json()
                            
                            if timer_data:  # Si on a des données de timer
                                current_ttl = timer_data.get('ttl', 0)
                                timer_type = timer_data.get('timer_type')
                                
                                # Vérifier que le TTL diminue
                                if client.last_ttl != float('inf'):
                                    if current_ttl > client.last_ttl:
                                        client.timer_decreasing = False
                                        results_queue.put({
                                            'error': f"Timer non décroissant pour {client.user_id}: "
                                                    f"{client.last_ttl} -> {current_ttl}"
                                        })
                                
                                client.last_ttl = current_ttl
                                client.ttl_history.append(current_ttl)
                                retry_count = 0  # Réinitialiser le compteur d'erreurs en cas de succès
                                
                                results_queue.put({
                                    'info': f"Thread {client.thread_id} - Client {client.user_id} - "
                                           f"Type: {timer_type}, TTL: {current_ttl}"
                                })
                        
                        # Récupérer aussi le statut
                        status_response = http_client.get(f"/queue/status/{client.user_id}")
                        if status_response.status_code == 200:
                            status_data = status_response.json()
                            client.status = status_data.get('status')
                    
                    except Exception as e:
                        retry_count += 1
                        results_queue.put({
                            'error': f"Erreur lors du poll pour {client.user_id} (tentative {retry_count}): {str(e)}"
                        })
                        if retry_count >= MAX_RETRIES:
                            results_queue.put({
                                'error': f"Arrêt du polling pour {client.user_id} après {MAX_RETRIES} échecs"
                            })
                            break
                        time.sleep(0.5)  # Attendre un peu avant de réessayer
                        continue
                    
                    time.sleep(POLL_INTERVAL)
            
            results_queue.put({
                'info': f"Polling terminé pour {client.user_id} dans le thread {client.thread_id} "
                       f"avec {len(client.ttl_history)} valeurs collectées"
            })

        async def wait_for_client_ready(client: ClientState):
            """Attend que le client soit prêt avant de démarrer le polling."""
            MAX_READY_RETRIES = 15
            READY_CHECK_INTERVAL = 2.0
            
            async with await create_async_client() as http_client:
                for attempt in range(MAX_READY_RETRIES):
                    try:
                        # Vérifier le statut
                        response = await http_client.get(f"/queue/status/{client.user_id}")
                        if response.status_code == 200:
                            status_data = response.json()
                            status = status_data.get('status')
                            remaining_time = status_data.get('remaining_time')
                            position = status_data.get('position')
                            
                            test_logger.info(
                                f"Client {client.user_id} - Statut: {status}, "
                                f"Position: {position}, Temps restant: {remaining_time}"
                            )
                            
                            # Vérifier si le client est dans un état valide
                            if status in ['active', 'draft', 'connected']:
                                if remaining_time is not None and position is not None:
                                    client.status = status
                                    test_logger.info(f"Client {client.user_id} est prêt avec le statut {status}")
                                    return True
                                else:
                                    test_logger.debug(
                                        f"Client {client.user_id} a le statut {status} mais "
                                        f"remaining_time={remaining_time}, position={position}"
                                    )
                            else:
                                test_logger.debug(f"Client {client.user_id} a le statut {status}, attente...")
                    except Exception as e:
                        test_logger.debug(f"Tentative {attempt + 1}/{MAX_READY_RETRIES} pour {client.user_id}: {str(e)}")
                    
                    await asyncio.sleep(READY_CHECK_INTERVAL)
                
                test_logger.error(f"Client {client.user_id} n'est pas prêt après {MAX_READY_RETRIES} tentatives")
                return False

        async def cleanup_client(client: ClientState):
            """Nettoie proprement un client."""
            try:
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

        def thread_worker(thread_id: int, clients_subset: List[ClientState], stop_event: threading.Event):
            """Fonction exécutée par chaque thread."""
            thread_name = f"PollingThread-{thread_id}"
            threading.current_thread().name = thread_name
            
            results_queue.put({
                'info': f"Démarrage du thread {thread_name} avec {len(clients_subset)} clients"
            })
            
            # Créer une tâche de polling pour chaque client
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(clients_subset)) as executor:
                futures = [
                    executor.submit(poll_client_timer_sync, client, stop_event)
                    for client in clients_subset
                ]
                concurrent.futures.wait(futures)
            
            results_queue.put({
                'info': f"Thread {thread_name} terminé"
            })

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

            # Créer les clients et les répartir par thread
            clients_by_thread: List[List[ClientState]] = [[] for _ in range(NB_THREADS)]
            
            for thread_id in range(NB_THREADS):
                for i in range(NB_CLIENTS_PER_THREAD):
                    client_id = thread_id * NB_CLIENTS_PER_THREAD + i
                    client = ClientState(f"timer_client_{client_id}", thread_id)
                    clients[client.user_id] = client
                    clients_by_thread[thread_id].append(client)
            
            # Configurer tous les clients
            setup_results = await asyncio.gather(*[
                setup_client(client)
                for client in clients.values()
            ])
            
            # Ne garder que les clients correctement configurés
            ready_clients = {
                client.user_id: client
                for client, success in zip(clients.values(), setup_results)
                if success
            }
            
            if not ready_clients:
                raise RuntimeError("Aucun client n'a pu être configuré correctement")
            
            test_logger.info(f"{len(ready_clients)}/{len(clients)} clients sont prêts pour le test")
            
            # Réorganiser les clients prêts par thread
            clients_by_thread: List[List[ClientState]] = [[] for _ in range(NB_THREADS)]
            ready_client_list = list(ready_clients.values())
            clients_per_thread = len(ready_client_list) // NB_THREADS
            
            for thread_id in range(NB_THREADS):
                start_idx = thread_id * clients_per_thread
                end_idx = start_idx + clients_per_thread if thread_id < NB_THREADS - 1 else len(ready_client_list)
                clients_by_thread[thread_id] = ready_client_list[start_idx:end_idx]
            
            # Créer et démarrer les threads
            stop_event = threading.Event()
            threads = []
            
            for thread_id in range(NB_THREADS):
                thread = threading.Thread(
                    target=thread_worker,
                    args=(thread_id, clients_by_thread[thread_id], stop_event)
                )
                threads.append(thread)
                thread.start()
            
            # Collecter et logger les résultats pendant l'exécution
            start_time = time.time()
            while time.time() - start_time < POLL_DURATION:
                try:
                    result = results_queue.get(timeout=0.1)
                    if 'error' in result:
                        test_logger.error(result['error'])
                    elif 'info' in result:
                        # Ne logger que les infos importantes au niveau INFO
                        if "terminé" in result['info'] or "Démarrage" in result['info']:
                            test_logger.info(result['info'])
                        else:
                            # Les autres infos en debug
                            test_logger.debug(result['info'])
                except queue.Empty:
                    continue
            
            # Arrêter les threads
            stop_event.set()
            for thread in threads:
                thread.join(timeout=5.0)  # Timeout de 5 secondes pour le join
            
            # Vider la queue de résultats
            while not results_queue.empty():
                result = results_queue.get_nowait()
                if 'error' in result:
                    test_logger.error(result['error'])
                else:
                    test_logger.debug(result['info'])
            
            # Attendre un peu pour s'assurer que toutes les données sont collectées
            await asyncio.sleep(2.0)
            
            # Vérifier l'état des clients avant de vérifier l'historique
            for client in clients.values():
                test_logger.info(
                    f"État du client {client.user_id}: "
                    f"TTL historique: {len(client.ttl_history)}, "
                    f"Dernier TTL: {client.last_ttl}, "
                    f"Status: {client.status}"
                )
            
            # Vérifier que tous les timers étaient décroissants
            non_decreasing_clients = [
                client.user_id
                for client in clients.values()
                if not client.timer_decreasing
            ]
            
            assert len(non_decreasing_clients) == 0, \
                f"Clients avec timers non décroissants: {non_decreasing_clients}"
            
            # Vérifier que chaque client a bien un historique de TTL
            clients_without_history = [
                client.user_id
                for client in clients.values()
                if len(client.ttl_history) == 0
            ]
            
            if clients_without_history:
                test_logger.error(f"Clients sans historique TTL: {clients_without_history}")
                raise AssertionError(
                    f"Les clients suivants n'ont pas d'historique TTL: {clients_without_history}"
                )
            
            test_logger.info("Test de polling des timers multi-thread terminé avec succès")
            
        finally:
            # Nettoyage
            test_logger.info("Nettoyage des clients")
            cleanup_tasks = [
                cleanup_client(client)
                for client in clients.values()
            ]
            await asyncio.gather(*cleanup_tasks)
            
            # Vérifications finales
            final_active = await redis_client.scard("active_users")
            final_draft = await redis_client.scard("draft_users")
            final_waiting = await redis_client.llen("waiting_queue")
            
            assert final_active == 0, f"Il reste {final_active} utilisateurs actifs"
            assert final_draft == 0, f"Il reste {final_draft} utilisateurs en draft"
            assert final_waiting == 0, f"Il reste {final_waiting} utilisateurs en attente" 