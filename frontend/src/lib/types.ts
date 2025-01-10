export interface UserRequest {
    user_id: string;
}

// Types pour les réponses de l'API
export interface QueueStatus {
    status: 'waiting' | 'draft' | 'connected' | 'disconnected';
    position?: number;
    remaining_time?: number;
    estimated_wait_time?: number;
}

export interface QueueMetrics {
    active_users: number;
    waiting_users: number;
    total_slots: number;
    average_wait_time: number;
    average_session_time: number;
}

export interface TimerInfo {
    timer_type: 'draft' | 'session';
    ttl: number;
    total_duration: number;
    channel?: string;
}

export interface ApiResponse {
    success: boolean;
    position?: number;
    detail?: string;
}

// Type pour le mock de fetch
export interface MockFetch {
    ok: boolean;
    json: () => Promise<QueueStatus | QueueMetrics | TimerInfo | ApiResponse>;
    status?: number;
    statusText?: string;
}
