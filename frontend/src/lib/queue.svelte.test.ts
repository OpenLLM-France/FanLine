import { describe, it, expect, vi } from 'vitest';
import { joinQueue, leaveQueue, confirmConnection, getStatus, heartbeat, getMetrics, getTimers } from './queue';
import type { UserRequest } from './types';

describe('API functions', () => {
	const userRequest: UserRequest = { user_id: '12345' };
	const API_URL = 'http://localhost:8000';

	beforeEach(() => {
		vi.resetAllMocks();
	});

	it('should handle network errors', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockRejectedValue(new Error('Failed to fetch'));

		await expect(joinQueue(userRequest)).rejects.toThrow('Failed to fetch');
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/join`,
			expect.any(Object)
		);
	});

	it('should join the queue and return position', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ position: 1 }),
		} as Response);

		const result = await joinQueue(userRequest);
		
		expect(fetchSpy).toHaveBeenCalledWith(
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
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Already in queue or active' }),
		} as Response);

		await expect(joinQueue(userRequest)).rejects.toThrow('Already in queue or active');
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/join`,
			expect.any(Object)
		);
	});

	it('should leave the queue and return success', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await leaveQueue(userRequest);
		
		expect(fetchSpy).toHaveBeenCalledWith(
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
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Not in queue' }),
		} as Response);

		await expect(leaveQueue(userRequest)).rejects.toThrow('Not in queue');
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/leave`,
			expect.any(Object)
		);
	});

	it('should confirm connection and return session duration', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ session_duration: 300 }),
		} as Response);

		const result = await confirmConnection(userRequest);
		
		expect(fetchSpy).toHaveBeenCalledWith(
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
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ status: 'waiting', position: 2 }),
		} as Response);

		const result = await getStatus('12345');
		
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/status/12345`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({ status: 'waiting', position: 2 });
	});

	it('should throw error when getting status fails', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'User not found' }),
		} as Response);

		await expect(getStatus('12345')).rejects.toThrow('User not found');
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/status/12345`,
			expect.any(Object)
		);
	});

	it('should send heartbeat and return success', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await heartbeat(userRequest);
		
		expect(fetchSpy).toHaveBeenCalledWith(
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
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ active_users: 10, queue_length: 5 }),
		} as Response);

		const result = await getMetrics();
		
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/metrics`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({ active_users: 10, queue_length: 5 });
	});

	it('should get user timers', async () => {
		const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ timer: 120 }),
		} as Response);

		const result = await getTimers('12345');
		
		expect(fetchSpy).toHaveBeenCalledWith(
			`${API_URL}/queue/timers/12345`,
			expect.objectContaining({ method: 'GET' })
		);
		expect(result).toEqual({ timer: 120 });
	});
});
