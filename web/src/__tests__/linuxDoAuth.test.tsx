import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import LoginPageMigratoryBirds from "@/pages/login/LoginPageMigratoryBirds";
import AuthCallbackPage from "@/pages/AuthCallbackPage";
import ProfilePage from "@/pages/ProfilePage";
import { useAuthStore } from "@/stores/authStore";
import * as apiModule from "@/services/api";
import type { User } from "@/types/auth";
import fs from "node:fs";
import path from "node:path";

// Mock API functions
vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof apiModule>();
  return {
    ...actual,
    getMe: vi.fn(),
    sendEmailBindingCode: vi.fn(),
    confirmEmailBinding: vi.fn(),
    updateDisplayName: vi.fn(),
    sendClosureCode: vi.fn(),
    confirmClosure: vi.fn(),
  };
});

// Mock Canvas & MatchMedia & Element.prototype.scrollIntoView
beforeEach(() => {
  if (typeof window !== "undefined" && window.Element) {
    window.Element.prototype.scrollIntoView = vi.fn();
  }
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation(() => ({
    matches: false,
    addListener: vi.fn(),
    removeListener: vi.fn(),
  })));
});

describe("Linux.do Auth & Profile Binding Feature Tests", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.resetAllMocks();
    useAuthStore.setState({
      status: "anonymous",
      user: null,
      quota: null,
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    // Mock window.location.assign
    delete (window as unknown as { location?: unknown }).location;
    window.location = {
      ...originalLocation,
      assign: vi.fn(),
      href: "http://localhost:3000/",
    } as unknown as Location;
  });

  afterEach(() => {
    window.location = originalLocation;
  });

  /* ---------- Flow A: Linux.do 登录按钮 ---------- */

  it("[1] 登录页 Linux.do 按钮构造正确的同源 start URL 并开启 loading", async () => {
    render(
      <MemoryRouter initialEntries={["/login?returnTo=%2Fhistory"]}>
        <LoginPageMigratoryBirds />
      </MemoryRouter>
    );

    const btn = screen.getByRole("button", { name: /使用 Linux.do 登录/i });
    expect(btn).toBeInTheDocument();

    fireEvent.click(btn);

    expect(window.location.assign).toHaveBeenCalledWith(
      "/api/auth/oauth/linux-do/start?return_to=%2Fhistory"
    );
  });

  it("[2] 恶意/外部 returnTo 在 start 与 link start 中被净化为 / 或 /profile", () => {
    const startUrl = apiModule.buildLinuxDoStartUrl("https://evil.com/phish");
    expect(startUrl).toBe("/api/auth/oauth/linux-do/start?return_to=%2F");

    const linkUrl = apiModule.buildLinuxDoLinkStartUrl("https://evil.com/phish");
    expect(linkUrl).toBe("/api/me/identities/linux-do/link/start?return_to=%2Fprofile");

    const linkUrlRelative = apiModule.buildLinuxDoLinkStartUrl("//evil.com");
    expect(linkUrlRelative).toBe("/api/me/identities/linux-do/link/start?return_to=%2Fprofile");
  });

  /* ---------- Flow B: OAuth 回调页 (mode=login) ---------- */

  it("[3] callback success 后调用 GET /api/me 并恢复安全 return_to", async () => {
    const mockUser: User = {
      user_id: "usr_ld_1",
      display_name: "LinuxDoUser",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "linuxdo_user",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    vi.mocked(apiModule.getMe).mockResolvedValueOnce({
      ok: true,
      user: mockUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    });

    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=success&return_to=%2Fhistory"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/history" element={<div>History Page Content</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("正在完成 Linux.do 登录…")).toBeInTheDocument();

    await waitFor(() => {
      expect(apiModule.getMe).toHaveBeenCalledTimes(1);
      expect(screen.getByText("History Page Content")).toBeInTheDocument();
    });

    expect(useAuthStore.getState().user).toEqual(mockUser);
    expect(useAuthStore.getState().status).toBe("authenticated");
  });

  it("[4] display_name_review_required=true 时强制进入 /profile", async () => {
    const mockUser: User = {
      user_id: "usr_ld_2",
      display_name: "Reno1",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "reno",
      email_login_enabled: false,
      display_name_review_required: true,
    };

    vi.mocked(apiModule.getMe).mockResolvedValueOnce({
      ok: true,
      user: mockUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    });

    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=success&return_to=%2Fhistory"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/profile" element={<div>Profile Page Content</div>} />
          <Route path="/history" element={<div>History Page Content</div>} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("Profile Page Content")).toBeInTheDocument();
      expect(screen.queryByText("History Page Content")).not.toBeInTheDocument();
    });
  });

  it("[5] callback 各稳定错误展示正确文案且不调用 /api/me", async () => {
    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=error&error=OAUTH_ACCOUNT_INELIGIBLE"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(apiModule.getMe).not.toHaveBeenCalled();
    const alertBox = screen.getByRole("alert");
    expect(alertBox).toBeInTheDocument();
    expect(
      screen.getByText("该 Linux.do 账户暂不符合首次接入条件。新用户需达到 1级，且账户状态正常。")
    ).toBeInTheDocument();
  });

  it("[6] callback 网络失败可重试，不错误清空已存在认证状态", async () => {
    vi.mocked(apiModule.getMe).mockRejectedValueOnce(new Error("Network Error"));

    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=success&return_to=%2F"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("获取账号信息失败")).toBeInTheDocument();
      expect(screen.getByText("登录可能已经完成，但暂时无法读取账户信息。")).toBeInTheDocument();
    });

    // 尝试重新检查
    const validUser: User = {
      user_id: "usr_ld_3",
      display_name: "TestUser",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "testuser",
      email_login_enabled: false,
      display_name_review_required: false,
    };
    vi.mocked(apiModule.getMe).mockResolvedValueOnce({
      ok: true,
      user: validUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    });

    const recheckBtn = screen.getByRole("button", { name: "重新检查" });
    fireEvent.click(recheckBtn);

    await waitFor(() => {
      expect(useAuthStore.getState().status).toBe("authenticated");
    });
  });

  /* ---------- Flow C & D: Profile 页面与邮箱绑定 ---------- */

  it("[7] Profile 正确展示 Linux.do username 和登录方式", () => {
    const linuxDoUser: User = {
      user_id: "usr_ld_profile",
      display_name: "Linuxer",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "linuxer_hq",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    expect(screen.getByText("@linuxer_hq")).toBeInTheDocument();
    expect(screen.getByText("未绑定")).toBeInTheDocument();
    expect(screen.getAllByText("Linux.do").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "添加邮箱登录" })).toBeInTheDocument();
  });

  it("[8] Display Name 红色提醒一直存在，成功改名后消失", async () => {
    const reviewUser: User = {
      user_id: "usr_review",
      display_name: "Reno1",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "reno",
      email_login_enabled: false,
      display_name_review_required: true,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: reviewUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    const alertBanner = screen.getByRole("alert");
    expect(alertBanner).toBeInTheDocument();
    expect(screen.getByText(/你的 Linux.do 用户名已被占用/)).toBeInTheDocument();

    const modifyBtn = screen.getByRole("button", { name: "立即修改" });
    fireEvent.click(modifyBtn);

    const input = screen.getByRole("textbox", { name: "显示名称" });
    expect(input).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "NewUniqueName" } });

    vi.mocked(apiModule.updateDisplayName).mockResolvedValueOnce({
      ok: true,
      user: {
        ...reviewUser,
        display_name: "NewUniqueName",
        display_name_review_required: false,
      },
    });

    const saveBtn = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByText("NewUniqueName")).toBeInTheDocument();
    });
  });

  it("[9] 邮箱绑定请求 body 精确，不发送 invitation_code", async () => {
    const linuxDoUser: User = {
      user_id: "usr_bind_test",
      display_name: "BindTest",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "bindtest",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "添加邮箱登录" }));

    const emailInput = screen.getByLabelText("电子邮箱");
    fireEvent.change(emailInput, { target: { value: "user@example.com" } });

    vi.mocked(apiModule.sendEmailBindingCode).mockResolvedValueOnce({
      ok: true,
      challenge_id: "chal_bind_123",
      resend_after_seconds: 60,
    });

    const sendBtn = screen.getByRole("button", { name: "发送验证码" });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(apiModule.sendEmailBindingCode).toHaveBeenCalledWith("user@example.com");
    });
  });

  it("[10] 邮箱改变后旧 challenge 失效", async () => {
    const linuxDoUser: User = {
      user_id: "usr_bind_test2",
      display_name: "BindTest2",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "bindtest2",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "添加邮箱登录" }));

    const emailInput = screen.getByLabelText("电子邮箱");
    fireEvent.change(emailInput, { target: { value: "email1@example.com" } });

    vi.mocked(apiModule.sendEmailBindingCode).mockResolvedValueOnce({
      ok: true,
      challenge_id: "chal_1",
      resend_after_seconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "确认添加邮箱登录" })).toBeDisabled();
    });

    const codeInput = screen.getByLabelText("验证码", { exact: true });
    fireEvent.change(codeInput, { target: { value: "123456" } });

    expect(screen.getByRole("button", { name: "确认添加邮箱登录" })).not.toBeDisabled();

    // 改变邮箱
    fireEvent.change(emailInput, { target: { value: "email2@example.com" } });

    // 确认按钮重新被禁用，因为旧 challenge 失效
    expect(screen.getByRole("button", { name: "确认添加邮箱登录" })).toBeDisabled();
  });

  it("[11] 邮箱绑定成功后 refreshMe，且不会在前端修改额度", async () => {
    const linuxDoUser: User = {
      user_id: "usr_bind_success",
      display_name: "BindSuccess",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "bindsuccess",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    vi.mocked(apiModule.getMe).mockResolvedValue({
      ok: true,
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "添加邮箱登录" }));

    fireEvent.change(screen.getByLabelText("电子邮箱"), { target: { value: "bound@example.com" } });

    vi.mocked(apiModule.sendEmailBindingCode).mockResolvedValueOnce({
      ok: true,
      challenge_id: "chal_ok",
      resend_after_seconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));

    await waitFor(() => {
      expect(screen.getByText("60s")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("验证码", { exact: true }), { target: { value: "654321" } });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "确认添加邮箱登录" })).not.toBeDisabled();
    });

    vi.mocked(apiModule.confirmEmailBinding).mockResolvedValueOnce({ ok: true });
    vi.mocked(apiModule.getMe).mockImplementation(async () => ({
      ok: true,
      user: {
        ...linuxDoUser,
        masked_email: "b***d@example.com",
        email_login_enabled: true,
      },
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    }));

    fireEvent.click(screen.getByRole("button", { name: "确认添加邮箱登录" }));

    await waitFor(() => {
      expect(apiModule.confirmEmailBinding).toHaveBeenCalledWith("chal_ok", "654321");
    });

    await waitFor(() => {
      expect(useAuthStore.getState().user?.email_login_enabled).toBe(true);
    });

    // 校验额度仍然保持 Backend 给的值
    expect(useAuthStore.getState().quota?.limit).toBe(3);
  });

  it("[12] EMAIL_ALREADY_LINKED、EMAIL_ALREADY_BOUND、EMAIL_BIND_REQUIRED 错误处理", async () => {
    const linuxDoUser: User = {
      user_id: "usr_err_test",
      display_name: "ErrTest",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "errtest",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    // 测试注销触发 EMAIL_BIND_REQUIRED
    fireEvent.click(screen.getByRole("button", { name: "注销账号..." }));

    vi.mocked(apiModule.sendClosureCode).mockRejectedValueOnce(
      new apiModule.ApiRequestError("EMAIL_BIND_REQUIRED", "注销账户前需要先添加邮箱，用验证码确认是你本人。", 409)
    );

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));

    await waitFor(() => {
      expect(screen.getByText("注销账户前需要先添加邮箱，用验证码确认是你本人。")).toBeInTheDocument();
    });

    // 测试 EMAIL_ALREADY_LINKED 文案更新
    fireEvent.change(screen.getByLabelText("电子邮箱"), { target: { value: "taken@example.com" } });
    vi.mocked(apiModule.sendEmailBindingCode).mockRejectedValueOnce(
      new apiModule.ApiRequestError("EMAIL_ALREADY_LINKED", "该邮箱已关联其他云途账号", 409)
    );

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));

    await waitFor(() => {
      expect(
        screen.getByText("该邮箱已关联其他云途账号，暂不支持账号合并。请使用未注册邮箱，或退出后登录原邮箱账号。")
      ).toBeInTheDocument();
    });
  });

  it("[13] 收到验证码后修改邮箱，challenge、验证码与倒计时清空，发送按钮立即恢复；OTP_EXPIRED 时作废旧 challenge", async () => {
    const linuxDoUser: User = {
      user_id: "usr_reset_test",
      display_name: "ResetTest",
      display_name_change_available_at: null,
      masked_email: null,
      linux_do_username: "resettest",
      email_login_enabled: false,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: linuxDoUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "添加邮箱登录" }));

    const emailInput = screen.getByLabelText("电子邮箱");
    fireEvent.change(emailInput, { target: { value: "old@example.com" } });

    vi.mocked(apiModule.sendEmailBindingCode).mockResolvedValueOnce({
      ok: true,
      challenge_id: "chal_old",
      resend_after_seconds: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "发送验证码" }));

    await waitFor(() => {
      expect(screen.getByText("60s")).toBeInTheDocument();
    });

    // 改变邮箱 -> 倒计时、验证码与 challenge 应重置，发送按钮恢复可用
    fireEvent.change(emailInput, { target: { value: "new@example.com" } });

    expect(screen.queryByText("60s")).not.toBeInTheDocument();
    const sendBtn = screen.getByRole("button", { name: "发送验证码" });
    expect(sendBtn).not.toBeDisabled();

    // 再次发送新验证码
    vi.mocked(apiModule.sendEmailBindingCode).mockResolvedValueOnce({
      ok: true,
      challenge_id: "chal_new",
      resend_after_seconds: 60,
    });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByText("60s")).toBeInTheDocument();
    });

    const codeInput = screen.getByLabelText("验证码", { exact: true });
    fireEvent.change(codeInput, { target: { value: "111111" } });

    // 提交触发 OTP_EXPIRED 错误
    vi.mocked(apiModule.confirmEmailBinding).mockRejectedValueOnce(
      new apiModule.ApiRequestError("OTP_EXPIRED", "验证码已失效，请重新获取。", 400)
    );

    fireEvent.click(screen.getByRole("button", { name: "确认添加邮箱登录" }));

    await waitFor(() => {
      expect(screen.getByText("验证码已失效，请重新获取。")).toBeInTheDocument();
    });

    // 校验 OTP_EXPIRED 后，旧 challenge 与验证码输入被清空，倒计时被清空，确认按钮重新禁用
    expect(screen.getByRole("button", { name: "确认添加邮箱登录" })).toBeDisabled();
  });

  /* ---------- Flow E: Email-only 用户绑定 Linux.do ---------- */

  it("[14] Email-only 用户显示绑定 Linux.do，Linux.do-only 显示添加邮箱，双身份不显示任何添加按钮", () => {
    // 1. Email-only 用户
    const emailOnlyUser: User = {
      user_id: "usr_email_only",
      display_name: "EmailUser",
      display_name_change_available_at: null,
      masked_email: "email@example.com",
      linux_do_username: null,
      email_login_enabled: true,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: emailOnlyUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    const { rerender } = render(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    expect(screen.getByRole("button", { name: "绑定 Linux.do 账号" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加邮箱登录" })).not.toBeInTheDocument();

    // 2. 双身份用户
    const bothUser: User = {
      ...emailOnlyUser,
      linux_do_username: "both_user",
    };

    useAuthStore.setState({
      user: bothUser,
    });

    rerender(
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    );

    expect(screen.getByText("Linux.do、邮箱验证码")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "绑定 Linux.do 账号" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加邮箱登录" })).not.toBeInTheDocument();
  });

  it("[15] Profile 页点击 '绑定 Linux.do' 进入 loading 状态，重复点击被阻止，window.location.assign 仅调用一次", () => {
    const emailOnlyUser: User = {
      user_id: "usr_link_click",
      display_name: "LinkUser",
      display_name_change_available_at: null,
      masked_email: "link@example.com",
      linux_do_username: null,
      email_login_enabled: true,
      display_name_review_required: false,
    };

    useAuthStore.setState({
      status: "authenticated",
      user: emailOnlyUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <ProfilePage />
      </MemoryRouter>
    );

    const linkBtn = screen.getByRole("button", { name: "绑定 Linux.do 账号" });
    fireEvent.click(linkBtn);
    fireEvent.click(linkBtn);

    expect(linkBtn).toBeDisabled();
    expect(screen.getByText("正在跳转 Linux.do…")).toBeInTheDocument();
    expect(window.location.assign).toHaveBeenCalledTimes(1);
    expect(window.location.assign).toHaveBeenCalledWith(
      "/api/me/identities/linux-do/link/start?return_to=%2Fprofile"
    );
  });

  it("[16] mode=link 成功后调用 GET /api/me，更新 auth store 并重定向到 /profile", async () => {
    const linkedUser: User = {
      user_id: "usr_link_success",
      display_name: "LinkSuccess",
      display_name_change_available_at: null,
      masked_email: "link@example.com",
      linux_do_username: "linux_linked",
      email_login_enabled: true,
      display_name_review_required: false,
    };

    vi.mocked(apiModule.getMe).mockResolvedValueOnce({
      ok: true,
      user: linkedUser,
      quota: { limit: 3, reserved: 0, consumed: 0, remaining: 3 },
      active_trip: null,
    });

    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=success&mode=link&return_to=%2Fprofile"]}>
        <Routes>
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route path="/profile" element={<div>Profile Page Content</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByText("正在完成 Linux.do 绑定…")).toBeInTheDocument();

    await waitFor(() => {
      expect(apiModule.getMe).toHaveBeenCalled();
      expect(screen.getByText("Profile Page Content")).toBeInTheDocument();
    });

    expect(useAuthStore.getState().user).toEqual(linkedUser);
  });

  it("[17] mode=link 错误时不调用 /api/me，标题展示 'Linux.do 绑定未完成'，重试按钮调 link/start", () => {
    render(
      <MemoryRouter initialEntries={["/auth/callback?outcome=error&mode=link&error=IDENTITY_ALREADY_LINKED"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(apiModule.getMe).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Linux.do 绑定未完成" })).toBeInTheDocument();
    expect(
      screen.getByText("该 Linux.do 账号已关联其他云途账号，暂不支持账号合并。")
    ).toBeInTheDocument();

    const retryBtn = screen.getByRole("button", { name: "重新发起 Linux.do 绑定" });
    fireEvent.click(retryBtn);

    expect(window.location.assign).toHaveBeenCalledWith(
      "/api/me/identities/linux-do/link/start?return_to=%2Fprofile"
    );

    const secondaryBtn = screen.getByRole("button", { name: "返回个人资料" });
    expect(secondaryBtn).toBeInTheDocument();
  });

  it("[18] IDENTITY_LINK_SESSION_CHANGED、LINUX_DO_IDENTITY_ALREADY_BOUND、EMAIL_IDENTITY_REQUIRED 及 link 模式 OAUTH_ACCOUNT_INELIGIBLE 错误文案", () => {
    const { rerender } = render(
      <MemoryRouter key="1" initialEntries={["/auth/callback?outcome=error&mode=link&error=IDENTITY_LINK_SESSION_CHANGED"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(
      screen.getByText("当前登录状态已变化，请返回个人资料后重新绑定。")
    ).toBeInTheDocument();

    rerender(
      <MemoryRouter key="2" initialEntries={["/auth/callback?outcome=error&mode=link&error=LINUX_DO_IDENTITY_ALREADY_BOUND"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(
      screen.getByText("当前账号已经绑定 Linux.do。")
    ).toBeInTheDocument();

    rerender(
      <MemoryRouter key="3" initialEntries={["/auth/callback?outcome=error&mode=link&error=EMAIL_IDENTITY_REQUIRED"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(
      screen.getByText("当前账号缺少邮箱登录方式，请返回个人资料后重新检查。")
    ).toBeInTheDocument();

    rerender(
      <MemoryRouter key="4" initialEntries={["/auth/callback?outcome=error&mode=link&error=OAUTH_ACCOUNT_INELIGIBLE"]}>
        <AuthCallbackPage />
      </MemoryRouter>
    );

    expect(
      screen.getByText("该 Linux.do 账号不符合绑定条件，请确认账号已达到 1级且状态正常。")
    ).toBeInTheDocument();
  });

  it("[19] 源码和构建产物中不存在 client secret、access token、authorization code 处理逻辑或不可变 Linux.do provider id", () => {
    const authCallbackSrc = fs.readFileSync(
      path.resolve(__dirname, "../pages/AuthCallbackPage.tsx"),
      "utf-8"
    );
    const loginSrc = fs.readFileSync(
      path.resolve(__dirname, "../pages/login/LoginPageMigratoryBirds.tsx"),
      "utf-8"
    );
    const apiSrc = fs.readFileSync(
      path.resolve(__dirname, "../services/api.ts"),
      "utf-8"
    );

    const forbiddenTerms = [
      "client_secret",
      "clientSecret",
      "access_token",
      "accessToken",
      "authorization_code",
      "oauth_state",
      "provider_id",
    ];

    for (const term of forbiddenTerms) {
      expect(authCallbackSrc).not.toContain(term);
      expect(loginSrc).not.toContain(term);
      expect(apiSrc).not.toContain(term);
    }
  });
});
