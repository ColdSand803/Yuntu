import type {
  CinematicDraft,
  CinematicStep,
} from "@/types/cinematic";
import {
  DRAFT_SCHEMA_VERSION,
  DRAFT_STORAGE_KEY,
} from "@/types/cinematic";
import { isDateExpired, validateDateRange } from "./cinematicDate";

export function loadCinematicDraft(): CinematicDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_STORAGE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      clearCinematicDraft();
      return null;
    }

    if (parsed.version !== DRAFT_SCHEMA_VERSION) {
      // Unknown or deprecated schema version: clear and require fresh input
      clearCinematicDraft();
      return null;
    }

    if (!parsed.cityName || typeof parsed.cityName !== "string") {
      clearCinematicDraft();
      return null;
    }

    const form = parsed.form && typeof parsed.form === "object" ? parsed.form : {};

    // Validate date expiration
    if (form.start_date && isDateExpired(form.start_date)) {
      form.start_date = "";
      form.end_date = "";
      form.days = 1;
    } else if (form.start_date && form.end_date) {
      const { valid, days } = validateDateRange(form.start_date, form.end_date);
      if (!valid) {
        form.start_date = "";
        form.end_date = "";
        form.days = 1;
      } else {
        form.days = days;
      }
    }

    // Sanitize bounds
    const peopleCount = typeof form.people_count === "number"
      ? Math.max(1, Math.min(30, Math.floor(form.people_count)))
      : 1;

    const draft: CinematicDraft = {
      version: DRAFT_SCHEMA_VERSION,
      step: (["dates", "companions", "preferences", "commute", "review"].includes(parsed.step)
        ? parsed.step
        : "dates") as CinematicStep,
      cityId: String(parsed.cityId || ""),
      cityName: String(parsed.cityName || ""),
      form: {
        to_city: parsed.cityName,
        start_date: form.start_date || "",
        end_date: form.end_date || "",
        days: form.days || 1,
        people_count: peopleCount,
        preferences: Array.isArray(form.preferences) ? form.preferences : ["适中"],
        avoid: Array.isArray(form.avoid) ? form.avoid : [],
        notes: typeof form.notes === "string" ? form.notes.slice(0, 200) : "",
        from_city: typeof form.from_city === "string" ? form.from_city.slice(0, 10) : undefined,
        commute_mode: ["driving", "transit", "cycling"].includes(form.commute_mode)
          ? form.commute_mode
          : "driving",
        accommodation: form.accommodation
          ? {
              name: typeof form.accommodation.name === "string"
                ? form.accommodation.name.slice(0, 160)
                : "",
            }
          : undefined,
        budget: typeof form.budget === "number" ? form.budget : undefined,
        daily_start: typeof form.daily_start === "string" ? form.daily_start : undefined,
        daily_end: typeof form.daily_end === "string" ? form.daily_end : undefined,
        must_include: Array.isArray(form.must_include) ? form.must_include : undefined,
      },
      selectedPois: (() => {
        if (!Array.isArray(parsed.selectedPois)) return [];
        const seen = new Set<number>();
        return parsed.selectedPois.filter((p: unknown): p is {id: number, name: string} => {
          if (!p || typeof p !== "object") return false;
          const po = p as Record<string, unknown>;
          if (typeof po.id !== "number" || !Number.isSafeInteger(po.id) || po.id <= 0) return false;
          if (typeof po.name !== "string" || po.name.trim().length === 0) return false;
          if (seen.has(po.id)) return false;
          seen.add(po.id);
          return true;
        }).slice(0, 5);
      })(),
      selectedPoiIds: Array.isArray(parsed.selectedPoiIds)
        ? parsed.selectedPoiIds.filter((id: unknown): id is number => typeof id === "number" && Number.isSafeInteger(id) && id > 0)
        : [],
      returnLayer: ["poi-picker", "accommodation", "notes"].includes(parsed.returnLayer)
        ? parsed.returnLayer
        : null,
      ownerUserId: typeof parsed.ownerUserId === "string" ? parsed.ownerUserId : null,
      intent: typeof parsed.intent === "string" && /^(edit-pois|submit-trip)(:[a-zA-Z0-9-]+)?$/.test(parsed.intent) ? parsed.intent : null,
      updatedAt: typeof parsed.updatedAt === "number" ? parsed.updatedAt : Date.now(),
    };

    return draft;
  } catch {
    clearCinematicDraft();
    return null;
  }
}

export function saveCinematicDraft(draft: CinematicDraft): void {
  try {
    const serialized = JSON.stringify({
      ...draft,
      updatedAt: Date.now(),
    });
    sessionStorage.setItem(DRAFT_STORAGE_KEY, serialized);
  } catch {
    // Storage quota exceeded or private browsing restricted
  }
}

export function clearCinematicDraft(): void {
  try {
    sessionStorage.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // Ignore storage clear error
  }
}

export function createInitialDraft(cityId: string, cityName: string): CinematicDraft {
  return {
    version: DRAFT_SCHEMA_VERSION,
    step: "dates",
    cityId,
    cityName,
    selectedPois: [],
    returnLayer: null,
    ownerUserId: null,
    intent: null,
    form: {
      to_city: cityName,
      start_date: "",
      end_date: "",
      days: 1,
      people_count: 1,
      preferences: ["适中"],
      avoid: [],
      notes: "",
      commute_mode: "driving",
    },
    updatedAt: Date.now(),
  };
}

export function switchDraftCity(
  draft: CinematicDraft,
  newCityId: string,
  newCityName: string,
): CinematicDraft {
  if (draft.cityName === newCityName && draft.cityId === newCityId) {
    return draft;
  }

  // Clear POI selections and accommodations on confirmed city change
  return {
    ...draft,
    cityId: newCityId,
    cityName: newCityName,
    selectedPois: [],
    intent: null,
    returnLayer: null,
    form: {
      ...draft.form,
      to_city: newCityName,
      must_include: undefined,
      accommodation: undefined,
    },
    updatedAt: Date.now(),
  };
}

export function scrubCinematicDraftOnAuthChange(currentUserId: string | null): void {
  const draft = loadCinematicDraft();
  if (!currentUserId) sessionStorage.removeItem("yuntu-cinematic-submission-v1");
  if (!draft) return;
  if (draft.ownerUserId && draft.ownerUserId !== currentUserId) {
    sessionStorage.removeItem("yuntu-cinematic-submission-v1");
    // Scrub private data when user changes or logs out
    const scrubbed: CinematicDraft = {
      ...draft,
      selectedPois: [],
      returnLayer: null,
      intent: null,
      ownerUserId: currentUserId,
      form: {
        ...draft.form,
        must_include: undefined,
        accommodation: undefined,
      }
    };
    saveCinematicDraft(scrubbed);
  } else if (!draft.ownerUserId && currentUserId) {
    // Adopt anonymous draft
    saveCinematicDraft({ ...draft, ownerUserId: currentUserId });
  }
}






