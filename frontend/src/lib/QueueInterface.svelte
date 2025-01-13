<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { joinQueue, leaveQueue, confirmConnection, getStatus, heartbeat, getTimers, getMetrics } from './queue';
    import type { UserRequest, QueueStatus, QueueMetrics, TimerInfo, ApiResponse } from './types';

    // Générer un ID utilisateur aléatoire
    const userId = `user-${Math.random().toString(36).substring(2, 9)}`;
    const userRequest: UserRequest = { user_id: userId };

    let status: 'waiting' | 'draft' | 'connected' | 'disconnected' | 'testing' = 'testing';
    let position: number | null = null;
    let draftTimer: number | null = null;
    let sessionTimer: number | null = null;
    let error: string | null = null;
    let testProgress: string[] = [];

    let statusCheckInterval: number;
    let timerCheckInterval: number;

    async function checkTimers() {
        try {
            const timers = await getTimers(userId);
            if (timers.timer_type === 'draft') {
                draftTimer = timers.ttl;
            } else if (timers.timer_type === 'session') {
                sessionTimer = timers.ttl;
            }
        } catch (err) {
            console.error('Erreur lors de la vérification des timers:', err);
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

    function startPolling() {
        clearInterval(statusCheckInterval);
        clearInterval(timerCheckInterval);
        statusCheckInterval = setInterval(checkStatus, 1000) as unknown as number;
        timerCheckInterval = setInterval(checkTimers, 1000) as unknown as number;
    }

    async function handleJoinQueue() {
        try {
            error = null;
            const result = await joinQueue(userRequest);
            position = result.position;
            status = 'waiting';
            startPolling();
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function handleConfirmConnection() {
        try {
            error = null;
            await confirmConnection(userRequest);
            status = 'connected';
            draftTimer = null;
            startPolling();
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function handleLeaveQueue() {
        try {
            error = null;
            await leaveQueue(userRequest);
            status = 'disconnected';
            position = null;
            draftTimer = null;
            sessionTimer = null;
            clearInterval(statusCheckInterval);
            clearInterval(timerCheckInterval);
        } catch (err) {
            error = err instanceof Error ? err.message : 'Une erreur est survenue';
        }
    }

    async function testEndpoint(name: string, fn: () => Promise<boolean>): Promise<boolean> {
        try {
            testProgress = [...testProgress, `Test de ${name}...`];
            const success = await fn();
            if (success) {
                testProgress = [...testProgress, `✅ ${name} OK`];
            } else {
                testProgress = [...testProgress, `❌ ${name} échec`];
            }
            return success;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Une erreur est survenue';
            testProgress = [...testProgress, `❌ ${name} erreur: ${message}`];
            return false;
        }
    }

    async function runTests() {
        testProgress = [];
        
        await testEndpoint('Heartbeat', async () => {
            const heartbeatResult = await heartbeat(userRequest);
            return heartbeatResult.success;
        });

        await testEndpoint('Metrics', async () => {
            const metricsResult = await getMetrics();
            return metricsResult.active_users >= 0;
        });

        await testEndpoint('Status', async () => {
            const statusResult = await getStatus(userId);
            return statusResult.status !== undefined;
        });

        await testEndpoint('Join Queue', async () => {
            const joinResult = await joinQueue(userRequest);
            return joinResult.position >= 0;
        });

        await testEndpoint('Leave Queue', async () => {
            const leaveResult = await leaveQueue(userRequest);
            return leaveResult.success;
        });

        // Attendre un peu avant de commencer à utiliser l'application
        setTimeout(() => {
            status = 'disconnected';
        }, 2000);
    }

    onMount(async () => {
        runTests();
    });

    onDestroy(() => {
        clearInterval(statusCheckInterval);
        clearInterval(timerCheckInterval);
        if (status !== 'disconnected' && status !== 'testing') {
            leaveQueue(userRequest).catch(console.error);
        }
    });
</script>

<div class="flex flex-col items-center justify-center min-h-screen bg-gray-100 p-4">
    <div class="bg-white shadow-md rounded px-8 pt-6 pb-8 mb-4 max-w-md w-full">
        <h1 class="text-2xl font-bold mb-4 text-center">File d'attente</h1>
        
        {#if error}
            <div data-testid="error-message" class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">
                <span class="block sm:inline">{error}</span>
            </div>
        {/if}

        {#if status === 'testing'}
            <div data-testid="test-screen">
                <h2>Test des endpoints</h2>
                <div data-testid="test-progress">
                    {#each testProgress as message}
                        <div data-testid="test-message">{message}</div>
                    {/each}
                </div>
            </div>
        {:else if status === 'disconnected'}
            <div data-testid="queue-screen">
                <button on:click={handleJoinQueue}>Rejoindre la file</button>
            </div>
        {:else if status === 'waiting'}
            <div data-testid="waiting-screen">
                <p>Position dans la file : {position}</p>
                <button on:click={handleLeaveQueue}>Quitter la file</button>
            </div>
        {:else if status === 'draft'}
            <div data-testid="draft-screen">
                <p>Temps restant : {draftTimer}s</p>
                <button on:click={handleConfirmConnection}>Confirmer la connexion</button>
                <button on:click={handleLeaveQueue}>Quitter la file</button>
            </div>
        {:else if status === 'connected'}
            <div data-testid="connected-screen">
                <p>Temps de session restant : {sessionTimer}s</p>
                <button on:click={handleLeaveQueue}>Terminer la session</button>
            </div>
        {/if}
    </div>
</div>

<style>
    /* Les styles sont gérés par Tailwind CSS */
</style> 