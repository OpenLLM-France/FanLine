import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import QueueInterface from './QueueInterface.svelte';
import { getMetrics } from './queue';
import { joinQueue, leaveQueue, confirmConnection, getStatus, getTimers } from './queue';
import { createClient } from 'redis';

interface TimerMessage {
    timer_type: 'draft' | 'session';
    ttl: number;
    updates_left: number;
    task_id: string | null;
}

describe('QueueInterface Integration Tests', () => {
    beforeAll(async () => {
        // Vérifier que l'API est disponible
        try {
            await getMetrics();
        } catch (err) {
            throw new Error('API non disponible. Assurez-vous que le serveur FastAPI est en cours d\'exécution.');
        }

        // Configuration de l'environnement de test
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: vi.fn().mockImplementation((query: string) => ({
                matches: false,
                media: query,
                onchange: null,
                addListener: vi.fn(),
                removeListener: vi.fn(),
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                dispatchEvent: vi.fn(),
            })),
        });
    });

    it("devrait afficher l'ecran de test au demarrage", () => {
        const { container } = render(QueueInterface);
        expect(container.textContent).toContain("Test des endpoints");
    });

    it("devrait afficher les resultats des tests", async () => {
        const { container } = render(QueueInterface);
        await waitFor(() => {
            expect(container.textContent).toContain("Test de Heartbeat...");
            expect(container.textContent).toContain("✅ Heartbeat OK");
        }, { timeout: 10000 });
    });

    it("devrait passer les tests automatiques", async () => {
        const { container } = render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(container.textContent).toContain("✨ Heartbeat OK");
            expect(container.textContent).toContain("✅ Metrics OK");
            expect(container.textContent).toContain("✅ Status OK");
            expect(container.textContent).toContain("✅ Join Queue OK");
            expect(container.textContent).toContain("✅ Leave Queue OK");
        }, { timeout: 20000 });
    });

    it("devrait rejoindre la file d'attente", async () => {
        const { container } = render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(container.textContent).toContain("✨ Heartbeat OK");
            expect(container.textContent).toContain("✅ Metrics OK");
            expect(container.textContent).toContain("✅ Status OK");
            expect(container.textContent).toContain("✅ Join Queue OK");
            expect(container.textContent).toContain("✅ Leave Queue OK");
        }, { timeout: 20000 });
        
        // Attendre que l'interface passe en mode file d'attente
        await waitFor(() => {
            expect(container.textContent).toContain("Rejoindre la file");
        }, { timeout: 10000 });
    }, 30000);

    it("devrait gérer le cycle complet", async () => {
        const { container } = render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(container.textContent).toContain("✨ Heartbeat OK");
            expect(container.textContent).toContain("✅ Metrics OK");
            expect(container.textContent).toContain("✅ Status OK");
            expect(container.textContent).toContain("✅ Join Queue OK");
            expect(container.textContent).toContain("✅ Leave Queue OK");
        }, { timeout: 20000 });
        
        // Attendre que l'interface passe en mode file d'attente
        await waitFor(() => {
            expect(container.textContent).toContain("Rejoindre la file");
        }, { timeout: 10000 });
    }, 40000);

    it('should receive timer updates from Redis', async () => {
        const userId = `test-user-${Math.random().toString(36).substring(2, 9)}`;
        const userRequest = { user_id: userId };
        
        // Rejoindre la file d'attente
        await joinQueue(userRequest);
        
        // Créer un client Redis pour écouter les messages
        const subscriber = createClient();
        await subscriber.connect();
        
        let receivedMessage: TimerMessage | null = null;
        const channel = `timer:channel:${userId}`;
        await subscriber.subscribe(channel, (message: string) => {
            const parsed = JSON.parse(message);
            if (
                typeof parsed === 'object' &&
                parsed !== null &&
                'timer_type' in parsed &&
                'ttl' in parsed &&
                'updates_left' in parsed &&
                'task_id' in parsed
            ) {
                receivedMessage = parsed as TimerMessage;
            }
        });

        // Attendre que l'utilisateur soit en draft
        let status = null;
        for (let i = 0; i < 10; i++) {
            status = await getStatus(userId);
            if (status.status === 'draft') break;
            await new Promise(resolve => setTimeout(resolve, 500));
        }

        // Récupérer les timers pour déclencher les mises à jour
        if (status?.status === 'draft') {
            const timers = await getTimers(userId);

            // Attendre que le message soit reçu
            await new Promise<void>((resolve) => {
                const checkMessage = setInterval(async () => {
                    if (receivedMessage) {
                        clearInterval(checkMessage);
                        resolve();
                    }
                }, 100);

                // Timeout après 5 secondes
                setTimeout(() => {
                    clearInterval(checkMessage);
                    resolve();
                }, 5000);
            });

            // Vérifier le message reçu
            expect(receivedMessage).not.toBeNull();
            if (receivedMessage) {
                expect(receivedMessage.timer_type).toBe('draft');
                expect(receivedMessage.ttl).toBeGreaterThan(0);
                expect(receivedMessage.updates_left).toBeDefined();
                expect(receivedMessage.task_id).toBeDefined();
            }
        }

        // Nettoyage
        await subscriber.unsubscribe(channel);
        await subscriber.quit();
        await leaveQueue(userRequest);
    }, 10000);
}); 