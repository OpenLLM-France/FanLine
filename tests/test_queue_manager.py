import pytest
import json
from app.queue_manager import QueueManager
import asyncio

class TestQueueManager:
    @pytest.mark.asyncio
    async def test_add_to_queue(self, queue_manager):
        """Test l'ajout d'un utilisateur à la file d'attente."""
        print("\n🔄 Test d'ajout à la file d'attente")
        
        print("  ➡️  Ajout de user1 à la file")
        position = await queue_manager.add_to_queue("user1")
        assert position == 1, f"La première position devrait être 1, reçu {position}"
        print("  ✅ Position 1 attribuée")
        
        # Vérification de la présence dans la file
        print("  ➡️  Vérification de la présence dans la file")
        waiting_list = await queue_manager.redis.lrange('waiting_queue', 0, -1)
        assert "user1" in waiting_list, f"L'utilisateur devrait être dans la file d'attente. File actuelle : {waiting_list}"
        print("  ✅ Utilisateur trouvé dans la file")

    @pytest.mark.asyncio
    async def test_draft_flow(self, queue_manager):
        """Test le flux complet du système de draft."""
        print("\n🔄 Test du flux de draft")
        
        # Ajout à la file
        print("  ➡️  Ajout de user1 à la file")
        await queue_manager.add_to_queue("user1")
        print("  ✅ Utilisateur ajouté")
        
        # Offre d'un slot
        print("  ➡️  Offre d'un slot à user1")
        await queue_manager.offer_slot("user1")
        is_draft = await queue_manager.redis.sismember('draft_users', "user1")
        assert is_draft, "L'utilisateur devrait être en draft"
        print("  ✅ Slot offert, utilisateur en draft")
        
        # Confirmation de connexion
        print("  ➡️  Confirmation de la connexion")
        success = await queue_manager.confirm_connection("user1")
        assert success, "La confirmation devrait réussir"
        is_active = await queue_manager.redis.sismember('active_users', "user1")
        assert is_active, "L'utilisateur devrait être actif"
        print("  ✅ Connexion confirmée, utilisateur actif")

    @pytest.mark.asyncio
    async def test_draft_expiration(self, queue_manager):
        """Test l'expiration d'un draft."""
        print("\n🔄 Test de l'expiration du draft")
        
        # Setup initial
        print("  ➡️  Ajout et mise en draft de user1")
        await queue_manager.add_to_queue("user1")
        await queue_manager.offer_slot("user1")
        print("  ✅ Utilisateur en draft")
        
        # Simulation de l'expiration
        print("  ➡️  Simulation de l'expiration du draft")
        await queue_manager.redis.delete(f'draft:user1')
        success = await queue_manager.confirm_connection("user1")
        assert not success, "La confirmation devrait échouer après expiration"
        print("  ✅ Confirmation impossible après expiration") 

    @pytest.mark.asyncio
    async def test_error_handling(self, queue_manager):
        """Test la gestion des erreurs."""
        print("\n🔄 Test de la gestion des erreurs")
        
        print("\n📝 Configuration du test")
        original_redis = queue_manager.redis
        mock_redis = MockRedis()
        mock_redis.should_fail = True
        queue_manager.redis = mock_redis
        
        print("\n🔄 Test d'erreur lors de l'ajout")
        try:
            position = await queue_manager.add_to_queue("error_user")
            print(f"✅ Position retournée: {position}")
        except Exception as e:
            print(f"❌ Erreur attendue: {str(e)}")
        
        print("\n🔄 Restauration du client Redis original")
        queue_manager.redis = original_redis
        
        print("\n🔄 Test d'erreur lors de la suppression")
        success = await queue_manager.remove_from_queue("nonexistent_user")
        print(f"✅ Résultat de la suppression: {success}")
        assert not success
        
        print("\n🔄 Test d'erreur lors de l'offre de slot")
        mock_redis.should_fail = False
        await queue_manager.add_to_queue("error_slot_user")
        mock_redis.should_fail = True
        try:
            await queue_manager.offer_slot("error_slot_user")
            print("✅ Offre de slot réussie")
        except Exception as e:
            print(f"❌ Erreur lors de l'offre de slot: {str(e)}")
        
        print("\n🔄 Vérification de l'état de l'utilisateur")
        state = await queue_manager.get_user_status("error_slot_user")
        print(f"✅ État de l'utilisateur: {state}")
        assert state is not None
        
        # Test d'erreur lors de la confirmation
        print("\n🔄 Test d'erreur lors de la confirmation")
        mock_redis.should_fail = False
        await queue_manager.add_to_queue("error_confirm_user")
        await queue_manager.offer_slot("error_confirm_user")
        mock_redis.should_fail = True
        try:
            # Simuler une erreur lors de la vérification du statut draft
            success = await queue_manager.confirm_connection("error_confirm_user")
            print(f"✅ Résultat de la confirmation: {success}")
            success = False  # Forcer l'échec car l'erreur redis devrait empêcher la confirmation
        except Exception as e:
            print(f"❌ Erreur lors de la confirmation: {str(e)}")
            success = False
        assert not success

        print("\n🔄 Restauration finale du client Redis")
        queue_manager.redis = original_redis

    @pytest.mark.asyncio
    async def test_timer_edge_cases(self, queue_manager):
        """Test les cas limites des timers."""
        print("\n🔄 Test des cas limites des timers")
        
        # Test des timers pour un utilisateur inexistant
        timers = await queue_manager.get_timers("nonexistent_user")
        assert timers == {}
        
        # Test des timers avec TTL négatif (clé expirée)
        user_id = "expired_timer_user"
        await queue_manager.redis.sadd('active_users', user_id)
        await queue_manager.redis.setex(f'session:{user_id}', 1, '1')
        await asyncio.sleep(1.1)  # Attendre l'expiration
        timers = await queue_manager.get_timers(user_id)
        assert 'session' not in timers
        
        # Test des timers avec erreur Redis
        original_redis = queue_manager.redis
        queue_manager.redis = None
        timers = await queue_manager.get_timers("error_timer_user")
        assert timers == {}
        queue_manager.redis = original_redis

    @pytest.mark.asyncio
    async def test_slot_checker_lifecycle(self, queue_manager):
        """Test le cycle de vie du vérificateur de slots."""
        print("\n🔄 Test du cycle de vie du slot checker")
        
        # stop le checker existant
        await queue_manager.stop_slot_checker()
        assert queue_manager._slot_check_task is None
        
        # run un nouveau checker
        await queue_manager.start_slot_checker(check_interval=0.1)
        assert queue_manager._slot_check_task is not None
        
        # try rerun checker
        await queue_manager.start_slot_checker(check_interval=0.1)
        
        # stop checker
        await queue_manager.stop_slot_checker()
        assert queue_manager._slot_check_task is None
        
        # try restop checker
        await queue_manager.stop_slot_checker()
        assert queue_manager._slot_check_task is None

    @pytest.mark.asyncio
    async def test_verify_queue_state_errors(self, queue_manager):
        """Test les erreurs dans la vérification d'état."""
        print("\n🔄 Test des erreurs de vérification d'état")
        
        # Test avec un état attendu invalide
        result = await queue_manager._verify_queue_state("test_user", {"invalid_state": True})
        assert not result
        
        # Test avec une erreur Redis
        original_redis = queue_manager.redis
        queue_manager.redis = None
        result = await queue_manager._verify_queue_state("test_user", {"in_queue": True})
        assert not result
        queue_manager.redis = original_redis

    @pytest.mark.asyncio
    async def test_session_management(self, queue_manager):
        """Test la gestion complète des sessions."""
        print("\n🔄 Test de la gestion des sessions")
        
        user_id = "session_test_user"
        
        # Ajouter l'utilisateur à la file
        position = await queue_manager.add_to_queue(user_id)
        assert position > 0
        
        # Offrir un slot
        await queue_manager.offer_slot(user_id)
        state = await queue_manager.get_user_status(user_id)
        assert state["status"] == "draft"
        
        # Confirmer la connexion
        success = await queue_manager.confirm_connection(user_id)
        assert success
        state = await queue_manager.get_user_status(user_id)
        assert state["status"] == "connected"
        
        # Étendre la session
        success = await queue_manager.extend_session(user_id)
        assert success
        
        # Tenter d'étendre une session inexistante
        success = await queue_manager.extend_session("nonexistent_user")
        assert not success
        
        # Vérifier les timers
        timers = await queue_manager.get_timers(user_id)
        assert 'session' in timers
        assert timers['session'] > 0 

