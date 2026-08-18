import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { SafeDeliveryNotice } from "@/components/result/SafeDeliveryNotice";
import * as api from "@/services/api";
import { useTripStore } from "@/stores/tripStore";
import { useTripTaskStore } from "@/stores/tripTaskStore";
import type { TripFormData } from "@/types/form";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    submitTrip: vi.fn(),
  };
});

const requestData: TripFormData = {
  from_city: "成都",
  to_city: "重庆",
  start_date: "2026-08-20",
  end_date: "2026-08-20",
  days: 1,
  people_count: 1,
  preferences: ["美食"],
  avoid: [],
  notes: "",
};

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderNotice(
  publishedVariant: "normal" | "safe",
  deliveryStatus: "NORMAL" | "DEGRADED",
) {
  return render(
    <MemoryRouter initialEntries={["/trip/results/501?job_id=job-old"]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <SafeDeliveryNotice
                result={{
                  published_variant: publishedVariant,
                  delivery_status: deliveryStatus,
                }}
                jobId="job-old"
              />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("v0.9.5 safe delivery notice", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    useTripTaskStore.getState().clearAllTasks();
    useTripStore.getState().reset();
  });

  it.each([
    ["normal", "NORMAL"],
    ["normal", "DEGRADED"],
  ] as const)("does not show for %s + %s", (variant, status) => {
    renderNotice(variant, status);
    expect(
      screen.queryByText("已生成基础行程，部分详细介绍暂未展开。"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "重新生成详细版" }),
    ).not.toBeInTheDocument();
  });

  it("shows user-facing copy only for the basic itinerary result", () => {
    renderNotice("safe", "DEGRADED");
    expect(
      screen.getByText("已生成基础行程，部分详细介绍暂未展开。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "重新生成详细版" }),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/safe|DEGRADED|Review/i);
  });

  it("reuses the stored form input and submits a new generation task", async () => {
    useTripStore.getState().setFormData(requestData);
    vi.mocked(api.submitTrip).mockResolvedValue({
      ok: true,
      job_id: "job-new",
    });

    renderNotice("safe", "DEGRADED");
    fireEvent.click(screen.getByRole("button", { name: "重新生成详细版" }));

    await waitFor(() => {
      expect(api.submitTrip).toHaveBeenCalledWith(
        requestData,
        expect.any(String),
      );
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/planning/job-new",
      );
    });
    expect(useTripStore.getState().formData).toEqual(requestData);
    expect(useTripTaskStore.getState().getTask("job-new")?.status).toBe(
      "pending",
    );
  });
});
