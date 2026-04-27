---
name: e2e-test
description: Run Playwright E2E tests for Tauri GUI projects. Supports smoke tests, page-specific tests, visual regression, and custom test generation. (Examples reference a specific project layout — adapt paths to your project.)
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent
---

# E2E Test Skill (Playwright)

Automated end-to-end testing for Tauri GUI applications using Playwright.

> The code examples below come from a specific project's layout (`gui/e2e/...`). When applying this skill to a different project, adapt the file paths and POM class names to match your codebase.

## Architecture

```
gui/
  playwright.config.ts    # Playwright configuration (port 1420, chromium)
  e2e/
    fixtures.ts           # Shared fixtures: Tauri mock injection, Page Object Models, test data
    smoke.spec.ts         # Quick sanity: app loads, no errors, nav works
    auto-factory.spec.ts  # AutoFactory page: KPIs, cards, pipeline, batch modal, history
    project-management.spec.ts  # Project list, creation, navigation
    visual-regression.spec.ts   # Screenshot comparison baselines
```

## Key Design Patterns

### Tauri Mock Injection
Since Playwright runs in a real browser (not inside Tauri), all `invoke()` calls need to be mocked.
The `injectTauriMocks()` function in `fixtures.ts` injects a `__TAURI_INTERNALS__` shim before each test.

```typescript
// Override specific commands per test:
await mockTauri({
  list_projects: [{ metadata: { id: 'custom', name: 'Custom Project', ... } }],
  get_project_status: { steps: { preflight: { done: true } } },
});
```

### Page Object Models (POM)
Each major page has a POM class in `fixtures.ts`:
- `SidebarPOM` - navigation
- `ProjectManagementPOM` - project list & creation
- `AutoFactoryPOM` - factory dashboard
- `ProjectWorkspacePOM` - project workspace

### Test Data Factories
Mock data constants in `fixtures.ts`:
- `MOCK_PROJECTS` - two sample projects (premium + image_text)
- `MOCK_STATUS` - pipeline status with mixed step states
- `MOCK_FACTORY_STATUS` / `MOCK_FACTORY_STATS` - factory KPI data

## Commands

| Command | Description |
|---------|-------------|
| `npm run e2e` | Run all E2E tests headlessly |
| `npm run e2e:ui` | Open Playwright UI mode (interactive) |
| `npm run e2e:headed` | Run tests in visible browser |
| `npm run e2e:smoke` | Run smoke tests only (fastest) |
| `npm run e2e:report` | View HTML test report |
| `npx playwright test --update-snapshots` | Update visual regression baselines |
| `npx playwright test -g "pattern"` | Run tests matching pattern |
| `npx playwright codegen localhost:1420` | Record new tests interactively |

## Usage Scenarios

### 1. Quick validation after code change
```
npm run e2e:smoke
```

### 2. Test a specific page
```
npx playwright test e2e/auto-factory.spec.ts --headed
```

### 3. Generate a new test interactively
```
npx playwright codegen localhost:1420
```
This opens a browser with recording. Actions are converted to test code.

### 4. Debug a failing test
```
npx playwright test --debug e2e/auto-factory.spec.ts
```

### 5. Visual regression check
```
npx playwright test e2e/visual-regression.spec.ts
# First run creates baselines in e2e/visual-regression.spec.ts-snapshots/
# Subsequent runs compare against baselines
```

## Writing New Tests

### Template
```typescript
import { test, expect } from './fixtures';

test.describe('Feature Name', () => {
  test.beforeEach(async ({ mockTauri }) => {
    await mockTauri({
      // Override mock data specific to these tests
    });
  });

  test('should do X when Y', async ({ page, factory }) => {
    await page.goto('/');
    // Navigate to the page
    // Assert expected behavior
  });
});
```

### Adding a new POM
Add to `e2e/fixtures.ts`:
```typescript
export class NewPagePOM {
  constructor(private page: Page) {}
  get someElement() { return this.page.locator('.selector'); }
}
```
Then register in the `Fixtures` type and `test.extend()`.

### Adding new mock commands
Add to the `handlers` object in `injectTauriMocks()`:
```typescript
const handlers = {
  ...existing,
  new_command: { your: 'mock data' },
};
```

## CI Integration

Add to CI pipeline:
```yaml
- name: E2E Tests
  run: |
    cd gui
    npm ci
    npx playwright install chromium
    npm run e2e
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Tests timeout | Check if vite dev server starts (`npm run dev`) |
| Tauri invoke errors | Add missing mock to `injectTauriMocks()` in fixtures.ts |
| Visual regression false positives | Update baselines: `npx playwright test --update-snapshots` |
| Browser not installed | Run `npx playwright install chromium` |
