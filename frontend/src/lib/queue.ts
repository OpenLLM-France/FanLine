import type { UserRequest } from './types';

// Base API URL
const API_URL = 'http://localhost:8000'; // Replace with your actual API URL

// Join Queue
export const joinQueue = async (userRequest: UserRequest): Promise<{ position: number }> => {
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
export const getStatus = async (userId: string): Promise<any> => {
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
export const getMetrics = async (): Promise<any> => {
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
export const getTimers = async (userId: string): Promise<any> => {
    const response = await fetch(`${API_URL}/queue/timers/${userId}`, {
        method: 'GET',
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
    }

    return await response.json();
};
