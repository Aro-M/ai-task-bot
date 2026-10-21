import { expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

it('uses cookie credentials and JSON headers only for request bodies', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ id: 'task' })));
  vi.stubGlobal('fetch', fetcher);
  await expect(
    api('/tasks', { method: 'POST', body: '{"title":"New"}' }),
  ).resolves.toEqual({ id: 'task' });
  expect(fetcher).toHaveBeenCalledWith(
    '/api/tasks',
    expect.objectContaining({
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
    }),
  );
  fetcher.mockResolvedValue(new Response(null, { status: 204 }));
  await expect(api('/tasks/1', { method: 'DELETE' })).resolves.toBeUndefined();
});
it('surfaces safe API details, malformed error bodies, and offline errors', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  fetcher.mockResolvedValue(
    new Response('{"detail":"Session expired"}', { status: 401 }),
  );
  await expect(api('/auth/me')).rejects.toMatchObject({
    message: 'Session expired',
    status: 401,
  });
  fetcher.mockResolvedValue(new Response('bad gateway', { status: 502 }));
  await expect(api('/tasks')).rejects.toThrow('Something went wrong (502)');
  fetcher.mockRejectedValue(new TypeError('Network disconnected'));
  await expect(api('/tasks')).rejects.toBeInstanceOf(ApiError);
  const abort = new DOMException('Cancelled', 'AbortError');
  fetcher.mockRejectedValue(abort);
  await expect(api('/tasks')).rejects.toBe(abort);
});

it('reads the structured error message without exposing error details', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      JSON.stringify({
        error: {
          code: 'TASK_NOT_FOUND',
          message: 'Task not found',
          details: { private: 'hidden' },
          request_id: 'fixture',
        },
      }),
      { status: 404 },
    ),
  );
  await expect(api('/tasks/missing')).rejects.toMatchObject({
    message: 'Task not found',
    status: 404,
  });
  fetchMock.mockRestore();
});
