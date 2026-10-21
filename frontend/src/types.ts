export const statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED'] as const;
export type Status = (typeof statuses)[number];
export type Priority = 'LOW' | 'MEDIUM' | 'HIGH';
export interface User {
  id: string;
  first_name: string;
  username: string | null;
  telegram_user_id: string;
}
export interface Task {
  id: string;
  title: string;
  description: string | null;
  status: Status;
  source: 'DASHBOARD' | 'TELEGRAM_TEXT' | 'TELEGRAM_VOICE';
  priority: Priority | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}
export interface TaskList {
  items: Task[];
  total: number;
  page: number;
  page_size: number;
}
export interface TaskInput {
  title: string;
  description: string | null;
  priority: Priority | null;
  due_date: string | null;
}
export const statusLabels: Record<Status, string> = {
  PENDING: 'To do',
  IN_PROGRESS: 'In progress',
  COMPLETED: 'Completed',
};
export const sourceLabels: Record<Task['source'], string> = {
  DASHBOARD: 'Dashboard',
  TELEGRAM_TEXT: 'Telegram text',
  TELEGRAM_VOICE: 'Telegram voice',
};
