import { useSyncExternalStore } from "react";
import type { ComponentProps } from "react";

const subscribe = (callback: () => void) => {
  window.addEventListener("fixture:navigate", callback);
  return () => window.removeEventListener("fixture:navigate", callback);
};
function navigate(path: string) {
  history.pushState({}, "", path);
  window.dispatchEvent(new Event("fixture:navigate"));
}
export function usePathname() {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}
export function useParams() {
  return { runId: "11111111-1111-4111-8111-111111111111" };
}
export function useRouter() {
  return { push: navigate };
}
export default function Link({ href, onClick, ...props }: ComponentProps<"a">) {
  return (
    <a
      href={href}
      {...props}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented && href?.startsWith("/")) {
          event.preventDefault();
          navigate(href);
        }
      }}
    />
  );
}
