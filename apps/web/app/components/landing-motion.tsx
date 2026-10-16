"use client";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { useEffect } from "react";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import Lenis from "lenis";
gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText);

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

function exists(selector: string) {
  return document.querySelector(selector) !== null;
}

/*
 * Scroll and pointer choreography for the public pages. Everything here is
 * progressive: without it, or with reduced motion, every element is already
 * in its final, readable state.
 */
export function LandingMotion() {
  useEffect(() => {
    const nav = document.querySelector<HTMLElement>(".lp-nav");
    if (!nav) return;
    const update = () => {
      nav.dataset.scrolled = String(window.scrollY > 8);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  // Tiles and cards catch a soft light under the cursor.
  useEffect(() => {
    if (!window.matchMedia("(hover: hover) and (pointer: fine)").matches)
      return;
    const move = (event: PointerEvent) => {
      const target = (event.target as Element | null)?.closest<HTMLElement>(
        "[data-spotlight]",
      );
      if (!target) return;
      const rect = target.getBoundingClientRect();
      target.style.setProperty("--mx", `${event.clientX - rect.left}px`);
      target.style.setProperty("--my", `${event.clientY - rect.top}px`);
    };
    document.addEventListener("pointermove", move, { passive: true });
    return () => document.removeEventListener("pointermove", move);
  }, []);

  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add(
      {
        motion: "(prefers-reduced-motion: no-preference)",
        fine: "(hover: hover) and (pointer: fine)",
        wide: "(min-width: 721px)",
      },
      (context) => {
        const { motion, fine, wide } = context.conditions as Record<
          string,
          boolean
        >;
        if (!motion) return;
        document.documentElement.classList.add("lp-motion");

        // Smooth, eased scrolling driven by the same clock as every tween,
        // so scrubbed scenes never lag a frame behind the page.
        const lenis = new Lenis({
          lerp: 0.11,
          autoRaf: false,
          allowNestedScroll: true,
          anchors: { offset: -88 },
          stopInertiaOnNavigate: true,
        });
        lenis.on("scroll", ScrollTrigger.update);
        const tick = (time: number) => lenis.raf(time * 1000);
        gsap.ticker.add(tick);
        gsap.ticker.lagSmoothing(0);

        if (exists(".lp-progress"))
          gsap.fromTo(
            ".lp-progress",
            { scaleX: 0 },
            {
              scaleX: 1,
              ease: "none",
              scrollTrigger: { start: 0, end: "max", scrub: 0.3 },
            },
          );

        // The hero recedes as the console comes forward.
        if (exists(".lp-stage-inner")) {
          const hero = () => ({
            start: 0,
            end: () => `+=${window.innerHeight * 0.7}`,
            scrub: 0.6,
          });
          gsap.fromTo(
            ".lp-stage-inner",
            { scale: 0.93 },
            {
              scale: 1,
              ease: "none",
              scrollTrigger: hero(),
            },
          );
          gsap.to(".lp-hero-copy", {
            y: -40,
            opacity: 0.35,
            ease: "none",
            scrollTrigger: hero(),
          });
          gsap.to(".lp-field-wrap", {
            yPercent: 14,
            ease: "none",
            scrollTrigger: hero(),
          });
        }

        if (exists(".lp-scrub"))
          gsap.fromTo(
            ".lp-scrub span",
            { opacity: 0.14 },
            {
              opacity: 1,
              stagger: 0.08,
              ease: "none",
              scrollTrigger: {
                trigger: ".lp-statement",
                start: "top 78%",
                end: "bottom 52%",
                scrub: 0.5,
              },
            },
          );

        // Source rows drift continuously and quicken with scroll speed.
        const rows = gsap.utils.toArray<HTMLElement>(".lp-marquee-row");
        if (rows.length) {
          const loops = rows.map((row) =>
            row.dataset.direction === "right"
              ? gsap.fromTo(
                  row,
                  { xPercent: -50 },
                  { xPercent: 0, duration: 64, ease: "none", repeat: -1 },
                )
              : gsap.to(row, {
                  xPercent: -50,
                  duration: 56,
                  ease: "none",
                  repeat: -1,
                }),
          );
          ScrollTrigger.create({
            trigger: ".lp-marquee",
            start: "top bottom",
            end: "bottom top",
            onToggle: (self) =>
              loops.forEach((loop) =>
                self.isActive ? loop.play() : loop.pause(),
              ),
            onUpdate: (self) => {
              const boost = 1 + Math.min(Math.abs(self.getVelocity()) / 240, 7);
              loops.forEach((loop) =>
                gsap.to(loop, {
                  timeScale: boost,
                  duration: 0.2,
                  overwrite: true,
                  onComplete: () => {
                    gsap.to(loop, {
                      timeScale: 1,
                      duration: 1.4,
                      ease: "power2.out",
                      overwrite: true,
                    });
                  },
                }),
              );
            },
          });
        }

        // Section headings rise line by line out of their own masks.
        gsap.utils
          .toArray<HTMLElement>(
            ".lp-section-head h2, .lp-method-intro h2, .lp-closing h2",
          )
          .forEach((heading) => {
            SplitText.create(heading, {
              type: "lines",
              mask: "lines",
              linesClass: "lp-split-line",
              autoSplit: true,
              onSplit: (split) =>
                gsap.from(split.lines, {
                  yPercent: 110,
                  duration: 1.05,
                  stagger: 0.09,
                  ease: EASE,
                  scrollTrigger: {
                    trigger: heading,
                    start: "top 86%",
                    once: true,
                  },
                }),
            });
          });

        // A copper trace draws down the method steps, carrying a marker.
        const trace = document.querySelector<HTMLElement>(".lp-steps-trace");
        if (trace && wide) {
          const scroll = {
            trigger: ".lp-steps",
            start: "top 62%",
            end: "bottom 70%",
            scrub: 0.6,
          };
          gsap.fromTo(
            trace.querySelector("i"),
            { "--trace": 0 },
            { "--trace": 1, ease: "none", scrollTrigger: scroll },
          );
          gsap.fromTo(
            trace.querySelector("b"),
            { y: 0, opacity: 1 },
            {
              y: () => trace.offsetHeight,
              ease: "none",
              scrollTrigger: { ...scroll, invalidateOnRefresh: true },
            },
          );
        }

        // The warm light behind the evidence band drifts slower than the page.
        if (exists(".lp-band-glow"))
          gsap.fromTo(
            ".lp-band-glow",
            { yPercent: -12 },
            {
              yPercent: 38,
              ease: "none",
              scrollTrigger: {
                trigger: ".lp-band",
                start: "top bottom",
                end: "bottom top",
                scrub: 0.8,
              },
            },
          );

        // Eyebrows and section intros follow their heading up.
        gsap.utils
          .toArray<HTMLElement>(".lp-section-head > p")
          .forEach((copy) =>
            gsap.from(copy, {
              opacity: 0,
              y: 14,
              duration: 0.9,
              delay: copy.classList.contains("lp-eyebrow") ? 0 : 0.18,
              ease: EASE,
              scrollTrigger: { trigger: copy, start: "top 90%", once: true },
            }),
          );

        ScrollTrigger.batch("[data-reveal]", {
          start: "top 88%",
          once: true,
          onEnter: (batch) =>
            gsap.fromTo(
              batch,
              { opacity: 0, y: 32, filter: "blur(6px)" },
              {
                opacity: 1,
                y: 0,
                filter: "blur(0px)",
                duration: 0.95,
                stagger: 0.12,
                ease: EASE,
                clearProps: "transform,filter",
              },
            ),
        });

        // Steps stick and stack; the one underneath settles back.
        const steps = gsap.utils.toArray<HTMLElement>(".lp-step");
        steps.forEach((step, index) => {
          gsap.fromTo(
            step.querySelectorAll(".lp-step-trail span"),
            { "--lit": 0 },
            {
              "--lit": 1,
              stagger: 0.3,
              ease: "none",
              scrollTrigger: {
                trigger: step,
                start: "top 70%",
                end: "top 30%",
                scrub: 0.4,
              },
            },
          );
          const next = steps[index + 1];
          const card = step.querySelector(".lp-step-card");
          // The card stays opaque so nothing shows through the one above it;
          // only its contents dim as it settles back.
          if (wide && next && card) {
            const settle = {
              trigger: next,
              start: "top 70%",
              end: "top 25%",
              scrub: 0.5,
            };
            gsap.to(card, { scale: 0.94, ease: "none", scrollTrigger: settle });
            gsap.to(card.children, {
              opacity: 0.35,
              ease: "none",
              scrollTrigger: settle,
            });
          }
        });

        // Closing panel opens out from a narrower card.
        if (exists(".lp-closing"))
          gsap.fromTo(
            ".lp-closing",
            { clipPath: "inset(7% 5% 7% 5% round 44px)" },
            {
              clipPath: "inset(0% 0% 0% 0% round 28px)",
              ease: "none",
              scrollTrigger: {
                trigger: ".lp-closing",
                start: "top 95%",
                end: "top 40%",
                scrub: 0.5,
              },
            },
          );

        // Primary buttons lean a little toward the cursor.
        const cleanups: (() => void)[] = [];
        if (fine)
          gsap.utils
            .toArray<HTMLElement>("[data-magnetic]")
            .forEach((button) => {
              const x = gsap.quickTo(button, "x", {
                duration: 0.5,
                ease: "power3",
              });
              const y = gsap.quickTo(button, "y", {
                duration: 0.5,
                ease: "power3",
              });
              const move = (event: PointerEvent) => {
                const rect = button.getBoundingClientRect();
                x((event.clientX - rect.left - rect.width / 2) * 0.22);
                y((event.clientY - rect.top - rect.height / 2) * 0.3);
              };
              const leave = () => {
                x(0);
                y(0);
              };
              button.addEventListener("pointermove", move);
              button.addEventListener("pointerleave", leave);
              cleanups.push(() => {
                button.removeEventListener("pointermove", move);
                button.removeEventListener("pointerleave", leave);
              });
            });

        return () => {
          gsap.ticker.remove(tick);
          gsap.ticker.lagSmoothing(500, 33);
          lenis.destroy();
          cleanups.forEach((cleanup) => cleanup());
          document.documentElement.classList.remove("lp-motion");
        };
      },
    );
    return () => media.revert();
  });
  return null;
}
