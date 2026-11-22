import { useEffect, useState } from "react";

/** Matches the phone layout in App.css (`@media (max-width: 480px)`). */
export const PHONE_MAX_WIDTH_PX = 480;

export function isPhoneViewport(width: number): boolean {
  return width <= PHONE_MAX_WIDTH_PX;
}

export function useViewport(): { width: number; phone: boolean } {
  const [width, setWidth] = useState(() =>
    typeof window === "undefined" ? PHONE_MAX_WIDTH_PX + 1 : window.innerWidth,
  );

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return { width, phone: isPhoneViewport(width) };
}
