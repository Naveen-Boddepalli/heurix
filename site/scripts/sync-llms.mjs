import { cpSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const siteRoot = resolve(__dirname, '..');
const repoRoot = resolve(siteRoot, '..');
const publicDir = resolve(siteRoot, 'public');
const dataDir = resolve(siteRoot, 'src/data');

mkdirSync(publicDir, { recursive: true });
mkdirSync(dataDir, { recursive: true });

// 1. Copy root llms.txt -> site/public/llms.txt
const rootLlmsPath = resolve(repoRoot, 'llms.txt');
const llmsTxt = readFileSync(rootLlmsPath, 'utf8');
cpSync(rootLlmsPath, resolve(publicDir, 'llms.txt'));

// 2. Build llms-full.txt from canonical repository markdown docs in reader order
const docSources = [
  { id: 'overview', title: 'Overview', file: 'README.md', group: 'Start here' },
  { id: 'getting-started', title: 'Getting Started', file: 'docs/getting-started.md', group: 'Guides' },
  { id: 'heuristics', title: 'Deep Heuristics Matrix', file: 'docs/heuristics.md', group: 'Reference' },
  { id: 'cli-reference', title: 'CLI Reference', file: 'docs/cli-reference.md', group: 'Reference' },
  { id: 'smart-merge', title: 'Non-Destructive Smart Merge', file: 'docs/smart-merge.md', group: 'Guides' },
  { id: 'kubernetes-and-ci', title: 'CI/CD & Kubernetes Outputs', file: 'docs/kubernetes-and-ci.md', group: 'Guides' },
  { id: 'drift-detection', title: 'Continuous Drift Detection', file: 'docs/drift-detection.md', group: 'Guides' },
  { id: 'ai-integration', title: 'AI Assistant Integration', file: 'docs/ai-integration.md', group: 'Guides' },
  { id: 'architecture', title: 'System Architecture & IR', file: 'docs/architecture.md', group: 'Architecture' },
];

const fullChunks = [];
const structuredDocs = [];

for (const doc of docSources) {
  const fullPath = resolve(repoRoot, doc.file);
  const content = readFileSync(fullPath, 'utf8').trim();
  fullChunks.push(`<!-- ${doc.file} -->\n\n${content}\n`);
  structuredDocs.push({
    id: doc.id,
    title: doc.title,
    file: doc.file,
    group: doc.group,
    markdown: content,
  });
}

// Include heurix.md master plan at the tail of llms-full.txt
const masterPlanPath = resolve(repoRoot, 'heurix.md');
const masterPlan = readFileSync(masterPlanPath, 'utf8').trim();
fullChunks.push(`<!-- heurix.md -->\n\n${masterPlan}\n`);

const llmsFullBody = fullChunks.join('\n---\n\n');
writeFileSync(resolve(publicDir, 'llms-full.txt'), llmsFullBody, 'utf8');

// 3. Emit generatedDocs.json so the frontend Docs Reader and llms.txt preview stay 100% synced
writeFileSync(
  resolve(dataDir, 'generatedDocs.json'),
  JSON.stringify(
    {
      llmsTxt: llmsTxt.trim(),
      llmsFullBytes: Buffer.byteLength(llmsFullBody, 'utf8'),
      llmsFullLines: llmsFullBody.split('\n').length,
      docs: structuredDocs,
    },
    null,
    2
  ),
  'utf8'
);

console.log(
  `sync-llms: synced llms.txt, llms-full.txt (${structuredDocs.length} docs, ${llmsFullBody.split('\n').length} lines)`
);
