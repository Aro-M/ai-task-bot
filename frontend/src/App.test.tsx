import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { Task } from './types';

class FakeStream extends EventTarget {
  static streams: FakeStream[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(
    public url: string,
    public options?: EventSourceInit,
  ) {
    super();
    FakeStream.streams.push(this);
  }
  emit(name: string) {
    this.dispatchEvent(new Event(name));
  }
}
const user = {
  id: 'user-1',
  first_name: 'Anna',
  username: 'anna',
  telegram_user_id: '42',
};
const initial: Task = {
  id: 'task-1',
  title: 'Prepare the launch',
  description: 'Review the final details',
  status: 'PENDING',
  source: 'TELEGRAM_VOICE',
  priority: 'HIGH',
  due_date: '2020-01-03T12:30:00Z',
  created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-20T10:00:00Z',
  completed_at: null,
};
let tasks: Task[];
let loggedIn: boolean;
let failTasks: boolean;
let fetcher: ReturnType<typeof vi.fn>;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

beforeEach(() => {
  tasks = [{ ...initial }];
  loggedIn = true;
  failTasks = false;
  FakeStream.streams = [];
  vi.stubGlobal('EventSource', FakeStream);
  fetcher = vi.fn(async (path: string, init: RequestInit = {}) => {
    const url = new URL(path, 'http://localhost');
    if (url.pathname === '/api/auth/me' && init.method === 'DELETE') {
      loggedIn = false;
      return new Response(null, { status: 204 });
    }
    if (url.pathname === '/api/auth/me')
      return loggedIn ? json(user) : json({ detail: 'Session expired' }, 401);
    if (url.pathname === '/api/auth/login') {
      const body = JSON.parse(init.body as string) as { code: string };
      if (body.code !== '12345678')
        return json({ detail: 'Code is invalid or expired' }, 401);
      loggedIn = true;
      return json({ ok: true });
    }
    if (url.pathname === '/api/auth/logout') {
      loggedIn = false;
      return new Response(null, { status: 204 });
    }
    if (!loggedIn) return json({ detail: 'Session expired' }, 401);
    if (url.pathname === '/api/tasks' && init.method === 'POST') {
      tasks.unshift({
        ...initial,
        ...JSON.parse(init.body as string),
        id: 'new-task',
        source: 'DASHBOARD',
      });
      return json(tasks[0], 201);
    }
    if (url.pathname.startsWith('/api/tasks/')) {
      const id = url.pathname.split('/').pop();
      if (init.method === 'DELETE') {
        tasks = tasks.filter((task) => task.id !== id);
        return new Response(null, { status: 204 });
      }
      tasks = tasks.map((task) =>
        task.id === id ? { ...task, ...JSON.parse(init.body as string) } : task,
      );
      return json(tasks.find((task) => task.id === id));
    }
    if (url.pathname === '/api/tasks') {
      if (failTasks)
        return json({ detail: 'Service temporarily unavailable' }, 503);
      let filtered = tasks;
      const status = url.searchParams.get('status'),
        search = url.searchParams.get('search');
      if (status) filtered = filtered.filter((task) => task.status === status);
      if (search)
        filtered = filtered.filter((task) => task.title.includes(search));
      const page = Number(url.searchParams.get('page') || 1);
      return json({
        items: filtered.slice((page - 1) * 20, page * 20),
        total: filtered.length,
        page,
        page_size: 20,
      });
    }
    return json({ detail: 'Not found' }, 404);
  });
  vi.stubGlobal('fetch', fetcher);
});

async function dashboard() {
  render(<App />);
  await screen.findByRole('heading', { name: 'My tasks.' });
  await screen.findByRole('article', { name: initial.title });
}

describe('authentication', () => {
  it('signs in with a one-time code, displays failures and signs out', async () => {
    loggedIn = false;
    const actor = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Welcome to Taskroom.' });
    expect(screen.getByText('/login')).toBeVisible();
    await actor.type(screen.getByLabelText('One-time code'), '87654321');
    await actor.click(screen.getByRole('button', { name: 'Open my taskroom' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Code is invalid or expired',
    );
    await actor.clear(screen.getByLabelText('One-time code'));
    await actor.type(screen.getByLabelText('One-time code'), '12345678');
    await actor.click(screen.getByRole('button', { name: 'Open my taskroom' }));
    await screen.findByRole('heading', { name: 'My tasks.' });
    await actor.click(screen.getByLabelText('Account options'));
    await actor.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(
      await screen.findByRole('heading', { name: 'Welcome to Taskroom.' }),
    ).toBeVisible();
    expect(FakeStream.streams.at(-1)?.close).toHaveBeenCalled();
  });
  it('does not mistake a session service outage for a signed-out account', async () => {
    fetcher.mockResolvedValueOnce(json({ detail: 'Service unavailable' }, 503));
    render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Service unavailable',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByRole('heading', { name: 'My tasks.' });
  });
});

describe('task management', () => {
  it('creates and edits task fields and renders untrusted titles as text', async () => {
    const actor = userEvent.setup();
    await dashboard();
    expect(screen.getByText('Telegram voice')).toBeVisible();
    expect(screen.getByText(/^Created /)).toHaveAttribute(
      'datetime',
      initial.created_at,
    );
    expect(screen.getByText('Overdue')).toBeVisible();
    await actor.click(screen.getByRole('button', { name: 'New task' }));
    const dialog = screen.getByRole('dialog');
    await actor.type(
      within(dialog).getByLabelText('Task title'),
      '<script>alert(1)</script>',
    );
    await actor.type(
      within(dialog).getByLabelText(/Description/),
      'Get the documents ready',
    );
    await actor.selectOptions(
      within(dialog).getByLabelText('Priority'),
      'MEDIUM',
    );
    fireEvent.change(within(dialog).getByLabelText(/Due date/), {
      target: { value: '2026-11-01T09:30' },
    });
    await actor.click(
      within(dialog).getByRole('button', { name: 'Create task' }),
    );
    expect(
      await screen.findByRole('article', { name: '<script>alert(1)</script>' }),
    ).toBeVisible();
    expect(document.querySelector('script:not([type="module"])')).toBeNull();
    expect(tasks[0]).toMatchObject({
      priority: 'MEDIUM',
      description: 'Get the documents ready',
    });
    expect(new Date(tasks[0].due_date!).getTime()).toBe(
      new Date('2026-11-01T09:30').getTime(),
    );
    await actor.click(
      screen.getByRole('button', { name: 'Edit Prepare the launch' }),
    );
    await actor.clear(screen.getByLabelText('Task title'));
    await actor.type(screen.getByLabelText('Task title'), 'Launch carefully');
    await actor.selectOptions(screen.getByLabelText('Priority'), 'LOW');
    await actor.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(
      await screen.findByRole('article', { name: 'Launch carefully' }),
    ).toBeVisible();
    expect(tasks.find((task) => task.id === 'task-1')?.priority).toBe('LOW');
  });
  it('moves tasks through statuses, reopens and confirms or cancels deletion', async () => {
    const actor = userEvent.setup();
    await dashboard();
    await actor.selectOptions(
      screen.getByLabelText('Status for Prepare the launch'),
      'IN_PROGRESS',
    );
    await waitFor(() => expect(tasks[0].status).toBe('IN_PROGRESS'));
    await actor.click(
      screen.getByRole('button', { name: 'Complete Prepare the launch' }),
    );
    await screen.findByRole('button', { name: 'Reopen Prepare the launch' });
    await actor.click(
      screen.getByRole('button', { name: 'Reopen Prepare the launch' }),
    );
    await screen.findByRole('button', { name: 'Complete Prepare the launch' });
    await actor.click(
      screen.getByRole('button', { name: 'Delete Prepare the launch' }),
    );
    await actor.click(screen.getByRole('button', { name: 'Keep task' }));
    expect(tasks).toHaveLength(1);
    await actor.click(
      screen.getByRole('button', { name: 'Delete Prepare the launch' }),
    );
    await actor.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Delete task',
      }),
    );
    expect(
      await screen.findByRole('heading', {
        name: 'Make room for your next idea.',
      }),
    ).toBeVisible();
    expect(tasks).toHaveLength(0);
    await actor.click(
      screen.getByRole('button', { name: 'Create your first task' }),
    );
    await actor.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });
  it('filters, searches, clears empty results and switches board/list without losing tasks', async () => {
    const actor = userEvent.setup();
    await dashboard();
    await actor.click(screen.getByRole('button', { name: 'Board' }));
    expect(screen.getByRole('region', { name: 'To do' })).toBeVisible();
    expect(
      screen.getAllByText('A little breathing room.', { selector: 'p' })[0],
    ).toBeVisible();
    await actor.click(screen.getByRole('button', { name: 'Completed' }));
    await screen.findByRole('heading', { name: 'Nothing here just yet.' });
    await actor.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByRole('article', { name: initial.title });
    await actor.type(screen.getByLabelText('Search tasks'), 'zzzz');
    await screen.findByRole('heading', { name: 'Nothing here just yet.' });
    await actor.click(screen.getByRole('button', { name: 'Clear filters' }));
    await screen.findByRole('article', { name: initial.title });
    await actor.click(screen.getByRole('button', { name: 'List' }));
    expect(screen.queryByRole('region', { name: 'To do' })).toBeNull();
    await actor.click(screen.getByRole('button', { name: 'All tasks' }));
    expect(screen.getByRole('article', { name: initial.title })).toBeVisible();
  });
  it('paginates across all tasks and moves back after deleting the last item on a page', async () => {
    tasks = Array.from({ length: 21 }, (_, index) => ({
      ...initial,
      id: String(index),
      title: `Task ${index}`,
    }));
    const actor = userEvent.setup();
    render(<App />);
    await screen.findByRole('article', { name: 'Task 0' });
    await actor.click(screen.getByRole('button', { name: 'Next page' }));
    await screen.findByRole('article', { name: 'Task 20' });
    expect(screen.queryByRole('article', { name: 'Task 0' })).toBeNull();
    await actor.click(screen.getByRole('button', { name: 'Previous page' }));
    await screen.findByRole('article', { name: 'Task 0' });
    await actor.click(screen.getByRole('button', { name: 'Next page' }));
    await screen.findByRole('article', { name: 'Task 20' });
    await actor.click(screen.getByRole('button', { name: 'Delete Task 20' }));
    await actor.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Delete task',
      }),
    );
    await screen.findByRole('article', { name: 'Task 0' });
    expect(screen.getByText('Page 1')).toBeVisible();
  });
  it('keeps an unsuccessful save open and allows recovery from list failures', async () => {
    const actor = userEvent.setup();
    await dashboard();
    await actor.click(
      screen.getByRole('button', { name: 'Edit Prepare the launch' }),
    );
    fetcher.mockResolvedValueOnce(
      json({ detail: 'Could not save. Try again.' }, 503),
    );
    await actor.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not save',
    );
    expect(screen.getByRole('dialog')).toBeVisible();
    await actor.click(screen.getByRole('button', { name: 'Close dialog' }));
    failTasks = true;
    act(() => FakeStream.streams.at(-1)!.emit('task.created'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Service temporarily unavailable',
    );
    failTasks = false;
    await actor.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
  it('allows account deletion only after explicit confirmation', async () => {
    const actor = userEvent.setup();
    await dashboard();
    await actor.click(screen.getByLabelText('Account options'));
    await actor.click(screen.getByRole('button', { name: 'Delete account' }));
    expect(screen.getByRole('dialog')).toHaveTextContent(
      'This cannot be undone',
    );
    await actor.click(screen.getByRole('button', { name: 'Keep account' }));
    expect(loggedIn).toBe(true);
    await actor.click(screen.getByRole('button', { name: 'Delete account' }));
    await actor.click(
      screen.getByRole('button', { name: 'Delete account permanently' }),
    );
    await screen.findByRole('heading', { name: 'Welcome to Taskroom.' });
    expect(loggedIn).toBe(false);
  });
});

