import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import LoginPageMigratoryBirds from "@/pages/login/LoginPageMigratoryBirds";
import { useAuthStore } from "@/stores/authStore";
import * as api from "@/services/api";


// Mock Canvas 和 Card3D 组件（jsdom 不支持 Canvas）
vi.mock("@/components/common/MigratoryBirdsCanvas", () => ({
  MigratoryBirdsCanvas: () => <div data-testid="migratory-birds-canvas" />,
}));

vi.mock("@/components/common/Card3D", () => ({
  Card3D: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="card-3d">{children}</div>
  ),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    sendEmailCode: vi.fn(),
    verifyEmailCode: vi.fn(),
  };
});

const mockedSendEmailCode = vi.mocked(api.sendEmailCode);
const mockedVerifyEmailCode = vi.mocked(api.verifyEmailCode);

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <LoginPageMigratoryBirds />
    </MemoryRouter>,
  );
}

/** 点击"邀请码注册"标签 */
function switchToRegister() {
  fireEvent.click(screen.getByRole("button", { name: "邀请码注册" }));
}

/** 点击"邮箱登录"标签 */
function switchToLogin() {
  fireEvent.click(screen.getByRole("button", { name: "邮箱登录" }));
}

/** 填写邀请码 */
function fillInvitationCode(code: string) {
  fireEvent.change(screen.getByPlaceholderText("输入公测邀请码"), {
    target: { value: code },
  });
}

/** 填写邮箱 */
function fillEmail(email: string) {
  fireEvent.change(screen.getByPlaceholderText("name@example.com"), {
    target: { value: email },
  });
}

/** 填写验证码 */
function fillOtp(code: string) {
  fireEvent.change(screen.getByPlaceholderText("6位数字"), {
    target: { value: code },
  });
}

/** 点击发送验证码按钮 */
function clickSendCode() {
  // 发送验证码按钮在倒计时期间显示 "XXs"，发送中显示 spinner
  // 找 min-w-[110px] 的按钮（发送验证码按钮的唯一标识）
  const buttons = screen.getAllByRole("button");
  const sendBtn = buttons.find(
    (btn) => btn.textContent === "发送验证码" || /^\d+s$/.test(btn.textContent || ""),
  );
  if (sendBtn) {
    fireEvent.click(sendBtn);
  }
}

/** 提交表单（点击登录/注册按钮） */
function submitForm() {
  const submitBtn = screen.getByRole("button", { name: /登录进入云途|注册云途账号/ });
  fireEvent.click(submitBtn);
}

