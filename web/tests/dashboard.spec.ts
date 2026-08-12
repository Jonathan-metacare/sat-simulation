import { expect, test } from "@playwright/test";

test("renders stepwise mission controls and AI mode dialog", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "星上智能计算数字孪生" })).toBeVisible();
  await expect(page.getByText("轨道态势与过站窗口")).toBeVisible();
  await expect(page.getByText("智能载荷 Provider")).toBeVisible();

  const create = page.getByRole("button", { name: /新建观测任务/ });
  await expect(create).toBeVisible();
  if (await create.isEnabled()) {
    await create.click();
    await expect(page.getByText("系统将创建独立 Run")).toBeVisible();
    await expect(page.getByRole("button", { name: /YOLO 检测/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /LLM 分析/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "初始化任务" })).toBeVisible();
  }
});
