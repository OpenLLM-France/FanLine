import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import QueueInterface from './QueueInterface.svelte';
import { getMetrics, joinQueue, getStatus, leaveQueue, heartbeat, getTimers, confirmConnection } from './queue';

// Mock des fonctions de l'API
vi.mock('./queue', () => ({
    getMetrics: vi.fn().mockResolvedValue({
        active_users: 5,
        waiting_users: 10,
        total_slots: 20,
        average_wait_time: 300,
        average_session_time: 600
    }),
    joinQueue: vi.fn().mockResolvedValue({
        last_status: null,
        last_position: null,
        commit_status: 'waiting',
        commit_position: 1
    }),
    getStatus: vi.fn().mockResolvedValue({
        status: 'waiting',
        position: 1,
        remaining_time: 300,
        estimated_wait_time: 600,
        timestamp: '2025-01-10 09:04:30'
    }),
    leaveQueue: vi.fn().mockResolvedValue({
        success: true
    }),
    heartbeat: vi.fn().mockResolvedValue({
        success: true
    }),
    getTimers: vi.fn().mockResolvedValue({
        timer_type: 'draft',
        ttl: 300,
        total_duration: 300,
        channel: 'timer:channel:test-user-123'
    }),
    confirmConnection: vi.fn().mockResolvedValue({
        session_duration: 300,
        total_duration: 600
    })
}));

describe('QueueInterface Tests', () => {
    beforeAll(() => {
        // Configuration de l'environnement de test
        Object.defineProperty(window, 'matchMedia', {
            writable: true,
            value: vi.fn().mockImplementation(query => ({
                matches: false,
                media: query,
                onchange: null,
                addListener: vi.fn(),
                removeListener: vi.fn(),
                addEventListener: vi.fn(),
                removeEventListener: vi.fn(),
                dispatchEvent: vi.fn(),
            }))
        });
    });

    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it('devrait afficher l\'ecran de test au demarrage', async () => {
        const { getByTestId } = render(QueueInterface);
        await waitFor(() => {
            const testScreen = getByTestId('test-screen');
            expect(testScreen).toBeTruthy();
            expect(testScreen.querySelector('h2')?.textContent).toBe('Test des endpoints');
        }, { timeout: 5000 });
    });

    it('devrait afficher les resultats des tests', async () => {
        const { getByTestId, findAllByTestId } = render(QueueInterface);
        await waitFor(async () => {
            const testProgress = getByTestId('test-progress');
            const messages = await findAllByTestId('test-message');
            expect(messages.length).toBeGreaterThan(0);
            expect(messages[0].textContent).toContain('Test de Heartbeat');
        }, { timeout: 5000 });
    });

    it('devrait passer les tests automatiques et rejoindre la file', async () => {
        const { getByTestId, findByTestId } = render(QueueInterface);
        await waitFor(async () => {
            const queueScreen = await findByTestId('queue-screen');
            expect(queueScreen).toBeTruthy();
            const button = queueScreen.querySelector('button');
            expect(button?.textContent).toBe('Rejoindre la file');
        }, { timeout: 5000 });
    });
}); 