import type { UserRequest } from './types.ts';

// Types de réponse de l'API
interface QueueStatus {
    status: 'waiting' | 'draft' | 'connected';
    position?: number;
}

interface QueueMetrics {
    active_users: number;
    waiting_users: number;
    total_slots: number;
}

interface TimerInfo {
    ttl: number;
    channel: string;
    timer_type: 'session' | 'draft';
}

// Base API URL
const API_URL = 'http://localhost:8000';

// Fonction utilitaire pour gérer les erreurs de fetch
const handleFetchError = (error: unknown) => {
    if (error instanceof TypeError && error.message === 'Failed to fetch') {
        throw new Error('Le serveur n\'est pas disponible');
    }
    throw error;
};

// Join Queue
export const joinQueue = async (userRequest: UserRequest): Promise<{ position: number }> => {
    try {
        const response = await fetch(`${API_URL}/queue/join`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(userRequest),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail);
        }

        return await response.json();
    } catch (error) {
        handleFetchError(error);
        throw error; // Si ce n'est pas une erreur de fetch, on la propage
    }
};

// Leave Queue
export const leaveQueue = async (userRequest: UserRequest): Promise<{ success: boolean }> => {
    const response = await fetch(`${API_URL}/queue/leave`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(userRequest),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};

// Confirm Connection
export const confirmConnection = async (userRequest: UserRequest): Promise<{ session_duration: number }> => {
    const response = await fetch(`${API_URL}/queue/confirm`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(userRequest),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};

// Get Status
export const getStatus = async (userId: string): Promise<QueueStatus> => {
    const response = await fetch(`${API_URL}/queue/status/${userId}`, {
        method: 'GET',
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};

// Heartbeat
export const heartbeat = async (userRequest: UserRequest): Promise<{ success: boolean }> => {
    const response = await fetch(`${API_URL}/queue/heartbeat`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(userRequest),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};

// Get Metrics
export const getMetrics = async (): Promise<QueueMetrics> => {
    const response = await fetch(`${API_URL}/queue/metrics`, {
        method: 'GET',
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};

// Get Timers
export const getTimers = async (userId: string): Promise<TimerInfo> => {
    const response = await fetch(`${API_URL}/queue/timers/${userId}`, {
        method: 'GET',
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};
