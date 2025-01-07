import pytest
from httpx import AsyncClient
from app.main import app
from app.queue_manager import QueueManager, update_timer_channel
import asyncio
import os
import json
import celery

@pytest.fixture
def queue_manager(redis_client):
    return QueueManager(redis_client)

class TestTimers:
    @pytest.mark.asyncio
    async def test_draft_timer_redis(self, queue_manager, redis_client):
        user_id = "test_user_draft"
        
        await queue_manager.offer_slot(user_id)
        exists = await redis_client.exists(f"draft:{user_id}")
        assert exists
        
        ttl = await redis_client.ttl(f"draft:{user_id}")
        assert 0 < ttl <= queue_manager.draft_duration
        
        await asyncio.sleep(2)
        
        new_ttl = await redis_client.ttl(f"draft:{user_id}")
        assert new_ttl < ttl
        
        await redis_client.delete(f"draft:{user_id}")
        await redis_client.srem("draft_users", user_id)

    @pytest.mark.asyncio
    async def test_session_timer_redis(self, queue_manager, redis_client):
        user_id = "test_user_session"
        
        # Setup: ajouter l'utilisateur en draft d'abord
        await redis_client.sadd("draft_users", user_id)
        await redis_client.setex(f"draft:{user_id}", queue_manager.draft_duration, "1")
        
        # Confirmer la connexion
        success = await queue_manager.confirm_connection(user_id)
        assert success, "La confirmation de connexion a échoué"
        
        exists = await redis_client.exists(f"session:{user_id}")
        assert exists, "La session n'existe pas"
        
        ttl = await redis_client.ttl(f"session:{user_id}")
        assert 0 < ttl <= queue_manager.session_duration
        
        await asyncio.sleep(2)
        
        new_ttl = await redis_client.ttl(f"session:{user_id}")
        assert new_ttl < ttl
        
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_draft(self, test_client, redis_client):
        user_id = "test_user_api_draft"
        
        await redis_client.sadd("draft_users", user_id)
        await redis_client.setex(f"draft:{user_id}", 300, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        
        timers = response.json()
        assert timers["timer_type"] == "draft"
        assert 0 < timers["ttl"] <= 300
        
        await redis_client.delete(f"draft:{user_id}")
        await redis_client.srem("draft_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_session(self, test_client, redis_client):
        user_id = "test_user_api_session"
        
        # Setup: ajouter l'utilisateur en tant qu'utilisateur actif
        await redis_client.sadd("active_users", user_id)
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        
        timers = response.json()
        assert timers["timer_type"] == "session"
        assert 0 < timers["ttl"] <= 1200
        
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_both(self, test_client, redis_client):
        user_id = "test_user_api_session"
        user_id_draft = "test_user_api_draft"
        await redis_client.sadd("draft_users", user_id_draft)
        await redis_client.sadd("active_users", user_id)
        len_draft_users = await redis_client.scard("draft_users")
        len_active_users = await redis_client.scard("active_users")
        assert len_draft_users == 1, f"len_draft_users is {len_draft_users}"
        assert len_active_users == 1, f"len_active_users is {len_active_users}"
        await redis_client.setex(f"draft:{user_id_draft}", 300, "1")
        await redis_client.setex(f"session:{user_id}", 1200, "1")
        
        response = await test_client.get(f"/queue/timers/{user_id}")
        response_draft = await test_client.get(f"/queue/timers/{user_id_draft}")
        assert response.status_code == 200
        
        timers = response.json()
        timers_draft = response_draft.json()

        # Le draft a priorité sur la session
        assert timers_draft["timer_type"] == "draft" , f"timer_type is {timers_draft}"
        assert 0 < timers_draft["ttl"] <= 300 , f"ttl is {timers_draft['ttl']}"
        
        await redis_client.delete(f"draft:{user_id_draft}")
        await redis_client.delete(f"session:{user_id}")
        await redis_client.srem("draft_users", user_id_draft)
        await redis_client.srem("active_users", user_id)
        len_draft_users = await redis_client.scard("draft_users")
        len_active_users = await redis_client.scard("active_users")
        assert len_draft_users == 0, f"len_draft_users is {len_draft_users}"
        assert len_active_users == 0, f"len_active_users is {len_active_users}"

    @pytest.mark.asyncio
    async def test_get_timers_endpoint_no_timers(self, test_client, redis_client):
        user_id = "test_user_api_none"
        response = await test_client.get(f"/queue/timers/{user_id}")
        assert response.status_code == 200
        timers = response.json()
        assert timers == {} 

    @pytest.mark.asyncio
    async def test_pubsub_connection_draft(self, queue_manager_with_checker, test_client, test_logger, redis_client):
        """Test la connexion pubsub pour le draft."""
        test_logger.info("Démarrage du test pubsub draft")
        user_id = "test_user_pubsub_draft"
        
        try:
            # Ajouter l'utilisateur à la file
            test_logger.debug(f"Ajout de l'utilisateur {user_id} à la file")
            response = await test_client.post("/queue/join", json={"user_id": user_id})
            assert response.status_code == 200
            
            # Attendre que l'utilisateur soit en draft
            test_logger.debug("Attente du placement en draft")
            max_wait = 2  # 2 secondes maximum
            start_time = asyncio.get_event_loop().time()
            is_draft = False
            
            while not is_draft and (asyncio.get_event_loop().time() - start_time) < max_wait:
                is_draft = await redis_client.sismember('draft_users', user_id)
                if not is_draft:
                    await asyncio.sleep(0.1)
            
            assert is_draft, "L'utilisateur n'a pas été placé en draft après 2 secondes"
            test_logger.info("Utilisateur placé en draft avec succès")
            
            # Vérifier les timers
            test_logger.debug("Vérification des timers")
            async def get_timers():
                response = await test_client.get(f"/queue/timers/{user_id}")
                assert response.status_code == 200
                timers = response.json()
                test_logger.info(f"Timers reçus: {timers}")
                
                # Vérifier le type de timer
                assert timers.get("timer_type") == "draft", f"Timer type incorrect: {timers}"
                assert timers.get("ttl") > 0, f"TTL invalide: {timers}"
                return timers
            
            timers = await asyncio.wait_for(get_timers(), timeout=5.0)
                
        except asyncio.TimeoutError:
            test_logger.error("Timeout lors du test pubsub draft")
            raise
        except Exception as e:
            test_logger.error(f"Erreur lors du test pubsub draft: {str(e)}")
            raise
        finally:
            # Nettoyage
            await redis_client.srem("draft_users", user_id)
            await redis_client.delete(f"draft:{user_id}")
            test_logger.info("Fin du test pubsub draft")

    @pytest.mark.asyncio
    async def test_pubsub_connection_session(self, test_client, redis_client, queue_manager_with_checker, test_logger, celery_app):
        """Test la connexion PubSub pour un timer de session."""
        # Forcer le mode EAGER pour Celery
        celery_app.conf.update(
            task_always_eager=True,
            task_eager_propagates=True
        )
        test_logger.info(f"Mode Celery configuré: EAGER={celery_app.conf.task_always_eager}")
        
        user_id = "test_user_pubsub_session"
        messages = []

        # Ajouter l'utilisateur à la file d'attente
        test_logger.debug(f"Tentative d'ajout de l'utilisateur {user_id} à la file d'attente")
        join_response = await test_client.post("/queue/join", json={"user_id": user_id})
        assert join_response.status_code == 200
        test_logger.info(f"Utilisateur {user_id} ajouté à la file d'attente avec succès")

        # Attendre que le slot checker place l'utilisateur en draft
        test_logger.debug("Attente du placement en draft")
        max_wait = 2  # 2 secondes maximum
        start_time = asyncio.get_event_loop().time()
        is_draft = False
        
        while not is_draft and (asyncio.get_event_loop().time() - start_time) < max_wait:
            is_draft = await redis_client.sismember('draft_users', user_id)
            if not is_draft:
                await asyncio.sleep(0.1)
        
        assert is_draft, "L'utilisateur n'a pas été placé en draft après 2 secondes"
        test_logger.info(f"Utilisateur {user_id} placé en draft avec succès")

        # Confirmer la connexion
        test_logger.debug("Tentative de confirmation de la connexion")
        confirm_response = await test_client.post("/queue/confirm", json={"user_id": user_id})
        assert confirm_response.status_code == 200
        test_logger.info(f"Connexion de l'utilisateur {user_id} confirmée avec succès")

        # Vérifier que l'utilisateur n'est plus dans draft et est maintenant dans active_users
        test_logger.debug("Vérification de l'état de l'utilisateur")
        is_draft = await redis_client.sismember('draft_users', user_id)
        assert not is_draft, "L'utilisateur ne devrait plus être dans draft après la confirmation"
        is_active = await redis_client.sismember('active_users', user_id)
        assert is_active, "L'utilisateur devrait être dans active_users après la confirmation"
        test_logger.info(f"État de l'utilisateur {user_id} vérifié: pas dans draft, mais dans active_users")

        try:
            # Setup pubsub connection avant de récupérer les timers
            test_logger.debug("Configuration de la connexion PubSub")
            pubsub = redis_client.pubsub()
            channel = f"timer:channel:{user_id}"
            await pubsub.subscribe(channel)
            test_logger.info(f"Abonnement PubSub réussi pour le channel {channel}")

            # Get timers pour démarrer la tâche
            test_logger.debug("Récupération des timers")
            timer_response = await test_client.get(f"/queue/timers/{user_id}")
            assert timer_response.status_code == 200
            timer_data = timer_response.json()
            assert "channel" in timer_data, "La réponse devrait contenir un channel"
            test_logger.info(f"Timers récupérés pour l'utilisateur {user_id}")

            # Collecter les messages pendant que la tâche s'exécute
            test_logger.debug("Collecte des messages")
            start_time = asyncio.get_event_loop().time()
            max_wait = 5  # 5 secondes maximum
            
            while (asyncio.get_event_loop().time() - start_time) < max_wait:
                message = await pubsub.get_message(timeout=0.1)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    messages.append(data)
                    test_logger.info(f"Message reçu: {data}")
                    if len(messages) >= 3:  # On attend au moins 3 messages
                        break
                await asyncio.sleep(0.1)

            # Verify messages
            assert len(messages) > 0, "Aucun message reçu"
            first_message = messages[0]
            assert first_message["timer_type"] == "session"
            assert 0 < first_message["ttl"] <= 1200
            test_logger.info(f"Messages vérifiés pour l'utilisateur {user_id}")

            # Vérifier que les TTL diminuent
            for i in range(1, len(messages)):
                assert messages[i]["ttl"] <= messages[i-1]["ttl"], \
                    f"Le TTL devrait diminuer: {messages[i-1]['ttl']} -> {messages[i]['ttl']}"

        finally:
            # Cleanup
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis_client.delete(f"session:{user_id}")
            await redis_client.srem("active_users", user_id)

    @pytest.mark.asyncio
    async def test_pubsub_multiple_updates(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test la réception de plusieurs mises à jour de timer."""
        user_id = "test_user_pubsub_multiple"
        messages = []

        # Ajouter l'utilisateur à la file d'attente
        test_logger.debug(f"Ajout de l'utilisateur {user_id} à la file")
        join_response = await test_client.post("/queue/join", json={"user_id": user_id})
        assert join_response.status_code == 200

        # Attendre que le slot checker place l'utilisateur en draft
        test_logger.debug("Attente du placement en draft")
        max_wait = 2  # 2 secondes maximum
        start_time = asyncio.get_event_loop().time()
        is_draft = False
        
        while not is_draft and (asyncio.get_event_loop().time() - start_time) < max_wait:
            is_draft = await redis_client.sismember('draft_users', user_id)
            if not is_draft:
                await asyncio.sleep(0.1)
        
        assert is_draft, "L'utilisateur n'a pas été placé en draft après 2 secondes"
        test_logger.info(f"Utilisateur {user_id} placé en draft avec succès")

        try:
            # Setup pubsub connection
            test_logger.debug("Configuration de la connexion PubSub")
            pubsub = redis_client.pubsub()
            channel = f"timer:channel:{user_id}"
            await pubsub.subscribe(channel)
            test_logger.info(f"Abonnement PubSub réussi pour le channel {channel}")

            # Vérifier le TTL du draft
            draft_ttl = await redis_client.ttl(f"draft:{user_id}")
            assert draft_ttl > 0, "Le TTL du draft devrait être positif"
            test_logger.info(f"TTL du draft: {draft_ttl}")

            # Lancer la tâche directement
            test_logger.debug("Lancement de la tâche update_timer_channel")
            task_result = await update_timer_channel(channel, draft_ttl, "draft", 3)
            test_logger.info(f"Résultat de la tâche: {task_result}")

            # Collecter les messages pendant que la tâche s'exécute
            test_logger.debug("Collecte des messages")
            start_time = asyncio.get_event_loop().time()
            max_wait = 5  # 5 secondes maximum
            
            while (asyncio.get_event_loop().time() - start_time) < max_wait:
                message = await pubsub.get_message(timeout=0.1)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    messages.append(data)
                    test_logger.info(f"Message reçu: {data}")
                    if len(messages) >= 3:  # On attend au moins 3 messages
                        break
                await asyncio.sleep(0.1)

            # Verify messages
            assert len(messages) >= 3, "Au moins 3 messages devraient être reçus"
            test_logger.info(f"Nombre de messages reçus: {len(messages)}")
            
            # Vérifier le premier message
            first_message = messages[0]
            assert first_message["timer_type"] == "draft"
            assert 0 < first_message["ttl"] <= 300
            test_logger.info(f"Premier message vérifié: {first_message}")

            # Vérifier que les TTL diminuent
            for i in range(1, len(messages)):
                assert messages[i]["ttl"] <= messages[i-1]["ttl"], \
                    f"Le TTL devrait diminuer: {messages[i-1]['ttl']} -> {messages[i]['ttl']}"
                test_logger.debug(f"TTL diminue correctement: {messages[i-1]['ttl']} -> {messages[i]['ttl']}")

        finally:
            # Cleanup
            test_logger.debug("Nettoyage")
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis_client.delete(f"draft:{user_id}")
            await redis_client.srem("draft_users", user_id)
            test_logger.info("Test terminé, nettoyage effectué")

@pytest.mark.asyncio
async def test_update_timer_channel(celery_app, redis_client, test_logger):
    """Test pour vérifier que la tâche update_timer_channel fonctionne correctement."""
    test_logger.info("Démarrage du test de update_timer_channel")
    
    # Configuration initiale
    user_id = "test_timer_user"
    channel = f"timer:channel:{user_id}"
    timer_type = "session"
    initial_ttl = 5
    max_updates = 3
    
    # Créer une clé de session pour le test
    await redis_client.setex(f"{timer_type}:{user_id}", initial_ttl, "1")
    test_logger.info(f"Clé de session créée: {timer_type}:{user_id} avec TTL={initial_ttl}")
    
    # S'abonner au canal pour recevoir les mises à jour
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    test_logger.info(f"Abonnement au canal {channel}")
    
    # Lancer la tâche de mise à jour
    test_logger.info("Lancement de la tâche update_timer_channel")
    try:
        result = await update_timer_channel.apply(
            args=[channel, initial_ttl, timer_type, max_updates]
        ).get()
        test_logger.info("Tâche update_timer_channel terminée")
    except Exception as e:
        test_logger.error(f"Erreur lors de l'exécution de update_timer_channel: {str(e)}")
        raise
    
    # Vérifier les messages reçus
    messages_received = 0
    
    async def check_messages():
        nonlocal messages_received
        while messages_received < max_updates:
            message = await pubsub.get_message(timeout=1.0)
            if message and message['type'] == 'message':
                data = json.loads(message['data'])
                test_logger.info(f"Message reçu: {data}")
                assert 'ttl' in data, "Le message devrait contenir un TTL"
                assert 'timer_type' in data, "Le message devrait contenir un timer_type"
                assert data['timer_type'] == timer_type, "Le type de timer devrait correspondre"
                messages_received += 1
    
    try:
        await asyncio.wait_for(check_messages(), timeout=2.0)
    except asyncio.TimeoutError:
        test_logger.warning("Timeout en attendant les messages")
    
    # Vérifier qu'on a reçu le bon nombre de messages
    assert messages_received > 0, "Aucun message reçu"
    test_logger.info(f"Nombre de messages reçus: {messages_received}")
    
    # Nettoyage
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()
    await redis_client.delete(f"{timer_type}:{user_id}")
    test_logger.info("Test terminé, nettoyage effectué")

@pytest.mark.asyncio
async def test_update_timer_channel_expiration(celery_app, redis_client, test_logger):
    """Test pour vérifier que la tâche update_timer_channel gère correctement l'expiration."""
    test_logger.info("Démarrage du test d'expiration du timer")
    
    # Configuration initiale
    user_id = "test_timer_expiration"
    channel = f"timer:channel:{user_id}"
    timer_type = "draft"
    initial_ttl = 1  # TTL court pour tester l'expiration
    max_updates = 5
    
    # Créer une clé de draft pour le test
    await redis_client.setex(f"{timer_type}:{user_id}", initial_ttl, "1")
    test_logger.info(f"Clé de draft créée: {timer_type}:{user_id} avec TTL={initial_ttl}")
    
    # S'abonner au canal
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    test_logger.info(f"Abonnement au canal {channel}")
    
    # Lancer la tâche
    test_logger.info("Lancement de la tâche update_timer_channel")
    try:
        result = await update_timer_channel.apply(
            args=[channel, initial_ttl, timer_type, max_updates]
        ).get()
        test_logger.info("Tâche update_timer_channel terminée")
    except Exception as e:
        test_logger.error(f"Erreur lors de l'exécution de update_timer_channel: {str(e)}")
        raise
    
    # Vérifier que la clé a expiré
    await asyncio.sleep(initial_ttl + 0.5)  # Attendre un peu plus que le TTL
    ttl = await redis_client.ttl(f"{timer_type}:{user_id}")
    assert ttl <= 0, f"La clé devrait avoir expiré, TTL actuel: {ttl}"
    test_logger.info("Clé expirée comme prévu")
    
    # Nettoyage
    await pubsub.unsubscribe(channel)
    await pubsub.aclose()
    await redis_client.delete(f"{timer_type}:{user_id}")
    test_logger.info("Test terminé, nettoyage effectué") 