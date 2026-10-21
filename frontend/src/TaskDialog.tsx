import {
  useLayoutEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { Priority, Task, TaskInput } from './types';
import { fromYerevanDateTimeLocal, toYerevanDateTimeLocal } from './dateTime';

export function Dialog({
  title,
  onClose,
  children,
  busy = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useLayoutEffect(() => {
    const opener = document.activeElement;
    const dialog = ref.current;
    dialog?.showModal();
    dialog?.querySelector<HTMLElement>('[data-initial-focus]')?.focus();
    return () => {
      dialog?.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="dialog-heading">
        <h2 id={titleId}>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          disabled={busy}
          onClick={onClose}
        >
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function TaskDialog({
  task,
  onClose,
  onSave,
}: {
  task?: Task;
  onClose: () => void;
  onSave: (input: TaskInput, id?: string) => Promise<void>;
}) {
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  return (
    <Dialog
      title={task ? 'Edit task' : 'Make a little progress'}
      onClose={onClose}
      busy={saving}
    >
      <p className="dialog-description">
        {task
          ? 'Give your task the details it needs.'
          : 'Big plans start with one small task.'}
      </p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const title = String(data.get('title')).trim();
          if (!title) {
            setError('Give your task a title.');
            return;
          }
          setSaving(true);
          setError('');
          try {
            await onSave(
              {
                title,
                description: String(data.get('description')).trim() || null,
                priority: (data.get('priority') as Priority) || null,
                due_date: data.get('due_date')
                  ? fromYerevanDateTimeLocal(String(data.get('due_date')))
                  : null,
              },
              task?.id,
            );
          } catch (err) {
            setError(
              err instanceof Error ? err.message : 'Could not save your task.',
            );
          } finally {
            setSaving(false);
          }
        }}
      >
        <label>
          Task title
          <input
            name="title"
            defaultValue={task?.title}
            maxLength={300}
            required
            data-initial-focus
            placeholder="What would you like to get done?"
            disabled={saving}
          />
        </label>
        <label>
          Description <span className="optional">optional</span>
          <textarea
            name="description"
            defaultValue={task?.description || ''}
            maxLength={5000}
            rows={4}
            placeholder="A few details, links, or a starting point…"
            disabled={saving}
          />
        </label>
        <div className="form-row">
          <label>
            Due date <span className="optional">Yerevan time, optional</span>
            <input
              type="datetime-local"
              name="due_date"
              defaultValue={toYerevanDateTimeLocal(task?.due_date)}
              disabled={saving}
            />
          </label>
          <label>
            Priority
            <select
              name="priority"
              defaultValue={task?.priority || ''}
              disabled={saving}
            >
              <option value="">No priority</option>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
            </select>
          </label>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button
            type="button"
            className="secondary"
            onClick={onClose}
            disabled={saving}
          >
            Cancel
          </button>
          <button className="primary" disabled={saving}>
            {saving ? 'Saving…' : task ? 'Save changes' : 'Create task'}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
