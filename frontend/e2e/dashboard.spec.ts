import { expect, test, type Page } from '@playwright/test';

async function prepare(page: Page, authenticated = true) {
  let signedIn = authenticated;
  let tasks = [
    {
      id: 'initial',
      title: 'Book the studio',
      description: 'Bring the microphone',
      status: 'PENDING',
      source: 'TELEGRAM_VOICE',
      priority: 'HIGH',
      due_date: null,
    },
  ];
  await page.addInitScript(() => {
    class BrowserStream extends EventTarget {
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      receive = (event: Event) => {
        const kind = (event as CustomEvent<string>).detail;
        if (kind === 'error') this.onerror?.();
        else this.dispatchEvent(new Event(kind));
      };
      constructor() {
        super();
        window.addEventListener('test:stream', this.receive);
        setTimeout(() => this.dispatchEvent(new Event('ready')), 100);
      }
      close() {
        window.removeEventListener('test:stream', this.receive);
      }
    }
    Object.defineProperty(window, 'EventSource', { value: BrowserStream });
  });
  await page.route('**/api/**', async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    const method = request.method();
    const fulfill = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    if (url.pathname === '/api/auth/login') {
      signedIn = request.postDataJSON().code === '12345678';
      return fulfill(
        signedIn ? {} : { detail: 'Invalid code' },
        signedIn ? 200 : 401,
      );
    }
    if (url.pathname === '/api/auth/me')
      return fulfill(
        signedIn
          ? { id: 'user', first_name: 'Anna', username: 'anna' }
          : { detail: 'Sign in required' },
        signedIn ? 200 : 401,
      );
    if (url.pathname === '/api/auth/logout') {
      signedIn = false;
      return fulfill({});
    }
    if (url.pathname === '/api/tasks' && method === 'POST') {
      tasks.unshift({
        ...request.postDataJSON(),
        id: 'created',
        source: 'DASHBOARD',
        status: 'PENDING',
      });
      return fulfill(tasks[0], 201);
    }
    if (url.pathname.startsWith('/api/tasks/')) {
      const id = url.pathname.split('/').pop();
      if (method === 'DELETE') {
        tasks = tasks.filter((task) => task.id !== id);
        return route.fulfill({ status: 204 });
      }
      tasks = tasks.map((task) =>
        task.id === id ? { ...task, ...request.postDataJSON() } : task,
      );
      return fulfill(tasks.find((task) => task.id === id));
    }
    if (url.pathname === '/api/tasks') {
      let results = tasks;
      if (url.searchParams.get('status'))
        results = results.filter(
          (task) => task.status === url.searchParams.get('status'),
        );
      if (url.searchParams.get('search'))
        results = results.filter((task) =>
          task.title
            .toLowerCase()
            .includes(url.searchParams.get('search')!.toLowerCase()),
        );
      return fulfill({
        items: results,
        total: results.length,
        page: 1,
        page_size: 20,
      });
    }
    return fulfill({}, 404);
  });
  return {
    pushTask: () =>
      tasks.push({
        id: 'remote',
        title: 'Sent from Telegram',
        description: '',
        status: 'PENDING',
        source: 'TELEGRAM_TEXT',
        priority: 'LOW',
        due_date: null,
      }),
  };
}

test('sign in, create, edit, move and delete a task with keyboard-accessible confirmation', async ({
  page,
}) => {
  await prepare(page, false);
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Welcome to Taskroom.' }),
  ).toBeVisible();
  await page.getByLabel('One-time code').fill('12345678');
  await page.getByRole('button', { name: 'Open my taskroom' }).click();
  await expect(page.getByRole('heading', { name: 'My tasks.' })).toBeVisible();
  await page.getByRole('button', { name: 'New task' }).click();
  await expect(page.getByLabel('Task title')).toBeFocused();
  await page.getByLabel('Task title').fill('Write a clear brief');
  await page.getByLabel('Description').fill('Include the launch notes');
  await page
    .getByRole('combobox', { name: 'Priority', exact: true })
    .selectOption('MEDIUM');
  await page.getByRole('button', { name: 'Create task' }).click();
  await expect(
    page.getByRole('article', { name: 'Write a clear brief' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Edit Write a clear brief' }).click();
  await page.getByLabel('Task title').fill('Write the final brief');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await page
    .getByLabel('Status for Write the final brief')
    .selectOption('IN_PROGRESS');
  await expect(page.getByLabel('Status for Write the final brief')).toHaveValue(
    'IN_PROGRESS',
  );
  await page
    .getByRole('button', { name: 'Complete Write the final brief' })
    .click();
  await expect(
    page.getByRole('button', { name: 'Reopen Write the final brief' }),
  ).toBeVisible();
  await page
    .getByRole('button', { name: 'Delete Write the final brief' })
    .click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Delete Write the final brief' }),
  ).toBeFocused();
  await page
    .getByRole('button', { name: 'Delete Write the final brief' })
    .click();
  await page.getByRole('button', { name: 'Delete task', exact: true }).click();
  await expect(
    page.getByRole('article', { name: 'Write the final brief' }),
  ).not.toBeVisible();
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test('receives remote tasks, recovers after reconnect and supports board search', async ({
  page,
}) => {
  const state = await prepare(page);
  await page.goto('/');
  await expect(page.getByText('Live updates on')).toBeVisible();
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).toBeVisible();
  state.pushTask();
  await page.evaluate(() =>
    window.dispatchEvent(
      new CustomEvent('test:stream', { detail: 'task.created' }),
    ),
  );
  await expect(
    page.getByRole('article', { name: 'Sent from Telegram' }),
  ).toBeVisible();
  await page.evaluate(() =>
    window.dispatchEvent(new CustomEvent('test:stream', { detail: 'error' })),
  );
  await expect(page.getByText('Reconnecting…')).toBeVisible();
  await page.evaluate(() =>
    window.dispatchEvent(new CustomEvent('test:stream', { detail: 'ready' })),
  );
  await expect(page.getByText('Live updates on')).toBeVisible();
  await page.getByRole('button', { name: 'Board', exact: true }).click();
  await expect(page.getByRole('region', { name: 'To do' })).toBeVisible();
  await page.getByLabel('Search tasks').fill('Telegram');
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).not.toBeVisible();
  await expect(
    page.getByRole('article', { name: 'Sent from Telegram' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Completed', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Nothing here just yet.' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test('keeps edits and existing tasks when the service fails', async ({
  page,
}) => {
  await prepare(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Edit Book the studio' }).click();
  await page.route('**/api/tasks/initial', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"detail":"Temporarily unavailable. Try again."}',
    }),
  );
  await page.getByLabel('Task title').fill('Keep my draft');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText(
    'Temporarily unavailable',
  );
  await expect(page.getByLabel('Task title')).toHaveValue('Keep my draft');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).toBeVisible();
});

test('dashboard and task dialog fit the viewport', async ({
  page,
}, testInfo) => {
  await prepare(page);
  await page.goto('/');
  await expect(
    page.getByRole('article', { name: 'Book the studio' }),
  ).toBeVisible();
  if (testInfo.project.name === 'mobile')
    await page.setViewportSize({ width: 375, height: 812 });
  const name = testInfo.project.name === 'mobile' ? 'mobile' : 'desktop';
  await page.screenshot({
    path: `test-results/dashboard-${name}.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: 'New task' }).click();
  const bounds = await page.getByRole('dialog').boundingBox();
  const viewport = page.viewportSize()!;
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.y).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewport.width);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(viewport.height);
  await page.screenshot({
    path: `test-results/dialog-${name}.png`,
    fullPage: true,
  });
});
