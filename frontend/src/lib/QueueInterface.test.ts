import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import QueueInterface from './QueueInterface.svelte';
import { getMetrics } from './queue';

describe('QueueInterface Tests', () => {
    beforeAll(async () => {
        // Vérifier que l'API est disponible
        try {
            await getMetrics();
        } catch (err) {
            console.warn('API non disponible. Les tests peuvent échouer.');
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

    it("devrait passer les tests automatiques et rejoindre la file", async () => {
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
    }, 30000);
}); 