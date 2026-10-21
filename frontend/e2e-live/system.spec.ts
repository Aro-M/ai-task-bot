import AxeBuilder from '@axe-core/playwright';
import { randomInt } from 'node:crypto';
import { expect, test, request } from '@playwright/test';

const controlURL =
  process.env.TASKBOT_QA_CONTROL_URL || 'http://localhost:18081';

async function control(path: string) {
  const client = await request.newContext({ baseURL: controlURL });
  try {
    const response = await client.post(path);
    expect(response.ok()).toBe(true);
    return await response.json();
  } finally {
    await client.dispose();
  }
}

function violations(result: Awaited<ReturnType<AxeBuilder['analyze']>>) {
  return result.violations.map((item) => ({
    id: item.id,
    impact: item.impact,
    nodes: item.nodes.map((node) => ({
      target: node.target,
      reason: node.failureSummary,
    })),
  }));
}

test('real login, CRUD, Telegram event, tenant isolation, accessibility and account erasure', async ({
  page,
}, testInfo) => {
  const fixture = (await control('/seed')) as {
    code: string;
    telegramId: number;
    foreignId: string;
  };
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Welcome to Taskroom.' }),
  ).toBeVisible();
  const loginA11y = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(violations(loginA11y)).toEqual([]);
  await page.getByLabel('One-time code').fill(fixture.code);
  await page.getByRole('button', { name: 'Open my taskroom' }).click();
  await expect(page.getByRole('heading', { name: 'My tasks.' })).toBeVisible();
  await expect(page.getByText('Live updates on')).toBeVisible();
  await page.getByRole('button', { name: 'New task' }).click();
  await expect(page.getByLabel('Task title')).toBeFocused();
  await page.getByLabel('Task title').fill('Full system QA task');
  await page
    .getByLabel('Description')
    .fill('<script>window.pwned=true</script> & հայկական նշում');
  const dialogA11y = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(violations(dialogA11y)).toEqual([]);
  await page.getByRole('button', { name: 'Create task' }).click();
  await expect(
    page.getByRole('article', { name: 'Full system QA task' }),
  ).toBeVisible();
  expect(await page.evaluate(() => 'pwned' in window)).toBe(false);
  await page
    .getByLabel('Status for Full system QA task')
    .selectOption('IN_PROGRESS');
  await expect(page.getByLabel('Status for Full system QA task')).toHaveValue(
    'IN_PROGRESS',
  );
  const origin = new URL(page.url()).origin;
  const webhook = await page.request.post('/telegram/webhook', {
    headers: { 'X-Telegram-Bot-Api-Secret-Token': 'qa-webhook-secret' },
    data: {
      update_id: randomInt(100000000, 999999999),
      message: {
        from: { id: fixture.telegramId, first_name: 'QA Owner' },
        chat: { id: fixture.telegramId, type: 'private' },
        text: 'Created by real Telegram webhook',
      },
    },
  });
  expect(webhook.status()).toBe(200);
  await control('/dispatch');
  await expect(
    page.getByRole('article', { name: 'Created by real Telegram webhook' }),
  ).toBeVisible();
  expect(
    (await page.request.get(`/api/tasks/${fixture.foreignId}`)).status(),
  ).toBe(403);
  expect(
    (
      await page.request.delete(`/api/tasks/${fixture.foreignId}`, {
        headers: { Origin: origin },
      })
    ).status(),
  ).toBe(403);
  for (const width of [320, 375, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results-live/${testInfo.project.name}-${width}.png`,
      fullPage: true,
    });
  }
  const dashboardA11y = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(violations(dashboardA11y)).toEqual([]);
  await page.getByRole('button', { name: 'Board', exact: true }).click();
  const boardA11y = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
    .analyze();
  expect(violations(boardA11y)).toEqual([]);
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await page
    .getByRole('button', { name: 'Delete Full system QA task' })
    .click();
  await page.getByRole('button', { name: 'Delete task', exact: true }).click();
  await expect(
    page.getByRole('article', { name: 'Full system QA task' }),
  ).not.toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('article', { name: 'Created by real Telegram webhook' }),
  ).toBeVisible();
  await page.getByLabel('Account options').click();
  await page
    .getByRole('button', { name: 'Delete account', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Delete account permanently' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Welcome to Taskroom.' }),
  ).toBeVisible();
  expect((await page.request.get('/api/tasks')).status()).toBe(401);
  expect(pageErrors).toEqual([]);
});
