export function ComparisonTable() {
  return (
    <section id="why-heurix" className="section">
      <div className="container">
        <div className="section-header">
          <span className="eyebrow">Why Pure Logic</span>
          <h2>Heurix vs. LLM prompts &amp; static templates</h2>
          <p>
            Infrastructure files govern builds, secrets, and production deployments. They require repeatable,
            auditable engineering—not probabilistic text generation.
          </p>
        </div>

        <div className="table-scroll">
          <table className="compare-table">
            <caption>Comparison of CI/CD and Kubernetes YAML synthesis approaches</caption>
            <thead>
              <tr>
                <th scope="col">Capability</th>
                <th scope="col" className="col-heurix">Heurix (Pure Logic)</th>
                <th scope="col">LLM Code Generators</th>
                <th scope="col">Static Starter Templates</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Determinism &amp; repeatability</th>
                <td className="col-heurix">
                  <strong>100% deterministic</strong> — identical inputs always yield byte-identical YAML.
                </td>
                <td>Non-deterministic; varies across runs and model versions.</td>
                <td>Deterministic, but blind to actual repo structure.</td>
              </tr>
              <tr>
                <th scope="row">Execution speed &amp; privacy</th>
                <td className="col-heurix">
                  <strong>&lt;50 ms, 100% offline</strong> — zero API keys or code leaving your machine.
                </td>
                <td>Seconds of latency; sends codebase context to external APIs.</td>
                <td>Instant, offline.</td>
              </tr>
              <tr>
                <th scope="row">Preserving manual edits</th>
                <td className="col-heurix">
                  <strong>AST round-trip Smart Merge</strong> preserves custom jobs and{' '}
                  <code># @heurix:preserve</code> blocks.
                </td>
                <td>Frequently drops comments or alters unrelated workflow steps.</td>
                <td>Overwrites files or fails on existing configs.</td>
              </tr>
              <tr>
                <th scope="row">Action &amp; runtime pinning</th>
                <td className="col-heurix">
                  Reads <code>.python-version</code>, <code>.nvmrc</code>, <code>rust-toolchain.toml</code>,{' '}
                  <code>go.mod</code>, and lockfiles directly.
                </td>
                <td>Prone to hallucinating outdated action tags or wrong lockfile flags.</td>
                <td>Hardcodes generic versions that require manual edits.</td>
              </tr>
              <tr>
                <th scope="row">Pre-flight validation</th>
                <td className="col-heurix">
                  Validates every output against JSON Schemas before writing a byte.
                </td>
                <td>May emit invalid schema keys or indentation errors.</td>
                <td>Fixed template validity only.</td>
              </tr>
              <tr>
                <th scope="row">Continuous drift detection</th>
                <td className="col-heurix">
                  <code>hx check</code> exits <code>1</code> in CI/pre-commit when dependencies drift from workflows.
                </td>
                <td>No built-in drift verification.</td>
                <td>No drift verification.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
