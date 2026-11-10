import { test, expect } from "@playwright/test";

const projectId = "11111111-1111-4111-8111-111111111111";
const jobId = "22222222-2222-4222-8222-222222222222";

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
  // Keep the test deterministic: exercise the real Explorer UI and seek handler,
  // while replacing browser codec/network timing with a controllable media element.
  await page.addInitScript(() => {
    const state = new WeakMap();
    const ensure = video => {
      if (!state.has(video)) state.set(video, { currentTime: 0, paused: true, playCalls: 0 });
      return state.get(video);
    };
    Object.defineProperty(HTMLMediaElement.prototype, "duration", {
      configurable: true,
      get: () => 60,
    });
    Object.defineProperty(HTMLMediaElement.prototype, "readyState", {
      configurable: true,
      get: () => 1,
    });
    Object.defineProperty(HTMLMediaElement.prototype, "currentTime", {
      configurable: true,
      get() { return ensure(this).currentTime; },
      set(value) {
        ensure(this).currentTime = Number(value);
        this.dispatchEvent(new Event("seeked"));
      },
    });
    Object.defineProperty(HTMLMediaElement.prototype, "paused", {
      configurable: true,
      get() { return ensure(this).paused; },
    });
    HTMLMediaElement.prototype.load = function () {};
    HTMLMediaElement.prototype.play = function () {
      const media = ensure(this);
      media.paused = false;
      media.playCalls += 1;
      this.dispatchEvent(new Event("play"));
      return Promise.resolve();
    };
    HTMLMediaElement.prototype.pause = function () {
      ensure(this).paused = true;
      this.dispatchEvent(new Event("pause"));
    };
  });

  await page.route("**/v1/projects/**/renders/**/story-continuity", route =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(graphResponse),
    }),
  );
  await page.route("**/mock-render.mp4", route =>
    route.fulfill({ status: 200, contentType: "video/mp4", body: Buffer.from("mock-video") }),
  );
});

async function loadExplorer(page) {
  await page.goto("/");
  await page.locator("#project-input").fill(projectId);
  await page.locator("#job-input").fill(jobId);
  await page.getByRole("button", { name: /load graph/i }).click();
  await expect(page.locator("#story-video")).toBeVisible();
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

  await page.locator('[data-edge="character-shot"]').click();

  await expect(page.getByText("Unaligned narration")).toBeVisible();
  await expect(page.locator(".evidence-card [data-jump-time]")).toHaveCount(0);
  await expect.poll(() => video.evaluate(el => el.currentTime)).toBe(8.5);
  await expect(page.locator(".evidence-card .evidence-time")).toHaveText("Time unavailable");
});
