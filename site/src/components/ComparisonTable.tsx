const ROWS: { label: string; hx: React.ReactNode; llm: string; template: string }[] = [
  {
    label: 'Same input, same output',
    hx: 'Yes. Re-running on an unchanged repo produces identical YAML.',
    llm: 'No. Output varies between runs and model versions.',
    template: 'Yes, but it ignores what is in the repo.',
  },
  {
    label: 'Runs offline',
    hx: 'Yes. No API keys, and your code stays on your machine.',
    llm: 'No. Repo contents are sent to an external API.',
    template: 'Yes.',
  },
  {
    label: 'Keeps your edits',
    hx: (
      <>
        Merges into the existing file. Comments, extra jobs, and <code># @heurix:preserve</code> lines are kept,
        and it lists anything it will overwrite.
      </>
    ),
    llm: 'Often rewrites unrelated steps or drops comments.',
    template: 'Overwrites the file, or you merge by hand.',
  },
  {
    label: 'Versions',
    hx: (
      <>
        Read from <code>.python-version</code>, <code>.nvmrc</code>, <code>rust-toolchain.toml</code>,{' '}
        <code>go.mod</code>, and lockfiles.
      </>
    ),
    llm: 'Can suggest action tags or install flags that are out of date.',
    template: 'Hardcoded; you update them yourself.',
  },
  {
    label: 'Validation',
    hx: 'Every file is checked against a JSON Schema before it is written.',
    llm: 'None built in.',
    template: 'Only as good as the template.',
  },
  {
    label: 'Catching drift',
    hx: (
      <>
        <code>hx check</code> exits 1 when the workflow no longer matches the repo.
      </>
    ),
    llm: 'None.',
    template: 'None.',
  },
  {
    label: 'Secrets',
    hx: (
      <>
        Sensitive keys become <code>{'${{ secrets.* }}'}</code>. Deploy tokens stay in deploy jobs.
      </>
    ),
    llm: 'May inline values or pass deploy tokens to every job.',
    template: 'Up to you.',
  },
];

export function ComparisonTable() {
  return (
    <section id="why-heurix" className="section">
      <div className="container">
        <div className="section-header">
          <h2>Why not an LLM or a starter template?</h2>
          <p>
            CI files decide what gets built, which secrets are exposed, and what gets deployed. They should be easy
            to review and should not change unless the repo did.
          </p>
        </div>

        <div className="table-scroll">
          <table className="compare-table">
            <caption>How hx compares with LLM-generated YAML and starter templates</caption>
            <thead>
              <tr>
                <th scope="col"></th>
                <th scope="col" className="col-heurix">
                  hx
                </th>
                <th scope="col">Asking an LLM</th>
                <th scope="col">Starter template</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.label}>
                  <th scope="row">{row.label}</th>
                  <td className="col-heurix">{row.hx}</td>
                  <td>{row.llm}</td>
                  <td>{row.template}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
