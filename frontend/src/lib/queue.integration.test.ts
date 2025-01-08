import { describe, it, expect, beforeAll } from 'vitest';
import { joinQueue, getStatus } from './queue';
import type { UserRequest } from './types';

const API_URL = 'http://localhost:8000';

// Ces tests nécessitent que le serveur soit en marche sur http://localhost:8000
describe('API Integration Tests', () => {
    // Skip les tests si nous ne sommes pas en mode intégration
    const runIntegrationTests = process.env.RUN_INTEGRATION_TESTS === 'true';
    
    (runIntegrationTests ? describe : describe.skip)('Queue API', () => {
        const userRequest: UserRequest = { 
            user_id: `test-${Date.now()}` // Utiliser un ID unique pour chaque test
        };

        beforeAll(async () => {
            // Vérifier si le serveur est disponible
            try {
                const response = await fetch(`${API_URL}/queue/metrics`);
                if (!response.ok) {
                    throw new Error('Le serveur répond mais avec une erreur');
                }
            } catch (error) {
                console.error(`❌ Le serveur n'est pas disponible sur ${API_URL}`);
                console.error('Assurez-vous que le serveur est en marche avant de lancer les tests d\'intégration');
                throw new Error('Le serveur n\'est pas disponible');
            }
        });

        it('should complete a full queue cycle', async () => {
            // Rejoindre la file d'attente
            const joinResult = await joinQueue(userRequest);
            expect(joinResult).toHaveProperty('position');
            expect(typeof joinResult.position).toBe('number');

            // Vérifier le statut
            const status = await getStatus(userRequest.user_id);
            expect(status).toHaveProperty('status');
            expect(status.status).toBe('waiting');
            expect(status).toHaveProperty('position');
        });
    });
}); 