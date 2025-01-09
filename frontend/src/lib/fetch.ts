// Fonction pour détecter l'environnement d'exécution
const isBrowser = typeof window !== 'undefined' && typeof window.fetch === 'function';

// Type pour les options de fetch qui fonctionne dans les deux environnements
type UniversalRequestInit = RequestInit & {
    body?: string | URLSearchParams | Blob | BufferSource | FormData | null;
};

// Fonction fetch personnalisée qui s'adapte à l'environnement
const customFetch = async (url: string, options?: UniversalRequestInit): Promise<Response> => {
    if (isBrowser) {
        return window.fetch(url, options);
    }
    
    const nodeFetch = (await import('node-fetch')).default;
    return nodeFetch(url, options as any) as unknown as Response;
};

export default customFetch; 