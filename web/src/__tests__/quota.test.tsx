import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Header from "@/components/layout/Header";
import { UserMenu } from "@/components/layout/UserMenu";
import ProfilePage from "@/pages/ProfilePage";
import InputPage from "@/pages/InputPage";
import { useAuthStore } from "@/stores/authStore";
import type { User, Quota } from "@/types/auth";

import { clearPendingSubmission } from "@/utils/pendingSubmission";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    getMe: vi.fn().mockResolvedValue({
      ok: true,
      user: {
        user_id: "usr_quota_test",
        display_name: "额度测试官",
        display_name_change_available_at: null,
        masked_email: "test@example.com",
        linux_do_username: null,
        email_login_enabled: true,
        display_name_review_required: false,
      },
      quota: {
        policy: "beta",
        limit: 13,
        reserved: 0,
        consumed: 4,
        remaining: 9,
      },
      active_trip: null,
    }),
    submitTrip: vi.fn(),
  };
});

describe("Quota Dynamic Limit & Exhaustion Tests", () => {
  const mockUser: User = {
    user_id: "usr_quota_test",
    display_name: "额度测试官",
    display_name_change_available_at: null,
    masked_email: "test@example.com",
    linux_do_username: null,
    email_login_enabled: true,
    display_name_review_required: false,
  };

  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    clearPendingSubmission();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  describe("Header & UserMenu Quota Display", () => {
    it("Header (mobile view) renders dynamic quota 9/13 when limit=13, consumed=4, remaining=9", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 4,
          remaining: 9,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <Header />
        </MemoryRouter>,
      );

      expect(screen.getByText("⚡ 9/13")).toBeInTheDocument();
    });

    it("Header (mobile view) renders '额度读取中' when quota is null", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <Header />
        </MemoryRouter>,
      );

      expect(screen.getByText("⚡ 额度读取中")).toBeInTheDocument();
      expect(screen.queryByText(/⚡ 3\/3/)).not.toBeInTheDocument();
    });

    it("UserMenu renders '额度 9/13' for limit=13, consumed=4, remaining=9", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 4,
          remaining: 9,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <UserMenu />
        </MemoryRouter>,
      );

      expect(screen.getByText("额度 9/13")).toBeInTheDocument();
    });

    it("UserMenu renders '额度 0/13' when limit=13, remaining=0", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 13,
          remaining: 0,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <UserMenu />
        </MemoryRouter>,
      );

      expect(screen.getByText("额度 0/13")).toBeInTheDocument();
      expect(screen.queryByText("额度 0/3")).not.toBeInTheDocument();
    });

    it("UserMenu renders '额度读取中' when quota is null", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <UserMenu />
        </MemoryRouter>,
      );

      expect(screen.getByText("额度读取中")).toBeInTheDocument();
      expect(screen.queryByText(/额度 3\/3/)).not.toBeInTheDocument();
    });
  });

  describe("ProfilePage Quota Display", () => {
    it("ProfilePage renders exact quota numbers for limit=13, consumed=4, remaining=9", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 4,
          remaining: 9,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>,
      );

      expect(screen.getByText("13")).toBeInTheDocument();
      expect(screen.getByText("4")).toBeInTheDocument();
      expect(screen.getByText("9")).toBeInTheDocument();
    });

    it("ProfilePage renders '-' for metrics when quota is null without defaulting to 3", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>,
      );

      const dashes = screen.getAllByText("-");
      expect(dashes.length).toBeGreaterThanOrEqual(3);
    });
  });

  describe("InputPage Quota & Exhaustion Behavior", () => {
    it("InputPage enables submit button with '帮我排行程' when remaining=9, limit=13", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 4,
          remaining: 9,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const buttons = screen.getAllByRole("button", { name: "帮我排行程" });
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons[0]).not.toBeDisabled();
    });

    it("InputPage disables submit button and shows '公测额度已耗尽 (0/13)' when remaining=0, limit=13", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 13,
          remaining: 0,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const buttons = screen.getAllByRole("button", {
        name: "公测额度已耗尽 (0/13)",
      });
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons[0]).toBeDisabled();
    });

    it("InputPage disables submit button and shows '额度读取中...' when logged in but quota is null", () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const buttons = screen.getAllByRole("button", {
        name: "额度读取中...",
      });
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons[0]).toBeDisabled();
    });

    it("InputPage form submission shows dynamic error message '公测免费额度已耗尽 (0/13)，无法创建新行程'", async () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: {
          policy: "beta",
          limit: 13,
          reserved: 0,
          consumed: 13,
          remaining: 0,
        },
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const btn = screen.getAllByRole("button", { name: "公测额度已耗尽 (0/13)" })[0];
      const form = btn?.closest("form");
      expect(form).not.toBeNull();
      if (form) {
        fireEvent.submit(form);
      }

      expect(
        await screen.findAllByText("公测免费额度已耗尽 (0/13)，无法创建新行程"),
      ).not.toHaveLength(0);
    });

    it("InputPage form submission when quota is null shows '额度读取中，请稍后重试'", async () => {
      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: null,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const btn = screen.getAllByRole("button", { name: "额度读取中..." })[0];
      const form = btn?.closest("form");
      expect(form).not.toBeNull();
      if (form) {
        fireEvent.submit(form);
      }

      expect(
        await screen.findAllByText("额度读取中，请稍后重试"),
      ).not.toHaveLength(0);
    });

    it("InputPage shows '公测额度已耗尽' without guessing numbers when limit is undefined", () => {
      const quotaNoLimit: Quota = {
        limit: undefined as unknown as number,
        remaining: 0,
        consumed: 5,
        reserved: 0,
      };

      useAuthStore.setState({
        status: "authenticated",
        user: mockUser,
        quota: quotaNoLimit,
        activeTrip: null,
        bootstrapped: true,
        bootstrapError: null,
      });

      render(
        <MemoryRouter>
          <InputPage />
        </MemoryRouter>,
      );

      const buttons = screen.getAllByRole("button", {
        name: "公测额度已耗尽",
      });
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons[0]).toBeDisabled();
      expect(screen.queryByText(/\(0\//)).not.toBeInTheDocument();
    });
  });
});
