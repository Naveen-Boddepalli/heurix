import type { PresetRepo } from './types';

export const PRESET_REPOS: PresetRepo[] = [
  {
    id: 'fastapi-uv',
    label: 'FastAPI + uv + Postgres',
    subtitle: 'Python 3.12 service with uv lockfile, ruff, pytest, Docker, and .env secrets',
    repoName: 'billing-api',
    badges: ['Python 3.12', 'uv', 'FastAPI', 'PostgreSQL', 'Docker'],
    files: [
      {
        path: '.python-version',
        enabled: true,
        content: '3.12.4\n',
      },
      {
        path: 'uv.lock',
        enabled: true,
        content: 'version = 1\nrequires-python = ">=3.12"\n',
      },
      {
        path: 'pyproject.toml',
        enabled: true,
        content: `[project]
name = "billing-api"
version = "0.4.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115.0",
  "psycopg2-binary>=2.9.9",
  "uvicorn>=0.30.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0.0",
  "ruff>=0.6.0",
]`,
      },
      {
        path: 'Dockerfile',
        enabled: true,
        content: `FROM python:3.12-slim AS builder
WORKDIR /app
COPY . .

FROM python:3.12-slim AS runtime
EXPOSE 8000
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]`,
      },
      {
        path: '.env.example',
        enabled: true,
        content: `APP_ENV=test
LOG_LEVEL=info
STRIPE_SECRET_KEY=sk_test_placeholder
DATABASE_PASSWORD=change_me`,
      },
    ],
    existingCiForMerge: `name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      # @heurix:preserve
      - name: Upload coverage to internal bucket
        run: ./scripts/upload-cov.sh
  slack_notify:
    needs: test
    if: failure()
    runs-on: ubuntu-latest
    steps:
      - uses: slackapi/slack-github-action@v1`,
  },
  {
    id: 'nextjs-monorepo-vercel',
    label: 'Next.js Monorepo + Vercel',
    subtitle: 'pnpm workspace monorepo pinned via .nvmrc with Prisma Postgres and Vercel deploy',
    repoName: 'acme-cloud',
    badges: ['Node 22.x', 'pnpm', 'Monorepo', 'Next.js', 'Vercel'],
    files: [
      {
        path: '.nvmrc',
        enabled: true,
        content: 'v22.11.0\n',
      },
      {
        path: 'pnpm-lock.yaml',
        enabled: true,
        content: "lockfileVersion: '9.0'\n",
      },
      {
        path: 'pnpm-workspace.yaml',
        enabled: true,
        content: "packages:\n  - 'apps/*'\n  - 'packages/*'\n",
      },
      {
        path: 'package.json',
        enabled: true,
        content: `{
  "name": "acme-cloud",
  "private": true,
  "scripts": {
    "build": "turbo run build",
    "test": "vitest run",
    "lint": "eslint ."
  },
  "dependencies": {
    "next": "^15.1.0",
    "@prisma/client": "^6.0.0"
  },
  "devDependencies": {
    "vitest": "^3.0.0",
    "turbo": "^2.3.0"
  }
}`,
      },
      {
        path: 'apps/web/package.json',
        enabled: true,
        content: `{ "name": "@acme/web", "private": true }`,
      },
      {
        path: 'packages/ui/package.json',
        enabled: true,
        content: `{ "name": "@acme/ui", "private": true }`,
      },
      {
        path: 'vercel.json',
        enabled: true,
        content: `{
  "name": "acme-cloud-web",
  "framework": "nextjs"
}`,
      },
    ],
    existingCiForMerge: `name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # @heurix:preserve
      - name: Run Playwright visual snapshot
        run: pnpm exec playwright test`,
  },
  {
    id: 'rust-axum-redis',
    label: 'Rust Axum + Redis',
    subtitle: 'Pinned Rust toolchain with Swatinem cache, Cargo clippy, and Compose Redis',
    repoName: 'edge-router',
    badges: ['Rust 1.82', 'Cargo', 'Axum', 'Redis', 'Docker'],
    files: [
      {
        path: 'rust-toolchain.toml',
        enabled: true,
        content: `[toolchain]
channel = "1.82.0"
components = ["clippy", "rustfmt"]`,
      },
      {
        path: 'Cargo.toml',
        enabled: true,
        content: `[package]
name = "edge-router"
version = "0.2.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
redis = "0.27"`,
      },
      {
        path: 'docker-compose.yml',
        enabled: true,
        content: `services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"`,
      },
      {
        path: 'Dockerfile',
        enabled: true,
        content: `FROM rust:1.82-slim AS builder
WORKDIR /usr/src/app
COPY . .
RUN cargo build --release

FROM debian:bookworm-slim
EXPOSE 8080
CMD ["edge-router"]`,
      },
    ],
    existingCiForMerge: `name: CI
on:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # @heurix:preserve
      - name: Run cargo-audit security scan
        uses: rustsec/audit-check@v2`,
  },
  {
    id: 'go-gin-firebase',
    label: 'Go Gin + Firebase',
    subtitle: 'Go 1.23 API with race detector tests, golangci-lint, Docker, and Firebase Hosting',
    repoName: 'pulse-gateway',
    badges: ['Go 1.23', 'Gin', 'Docker', 'Firebase'],
    files: [
      {
        path: 'go.mod',
        enabled: true,
        content: `module github.com/acme/pulse-gateway

go 1.23

require (
	github.com/gin-gonic/gin v1.10.0
)`,
      },
      {
        path: 'Dockerfile',
        enabled: true,
        content: `FROM golang:1.23-alpine AS build
WORKDIR /src
COPY . .
RUN go build -o /gateway ./cmd/server

FROM alpine:3.20
EXPOSE 8080
HEALTHCHECK CMD wget -qO- http://localhost:8080/healthz || exit 1
ENTRYPOINT ["/gateway"]`,
      },
      {
        path: 'firebase.json',
        enabled: true,
        content: `{
  "hosting": {
    "public": "public"
  },
  "firestore": {
    "rules": "firestore.rules"
  }
}`,
      },
      {
        path: '.firebaserc',
        enabled: true,
        content: `{
  "projects": {
    "default": "pulse-gateway-prod"
  }
}`,
      },
      {
        path: '.env.example',
        enabled: true,
        content: `PORT=8080
JWT_SIGNING_KEY=replace_in_prod`,
      },
    ],
  },
  {
    id: 'cpp-cmake',
    label: 'C++20 CMake + clang-tidy',
    subtitle: 'Modern CMake build exporting compile_commands.json for clang-tidy + ctest',
    repoName: 'tensor-core',
    badges: ['C++20', 'CMake', 'clang-tidy', 'CTest'],
    files: [
      {
        path: 'CMakeLists.txt',
        enabled: true,
        content: `cmake_minimum_required(VERSION 3.25)
project(tensor_core LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

enable_testing()
add_executable(tensor_tests tests/main.cpp)
add_test(NAME core_unit COMMAND tensor_tests)`,
      },
      {
        path: '.clang-tidy',
        enabled: true,
        content: `Checks: 'bugprone-*,modernize-*,performance-*'
WarningsAsErrors: '*'`,
      },
      {
        path: 'Dockerfile',
        enabled: true,
        content: `FROM ubuntu:24.04 AS runner
EXPOSE 9090
CMD ["./build/tensor_server"]`,
      },
    ],
  },
  {
    id: 'polyglot-fullstack',
    label: 'Polyglot Stack (Py + Node)',
    subtitle: 'Dual Python + Node repository with Docker Compose Postgres & Redis',
    repoName: 'data-studio',
    badges: ['Python 3.12', 'Node 20.x', 'Streamlit', 'Compose'],
    files: [
      {
        path: '.python-version',
        enabled: true,
        content: '3.12\n',
      },
      {
        path: 'pyproject.toml',
        enabled: true,
        content: `[project]
name = "data-studio"
dependencies = [
  "streamlit>=1.38.0",
  "pytest>=8.3.0",
  "ruff>=0.6.0",
]`,
      },
      {
        path: 'uv.lock',
        enabled: true,
        content: 'version = 1\n',
      },
      {
        path: 'package.json',
        enabled: true,
        content: `{
  "name": "studio-frontend",
  "scripts": {
    "build": "vite build",
    "test": "vitest run"
  },
  "devDependencies": {
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}`,
      },
      {
        path: 'pnpm-lock.yaml',
        enabled: true,
        content: "lockfileVersion: '9.0'\n",
      },
      {
        path: 'docker-compose.yml',
        enabled: true,
        content: `services:
  postgres:
    image: postgres:16-alpine
  redis:
    image: redis:7-alpine`,
      },
    ],
  },
];

