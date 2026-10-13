import Link from "next/link";
import Image from "next/image";
import { ActionLink, Brand, Icon } from "./components/ui";
import { LandingMotion } from "./components/landing-motion";

export default function HomePage() {
  return (
    <div className="site-page">
      <a className="skip-link" href="#introduction">
        Skip to introduction
      </a>
      <header className="site-nav">
        <Brand />
        <nav aria-label="Main navigation">
          <a href="#capabilities">The workspace</a>
          <a href="#method">Our method</a>
          <Link href="/login">Log in</Link>
        </nav>
        <ActionLink href="/research">Start research</ActionLink>
      </header>
      <main id="introduction">
        <section className="landing-hero">
          <div className="hero-copy">
            <h1>
              A clearer answer.
              <br />A traceable path.
            </h1>
            <p>
              Go beyond the search result. Turn a question into a considered
              answer, with the evidence close at hand.
            </p>
            <div className="hero-actions">
              <ActionLink href="/research">Start research</ActionLink>
              <a className="inline-action" href="#method">
                See the method
                <Icon name="arrow" size={17} />
              </a>
            </div>
          </div>
          <div
            className="instrument-stage"
            aria-label="An illustration of a question connected to its evidence"
          >
            <Image
              src="/images/research-instrument.webp"
              alt="Layered glass document plates connected by copper traces"
              fill
              loading="eager"
              fetchPriority="high"
              sizes="(max-width: 760px) 100vw, 1160px"
              className="instrument-artwork"
            />
            <div className="instrument-flow">
              <span>Question</span>
              <Icon name="arrow" size={15} />
              <span>Evidence</span>
              <Icon name="arrow" size={15} />
              <span>Perspective</span>
            </div>
          </div>
        </section>
        <section className="capability-section" id="capabilities">
          <div className="section-heading">
            <h2>
              The answer is only
              <br />
              the beginning.
            </h2>
            <p>
              A workspace for following a thought all the way through. From the
              first question to the sources behind the conclusion.
            </p>
          </div>
          <div className="capability-grid">
            <article className="capability-feature bezel">
              <div className="bezel-core">
                <Icon name="book" size={25} />
                <h3>
                  Keep the evidence
                  <br />
                  within reach.
                </h3>
                <p>
                  Read the answer and explore its sources in the same workspace.
                  Follow a reference without losing your place.
                </p>
                <div className="mini-source">
                  <div>
                    <span className="mini-source-icon">
                      <Icon name="external" size={16} />
                    </span>
                    <strong>Source material</strong>
                    <span className="mini-status">Preserved</span>
                  </div>
                  <p>
                    Every collected source stays connected to the research that
                    found it.
                  </p>
                  <div className="source-lines">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <Link className="inline-action" href="/research">
                  Explore the workspace
                  <Icon name="arrow" size={17} />
                </Link>
              </div>
            </article>
            <article className="capability-small">
              <div className="feature-symbol">
                <Icon name="search" size={24} />
              </div>
              <h3>Give curiosity a direction.</h3>
              <p>
                Start with a comparison, a complex question, or something you
                need to understand. Set the scope before research begins.
              </p>
            </article>
            <article className="capability-small">
              <div className="feature-symbol">
                <Icon name="layers" size={24} />
              </div>
              <h3>See how the work unfolded.</h3>
              <p>
                Follow the plan, source collection, and research activity. The
                process stays visible alongside the result.
              </p>
            </article>
          </div>
        </section>
        <section className="method-section" id="method">
          <div className="method-intro">
            <span className="method-line" />
            <h2>
              From question
              <br />
              to clarity.
            </h2>
            <p>
              Good research is a sequence of careful decisions. Each step makes
              the next one more useful.
            </p>
            <Link href="/research" className="inline-action">
              Try a question
              <Icon name="arrow" size={17} />
            </Link>
          </div>
          <div className="method-steps">
            {[
              [
                "Frame the question",
                "A broad topic becomes a bounded plan. Focus the search on the parts that matter.",
              ],
              [
                "Follow the evidence",
                "Collect sources, preserve their material, and review the claims they support.",
              ],
              [
                "Write with context",
                "Bring the findings together. Keep references and limitations visible so you can decide what comes next.",
              ],
            ].map(([title, description], index) => (
              <details key={title} open={index === 0}>
                <summary>
                  <span className="method-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3>{title}</h3>
                  <span className="details-plus">
                    <Icon name="plus" />
                  </span>
                </summary>
                <p>{description}</p>
              </details>
            ))}
            <p className="method-footnote">
              Built for the live web. Designed to show its work.
            </p>
          </div>
        </section>
        <section className="closing-section">
          <div className="closing-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <h2>
            Your next question
            <br />
            deserves a better answer.
          </h2>
          <p>Make space for a more considered perspective.</p>
          <ActionLink href="/research">Open the workspace</ActionLink>
          <footer className="site-footer">
            <Brand />
            <span>Curiosity, with a paper trail.</span>
            <nav aria-label="Footer navigation">
              <Link href="/login">Log in</Link>
              <Link href="/signup">Create account</Link>
            </nav>
          </footer>
        </section>
      </main>
      <LandingMotion />
    </div>
  );
}
