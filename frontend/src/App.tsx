import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from './api';
import { Dialog, TaskDialog } from './TaskDialog';
import {
  sourceLabels,
  statusLabels,
  statuses,
  type Status,
  type Task,
  type TaskInput,
  type TaskList,
  type User,
} from './types';

function Brand() {
  return (
    <a className="brand" href="/" aria-label="Taskroom home">
      <span className="brand-mark" aria-hidden="true">
        ✓
      </span>
      taskroom<span className="brand-dot">.</span>
    </a>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<User>('/auth/me', { signal: controller.signal })
      .then(setUser)
      .catch((err: unknown) => {
        if (
          !controller.signal.aborted &&
          !(err instanceof ApiError && err.status === 401)
        )
          setError(
            err instanceof Error
              ? err.message
              : 'Could not check your session.',
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setChecking(false);
      });
    return () => controller.abort();
  }, [attempt]);
  if (checking)
    return (
      <div className="initial-loading" role="status">
        <Brand />
        <span>Getting things ready…</span>
      </div>
    );
  if (error)
    return (
      <main className="initial-loading">
        <Brand />
        <p role="alert">{error}</p>
        <button
          className="primary"
          onClick={() => {
            setError('');
            setChecking(true);
            setAttempt(attempt + 1);
          }}
        >
          Try again
        </button>
      </main>
    );
  return user ? (
    <Dashboard user={user} onSignedOut={() => setUser(null)} />
  ) : (
    <Login onSignedIn={setUser} />
  );
}

