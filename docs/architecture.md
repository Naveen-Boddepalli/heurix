# System Architecture

Heurix enforces a strict unidirectional data pipeline across five decoupled layers so generators never read the filesystem directly:

```text
[ 1. RepoIndexer ]       (.gitignore-aware file tree & in-memory content cache)
        │
        ▼
[ 2. Modular Detectors ] (Python, Node, Rust, Go, C++, Docker, Env, Cloud)
        │
        ▼
[ 3. ProjectContext IR ] (Strongly-typed Pydantic Intermediate Representation)
        │
        ▼
[ 4. Synthesizers ]      (GitHub Actions, Dependabot, Kubernetes + SmartMerger)
        │
        ▼
[ 5. PreflightValidator ] (JSON Schema validation before writing any byte)
```

## Intermediate Representation (`ProjectContext`)

Every detector populates fields on `heurix.core.context.ProjectContext`:

- `repo_name`, `repo_root`, `runner`, `policy_config`
- `is_monorepo`, `monorepo_packages: list[MonorepoPackage]`
- `languages: list[LanguageContext]` (`language`, `runtime_version`, `version_source`, `package_manager`, `install_cmd`, `build_cmd`, `test_cmd`, `lint_cmd`, `framework`, `confidence`)
- `services: list[ServiceRequirement]` (`name`, `image`, `ports`, `env`, `source_file`)
- `containers: list[ContainerContext]` (`dockerfile_path`, `exposed_ports`, `base_image`, `has_healthcheck`, `build_target`)
- `deployment_targets: list[DeploymentTarget]` (`platform`, `config_file`, `project_id`, `features`, `deploy_cmd`, `required_secrets`)
- `required_secrets: list[str]`, `env_vars: dict[str, str]`
- `explain_log: list[str]`

Inspect the live IR for any repository with `hx scan`.
