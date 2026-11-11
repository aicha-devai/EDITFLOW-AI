import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// This suite intentionally has no route.fulfill(), API stubs or mocked media.
// Run it against a deployed staging URL with a pre-verified staging account:
// EDITFLOW_STAGING_URL, EDITFLOW_E2E_EMAIL and EDITFLOW_E2E_PASSWORD.
const stagingUrl = process.env.EDITFLOW_STAGING_URL;
const email = process.env.EDITFLOW_E2E_EMAIL;
const password = process.env.EDITFLOW_E2E_PASSWORD;
const enabled = Boolean(stagingUrl && email && password);
let fixtureDirectory;
let sourceVideo;

test.describe("real Staging upload → render → Story Graph flow", () => {
  test.skip(!enabled, "Set EDITFLOW_STAGING_URL, EDITFLOW_E2E_EMAIL and EDITFLOW_E2E_PASSWORD to run live Staging E2E.");

  test.beforeAll(() => {
    fixtureDirectory = mkdtempSync(join(tmpdir(), "editflow-staging-e2e-"));
    sourceVideo = join(fixtureDirectory, "staging-source.mp4");
    execFileSync("ffmpeg", [
      "-hide_banner", "-loglevel", "error",
      "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=24:duration=8",
      "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
      "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
      "-c:a", "aac", "-movflags", "+faststart", "-y", sourceVideo,
    ]);
  });

  test.afterAll(() => {
    if (fixtureDirectory) rmSync(fixtureDirectory, { recursive: true, force: true });
  });

  test("creates project, uploads real MP4, renders it and opens timestamped evidence", async ({ page }) => {
    test.setTimeout(60 * 60 * 1000);
    await page.goto(stagingUrl);
    await page.locator("#account-btn").click();
    await page.locator("#account-email").fill(email);
    await page.locator("#account-password").fill(password);
    await page.locator("#account-login").click();
    await expect(page.locator("#account-status")).toContainText(email, { timeout: 20_000 });
    await expect(page.locator(".studio-panel")).toHaveAttribute("data-studio-ready", "true", { timeout: 20_000 });

    const title = "Staging E2E " + new Date().toISOString();
    await page.locator("#studio-project-title").fill(title);
    await page.locator("#studio-project-form button[type=submit]").click();
    await expect(page.locator("#studio-project-select")).toContainText(title, { timeout: 20_000 });

    await page.locator("#studio-video-file").setInputFiles(sourceVideo);
    await page.locator("#studio-upload").click();
    await expect(page.locator("[data-testid=uploaded-asset]")).toBeVisible({ timeout: 90_000 });
    await expect(page.locator("[data-testid=uploaded-asset]")).toContainText("SHA-256");

    await page.locator("#studio-render").click();
    await expect(page.locator("#studio-status")).toContainText("Render complete", { timeout: 60 * 60 * 1000 });
    const video = page.locator("#story-video");
    await expect(video).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => video.evaluate(el => el.readyState), { timeout: 60_000 }).toBeGreaterThanOrEqual(1);
    await expect.poll(() => video.evaluate(el => el.duration), { timeout: 60_000 }).toBeGreaterThan(7);

    const markers = page.locator(".evidence-marker[data-evidence-node][data-jump-time]");
    await expect(markers.first()).toBeVisible({ timeout: 30_000 });
    const firstTimestamp = Number(await markers.first().getAttribute("data-jump-time"));
    expect(Number.isFinite(firstTimestamp)).toBeTruthy();
    await markers.first().click();
    await expect.poll(() => video.evaluate(el => Math.abs(el.currentTime - Math.min(firstTimestamp, el.duration - 0.05))))
      .toBeLessThan(0.15);
    await expect(page.locator("#active-evidence-label")).not.toContainText("No active evidence");
  });
});
