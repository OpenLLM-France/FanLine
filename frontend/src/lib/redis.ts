import { createClient } from 'redis';
import type { RedisClientType } from 'redis';

// Créer un client Redis avec les paramètres de connexion
const redisClient = createClient({
    url: process.env.REDIS_URL || 'redis://localhost:6379',
    database: Number.parseInt(process.env.REDIS_DB || '0')
});

// Connexion à Redis
redisClient.connect().catch((error: Error) => console.error('Redis Connection Error:', error));

// Gérer les erreurs de connexion
redisClient.on('error', (error: Error) => console.error('Redis Client Error:', error));

// Wrapper pour les méthodes Redis
const wrappedClient = {
    async SREM(key: string, member: string): Promise<number> {
        return redisClient.SREM(key, member);
    },

    async SADD(key: string, member: string): Promise<number> {
        return redisClient.SADD(key, member);
    },

    async LREM(key: string, count: number, element: string): Promise<number> {
        return redisClient.LREM(key, count, element);
    },

    async RPUSH(key: string, element: string): Promise<number> {
        return redisClient.RPUSH(key, element);
    },

    async LPOS(key: string, element: string): Promise<number | null> {
        return redisClient.LPOS(key, element);
    },

    async EXISTS(key: string): Promise<number> {
        return redisClient.EXISTS(key);
    },

    async SETEX(key: string, seconds: number, value: string): Promise<string | null> {
        return redisClient.SETEX(key, seconds, value);
    },

    async DEL(key: string): Promise<number> {
        return redisClient.DEL(key);
    }
};

export { wrappedClient as redisClient }; 