function Login({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <main className="login-layout">
      <section className="login-story">
        <Brand />
        <div className="login-copy">
          <span className="eyebrow">LESS FRICTION. MORE DOING.</span>
          <h1>
            A thought.
            <br />A voice note.
            <br />
            <em>A little progress.</em>
          </h1>
          <p>
            Capture it in Telegram.
            <br />
            Make it happen in Taskroom.
          </p>
        </div>
        <span className="login-footer">
          A little room for everything you need to do.
        </span>
      </section>
      <section className="login-form">
        <div className="login-card">
          <span className="eyebrow">YOUR SPACE TO GET THINGS DONE</span>
          <h2>Welcome to Taskroom.</h2>
          <p>
            Sign in with your Telegram account. Your tasks will be right here.
          </p>
          <ol className="login-steps">
            <li>Open your Taskroom bot in Telegram.</li>
            <li>
              Send <code>/login</code> to receive a one-time code.
            </li>
            <li>Enter your 8-digit code below.</li>
          </ol>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              setError('');
              setBusy(true);
              const code = String(
                new FormData(event.currentTarget).get('code'),
              ).trim();
              try {
                await api('/auth/login', {
                  method: 'POST',
                  body: JSON.stringify({ code }),
                });
                onSignedIn(await api<User>('/auth/me'));
              } catch (err) {
                setError(
                  err instanceof Error ? err.message : 'Could not sign in.',
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              One-time code
              <input
                className="code-input"
                name="code"
                aria-describedby="code-hint"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{8}"
                minLength={8}
                maxLength={8}
                required
                placeholder="00000000"
                disabled={busy}
              />
            </label>
            <p className="field-hint" id="code-hint">
              Codes expire in 5 minutes and can only be used once.
            </p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <button className="primary full-width" disabled={busy}>
              {busy ? 'Signing in…' : 'Open my taskroom'}
              <span aria-hidden="true"> →</span>
            </button>
          </form>
          <p className="privacy-note">
            No passwords to remember. Your tasks stay private.
          </p>
        </div>
      </section>
    </main>
  );
}

function Dashboard({
  user,
  onSignedOut,
}: {
  user: User;
  onSignedOut: () => void;
}) {
  const [data, setData] = useState<TaskList>({
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filter, setFilter] = useState<Status | ''>('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [view, setView] = useState<'list' | 'board'>('list');
  const [connection, setConnection] = useState('Connecting');
  const [editing, setEditing] = useState<Task | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Task | 'account' | null>(null);
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const mounted = useRef(true);
  const fail = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        onSignedOut();
        return;
      }
      setError(
        err instanceof Error
          ? err.message
          : 'Something went wrong. Please try again.',
      );
    },
    [onSignedOut],
  );
  const reload = useCallback(() => setRefresh((value) => value + 1), []);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (search !== query) {
        setLoading(true);
        setQuery(search);
        setPage(1);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [search, query]);
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), page_size: '20' });
    if (filter) params.set('status', filter);
    if (query) params.set('search', query);
    api<TaskList>(`/tasks?${params}`, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        if (page > 1 && !result.items.length) {
          setPage((value) => value - 1);
          return;
        }
        setData(result);
        setError('');
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) fail(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [filter, query, page, refresh, fail]);
  useEffect(() => {
    mounted.current = true;
    const stream = new EventSource('/api/events', { withCredentials: true });
    const ready = () => {
      setConnection('Live');
      reload();
    };
    const update = () => reload();
    stream.addEventListener('ready', ready);
    for (const name of ['task.created', 'task.updated', 'task.deleted'])
      stream.addEventListener(name, update);
    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { event?: string };
        if (payload.event?.startsWith('task.')) reload();
      } catch {
        /* Ignore unrelated heartbeat data. */
      }
    };
    stream.onerror = () => {
      setConnection('Reconnecting');
      void api<User>('/auth/me').catch((err: unknown) => {
        if (mounted.current && err instanceof ApiError && err.status === 401)
          onSignedOut();
      });
    };
    return () => {
      mounted.current = false;
      stream.close();
    };
  }, [onSignedOut, reload]);
  async function save(input: TaskInput, id?: string) {
    try {
      await api(id ? `/tasks/${id}` : '/tasks', {
        method: id ? 'PATCH' : 'POST',
        body: JSON.stringify(input),
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onSignedOut();
      throw err;
    }
    setEditing(null);
    setNotice(id ? 'Changes saved.' : 'Task created. One step closer.');
    reload();
  }
  async function changeStatus(task: Task, status: Status) {
    setChanging(task.id);
    setError('');
    try {
      await api(`/tasks/${task.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      setNotice(`Task moved to ${statusLabels[status].toLowerCase()}.`);
      reload();
    } catch (err) {
      fail(err);
    } finally {
      setChanging(null);
    }
  }
  const hasFilters = Boolean(filter || query);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <div className="workspace-label">PERSONAL WORKSPACE</div>
        <a href="#tasks" className="nav-active">
          <span aria-hidden="true">▦</span> My tasks
          <span className="nav-arrow" aria-hidden="true">
            ↗
          </span>
        </a>
        <div className="capture-tip">
          <span className="tip-icon" aria-hidden="true">
            ↗
          </span>
          <h3>Catch the thought.</h3>
          <p>
            Send a text or voice note to your Telegram bot. We’ll save it as a
            task.
          </p>
          <span className="tip-detail">Your ideas, all in one place.</span>
        </div>
        <div className="account">
          <div className="avatar" aria-hidden="true">
            {user.first_name.slice(0, 1).toUpperCase()}
          </div>
          <div className="account-name">
            <strong>{user.first_name}</strong>
            <span>
              {user.username ? `@${user.username}` : 'Personal account'}
            </span>
          </div>
          <details className="account-menu">
            <summary aria-label="Account options">···</summary>
            <div>
              <button
                onClick={async () => {
                  try {
                    await api('/auth/logout', { method: 'POST' });
                    onSignedOut();
                  } catch (err) {
                    fail(err);
                  }
                }}
              >
                Sign out
              </button>
              <button
                className="danger-text"
                onClick={() => {
                  setError('');
                  setDeleting('account');
                }}
              >
                Delete account
              </button>
            </div>
          </details>
        </div>
      </aside>
      <main className="workspace" id="tasks">
        <header className="topbar">
          <span>
            Workspace <span className="breadcrumb-slash">/</span>{' '}
            <strong>My tasks</strong>
          </span>
          <span
            className={`connection ${connection === 'Live' ? 'is-live' : ''}`}
            role="status"
          >
            <span className="connection-dot" />
            {connection === 'Live'
              ? 'Live updates on'
              : connection === 'Connecting'
                ? 'Connecting…'
                : 'Reconnecting…'}
          </span>
        </header>
        <div className="workspace-body">
          <div className="page-heading">
            <div>
              <span className="eyebrow">A LITTLE PROGRESS, EVERY DAY</span>
              <h1>
                My tasks<span className="heading-dot">.</span>
              </h1>
              <p>A clear space for what’s next.</p>
            </div>
            <button
              className="primary new-task"
              onClick={() => setEditing('new')}
            >
              <span aria-hidden="true">＋</span> New task
            </button>
          </div>
          <div className="tools">
            <div className="search-box">
              <svg aria-hidden="true" viewBox="0 0 24 24">
                <circle cx="10.5" cy="10.5" r="6.5" />
                <path d="m16 16 4 4" />
              </svg>
              <input
                aria-label="Search tasks"
                type="search"
                placeholder="Find a task…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                }}
              />
            </div>
            <div className="view-switch" role="group" aria-label="Task view">
              <button
                aria-pressed={view === 'list'}
                onClick={() => setView('list')}
              >
                <span aria-hidden="true">☷</span> List
              </button>
              <button
                aria-pressed={view === 'board'}
                onClick={() => setView('board')}
              >
                <span aria-hidden="true">▥</span> Board
              </button>
            </div>
          </div>
          <div className="filter-bar">
            <div
              className="filter-tabs"
              role="group"
              aria-label="Filter by status"
            >
              {(['', ...statuses] as const).map((status) => (
                <button
                  key={status}
                  aria-pressed={filter === status}
                  onClick={() => {
                    if (filter !== status) {
                      setLoading(true);
                      setFilter(status);
                      setPage(1);
                    }
                  }}
                >
                  {status ? statusLabels[status] : 'All tasks'}
                </button>
              ))}
            </div>
            <span className="result-count">
              {loading
                ? 'Loading…'
                : `${data.total} ${data.total === 1 ? 'task' : 'tasks'}`}
            </span>
          </div>
          {error && (
            <div className="error error-banner" role="alert">
              {error}
              <button
                onClick={() => {
                  setLoading(true);
                  reload();
                }}
              >
                Try again
              </button>
            </div>
          )}
          <div className="sr-only" role="status">
            {notice}
          </div>
          {loading ? (
            <div className="empty-state" role="status">
              <span className="loader" />
              Gathering your tasks…
            </div>
          ) : !data.items.length ? (
            <div className="empty-state">
              <span className="empty-icon" aria-hidden="true">
                ✓
              </span>
              <h2>
                {hasFilters
                  ? 'Nothing here just yet.'
                  : 'Make room for your next idea.'}
              </h2>
              <p>
                {hasFilters
                  ? 'Try another search or change your status filter.'
                  : 'Add your first task, or send a text or voice note to your Telegram bot.'}
              </p>
              {hasFilters ? (
                <button
                  className="secondary"
                  onClick={() => {
                    setSearch('');
                    setQuery('');
                    setFilter('');
                    setPage(1);
                    setLoading(true);
                  }}
                >
                  Clear filters
                </button>
              ) : (
                <button className="primary" onClick={() => setEditing('new')}>
                  Create your first task
                </button>
              )}
            </div>
          ) : view === 'list' ? (
            <div className="task-list">
              <div className="list-header">
                <span>TASK</span>
                <span>STATUS</span>
                <span className="list-header-date">DUE DATE</span>
                <span className="sr-only">Actions</span>
              </div>
              {data.items.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  changing={Boolean(changing)}
                  onStatus={changeStatus}
                  onEdit={setEditing}
                  onDelete={(value) => {
                    setError('');
                    setDeleting(value);
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="board">
              {statuses.map((status) => (
                <section
                  className="board-column"
                  key={status}
                  aria-label={statusLabels[status]}
                >
                  <h2>
                    <span className={`status-dot ${status.toLowerCase()}`} />
                    {statusLabels[status]}
                    <span>
                      {
                        data.items.filter((task) => task.status === status)
                          .length
                      }
                    </span>
                  </h2>
                  {data.items
                    .filter((task) => task.status === status)
                    .map((task) => (
                      <TaskCard
                        key={task.id}
                        task={task}
                        changing={Boolean(changing)}
                        onStatus={changeStatus}
                        onEdit={setEditing}
                        onDelete={(value) => {
                          setError('');
                          setDeleting(value);
                        }}
                      />
                    ))}
                  {!data.items.some((task) => task.status === status) && (
                    <p className="column-empty">A little breathing room.</p>
                  )}
                </section>
              ))}
            </div>
          )}
          <footer className="task-footer">
            <span>
              {data.total > 0
                ? `Showing ${Math.min((page - 1) * 20 + 1, data.total)}–${Math.min(page * 20, data.total)} of ${data.total}${view === 'board' ? ' · board shows this page' : ''}`
                : 'Every small step counts.'}
            </span>
            <div className="pagination">
              <button
                className="secondary"
                aria-label="Previous page"
                disabled={page === 1 || loading}
                onClick={() => {
                  setLoading(true);
                  setPage(page - 1);
                }}
              >
                ←
              </button>
              <span>Page {page}</span>
              <button
                className="secondary"
                aria-label="Next page"
                disabled={page * 20 >= data.total || loading}
                onClick={() => {
                  setLoading(true);
                  setPage(page + 1);
                }}
              >
                →
              </button>
            </div>
          </footer>
          <div className="workspace-note">
            <span aria-hidden="true">↗</span> From a passing thought to a
            finished task.
          </div>
        </div>
      </main>
      {editing && (
        <TaskDialog
          task={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSave={save}
        />
      )}
      {deleting && (
        <Dialog
          title={
            deleting === 'account'
              ? 'Delete your account?'
              : 'Delete this task?'
          }
          busy={busy}
          onClose={() => setDeleting(null)}
        >
          <p className="dialog-description">
            {deleting === 'account' ? (
              'This permanently deletes your account, all tasks, and transcription history. This cannot be undone.'
            ) : (
              <>
                “{deleting.title}” will be permanently deleted. This cannot be
                undone.
              </>
            )}
          </p>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="dialog-actions">
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setDeleting(null)}
            >
              Keep {deleting === 'account' ? 'account' : 'task'}
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError('');
                try {
                  await api(
                    deleting === 'account'
                      ? '/auth/me'
                      : `/tasks/${deleting.id}`,
                    { method: 'DELETE' },
                  );
                  if (deleting === 'account') {
                    onSignedOut();
                  } else {
                    setDeleting(null);
                    setNotice('Task deleted.');
                    reload();
                  }
                } catch (err) {
                  fail(err);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy
                ? 'Deleting…'
                : deleting === 'account'
                  ? 'Delete account permanently'
                  : 'Delete task'}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function TaskCard({
  task,
  changing,
  onStatus,
  onEdit,
  onDelete,
}: {
  task: Task;
  changing: boolean;
  onStatus: (task: Task, status: Status) => void;
  onEdit: (task: Task) => void;
  onDelete: (task: Task) => void;
}) {
  const overdue =
    task.due_date &&
    new Date(task.due_date).getTime() < new Date().getTime() &&
    task.status !== 'COMPLETED';
  return (
    <article
      className={`task-card ${task.status === 'COMPLETED' ? 'task-completed' : ''}`}
      aria-label={task.title}
    >
      <div className="task-main">
        <button
          className={`task-check ${task.status === 'COMPLETED' ? 'checked' : ''}`}
          aria-label={
            task.status === 'COMPLETED'
              ? `Reopen ${task.title}`
              : `Complete ${task.title}`
          }
          disabled={changing}
          onClick={() =>
            onStatus(
              task,
              task.status === 'COMPLETED' ? 'PENDING' : 'COMPLETED',
            )
          }
        >
          {task.status === 'COMPLETED' ? '✓' : ''}
        </button>
        <div className="task-content">
          <button className="task-title" onClick={() => onEdit(task)}>
            {task.title}
          </button>
          {task.description && (
            <p className="task-description">{task.description}</p>
          )}
          <div className="task-meta">
            <span className={`source-badge ${task.source.toLowerCase()}`}>
              <span aria-hidden="true">
                {task.source === 'TELEGRAM_VOICE'
                  ? '◉'
                  : task.source === 'TELEGRAM_TEXT'
                    ? '↗'
                    : '▦'}
              </span>{' '}
              {sourceLabels[task.source]}
            </span>
            {task.created_at && (
              <time
                dateTime={task.created_at}
                title={new Date(task.created_at).toLocaleString()}
              >
                Created {new Date(task.created_at).toLocaleDateString()}
              </time>
            )}
            {task.priority && (
              <span className={`priority ${task.priority.toLowerCase()}`}>
                <span aria-hidden="true">⚑</span>{' '}
                {task.priority.charAt(0) + task.priority.slice(1).toLowerCase()}
              </span>
            )}
          </div>
        </div>
      </div>
      <label className="status-select">
        <span className="sr-only">Status for {task.title}</span>
        <select
          value={task.status}
          disabled={changing}
          onChange={(event) => onStatus(task, event.target.value as Status)}
        >
          {statuses.map((status) => (
            <option key={status} value={status}>
              {statusLabels[status]}
            </option>
          ))}
        </select>
      </label>
      <span className={`due-date ${overdue ? 'overdue' : ''}`}>
        {task.due_date ? (
          <time
            dateTime={task.due_date}
            title={new Date(task.due_date).toLocaleString()}
          >
            {new Date(task.due_date).toLocaleDateString(undefined, {
              month: 'short',
              day: 'numeric',
              year:
                new Date(task.due_date).getFullYear() ===
                new Date().getFullYear()
                  ? undefined
                  : 'numeric',
            })}
            {overdue && <span>Overdue</span>}
          </time>
        ) : (
          <span className="no-date">—</span>
        )}
      </span>
      <div className="task-actions">
        <button
          className="icon-button"
          aria-label={`Edit ${task.title}`}
          onClick={() => onEdit(task)}
        >
          ↗
        </button>
        <button
          className="icon-button delete-button"
          aria-label={`Delete ${task.title}`}
          onClick={() => onDelete(task)}
        >
          ×
        </button>
      </div>
    </article>
  );
}
