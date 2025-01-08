import { describe, it, expect, beforeAll } from 'vitest';
import { joinQueue, getStatus } from './queue';
import type { UserRequest } from './types';
import fetch from 'node-fetch';

const API_URL = 'http://localhost:8000';
const MAX_RETRIES = 10;
const RETRY_DELAY = 2000;  // 2 secondes
const HOOK_TIMEOUT = 30000;  // 30 secondes

async function wait(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function checkServerWithRetry(retries = MAX_RETRIES): Promise<boolean> {
    try {
        const response = await fetch(`${API_URL}/queue/metrics`);
        console.log('Response status:', response.status);
        return response.ok;
    } catch (error) {
        console.error('Erreur de connexion:', error);
        if (retries > 0) {
            console.log(`Tentative échouée, reste ${retries} essais...`);
            await wait(RETRY_DELAY);
            return checkServerWithRetry(retries - 1);
        }
        return false;
    }
}

// Ces tests nécessitent que le serveur soit en marche sur http://localhost:8000
describe('API Integration Tests', () => {
    // Skip les tests si nous ne sommes pas en mode intégration
    const runIntegrationTests = process.env.RUN_INTEGRATION_TESTS === 'true';
    
    (runIntegrationTests ? describe : describe.skip)('Queue API', () => {
        const userRequest: UserRequest = { 
            user_id: `test-${Date.now()}` // Utiliser un ID unique pour chaque test
        };

        beforeAll(async () => {
            // Vérifier si le serveur est disponible avec retry
            const isServerAvailable = await checkServerWithRetry();
            if (!isServerAvailable) {
                console.error(`❌ Le serveur n'est pas disponible sur ${API_URL} après ${MAX_RETRIES} tentatives`);
                console.error('Assurez-vous que le serveur est en marche avant de lancer les tests d\'intégration');
                throw new Error('Le serveur n\'est pas disponible');
            }
        }, HOOK_TIMEOUT);

        it('should complete a full queue cycle', async () => {
            // Rejoindre la file d'attente
            const joinResult = await joinQueue(userRequest);
            expect(joinResult).toHaveProperty('position');
            expect(typeof joinResult.position).toBe('number');

            // Vérifier le statut
            const status = await getStatus(userRequest.user_id);
            expect(status).toHaveProperty('status');
            // L'utilisateur peut être en attente ou en draft selon la disponibilité des slots
            expect(['waiting', 'draft']).toContain(status.status);
            // La position n'est présente que si le statut est 'waiting'
            if (status.status === 'waiting') {
                expect(status).toHaveProperty('position');
            }
        });
    });
}); 