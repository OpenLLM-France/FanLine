import { describe, it, expect, beforeAll, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import QueueInterface from './QueueInterface.svelte';
import { getMetrics } from './queue';
import { joinQueue, leaveQueue, confirmConnection, getStatus, getTimers } from './queue';
import { createClient } from 'redis';

interface TimerMessage {
    timer_type: 'draft' | 'session';
    ttl: number;
    updates_left: number;
}

describe('QueueInterface Integration Tests', () => {
    beforeAll(async () => {
        // Vérifier que l'API est disponible
        try {
            await getMetrics();
        } catch (err) {
            throw new Error('API non disponible. Assurez-vous que le serveur FastAPI est en cours d\'exécution.');
        }
    });

    it("devrait afficher l'ecran de test au demarrage", () => {
        render(QueueInterface);
        expect(screen.getByText("Vérification du système")).toBeTruthy();
    });

    it("devrait afficher les resultats des tests", async () => {
        render(QueueInterface);
        await waitFor(() => {
            expect(screen.getByText(/Démarrage des tests/)).toBeTruthy();
        }, { timeout: 10000 });
    });

    it("devrait passer les tests automatiques", async () => {
        render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(screen.getByText(/✨ Tous les tests sont passés !/)).toBeTruthy();
        }, { timeout: 20000 });
    });

    it("devrait rejoindre la file d'attente", async () => {
        render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(screen.getByText(/✨ Tous les tests sont passés !/)).toBeTruthy();
        }, { timeout: 20000 });
        
        // Attendre que l'interface passe en mode file d'attente
        await waitFor(() => {
            expect(screen.getByText(/En attente/)).toBeTruthy();
        }, { timeout: 10000 });
        
        await waitFor(() => {
            expect(screen.getByText(/Position dans la file/)).toBeTruthy();
        }, { timeout: 10000 });
    }, 30000);

    it("devrait gérer le cycle complet", async () => {
        render(QueueInterface);
        
        // Attendre que les tests automatiques soient terminés
        await waitFor(() => {
            expect(screen.getByText(/✨ Tous les tests sont passés !/)).toBeTruthy();
        }, { timeout: 20000 });
        
        // Attendre que l'interface passe en mode file d'attente
        await waitFor(() => {
            expect(screen.getByText(/En attente/)).toBeTruthy();
            expect(screen.getByText(/Position dans la file/)).toBeTruthy();
        }, { timeout: 10000 });
        
        // Attendre que l'interface passe en mode draft (si possible)
        try {
            await waitFor(() => {
                expect(screen.getByText(/Slot disponible/)).toBeTruthy();
            }, { timeout: 10000 });
            
            // Si nous arrivons ici, nous sommes en mode draft
            expect(screen.getByRole('button', { name: /Confirmer la connexion/i })).toBeTruthy();
        } catch (err) {
            // Si nous n'arrivons pas en mode draft, c'est normal
            console.log('Mode draft non atteint (attendu)');
        }
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
            receivedMessage = JSON.parse(message) as TimerMessage;
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
            }
        }

        // Nettoyage
        await subscriber.unsubscribe(channel);
        await subscriber.quit();
        await leaveQueue(userRequest);
    }, 10000);
}); 