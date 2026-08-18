/* eslint-disable react-refresh/only-export-components */
import { createBrowserRouter } from "react-router-dom";
import { lazy, Suspense } from "react";
import App from "./App";
import { ProtectedRoute } from "./components/auth/ProtectedRoute";

const InputPage = lazy(() => import("./pages/InputPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const AuthCallbackPage = lazy(() => import("./pages/AuthCallbackPage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const ProfilePage = lazy(() => import("./pages/ProfilePage"));
const PlanningPage = lazy(() => import("./pages/PlanningPage"));
const ResultPage = lazy(() => import("./pages/ResultPage"));
const PlanDetailPage = lazy(() => import("./pages/PlanDetailPage"));
const DemoResultPage = lazy(() => import("./pages/DemoResultPage"));
const PlanDetailDemoLight = lazy(() => import("./pages/PlanDetailDemoLight"));
const PlanDetailClassicPage = lazy(
  () => import("./pages/PlanDetailClassicPage"),
);
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-primary-200 border-t-primary-500" />
          <p className="text-sm text-gray-400">加载中…</p>
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

const DemoInputCapsule = lazy(() => import("./pages/demo/DemoInputCapsule"));
const DemoPlanningPage = lazy(() => import("./pages/demo/DemoPlanningPage"));
const DemoHistoryPage = lazy(() => import("./pages/demo/DemoHistoryPage"));
const DemoProfilePage = lazy(() => import("./pages/demo/DemoProfilePage"));

const demoRoutes = [
  {
    path: "demo/input-capsule",
    element: (
      <LazyPage>
        <DemoInputCapsule />
      </LazyPage>
    ),
  },
  {
    path: "demo/planning",
    element: (
      <LazyPage>
        <DemoPlanningPage />
      </LazyPage>
    ),
  },
  {
    path: "demo/history",
    element: (
      <LazyPage>
        <DemoHistoryPage />
      </LazyPage>
    ),
  },
  {
    path: "demo/profile",
    element: (
      <LazyPage>
        <DemoProfilePage />
      </LazyPage>
    ),
  },
  {
    path: "demo",
    element: (
      <LazyPage>
        <DemoResultPage />
      </LazyPage>
    ),
  },
  {
    path: "demo/detail-light",
    element: (
      <LazyPage>
        <PlanDetailDemoLight />
      </LazyPage>
    ),
  },
  {
    path: "demo/detail-classic",
    element: (
      <LazyPage>
        <PlanDetailClassicPage />
      </LazyPage>
    ),
  },
];

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      {
        index: true,
        element: (
          <LazyPage>
            <InputPage />
          </LazyPage>
        ),
      },
      {
        path: "login",
        element: (
          <LazyPage>
            <LoginPage />
          </LazyPage>
        ),
      },
      {
        path: "auth/callback",
        element: (
          <LazyPage>
            <AuthCallbackPage />
          </LazyPage>
        ),
      },
      {
        path: "history",
        element: (
          <ProtectedRoute>
            <LazyPage>
              <HistoryPage />
            </LazyPage>
          </ProtectedRoute>
        ),
      },
      {
        path: "profile",
        element: (
          <ProtectedRoute>
            <LazyPage>
              <ProfilePage />
            </LazyPage>
          </ProtectedRoute>
        ),
      },
      {
        path: "planning/:jobId",
        element: (
          <ProtectedRoute>
            <LazyPage>
              <PlanningPage />
            </LazyPage>
          </ProtectedRoute>
        ),
      },
      {
        path: "result/:resultId",
        element: (
          <ProtectedRoute>
            <LazyPage>
              <ResultPage />
            </LazyPage>
          </ProtectedRoute>
        ),
      },
      {
        path: "plan/:resultId/:planId",
        element: (
          <ProtectedRoute>
            <LazyPage>
              <PlanDetailPage />
            </LazyPage>
          </ProtectedRoute>
        ),
      },
      ...demoRoutes,
      {
        path: "*",
        element: (
          <LazyPage>
            <NotFoundPage />
          </LazyPage>
        ),
      },
    ],
  },
]);
