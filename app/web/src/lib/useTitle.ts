import { useEffect } from "react";

export function useTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} · Minutas` : "Minutas";
    return () => {
      document.title = "Minutas";
    };
  }, [title]);
}
