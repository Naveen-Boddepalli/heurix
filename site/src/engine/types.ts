export interface ServiceRequirement {
  name: string;
  image: string;
  ports: number[];
  env: Record<string, string>;
  source_file: string;
}

export interface LanguageContext {
  language: 'python' | 'node' | 'rust' | 'go' | 'cpp';
  runtime_version: string;
  version_source: string;
  package_manager: string;
  install_cmd: string;
  build_cmd: string | null;
  test_cmd: string | null;
  lint_cmd: string | null;
  working_dir: string;
  framework: string | null;
  confidence: number;
}

export interface ContainerContext {
  dockerfile_path: string;
  exposed_ports: number[];
  base_image: string;
  has_healthcheck: boolean;
  build_target: string | null;
}

export interface DeploymentTarget {
  platform: 'vercel' | 'firebase';
  config_file: string;
  project_id: string | null;
  features: string[];
  deploy_cmd: string | null;
  preview_deploy_cmd: string | null;
  required_secrets: string[];
}

export interface MonorepoPackage {
  name: string;
  path: string;
  language: string;
  package_manager: string;
}

export interface ProjectContext {
  repo_name: string;
  repo_root: string;
  is_monorepo: boolean;
  monorepo_packages: MonorepoPackage[];
  languages: LanguageContext[];
  services: ServiceRequirement[];
  containers: ContainerContext[];
  deployment_targets: DeploymentTarget[];
  required_secrets: string[];
  env_vars: Record<string, string>;
  explain_log: string[];
  confidence: number;
  runner: string;
}

export interface VirtualFile {
  path: string;
  content: string;
  enabled: boolean;
}

export interface PresetRepo {
  id: string;
  label: string;
  subtitle: string;
  repoName: string;
  badges: string[];
  files: VirtualFile[];
  existingCiForMerge?: string;
}

export interface DriftFinding {
  file_path: string;
  issue: string;
  severity: 'WARNING' | 'ERROR';
  recommendation: string;
}

export interface ScanResult {
  context: ProjectContext;
  synthesized: Record<string, string>;
  durationMs: number;
}
