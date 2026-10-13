"use client";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
gsap.registerPlugin(useGSAP, ScrollTrigger);
export function LandingMotion() {
  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add("(prefers-reduced-motion: no-preference)", (context) => {
      gsap.fromTo(
        ".hero-copy > *",
        { opacity: 0.35, y: 14 },
        {
          opacity: 1,
          y: 0,
          duration: 0.55,
          stagger: 0.07,
          ease: "power3.out",
          clearProps: "transform,opacity",
        },
      );
      gsap.utils
        .toArray<HTMLElement>(
          ".capability-grid > article, .closing-section > h2",
        )
        .forEach((target) => {
          gsap.fromTo(
            target,
            { opacity: 0.5, y: 18 },
            {
              opacity: 1,
              y: 0,
              duration: 0.5,
              ease: "power3.out",
              clearProps: "transform,opacity",
              scrollTrigger: { trigger: target, start: "top 94%", once: true },
            },
          );
        });
      const details = document.querySelectorAll<HTMLDetailsElement>(
        ".method-steps details",
      );
      const onToggle = (event: Event) => {
        const detail = event.currentTarget as HTMLDetailsElement;
        if (!detail.open) return;
        const content = detail.querySelector("p");
        if (content)
          gsap.fromTo(
            content,
            { opacity: 0.3, y: -6 },
            {
              opacity: 1,
              y: 0,
              duration: 0.24,
              ease: "power3.out",
              clearProps: "transform,opacity",
              overwrite: true,
            },
          );
      };
      // contextSafe binds delayed DOM-event animations to the lifecycle cleanup.
      const safeToggle = context.add("onToggle", onToggle);
      const listener: EventListener = (event) => safeToggle(event);
      details.forEach((detail) => detail.addEventListener("toggle", listener));
      return () =>
        details.forEach((detail) =>
          detail.removeEventListener("toggle", listener),
        );
    });
    media.add(
      "(prefers-reduced-motion: no-preference) and (min-width: 1000px)",
      () => {
        gsap.fromTo(
          ".instrument-stage",
          { opacity: 0.7, transform: "translateY(24px) scale(0.98)" },
          {
            opacity: 1,
            transform: "translateY(0) scale(1)",
            duration: 1,
            ease: "power3.out",
          },
        );
        gsap.fromTo(
          ".method-intro h2",
          { opacity: 0.55 },
          {
            opacity: 1,
            scrollTrigger: {
              trigger: ".method-section",
              start: "top 85%",
              end: "top 40%",
              scrub: 0.4,
            },
          },
        );
        ScrollTrigger.create({
          trigger: ".method-intro",
          pin: true,
          start: "top 160px",
          endTrigger: ".method-section",
          end: "bottom 75%",
          pinSpacing: false,
        });
      },
    );
    return () => media.revert();
  });
  return null;
}
