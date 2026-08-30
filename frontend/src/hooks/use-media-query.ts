import { useEffect, useState } from "react";

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(
    () => window.matchMedia(query).matches,
  );

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const updateMatches = () => setMatches(mediaQuery.matches);

    mediaQuery.addEventListener("change", updateMatches);
    updateMatches();

    return () => mediaQuery.removeEventListener("change", updateMatches);
  }, [query]);

  return matches;
}
