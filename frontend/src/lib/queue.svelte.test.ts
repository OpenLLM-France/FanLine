import { describe, it, expect, vi } from 'vitest';
import { joinQueue, leaveQueue, confirmConnection, getStatus, heartbeat, getMetrics, getTimers } from './queue';
import type { UserRequest } from './types';

describe('API functions', () => {
	const userRequest: UserRequest = { user_id: '12345' };
	const API_URL = 'http://localhost:6379';

	it('should join the queue and return position', async () => {
		// vi.spyOn(global, 'fetch').mockResolvedValue({
		// 	ok: true,
		// 	json: async () => ({ position: 1 }),
		// } as Response);

		const result = await joinQueue(userRequest);
		expect(result).toEqual({ position: 1 });
	});

	it('should throw error when joining queue fails', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Already in queue or active' }),
		} as Response);

		await expect(joinQueue(userRequest)).rejects.toThrow('Already in queue or active');
	});

	it('should leave the queue and return success', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await leaveQueue(userRequest);
		expect(result).toEqual({ success: true });
	});

	it('should throw error when leaving queue fails', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'Not in queue' }),
		} as Response);

		await expect(leaveQueue(userRequest)).rejects.toThrow('Not in queue');
	});

	it('should confirm connection and return session duration', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ session_duration: 300 }),
		} as Response);

		const result = await confirmConnection(userRequest);
		expect(result).toEqual({ session_duration: 300 });
	});

	it('should get user status', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ status: 'waiting', position: 2 }),
		} as Response);

		const result = await getStatus('12345');
		expect(result).toEqual({ status: 'waiting', position: 2 });
	});

	it('should throw error when getting status fails', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: false,
			json: async () => ({ detail: 'User not found' }),
		} as Response);

		await expect(getStatus('12345')).rejects.toThrow('User not found');
	});

	it('should send heartbeat and return success', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ success: true }),
		} as Response);

		const result = await heartbeat(userRequest);
		expect(result).toEqual({ success: true });
	});

	it('should get queue metrics', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ active_users: 10, queue_length: 5 }),
		} as Response);

		const result = await getMetrics();
		expect(result).toEqual({ active_users: 10, queue_length: 5 });
	});

	it('should get user timers', async () => {
		vi.spyOn(global, 'fetch').mockResolvedValue({
			ok: true,
			json: async () => ({ timer: 120 }),
		} as Response);

		const result = await getTimers('12345');
		expect(result).toEqual({ timer: 120 });
	});
});
