import { STAGE_MAP, TOTAL_STAGES } from "@/constants/stages";
import type { StageCode } from "@/types/trip";

interface ProgressStepsProps {
  currentCode: StageCode | null;
  failed?: boolean;
}

const ORDERED_CODES: StageCode[] = [
  "ANALYZING",
  "PLANNING",
  "COMPOSING",
  "FINALIZING",
];

export function ProgressSteps({ currentCode, failed }: ProgressStepsProps) {
  const currentStep = currentCode ? STAGE_MAP[currentCode].step : 0;

  return (
    <div className="space-y-4">
      {ORDERED_CODES.map((code) => {
        const info = STAGE_MAP[code];
        const isDone = info.step < currentStep;
        const isActive = info.step === currentStep;
        const isFailed = failed && isActive;

        return (
          <div key={code} className="flex items-start gap-3">
            <div className="flex flex-col items-center">
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-medium transition-all duration-300 ${
                  isFailed
                    ? "bg-red-100 text-red-600"
                    : isDone
                      ? "bg-primary-100 text-primary-600"
                      : isActive
                        ? "bg-accent-100 text-accent-600 shadow-sm"
                        : "bg-sand-100 text-sand-400"
                }`}
              >
                {isFailed ? (
                  <XIcon />
                ) : isDone ? (
                  <CheckIcon />
                ) : isActive ? (
                  <SpinnerIcon />
                ) : (
                  info.step
                )}
              </div>
              {info.step < TOTAL_STAGES && (
                <div
                  className={`mt-1 h-6 w-0.5 transition-colors duration-300 ${
                    isDone ? "bg-primary-200" : "bg-sand-200"
                  }`}
                />
              )}
            </div>
            <div className="pt-1">
              <p
                className={`text-sm font-medium transition-colors duration-300 ${
                  isFailed
                    ? "text-red-600"
                    : isDone
                      ? "text-primary-700"
                      : isActive
                        ? "text-primary-800"
                        : "text-sand-400"
                }`}
              >
                {info.label}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CheckIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
      <path
        fillRule="evenodd"
        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function XIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
      <path
        fillRule="evenodd"
        d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
