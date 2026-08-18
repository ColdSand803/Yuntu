import { create } from "zustand";

interface ToastState {
  message: string;
  type: "success" | "error";
  visible: boolean;
  showToast: (message: string, type?: "success" | "error") => void;
  hideToast: () => void;
}

export const useToastStore = create<ToastState>((set) => ({
  message: "",
  type: "success",
  visible: false,
  showToast: (message, type = "success") => {
    set({ message, type, visible: true });
  },
  hideToast: () => set({ visible: false }),
}));

export function showToast(message: string, type: "success" | "error" = "success") {
  useToastStore.getState().showToast(message, type);
}
