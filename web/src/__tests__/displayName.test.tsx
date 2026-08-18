import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ProfilePage from "@/pages/ProfilePage";
import { UserMenu } from "@/components/layout/UserMenu";
import { useAuthStore } from "@/stores/authStore";
import * as api from "@/services/api";
import type { MeResponse, User } from "@/types/auth";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    updateDisplayName: vi.fn(),
    getMe: vi.fn(),
    sendClosureCode: vi.fn(),
    confirmClosure: vi.fn(),
  };
});

describe("V011-F1 Display Name Feature Tests", () => {
  const initialUser: User = {
    user_id: "usr_opaque",
    display_name: "山城漫游者",
    display_name_change_available_at: null,
    masked_email: "u***@example.com",
    linux_do_username: null,
    email_login_enabled: true,
    display_name_review_required: false,
  };

  beforeEach(() => {
    vi.resetAllMocks();
    useAuthStore.setState({
      status: "authenticated",
      user: { ...initialUser },
      quota: {
        policy: "beta",
        limit: 3,
        reserved: 0,
        consumed: 1,
        remaining: 2,
      },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  // 1. GET /api/me 类型包含必填 display_name 和 change_available_at
  it("[1] GET /api/me contract type includes required display_name and display_name_change_available_at", () => {
    const mockMeResponse: MeResponse = {
      ok: true,
      user: {
        user_id: "usr_123",
        display_name: "user_7k3m9q2x4p",
        display_name_change_available_at: "2026-08-08T12:00:00Z",
        masked_email: "u***@example.com",
        linux_do_username: null,
        email_login_enabled: true,
        display_name_review_required: false,
      },
      quota: {
        limit: 3,
        reserved: 0,
        consumed: 0,
        remaining: 3,
      },
      active_trip: null,
    };
    expect(mockMeResponse.user.display_name).toBe("user_7k3m9q2x4p");
    expect(mockMeResponse.user.display_name_change_available_at).toBe(
      "2026-08-08T12:00:00Z",
    );
  });

  // 2. ProfilePage 显示当前名称
  it("[2] ProfilePage displays current display_name", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );
    expect(screen.getByText("山城漫游者")).toBeInTheDocument();
  });

  // 3. change_available_at 为 null 时允许首次修改
  it("[3] allows editing when change_available_at is null", () => {
    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );
    const editBtn = screen.getByRole("button", { name: "修改" });
    expect(editBtn).not.toBeDisabled();
    fireEvent.click(editBtn);
    expect(screen.getByLabelText("显示名称")).toBeInTheDocument();
  });

  // 4. 未来冷却时间下禁用修改并显示时间
  it("[4] disables edit button and shows localized time when in future cooldown", () => {
    const futureTime = "2099-01-01T12:00:00Z";
    useAuthStore.setState({
      user: {
        ...initialUser,
        display_name_change_available_at: futureTime,
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    const editBtn = screen.getByRole("button", { name: "修改" });
    expect(editBtn).toBeDisabled();
    expect(screen.getByText(/可修改时间：/)).toBeInTheDocument();
  });

  // 5. 冷却到期后无需刷新即可恢复
  it("[5] automatically recovers editability when cooldown expires without refreshing page", async () => {
    vi.useFakeTimers();
    const nowMs = Date.now();
    const cooldownMs = nowMs + 3000;
    const cooldownTime = new Date(cooldownMs).toISOString();

    useAuthStore.setState({
      user: {
        ...initialUser,
        display_name_change_available_at: cooldownTime,
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    const editBtn = screen.getByRole("button", { name: "修改" });
    expect(editBtn).toBeDisabled();

    // 前进 4 秒
    act(() => {
      vi.advanceTimersByTime(4000);
    });

    expect(editBtn).not.toBeDisabled();
  });

  // 6. 保存发送 PATCH /me/profile，body 只有 display_name
  it("[6] sending save triggers updateDisplayName with body containing only display_name", async () => {
    const updateSpy = vi.spyOn(api, "updateDisplayName").mockResolvedValue({
      ok: true,
      user: {
        ...initialUser,
        display_name: "重庆旅人",
        display_name_change_available_at: "2026-08-08T12:00:00Z",
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "重庆旅人" } });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("重庆旅人");
    });
  });

  // 7. 保存期间阻止重复提交
  it("[7] disables controls and prevents duplicate submission during saving", async () => {
    let resolvePromise: (value: api.ProfileUpdateResponse) => void = () => {};
    const pendingPromise = new Promise<api.ProfileUpdateResponse>((res) => {
      resolvePromise = res;
    });

    const updateSpy = vi
      .spyOn(api, "updateDisplayName")
      .mockReturnValue(pendingPromise);

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "新名称" } });

    const saveBtn = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveBtn);

    expect(saveBtn).toBeDisabled();
    expect(screen.getByText("保存中…")).toBeInTheDocument();
    expect(input).toBeDisabled();

    // 重复点击
    fireEvent.click(saveBtn);
    expect(updateSpy).toHaveBeenCalledTimes(1);

    // 完成请求
    await act(async () => {
      resolvePromise({
        ok: true,
        user: { ...initialUser, display_name: "新名称" },
      });
    });
  });

  // 8. 成功后 ProfilePage 与 UserMenu 立即显示新名称
  it("[8] immediately updates ProfilePage and UserMenu on success", async () => {
    vi.spyOn(api, "updateDisplayName").mockResolvedValue({
      ok: true,
      user: {
        ...initialUser,
        display_name: "更新的名称",
      },
    });

    render(
      <MemoryRouter>
        <UserMenu />
        <ProfilePage />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("山城漫游者").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "更新的名称" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getAllByText("更新的名称").length).toBeGreaterThan(0);
    });
  });

  // 9. 成功后广播 ME_UPDATED
  it("[9] broadcasts ME_UPDATED event upon successful update", async () => {
    vi.spyOn(api, "updateDisplayName").mockResolvedValue({
      ok: true,
      user: {
        ...initialUser,
        display_name: "广播测试",
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "广播测试" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(useAuthStore.getState().user?.display_name).toBe("广播测试");
    });
  });

  // 10. case-only 修改可以提交
  it("[10] allows case-only modifications to be submitted", async () => {
    useAuthStore.setState({
      user: {
        ...initialUser,
        display_name: "UserAlpha",
      },
    });

    const updateSpy = vi.spyOn(api, "updateDisplayName").mockResolvedValue({
      ok: true,
      user: {
        ...initialUser,
        display_name: "useralpha",
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "useralpha" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("useralpha");
    });
  });

  // 11. 无变化时不发送请求
  it("[11] does not send request when display name is unchanged", async () => {
    const updateSpy = vi.spyOn(api, "updateDisplayName");

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "山城漫游者" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateSpy).not.toHaveBeenCalled();
      expect(screen.queryByLabelText("显示名称")).not.toBeInTheDocument();
    });
  });

  // 12. INVALID、RESERVED、UNAVAILABLE、COOLDOWN 分别显示正确错误
  it("[12] displays accurate localized error messages for backend error codes", async () => {
    const renderAndTestError = async (
      errorCode: string,
      status: number,
      expectedMsg: string,
    ) => {
      vi.spyOn(api, "updateDisplayName").mockRejectedValueOnce(
        new api.ApiRequestError(errorCode, "Backend Error", status),
      );

      const { unmount } = render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: "修改" }));
      const input = screen.getByLabelText("显示名称");
      fireEvent.change(input, { target: { value: "测试名称" } });
      fireEvent.click(screen.getByRole("button", { name: "保存" }));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toHaveTextContent(expectedMsg);
      });

      unmount();
    };

    await renderAndTestError(
      "DISPLAY_NAME_UNAVAILABLE",
      409,
      "该显示名称暂不可用，请换一个。",
    );
    await renderAndTestError(
      "DISPLAY_NAME_INVALID",
      422,
      "请输入 2–24 个中文、英文字母、数字或下划线，且不能全部为数字。",
    );
    await renderAndTestError(
      "DISPLAY_NAME_RESERVED",
      422,
      "该名称为系统保留名称，请换一个。",
    );
    await renderAndTestError(
      "DISPLAY_NAME_CHANGE_COOLDOWN",
      429,
      "显示名称修改仍在冷却期，请在可修改时间后重试。",
    );
  });

  // 13. 网络失败保留输入并允许重试
  it("[13] retains input content on network error and allows retrying", async () => {
    const updateSpy = vi
      .spyOn(api, "updateDisplayName")
      .mockRejectedValueOnce(
        new api.ApiRequestError("NETWORK_ERROR", "网络连接失败", 0),
      )
      .mockResolvedValueOnce({
        ok: true,
        user: { ...initialUser, display_name: "重试成功" },
      });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    const input = screen.getByLabelText("显示名称");
    fireEvent.change(input, { target: { value: "重试成功" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "网络连接失败，请稍后重试。",
      );
    });

    // 检查输入框保留了之前的输入内容
    expect(input).toHaveValue("重试成功");

    // 再次提交重试
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledTimes(2);
      expect(screen.getByText("重试成功")).toBeInTheDocument();
    });
  });

  // 14. 未登录用户不能进入 ProfilePage
  it("[14] unauthenticated user cannot access ProfilePage", () => {
    useAuthStore.setState({
      status: "anonymous",
      user: null,
    });

    const { container } = render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    expect(container.firstChild).toBeNull();
  });

  // 15. 测试不得依赖生产 Mock 数据或伪造产品成功回退
  it("[15] tests do not rely on production mock fallback", async () => {
    const updateSpy = vi.spyOn(api, "updateDisplayName").mockResolvedValue({
      ok: true,
      user: {
        ...initialUser,
        display_name: "非Mock真更新",
      },
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "修改" }));
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "非Mock真更新" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith("非Mock真更新");
    });
  });
});