export interface FileTemplate {
  name: string;
  defaultPath: string;
  content: string;
}

export const STARTER_FILE_TEMPLATES: FileTemplate[] = [
  {
    name: 'Blank File',
    defaultPath: 'config.toml',
    content: '# New configuration file\n',
  },
  {
    name: 'Dockerfile (Container)',
    defaultPath: 'Dockerfile',
    content: `FROM python:3.12-slim AS runtime
WORKDIR /app
COPY . .
EXPOSE 8000
HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
CMD ["python", "main.py"]\n`,
  },
  {
    name: 'docker-compose.yml (Postgres + Redis)',
    defaultPath: 'docker-compose.yml',
    content: `services:
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"\n`,
  },
  {
    name: '.env.example (Secrets & Config)',
    defaultPath: '.env.example',
    content: `APP_ENV=development
API_PORT=8000
DATABASE_URL=postgres://localhost:5432/app
JWT_SECRET_KEY=replace_with_secret_token
STRIPE_API_KEY=sk_test_mock\n`,
  },
  {
    name: 'pnpm-workspace.yaml (Monorepo)',
    defaultPath: 'pnpm-workspace.yaml',
    content: `packages:
  - 'apps/*'
  - 'packages/*'\n`,
  },
  {
    name: 'vercel.json (Vercel Target)',
    defaultPath: 'vercel.json',
    content: `{\n  "name": "my-cloud-app",\n  "framework": "nextjs"\n}\n`,
  },
  {
    name: 'firebase.json (Firebase Target)',
    defaultPath: 'firebase.json',
    content: `{\n  "hosting": {\n    "public": "dist"\n  }\n}\n`,
  },
];