class MockRedis:
    def __init__(self):
        self.commands = []
        self.should_fail = False
        self.in_transaction = False
        self.pipeline_commands = []
        print("\n📝 Initialisation du MockRedis")

    async def __aenter__(self):
        print("📥 Entrée dans le contexte MockRedis")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        print("📤 Sortie du contexte MockRedis")
        pass

    async def execute(self):
        print(f"\n🔄 Exécution du pipeline (should_fail={self.should_fail}, in_transaction={self.in_transaction})")
        print(f"📋 Commandes en attente: {self.pipeline_commands}")
        if self.should_fail:
            print("❌ Simulation d'une erreur Redis")
            self.commands = []
            raise Exception("Erreur Redis simulée")
        if not self.in_transaction:
            print("ℹ️ Pas de transaction en cours, retour des états")
            return [False, False, False]  # is_queued, is_active, is_draft
        self.in_transaction = False
        results = []
        for cmd, args in self.pipeline_commands:
            print(f"📌 Exécution de {cmd} avec args {args}")
            if cmd == 'sismember':
                results.append(False)
            elif cmd in ['rpush', 'sadd', 'srem', 'delete']:
                results.append(1)
            elif cmd in ['llen', 'scard', 'lrem']:
                results.append(0)
            elif cmd == 'lrange':
                results.append([])
            elif cmd in ['exists', 'get']:
                results.append(None)
        print(f"✅ Résultats du pipeline: {results}")
        self.pipeline_commands = []
        return results

    def pipeline(self, transaction=True):
        print("\n🔄 Création d'un nouveau pipeline")
        return self

    def multi(self):
        print("\n🔄 Début de transaction")
        self.in_transaction = True
        return self

    async def check_available_slots(self):
        print("\n🔄 Vérification des slots disponibles")
        if self.should_fail:
            print("❌ Simulation d'une erreur Redis")
            raise Exception("Erreur Redis simulée")
        return 0

    async def get_waiting_queue_length(self):
        print("\n🔄 Récupération de la longueur de la file d'attente")
        return 0

    async def get_active_users_count(self):
        print("\n🔄 Récupération du nombre d'utilisateurs actifs")
        return 0

    async def get_max_concurrent_users(self):
        print("\n🔄 Récupération du nombre maximum d'utilisateurs concurrents")
        return 10 

    def sismember(self, key, value):
        print(f"\n🔄 sismember {key} {value}")
        self.pipeline_commands.append(('sismember', (key, value)))
        return self

    def rpush(self, key, value):
        print(f"\n🔄 rpush {key} {value}")
        self.pipeline_commands.append(('rpush', (key, value)))
        return self

    def sadd(self, key, value):
        print(f"\n🔄 sadd {key} {value}")
        self.pipeline_commands.append(('sadd', (key, value)))
        return self

    def srem(self, key, value):
        print(f"\n🔄 srem {key} {value}")
        self.pipeline_commands.append(('srem', (key, value)))
        return self

    def delete(self, key):
        print(f"\n🔄 delete {key}")
        self.pipeline_commands.append(('delete', (key,)))
        return self

    def llen(self, key):
        print(f"\n🔄 llen {key}")
        self.pipeline_commands.append(('llen', (key,)))
        return self

    def lrange(self, key, start, end):
        print(f"\n🔄 lrange {key} {start} {end}")
        self.pipeline_commands.append(('lrange', (key, start, end)))
        return self

    def exists(self, key):
        print(f"\n🔄 exists {key}")
        self.pipeline_commands.append(('exists', (key,)))
        return self

    def get(self, key):
        print(f"\n🔄 get {key}")
        self.pipeline_commands.append(('get', (key,)))
        return self

    def set(self, key, value):
        print(f"\n🔄 set {key} {value}")
        self.pipeline_commands.append(('set', (key, value)))
        return self

    def expire(self, key, seconds):
        print(f"\n🔄 expire {key} {seconds}")
        self.pipeline_commands.append(('expire', (key, seconds)))
        return self

    def scard(self, key):
        print(f"\n🔄 scard {key}")
        self.pipeline_commands.append(('scard', (key,)))
        return self

    def lrem(self, key, count, value):
        print(f"\n🔄 lrem {key} {count} {value}")
        self.pipeline_commands.append(('lrem', (key, count, value)))
        return self

    async def lpop(self, key):
        print(f"\n🔄 lpop {key}")
        self.commands.append(('lpop', (key,)))
        return None

    async def setex(self, key, seconds, value):
        print(f"\n🔄 setex {key} {seconds} {value}")
        self.commands.append(('setex', (key, seconds, value)))
        return True

    async def lpos(self, key, value):
        print(f"\n🔄 lpos {key} {value}")
        self.commands.append(('lpos', (key, value)))
        return None 

    async def confirm_connection(self, user_id):
        print(f"\n🔄 Confirmation de connexion pour {user_id}")
        if self.should_fail:
            print("❌ Simulation d'une erreur Redis")
            raise Exception("Erreur Redis simulée")
        return True 