describe('real-time state', () => {
  it('refetches on ready, task events and reconnect while showing accurate connection state', async () => {
    await dashboard();
    const stream = FakeStream.streams.at(-1)!;
    expect(stream.options).toEqual({ withCredentials: true });
    expect(screen.getByText('Connecting…')).toBeVisible();
    tasks.push({
      ...initial,
      id: 'telegram-text',
      title: 'A new Telegram idea',
      source: 'TELEGRAM_TEXT',
    });
    act(() => stream.emit('ready'));
    expect(
      await screen.findByRole('article', { name: 'A new Telegram idea' }),
    ).toBeVisible();
    expect(screen.getByText('Live updates on')).toBeVisible();
    act(() => stream.onerror?.());
    expect(screen.getByText('Reconnecting…')).toBeVisible();
    tasks = tasks.filter((task) => task.id !== 'telegram-text');
    act(() => stream.emit('ready'));
    await waitFor(() =>
      expect(
        screen.queryByRole('article', { name: 'A new Telegram idea' }),
      ).toBeNull(),
    );
    tasks[0].title = 'Updated remotely';
    act(() =>
      stream.onmessage?.(
        new MessageEvent('message', { data: '{"event":"task.updated"}' }),
      ),
    );
    expect(
      await screen.findByRole('article', { name: 'Updated remotely' }),
    ).toBeVisible();
    act(() =>
      stream.onmessage?.(new MessageEvent('message', { data: 'heartbeat' })),
    );
  });
  it('returns to login when a session expires during a reconnect', async () => {
    await dashboard();
    loggedIn = false;
    act(() => FakeStream.streams.at(-1)!.onerror?.());
    expect(
      await screen.findByRole('heading', { name: 'Welcome to Taskroom.' }),
    ).toBeVisible();
  });
  it('returns to login when a mutation reports an expired session', async () => {
    await dashboard();
    loggedIn = false;
    await userEvent.click(
      screen.getByRole('button', { name: 'Complete Prepare the launch' }),
    );
    expect(
      await screen.findByRole('heading', { name: 'Welcome to Taskroom.' }),
    ).toBeVisible();
  });
});
