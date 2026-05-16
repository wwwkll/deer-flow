import { expect, test, describe } from "vitest";

import {
  _TEST_CONSTANTS,
  _testBuildResumePrompt,
  _testShouldResume,
  _testHasRequiredChapters,
  _testDetectErrorPattern,
} from "@/hooks/use-auto-resume-monitor";

// ---------------------------------------------------------------------------
// buildResumePrompt tests
// ---------------------------------------------------------------------------

describe("buildResumePrompt", () => {
  test("generates correct prompt with detected chapters (shows recent 5)", () => {
    const prompt = _testBuildResumePrompt(
      [1, 2, 3, 96, 97, 98, 99, 100],
      100,
    );
    expect(prompt).toContain("【自动续传监控】");
    expect(prompt).toContain("距离目标章节100章");
    expect(prompt).toContain("第96章、第97章、第98章、第99章、第100章");
    expect(prompt).not.toContain("第1章");
    expect(prompt).toContain("<system_notification>");
    expect(prompt).toContain("</system_notification>");
  });

  test("shows missing chapters when gaps exist", () => {
    const prompt = _testBuildResumePrompt([1, 2, 4, 46, 47], 50);
    expect(prompt).toContain("距离目标章节50章");
    expect(prompt).toContain("最近5章已检测到：第1章、第2章、第4章、第46章、第47章");
    expect(prompt).toContain("第3、5、6");
    expect(prompt).toContain("章缺失");
    expect(prompt).toContain("请自行补充后继续写");
  });

  test("no missing info when chapters are contiguous", () => {
    const prompt = _testBuildResumePrompt([1, 2, 3, 4, 5], 10);
    expect(prompt).toContain("第1章、第2章、第3章、第4章、第5章");
    expect(prompt).not.toContain("缺失");
  });

  test("generates prompt with no detected chapters", () => {
    const prompt = _testBuildResumePrompt([], 50);
    expect(prompt).toContain("最近5章已检测到：无");
    expect(prompt).toContain("距离目标章节50章");
  });

  test("includes file naming instruction", () => {
    const prompt = _testBuildResumePrompt([1, 2], 10);
    expect(prompt).toContain("第N章.md");
    expect(prompt).toContain("文件名是否符合规范");
  });

  test("includes monitoring notification", () => {
    const prompt = _testBuildResumePrompt([], 5);
    expect(prompt).toContain("你正在被自动续传系统监控");
    expect(prompt).toContain("严格按照步骤逐章写作");
    expect(prompt).toContain("writing工作流");
  });

  test("shows fewer than 5 chapters when less than 5 detected", () => {
    const prompt = _testBuildResumePrompt([20], 50);
    expect(prompt).toContain("最近5章已检测到：第20章");
  });

  test("detects multiple missing chapters", () => {
    const prompt = _testBuildResumePrompt([1, 5, 10], 15);
    expect(prompt).toContain("第2、3、4、6、7、8、9章缺失");
  });
});

// ---------------------------------------------------------------------------
// hasRequiredChapters tests
// ---------------------------------------------------------------------------

