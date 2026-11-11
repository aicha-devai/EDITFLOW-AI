import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const projectId = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";
let mediaDirectory;
let mediaFixture;

const graphResponse = {
  media_available: true,
  media_url: "/mock-render.mp4",
  graph: {
    status: "completed",
    entity_extraction_status: "completed",
    integrity: { automatic_timeline_changes: 0 },
    limitations: [],
    nodes: [
      {
        id: "character-untimed",
        type: "character",
        label: "Untimed character",
        description: "A character node without timestamp evidence.",
        evidence_refs: [],
      },
      {
        id: "shot-12",
        type: "shot",
        label: "Hallway shot",
        description: "A timestamped shot.",
        start_seconds: 12.5,
        end_seconds: 16,
        evidence_refs: [],
      },
      {
        id: "narration-untimed",
        type: "narration",
        label: "Unaligned narration",
        description: "Transcript text with no aligned timestamp.",
        start_seconds: null,
        end_seconds: null,
        evidence_refs: [],
      },
    ],
    edges: [
      {
        id: "character-shot",
        source: "character-untimed",
        target: "shot-12",
        type: "appears_in",
        verification_status: "requires_review",
        evidence_refs: ["narration-untimed"],
        requires_human_review: true,
      },
    ],
  },
};

test.beforeAll(() => {
  mediaDirectory = mkdtempSync(join(tmpdir(), "editflow-playwright-media-"));
  mediaFixture = join(mediaDirectory, "mock-render.mp4");
  execFileSync("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10:d=20",
    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-y", mediaFixture,
  ]);
});

test.afterAll(() => {
  if (mediaDirectory) rmSync(mediaDirectory, { recursive: true, force: true });
});

test.beforeEach(async ({ page }) => {
  await page.route("**/v1/projects/**/renders/**/story-continuity", route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(graphResponse),
    }),
  );
  await page.route("**/mock-render.mp4", route =>
    route.fulfill({
      status: 200,
      contentType: "video/mp4",
      headers: { "accept-ranges": "bytes", "cache-control": "no-store" },
      body: readFileSync(mediaFixture),
    }),
  );
});ort { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const projectId = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";
let mediaDirectory;
let mediaFixture;

const graphResponse = {
  media_available: true,
  media_url: "/mock-render.mp4",
  graph: {
    status: "completed",
    entity_extraction_status: "completed",
    integrity: { automatic_timeline_changes: 0 },
    limitations: [],
    nodes: [
      {
        id: "character-untimed",
        type: "character",
        label: "Untimed character",
        description: "A character node without timestamp evidence.",
        evidence_refs: [],
      },
      {
        id: "shot-12",
        type: "shot",
        label: "Hallway shot",
        description: "A timestamped shot.",
        start_seconds: 12.5,
        end_seconds: 16,
        evidence_refs: [],
      },
      {
        id: "narration-untimed",
        type: "narration",
        label: "Unaligned narration",
        description: "Transcript text with no aligned timestamp.",
        start_seconds: null,
        end_seconds: null,
        evidence_refs: [],
      },
    ],
    edges: [
      {
        id: "character-shot",
        source: "character-untimed",
        target: "shot-12",
        type: "appears_in",
        verification_status: "requires_review",
        evidence_refs: ["narration-untimed"],
        requires_human_review: true,
      },
    ],
  },
};

test.beforeEach(async ({ page }) => {
  // A tiny, valid H.264 MP4 lets Chromium exercise the real media element,
  // metadata lifecycle, seeking and playback instead of a synthetic media shim.
  await page.route("**/v1/projects/**/renders/**/story-continuity", route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(graphResponse),
    }),
  );
  await page.route("**/mock-render.mp4", route =>
    route.fulfill({
      status: 200,
      contentType: "video/mp4",
      headers: { "accept-ranges": "bytes", "cache-control": "no-store" },
      body: Buffer.from("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", "base64"),
    }),
  );
});

async function loadExplorer(page) {
  await page.goto("/");
  await page.locator("#project-input").fill(projectId);
  await page.locator("#job-input").fill(jobId);
  await page.getByRole("button", { name: /load graph/i }).click();
  const video = page.locator("#story-video");
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate(el => el.readyState)).toBeGreaterThanOrEqual(1);
  await expect.poll(() => video.evaluate(el => el.duration)).toBeGreaterThan(16);
}

test("clicking timestamped evidence seeks to its exact timestamp and starts playback", async ({ page }) => {
  await loadExplorer(page);

  await page.locator('[data-evidence-node="shot-12"]').click();

  const video = page.locator("#story-video");
  await expect.poll(() => video.evaluate(el => el.currentTime)).toBe(12.5);
  await expect(page.locator("#player-time")).toHaveText("00:12.5");
  await expect(page.locator("#active-evidence-label")).toContainText("Hallway shot");
  await expect.poll(() => video.evaluate(el => el.paused)).toBe(false);
});

test("untimed graph nodes remain inspectable and never seek the video to zero", async ({ page }) => {
  await loadExplorer(page);

  const video = page.locator("#story-video");
  await video.evaluate(el => {
    el.currentTime = 7.25;
    el.dispatchEvent(new Event("timeupdate"));
  });
  await expect(page.locator("#player-time")).toHaveText("00:07.3");

  await page.locator('[data-node="character-untimed"]').click();

  await expect(page.getByRole("heading", { name: "Untimed character" })).toBeVisible();
  await expect.poll(() => video.evaluate(el => el.currentTime)).toBe(7.25);
  await expect(page.locator('[data-evidence-node="character-untimed"]')).toHaveCount(0);
});

test("null timestamp evidence is excluded from the evidence track", async ({ page }) => {
  await loadExplorer(page);

  await expect(page.locator('[data-evidence-node="narration-untimed"]')).toHaveCount(0);
  await expect(page.locator('[data-evidence-node="shot-12"]')).toHaveCount(1);
});

test("untimed relationship evidence has no jump control and does not move playback", async ({ page }) => {
  await loadExplorer(page);

  const video = page.locator("#story-video");
  await video.evaluate(el => {
    el.currentTime = 8.5;
    el.dispatchEvent(new Event("timeupdate"));
  });

  await page.locator('[data-edge="character-shot"]').dispatchEvent("click");

  await expect(page.getByText("Unaligned narration")).toBeVisible();
  await expect(page.locator(".evidence-card [data-jump-time]")).toHaveCount(0);
  await expect.poll(() => video.evaluate(el => el.currentTime)).toBe(8.5);
  await expect(page.locator(".evidence-card .evidence-time")).toHaveText("Time unavailable");
});
