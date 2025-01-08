import pytest
from httpx import AsyncClient
import asyncio
import json
from celery_test_config import setup_test_celery

class TestTimersAsync:
    @pytest.mark.asyncio
    async def test_pubsub_multiple_updates_async(self, test_client, redis_client, queue_manager_with_checker, test_logger):
        """Test la réception de plusieurs mises à jour de timer en mode asynchrone."""
        # Configuration de Celery en mode asynchrone
        celery_app = setup_test_celery()
        test_logger.info("Celery configuré en mode asynchrone")
        
        user_id = "test_user_pubsub_multiple_async"
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

            # Lancer la tâche de manière asynchrone
            test_logger.debug("Lancement de la tâche update_timer_channel en mode asynchrone")
            task = celery_app.send_task(
                'app.queue_manager.update_timer_channel',
                kwargs={
                    'channel': channel,
                    'initial_ttl': draft_ttl,
                    'timer_type': "draft",
                    'max_updates': 3
                }
            )
            test_logger.info(f"Tâche lancée avec l'ID: {task.id}")

            # Collecter les messages pendant que la tâche s'exécute
            test_logger.debug("Collecte des messages")
            start_time = asyncio.get_event_loop().time()
            max_wait = 10  # 10 secondes maximum pour le mode asynchrone
            
            while (asyncio.get_event_loop().time() - start_time) < max_wait:
                message = await pubsub.get_message(timeout=0.1)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    messages.append(data)
                    test_logger.info(f"Message reçu: {data}")
                    if len(messages) >= 3:  # On attend au moins 3 messages
                        break
                await asyncio.sleep(0.1)

            # Attendre que la tâche soit terminée
            try:
                task_result = await asyncio.wait_for(
                    asyncio.to_thread(task.get),
                    timeout=5.0
                )
                test_logger.info(f"Résultat de la tâche: {task_result}")
            except asyncio.TimeoutError:
                test_logger.warning("Timeout en attendant le résultat de la tâche")

            # Verify messages
            assert len(messages) >= 3, f"Au moins 3 messages devraient être reçus (reçu: {len(messages)})"
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
    async def test_update_timer_channel_async(self, redis_client, test_logger):
        """Test pour vérifier que la tâche update_timer_channel fonctionne correctement en mode asynchrone."""
        # Configuration de Celery en mode asynchrone
        celery_app = setup_test_celery()
        test_logger.info("Celery configuré en mode asynchrone")
        
        # Configuration initiale
        user_id = "test_timer_user_async"
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
            task = celery_app.send_task(
                'app.queue_manager.update_timer_channel',
                args=[channel, initial_ttl, timer_type, max_updates]
            )
            test_logger.info(f"Tâche lancée avec l'ID: {task.id}")
            
            # Vérifier les messages reçus
            messages_received = 0
            start_time = asyncio.get_event_loop().time()
            max_wait = 10  # 10 secondes maximum
            
            while (asyncio.get_event_loop().time() - start_time) < max_wait:
                message = await pubsub.get_message(timeout=0.1)
                if message and message['type'] == 'message':
                    data = json.loads(message['data'])
                    test_logger.info(f"Message reçu: {data}")
                    assert 'ttl' in data, "Le message devrait contenir un TTL"
                    assert 'timer_type' in data, "Le message devrait contenir un timer_type"
                    assert data['timer_type'] == timer_type, "Le type de timer devrait correspondre"
                    messages_received += 1
                    if messages_received >= max_updates:
                        break
                await asyncio.sleep(0.1)
            
            # Attendre que la tâche soit terminée
            try:
                task_result = await asyncio.wait_for(
                    asyncio.to_thread(task.get),
                    timeout=5.0
                )
                test_logger.info(f"Résultat de la tâche: {task_result}")
            except asyncio.TimeoutError:
                test_logger.warning("Timeout en attendant le résultat de la tâche")
            
            # Vérifier qu'on a reçu le bon nombre de messages
            assert messages_received > 0, "Aucun message reçu"
            test_logger.info(f"Nombre de messages reçus: {messages_received}")
            
        finally:
            # Nettoyage
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await redis_client.delete(f"{timer_type}:{user_id}")
            test_logger.info("Test terminé, nettoyage effectué") 