describe("LoginPageMigratoryBirds 验证码挑战状态管理", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });

    useAuthStore.setState({
      status: "anonymous",
      user: null,
      quota: null,
      activeTrip: null,
      bootstrapped: true,
      bootstrapError: null,
    });

    // 默认 mock：sendEmailCode 返回有效 challenge
    mockedSendEmailCode.mockResolvedValue({
      ok: true,
      challenge_id: "ch_register_001",
      resend_after_seconds: 60,
    });

    mockedVerifyEmailCode.mockResolvedValue({ ok: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ────────────────────────────────────────────────────────
  // 测试 1：注册发送验证码 → 切到登录 → 切回注册 → 原注册 challenge 仍可提交
  // ────────────────────────────────────────────────────────
  it("注册发送验证码 → 切换到登录 → 切回注册 → 使用原 challenge 提交成功", async () => {
    renderLogin();

    // 切到注册模式
    switchToRegister();
    fillInvitationCode("INVITE-001");
    fillEmail("test@example.com");

    // 发送验证码
    await act(async () => {
      clickSendCode();
    });

    expect(mockedSendEmailCode).toHaveBeenCalledWith(
      "register",
      "test@example.com",
      "INVITE-001",
    );

    // 切换到登录
    await act(async () => {
      switchToLogin();
    });

    // 切回注册
    await act(async () => {
      switchToRegister();
    });

    // 填写验证码并提交
    fillOtp("123456");

    // mock bootstrap
    const bootstrapMock = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ bootstrap: bootstrapMock });

    await act(async () => {
      submitForm();
    });

    // 应该用原 challenge 调用 verify
    expect(mockedVerifyEmailCode).toHaveBeenCalledWith("ch_register_001", "123456");
  });

  // ────────────────────────────────────────────────────────
  // 测试 2：注册模式倒计时在切换后继续计算，不重置
  // ────────────────────────────────────────────────────────
  it("注册模式倒计时在切换后继续计算，不从 60s 重置", async () => {
    renderLogin();

    switchToRegister();
    fillInvitationCode("INVITE-001");
    fillEmail("test@example.com");

    await act(async () => {
      clickSendCode();
    });

    // 验证倒计时开始（应显示 60s 或接近）
    expect(screen.getByText(/\d+s/)).toBeInTheDocument();

    // 推进 30 秒
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    // 切到登录
    await act(async () => {
      switchToLogin();
    });

    // 再过 10 秒
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    // 切回注册
    await act(async () => {
      switchToRegister();
    });

    // 剩余应约 20s，不是 60s
    const countdownText = screen.getByText(/\d+s/);
    const seconds = parseInt(countdownText.textContent || "0");
    expect(seconds).toBeLessThanOrEqual(21);
    expect(seconds).toBeGreaterThanOrEqual(18);
  });

  // ────────────────────────────────────────────────────────
  // 测试 3：注册 challenge 不能被登录模式使用
  // ────────────────────────────────────────────────────────
  it("注册 challenge 不能被登录模式使用", async () => {
    renderLogin();

    // 在注册模式发送验证码
    switchToRegister();
    fillInvitationCode("INVITE-001");
    fillEmail("test@example.com");

    await act(async () => {
      clickSendCode();
    });

    // 切到登录模式
    await act(async () => {
      switchToLogin();
    });

    // 尝试填写验证码并提交
    fillOtp("123456");

    await act(async () => {
      submitForm();
    });

    // 不应调用 verify（因为登录模式没有自己的 challenge）
    expect(mockedVerifyEmailCode).not.toHaveBeenCalled();
    // 应显示"请先获取邮箱验证码"
    expect(screen.getByText("请先获取邮箱验证码")).toBeInTheDocument();
  });

  // ────────────────────────────────────────────────────────
  // 测试 4：登录 challenge 不能被注册模式使用
  // ────────────────────────────────────────────────────────
  it("登录 challenge 不能被注册模式使用", async () => {
    mockedSendEmailCode.mockResolvedValue({
      ok: true,
      challenge_id: "ch_login_001",
      resend_after_seconds: 60,
    });

    renderLogin();

    // 在登录模式发送验证码
    fillEmail("test@example.com");

    await act(async () => {
      clickSendCode();
    });

    expect(mockedSendEmailCode).toHaveBeenCalledWith("login", "test@example.com", null);

    // 切到注册模式
    await act(async () => {
      switchToRegister();
    });

    // 尝试填写验证码并提交
    fillInvitationCode("INVITE-001");
    fillOtp("654321");

    await act(async () => {
      submitForm();
    });

    // 不应调用 verify（注册模式没有自己的 challenge）
    expect(mockedVerifyEmailCode).not.toHaveBeenCalled();
    expect(screen.getByText("请先获取邮箱验证码")).toBeInTheDocument();
  });

  // ────────────────────────────────────────────────────────
  // 测试 5：修改邮箱后旧 challenge 失效
  // ────────────────────────────────────────────────────────
  it("修改邮箱后旧 challenge 失效，要求重新获取验证码", async () => {
    renderLogin();

    // 在登录模式发送验证码
    fillEmail("old@example.com");

    await act(async () => {
      clickSendCode();
    });

    // 修改邮箱
    fillEmail("new@example.com");

    // 填写验证码并提交
    fillOtp("123456");

    await act(async () => {
      submitForm();
    });

    // 不应调用 verify
    expect(mockedVerifyEmailCode).not.toHaveBeenCalled();
    // 应提示重新获取
    expect(screen.getByText("请先获取邮箱验证码")).toBeInTheDocument();
  });

  // ────────────────────────────────────────────────────────
  // 测试 6：修改邀请码后旧注册 challenge 失效
  // ────────────────────────────────────────────────────────
  it("修改邀请码后旧注册 challenge 失效", async () => {
    renderLogin();

    switchToRegister();
    fillInvitationCode("INVITE-001");
    fillEmail("test@example.com");

    await act(async () => {
      clickSendCode();
    });

    // 修改邀请码
    fillInvitationCode("INVITE-002");

    // 填写验证码并提交
    fillOtp("123456");

    await act(async () => {
      submitForm();
    });

    // 不应调用 verify
    expect(mockedVerifyEmailCode).not.toHaveBeenCalled();
    expect(screen.getByText("请先获取邮箱验证码")).toBeInTheDocument();
  });

  // ────────────────────────────────────────────────────────
  // 测试 7：发送注册验证码请求尚未完成时切到登录，响应返回后仍归属于注册模式
  // ────────────────────────────────────────────────────────
  it("发送注册验证码请求未完成时切到登录，响应返回后归属注册模式", async () => {
    // 使用手动 resolve 的 promise 来控制时序
    let resolvePromise!: (value: { ok: boolean; challenge_id: string; resend_after_seconds: number }) => void;
    const pendingPromise = new Promise<{ ok: boolean; challenge_id: string; resend_after_seconds: number }>((resolve) => {
      resolvePromise = resolve;
    });
    mockedSendEmailCode.mockReturnValue(pendingPromise);

    renderLogin();

    switchToRegister();
    fillInvitationCode("INVITE-001");
    fillEmail("test@example.com");

    // 发送验证码（请求会挂起）
    await act(async () => {
      clickSendCode();
    });

    // 在请求完成前切到登录模式
    await act(async () => {
      switchToLogin();
    });

    // 现在让请求完成
    await act(async () => {
      resolvePromise({
        ok: true,
        challenge_id: "ch_register_async",
        resend_after_seconds: 60,
      });
    });

    // 切回注册模式
    await act(async () => {
      switchToRegister();
    });

    // 应该能看到注册的 challenge 已保存
    fillOtp("123456");

    const bootstrapMock = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ bootstrap: bootstrapMock });

    await act(async () => {
      submitForm();
    });

    // 应使用注册模式的 challenge 提交
    expect(mockedVerifyEmailCode).toHaveBeenCalledWith("ch_register_async", "123456");
  });

  // ────────────────────────────────────────────────────────
  // 测试 8：五个废弃主题不存在残留引用
  // ────────────────────────────────────────────────────────
  it("五个废弃主题文件已删除且无残留引用", async () => {
    // 动态 import Node.js 模块以避免 tsc 编译报错（vitest 运行时可用）
    const fs = await import(/* @vite-ignore */ "node:fs");
    const path = await import(/* @vite-ignore */ "node:path");
    const { fileURLToPath } = await import(/* @vite-ignore */ "node:url");

    const currentFile = fileURLToPath(import.meta.url);
    const currentDir = path.dirname(currentFile);

    const deletedFiles = [
      "LoginPageTopoCompass.tsx",
      "LoginPageObservatory.tsx",
      "LoginPageFrontispiece.tsx",
      "LoginPageEnvelope.tsx",
      "LoginPageBoardingPass.tsx",
    ];

    const loginDir = path.resolve(currentDir, "../pages/login");

    for (const file of deletedFiles) {
      const filePath = path.join(loginDir, file);
      expect(fs.existsSync(filePath)).toBe(false);
    }

    // 检查残留引用：扫描 src 目录中的所有 .ts/.tsx 文件（排除本测试文件自身）
    const srcDir = path.resolve(currentDir, "..");
    const thisTestFile = path.resolve(currentDir, "loginChallenge.test.tsx");
    const themeNames = [
      "LoginPageTopoCompass",
      "LoginPageObservatory",
      "LoginPageFrontispiece",
      "LoginPageEnvelope",
      "LoginPageBoardingPass",
    ];

    function scanDir(dir: string): string[] {
      const results: string[] = [];
      let entries: ReturnType<typeof fs.readdirSync>;
      try {
        entries = fs.readdirSync(dir, { withFileTypes: true }) as unknown as ReturnType<typeof fs.readdirSync>;
      } catch {
        return results;
      }
      for (const entry of entries as unknown as Array<{ isDirectory(): boolean; isFile(): boolean; name: string }>) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory() && entry.name !== "node_modules" && entry.name !== ".git") {
          results.push(...scanDir(fullPath));
        } else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) {
          results.push(fullPath);
        }
      }
      return results;
    }

    const tsFiles = scanDir(srcDir).filter((f) => path.resolve(f) !== thisTestFile);
    for (const tsFile of tsFiles) {
      const content = fs.readFileSync(tsFile, "utf-8");
      for (const name of themeNames) {
        expect(content).not.toContain(name);
      }
    }
  });
});
