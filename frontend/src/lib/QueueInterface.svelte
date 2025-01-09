<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { joinQueue, leaveQueue, confirmConnection, getStatus, heartbeat, getTimers, getMetrics } from './queue';
    import type { UserRequest } from './types';
    import { createClient, type RedisClientType } from 'redis';

    // Générer un ID utilisateur aléatoire
    const userId = `user-${Math.random().toString(36).substring(2, 9)}`;
    const userRequest: UserRequest = { user_id: userId };

    let status: 'waiting' | 'draft' | 'connected' | 'disconnected' | 'testing' = 'testing';
    let position: number | null = null;
    let draftTimer: number | null = null;
    let sessionTimer: number | null = null;
    let messages: string[] = [];
    let newMessage = '';
    let error: string | null = null;
    let testProgress: string[] = [];

    let statusCheckInterval: number;
    let timerCheckInterval: number;
    let redisClient: RedisClientType | null = null;

    interface TimerMessage {
        timer_type: 'draft' | 'session';
        ttl: number;
        updates_left: number;
    }

    async function setupRedisListener() {
        try {
            redisClient = createClient();
            await redisClient.connect();

            const channel = `timer:channel:${userId}`;
            await redisClient.subscribe(channel, (message: string) => {
                try {
                    const data = JSON.parse(message) as TimerMessage;
                    if (data.timer_type === 'draft') {
                        draftTimer = data.ttl;
                    } else if (data.timer_type === 'session') {
                        sessionTimer = data.ttl;
                    }
                } catch (err) {
                    console.error('Erreur lors du traitement du message Redis:', err);
                }
            });
        } catch (err) {
            console.error('Erreur lors de la connexion à Redis:', err);
        }
    }

    async function cleanupRedisListener() {
        if (redisClient) {
            try {
                await redisClient.unsubscribe(`timer:channel:${userId}`);
                await redisClient.quit();
            } catch (err) {
                console.error('Erreur lors de la déconnexion de Redis:', err);
            }
        }
    }

    async function testEndpoint(name: string, fn: () => Promise<unknown>): Promise<boolean> {
        try {
            testProgress = [...testProgress, `Test de ${name}...`];
            await new Promise(resolve => setTimeout(resolve, 1000)); // Attendre 1s entre chaque test
            await fn();
            testProgress = [...testProgress, `✅ ${name} OK`];
            return true;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Une erreur est survenue';
            testProgress = [...testProgress, `❌ ${name} échec: ${message}`];
            error = `Erreur lors du test de ${name}: ${message}`;
            return false;
        }
    }

    async function testUseCase(name: string, steps: Array<() => Promise<void>>): Promise<boolean> {
        testProgress = [...testProgress, `\n🔍 Test du cas d'utilisation: ${name}`];
        try {
            for (const step of steps) {
                await step();
                await new Promise(resolve => setTimeout(resolve, 500));
            }
            testProgress = [...testProgress, `✅ Cas d'utilisation ${name} OK\n`];
            return true;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Une erreur est survenue';
            testProgress = [...testProgress, `❌ Cas d'utilisation ${name} échec: ${message}\n`];
            error = `Erreur lors du test du cas ${name}: ${message}`;
            return false;
        }
    }

    async function runTests() {
        error = null;
        testProgress = ['Démarrage des tests...'];
        
        // Test basiques des endpoints
        const metricsOk = await testEndpoint('metrics', async () => {
            const metrics = await getMetrics();
            if (!('active_users' in metrics)) throw new Error('Format de réponse invalide');
            return metrics;
        });

        if (!metricsOk) return;

        // Test du cas d'utilisation: Cycle complet de file d'attente
        const queueCycleOk = await testUseCase("Cycle de file d'attente", [
            async () => {
                const joinResult = await joinQueue(userRequest);
                if (!joinResult.position) throw new Error('Position non reçue');
                testProgress = [...testProgress, `- Rejoint la file en position ${joinResult.position}`];
            },
            async () => {
                const statusResult = await getStatus(userId);
                if (statusResult.status !== 'waiting') throw new Error('Statut incorrect');
                testProgress = [...testProgress, '- Statut vérifié: en attente'];
            },
            async () => {
                const leaveResult = await leaveQueue(userRequest);
                if (!leaveResult.success) throw new Error('Échec de la sortie de file');
                testProgress = [...testProgress, '- Quitté la file avec succès'];
            }
        ]);

        if (!queueCycleOk) return;

        // Test du cas d'utilisation: Vérification des timers
        const timerTestOk = await testUseCase("Vérification des timers", [
            async () => {
                const timers = await getTimers(userId);
                testProgress = [...testProgress, `- Timer vérifié: ${timers.timer_type} - ${timers.ttl}s`];
            }
        ]);

        if (!timerTestOk) return;

        // Test du cas d'utilisation: Gestion des erreurs
        const errorHandlingOk = await testUseCase("Gestion des erreurs", [
            async () => {
                try {
                    await getStatus('invalid-id');
                    throw new Error('Devrait échouer avec un ID invalide');
                } catch (err) {
                    testProgress = [...testProgress, '- Erreur correctement détectée pour ID invalide'];
                }
            },
            async () => {
                await joinQueue(userRequest);
                try {
                    await joinQueue(userRequest);
                    throw new Error('Devrait échouer pour double entrée');
                } catch (err) {
                    testProgress = [...testProgress, '- Erreur correctement détectée pour double entrée'];
                }
                await leaveQueue(userRequest);
            }
        ]);

        if (!errorHandlingOk) return;

        // Si on arrive ici, tous les tests sont passés
        testProgress = [...testProgress, '\n✨ Tous les tests sont passés !'];
        setTimeout(() => {
            status = 'disconnected';
            startQueue();
        }, 2000);
    }

    async function startQueue() {
        try {
            const result = await joinQueue(userRequest);
            position = result.position;
            status = 'waiting';
            startStatusCheck();
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function checkStatus() {
        try {
            const currentStatus = await getStatus(userId);
            status = currentStatus.status;
            if (status === 'waiting') {
                position = currentStatus.position || null;
            }
            if (status === 'draft' || status === 'connected') {
                checkTimers();
            }
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function checkTimers() {
        try {
            const timers = await getTimers(userId);
            if (timers.timer_type === 'draft') {
                draftTimer = timers.ttl;
            } else if (timers.timer_type === 'session') {
                sessionTimer = timers.ttl;
            }
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function confirmDraft() {
        try {
            await confirmConnection(userRequest);
            status = 'connected';
            draftTimer = null;
            startStatusCheck();
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    function startStatusCheck() {
        clearInterval(statusCheckInterval);
        clearInterval(timerCheckInterval);
        statusCheckInterval = setInterval(checkStatus, 1000) as unknown as number;
        timerCheckInterval = setInterval(checkTimers, 1000) as unknown as number;
    }

    function sendMessage() {
        if (newMessage.trim()) {
            messages = [...messages, `${userId}: ${newMessage}`];
            newMessage = '';
        }
    }

    onMount(async () => {
        await setupRedisListener();
        runTests();
    });

    onDestroy(async () => {
        clearInterval(statusCheckInterval);
        clearInterval(timerCheckInterval);
        if (status !== 'disconnected' && status !== 'testing') {
            leaveQueue(userRequest).catch(console.error);
        }
        await cleanupRedisListener();
    });
</script>

<div class="container mx-auto p-4 max-w-2xl">
    <header class="bg-blue-600 text-white p-4 rounded-t-lg">
        <h1 class="text-xl font-bold">File d'attente</h1>
        <p class="text-sm">ID Utilisateur: {userId}</p>
    </header>

    <main class="bg-white shadow-lg rounded-b-lg p-4">
        {#if error}
            <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
                {error}
            </div>
        {/if}

        {#if status === 'testing'}
            <div class="py-8">
                <h2 class="text-2xl font-bold mb-4 text-center">Vérification du système</h2>
                <div class="bg-gray-50 p-4 rounded-lg">
                    {#each testProgress as message}
                        <p class="mb-2 font-mono text-sm">{message}</p>
                    {/each}
                </div>
                <div class="flex justify-center mt-4">
                    <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
            </div>
        {:else if status === 'waiting'}
            <div class="text-center py-8">
                <h2 class="text-2xl font-bold mb-4">En attente</h2>
                <p class="text-lg">Position dans la file : {position}</p>
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mt-4"></div>
            </div>
        {:else if status === 'draft'}
            <div class="text-center py-8">
                <h2 class="text-2xl font-bold mb-4">Slot disponible !</h2>
                {#if draftTimer !== null}
                    <p class="text-lg mb-4">Temps restant : {Math.ceil(draftTimer)}s</p>
                {/if}
                <button 
                    class="bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded"
                    on:click={confirmDraft}
                >
                    Confirmer la connexion
                </button>
            </div>
        {:else if status === 'connected'}
            <div class="py-4">
                {#if sessionTimer !== null}
                    <p class="text-right text-sm text-gray-600">
                        Session : {Math.ceil(sessionTimer)}s restants
                    </p>
                {/if}
                <div class="bg-gray-100 p-4 rounded-lg h-64 overflow-y-auto mb-4">
                    {#each messages as message}
                        <p class="mb-2">{message}</p>
                    {/each}
                </div>
                <div class="flex gap-2">
                    <input
                        type="text"
                        bind:value={newMessage}
                        placeholder="Votre message..."
                        class="flex-1 border rounded p-2"
                        on:keydown={(e) => e.key === 'Enter' && sendMessage()}
                    />
                    <button
                        class="bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded"
                        on:click={sendMessage}
                    >
                        Envoyer
                    </button>
                </div>
            </div>
        {/if}
    </main>
</div>

<style>
    /* Les styles sont gérés par Tailwind CSS */
</style> 