describe("hasRequiredChapters", () => {
  test("returns true when all 5 chapters near target are present", () => {
    expect(_testHasRequiredChapters([96, 97, 98, 99, 100], 100)).toBe(true);
  });

  test("returns false when fewer than 5 chapters are present", () => {
    expect(_testHasRequiredChapters([96, 97, 98], 100)).toBe(false);
  });

  test("returns false when no chapters are present", () => {
    expect(_testHasRequiredChapters([], 100)).toBe(false);
  });

  test("handles target less than 5", () => {
    expect(_testHasRequiredChapters([1, 2, 3, 4], 4)).toBe(true);
  });

  test("handles target of 1", () => {
    expect(_testHasRequiredChapters([1], 1)).toBe(true);
  });

  test("returns false when chapters are outside the required range", () => {
    expect(_testHasRequiredChapters([90, 91, 92, 93, 94], 100)).toBe(false);
  });

  test("works with extra chapters present", () => {
    expect(
      _testHasRequiredChapters([90, 95, 96, 97, 98, 99, 100, 101], 100),
    ).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// shouldResume tests
// ---------------------------------------------------------------------------

describe("shouldResume", () => {
  test("returns true when not enough chapters near target", () => {
    expect(_testShouldResume([96, 97, 98], 100)).toBe(true);
    expect(_testShouldResume([], 1)).toBe(true);
  });

  test("returns false when enough chapters near target", () => {
    expect(_testShouldResume([96, 97, 98, 99, 100], 100)).toBe(false);
    expect(_testShouldResume([1], 1)).toBe(false);
  });

  test("returns true when chapters are outside required range", () => {
    expect(_testShouldResume([90, 91, 92, 93, 94], 100)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// detectErrorPattern (anti-stuck mechanism) tests
// ---------------------------------------------------------------------------

describe("detectErrorPattern", () => {
  test("no detection with fewer than 3 stops", () => {
    const now = Date.now();
    const stops = [now - 1000, now - 500];
    const result = _testDetectErrorPattern(stops);
    expect(result.detected).toBe(false);
  });

  test("detects pattern: 3 stops within 2 minutes", () => {
    const now = Date.now();
    const stops = [now - 60000, now - 30000, now - 1000];
    const result = _testDetectErrorPattern(stops);
    expect(result.detected).toBe(true);
    expect(result.shouldPause).toBe(true);
  });

  test("no detection: 3 stops spread over > 2 minutes", () => {
    const now = Date.now();
    const stops = [now - 200000, now - 100000, now - 1000];
    const result = _testDetectErrorPattern(stops);
    expect(result.detected).toBe(false);
  });

  test("prunes stops older than the window", () => {
    const now = Date.now();
    const stops = [now - 5 * 60 * 1000, now - 60000, now - 30000, now - 1000];
    const recent = stops.filter(
      (t) => now - t <= _TEST_CONSTANTS.MAX_STOP_WINDOW_MS * 2,
    );
    expect(recent.length).toBe(3);
    expect(recent[0]).toBe(stops[1]);
  });

  test("exactly at 2 minute boundary is detected", () => {
    const now = Date.now();
    const stops = [
      now - _TEST_CONSTANTS.MAX_STOP_WINDOW_MS,
      now - _TEST_CONSTANTS.MAX_STOP_WINDOW_MS / 2,
      now - 1000,
    ];
    const result = _testDetectErrorPattern(stops);
    expect(result.detected).toBe(true);
  });

  test("just over 2 minute boundary is not detected", () => {
    const now = Date.now();
    const stops = [
      now - _TEST_CONSTANTS.MAX_STOP_WINDOW_MS - 2000,
      now - _TEST_CONSTANTS.MAX_STOP_WINDOW_MS / 2,
      now - 1000,
    ];
    const result = _testDetectErrorPattern(stops);
    expect(result.detected).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Constants tests
// ---------------------------------------------------------------------------

describe("constants", () => {
  test("MAX_STOP_WINDOW_MS is 2 minutes", () => {
    expect(_TEST_CONSTANTS.MAX_STOP_WINDOW_MS).toBe(2 * 60 * 1000);
  });

  test("PAUSE_RETRY_MS is 10 minutes", () => {
    expect(_TEST_CONSTANTS.PAUSE_RETRY_MS).toBe(10 * 60 * 1000);
  });

  test("STOP_COUNT_THRESHOLD is 3", () => {
    expect(_TEST_CONSTANTS.STOP_COUNT_THRESHOLD).toBe(3);
  });

  test("MAX_RETRY_ROUNDS is 1", () => {
    expect(_TEST_CONSTANTS.MAX_RETRY_ROUNDS).toBe(1);
  });
});
