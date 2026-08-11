import { expect, test } from "@playwright/test";
test("renders mission control surfaces",async({page})=>{await page.goto("/");await expect(page.getByRole("heading",{name:"星上智能计算数字孪生"})).toBeVisible();await expect(page.getByText("轨道态势与过站窗口")).toBeVisible();await expect(page.getByRole("button",{name:/新建观测任务/})).toBeVisible();await expect(page.getByText("智能载荷 Provider")).toBeVisible();});
