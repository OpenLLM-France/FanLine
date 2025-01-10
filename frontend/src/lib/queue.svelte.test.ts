import { describe, it, expect, vi } from 'vitest';
import { joinQueue, leaveQueue, confirmConnection, getStatus, heartbeat, getMetrics, getTimers } from './queue';
import type { UserRequest } from './types';
import type { Response } from 'node-fetch';

// Mock notre fetch personnalisé
vi.mock('./fetch', () => {
	return {
		default: vi.fn()
	};
});

// Import le mock après la configuration
import customFetch from './fetch';
const mockedFetch = customFetch as unknown as jest.Mock;

describe('API functions', () => {
	const userRequest: UserRequest = { user_id: '12345' };
	const API_URL = 'http://localhost:8000';

	beforeEach(() => {
		vi.resetAllMocks();
	});

	it('should handle network errors', async () => {
		mockedFetch.mockRejectedValue(new Error('Failed to fetch'));

		await expect(joinQueue(userRequest)).rejects.toThrow('Failed to fetch');
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/join`,
			expect.any(Object)
		);
	});

	it('should join the queue and return position', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({ position: 1 }),
		} as Response);

		const result = await joinQueue(userRequest);
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/join`,
			expect.objectContaining({
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(userRequest)
			})
		);
		expect(result).toEqual({ position: 1 });
	});

	it('should throw error when joining queue fails', async () => {
		mockedFetch.mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Already in queue or active' }),
		} as Response);

		await expect(joinQueue(userRequest)).rejects.toThrow('Already in queue or active');
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/join`,
			expect.any(Object)
		);
	});

	it('should leave the queue and return success', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await leaveQueue(userRequest);
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/leave`,
			expect.objectContaining({
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(userRequest)
			})
		);
		expect(result).toEqual({ success: true });
	});

	it('should throw error when leaving queue fails', async () => {
		mockedFetch.mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Not in queue' }),
		} as Response);

		await expect(leaveQueue(userRequest)).rejects.toThrow('Not in queue');
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/leave`,
			expect.any(Object)
		);
	});

	it('should confirm connection and return session duration', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({ session_duration: 300 }),
		} as Response);

		const result = await confirmConnection(userRequest);
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/confirm`,
			expect.objectContaining({
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(userRequest)
			})
		);
		expect(result).toEqual({ session_duration: 300 });
	});

	it('should get user status', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({
				status: 'waiting',
				position: 2,
				remaining_time: 300,
				estimated_wait_time: 600
			}),
		} as Response);

		const result = await getStatus('12345');
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/status/12345`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({
			status: 'waiting',
			position: 2,
			remaining_time: 300,
			estimated_wait_time: 600
		});
	});

	it('should throw error when getting status fails', async () => {
		mockedFetch.mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'User not found' }),
		} as Response);

		await expect(getStatus('12345')).rejects.toThrow('User not found');
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/status/12345`,
			expect.any(Object)
		);
	});

	it('should send heartbeat and return success', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await heartbeat(userRequest);
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/heartbeat`,
			expect.objectContaining({
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(userRequest)
			})
		);
		expect(result).toEqual({ success: true });
	});

	it('should get queue metrics', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({
				active_users: 10,
				waiting_users: 5,
				total_slots: 20,
				average_wait_time: 300,
				average_session_time: 600
			}),
		} as Response);

		const result = await getMetrics();
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/metrics`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({
			active_users: 10,
			waiting_users: 5,
			total_slots: 20,
			average_wait_time: 300,
			average_session_time: 600
		});
	});

	it('should get user timers', async () => {
		mockedFetch.mockResolvedValue({
			ok: true,
			json: async () => ({
				timer_type: 'session',
				ttl: 120,
				total_duration: 300
			}),
		} as Response);

		const result = await getTimers('12345');
		
		expect(mockedFetch).toHaveBeenCalledWith(
			`${API_URL}/queue/timers/12345`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({
			timer_type: 'session',
			ttl: 120,
			total_duration: 300
		});
	});
});
