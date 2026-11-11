"""
Tests for PreflightValidator against valid and malformed YAML schemas.
"""

from __future__ import annotations

from heurix.core.validator import PreflightValidator


def test_validator_syntax_error():
    validator = PreflightValidator()
    invalid_yaml = "jobs:\n  test:\n    - [unbalanced bracket"
    is_valid, errors = validator.validate(".github/workflows/ci.yml", invalid_yaml)
    assert not is_valid
    assert len(errors) == 1
    assert "YAML Syntax Error" in errors[0]


def test_validator_non_dictionary():
    validator = PreflightValidator()
    is_valid, errors = validator.validate(".github/workflows/ci.yml", "- item1\n- item2\n")
    assert not is_valid
    assert any("not a valid dictionary" in e for e in errors)


def test_validator_valid_github_workflow():
    validator = PreflightValidator()
    content = """
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run test
        run: pytest
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", content)
    assert is_valid
    assert errors == []


def test_validator_malformed_github_workflow():
    validator = PreflightValidator()

    # Missing 'jobs' key
    is_valid, errors = validator.validate(".github/workflows/ci.yml", "name: CI\non: push\n")
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)

    # Job missing 'runs-on'
    bad_job = """
jobs:
  test:
    steps:
      - run: echo 1
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_job)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)

    # Job missing 'steps'
    bad_steps = """
jobs:
  test:
    runs-on: ubuntu-latest
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_steps)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)


def test_validator_valid_dependabot():
    validator = PreflightValidator()
    content = """
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
"""
    is_valid, errors = validator.validate(".github/dependabot.yml", content)
    assert is_valid
    assert errors == []


def test_validator_malformed_dependabot():
    validator = PreflightValidator()

    # Missing 'version'
    bad_content = """
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
"""
    is_valid, errors = validator.validate(".github/dependabot.yml", bad_content)
    assert not is_valid
    assert any("Dependabot Schema Error" in e for e in errors)

    # Missing required field in updates
    missing_fields = """
version: 2
updates:
  - package-ecosystem: "npm"
"""
    is_valid, errors = validator.validate(".github/dependabot.yml", missing_fields)
    assert not is_valid
    assert any("Dependabot Schema Error" in e for e in errors)


def test_validator_valid_kubernetes():
    validator = PreflightValidator()
    deployment = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app
spec:
  replicas: 1
"""
    is_valid, errors = validator.validate("k8s/deployment.yaml", deployment)
    assert is_valid
    assert errors == []


def test_validator_malformed_kubernetes():
    validator = PreflightValidator()

    # Missing 'apiVersion'
    missing_api = """
kind: Deployment
metadata:
  name: test-app
"""
    is_valid, errors = validator.validate("k8s/deployment.yaml", missing_api)
    assert not is_valid
    assert any("Kubernetes Manifest Schema Error" in e for e in errors)

    # Missing 'kind'
    missing_kind = """
apiVersion: apps/v1
metadata:
  name: test-app
"""
    is_valid, errors = validator.validate("k8s/deployment.yaml", missing_kind)
    assert not is_valid
    assert any("Kubernetes Manifest Schema Error" in e for e in errors)

    # Missing 'metadata'
    missing_meta = """
apiVersion: apps/v1
kind: Deployment
"""
    is_valid, errors = validator.validate("k8s/deployment.yaml", missing_meta)
    assert not is_valid
    assert any("Kubernetes Manifest Schema Error" in e for e in errors)


def test_validator_multidoc_valid_kubernetes_manifest():
    validator = PreflightValidator()
    multidoc = """---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
spec:
  replicas: 2
---
apiVersion: v1
kind: Service
metadata:
  name: demo-app-service
spec:
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: demo-app-ingress
---
"""
    is_valid, errors = validator.validate("k8s/manifests.yaml", multidoc)
    assert is_valid
    assert errors == []

    is_valid_ext, errors_ext = validator.validate("deploy/bundle.k8s.yaml", multidoc)
    assert is_valid_ext
    assert errors_ext == []


def test_validator_multidoc_reports_schema_error_in_any_document():
    validator = PreflightValidator()
    multidoc = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
---
apiVersion: v1
kind: Service
spec:
  ports:
    - port: 80
---
kind: Ingress
metadata:
  name: demo-app-ingress
"""
    is_valid, errors = validator.validate("k8s/manifests.yaml", multidoc)
    assert not is_valid
    assert len(errors) == 2
    assert all("Kubernetes Manifest Schema Error" in e for e in errors)


def test_validator_multidoc_syntax_error_in_second_document():
    validator = PreflightValidator()
    multidoc = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-app
---
apiVersion: v1
kind: Service
spec:
  - [broken bracket
"""
    is_valid, errors = validator.validate("k8s/manifests.yaml", multidoc)
    assert not is_valid
    assert len(errors) == 1
    assert "YAML Syntax Error" in errors[0]


def test_validator_multijob_needs_strategy_defaults():
    validator = PreflightValidator()

    valid_multijob = """
name: CI
on:
  push:
    branches: [main]
    paths:
      - apps/web/**
      - services/api/**
jobs:
  test-apps-web:
    runs-on: ${{ matrix.os }}
    defaults:
      run:
        working-directory: apps/web
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        node-version: ['18.x', '20.x']
    steps:
      - uses: actions/checkout@v4
      - run: npm test
  test-services-api:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: services/api
    steps:
      - uses: actions/checkout@v4
      - run: pytest
  deploy_vercel:
    runs-on: ubuntu-latest
    needs:
      - test-apps-web
      - test-services-api
    steps:
      - uses: actions/checkout@v4
  deploy_single_dep:
    runs-on: ubuntu-latest
    needs: test-services-api
    steps:
      - uses: actions/checkout@v4
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", valid_multijob)
    assert is_valid, f"Expected valid multi-job workflow, got errors: {errors}"
    assert errors == []

    # Invalid 'needs' scalar type (integer instead of string or array of strings)
    bad_needs_int = """
jobs:
  deploy_vercel:
    runs-on: ubuntu-latest
    needs: 123
    steps:
      - run: echo deploy
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_needs_int)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)

    # Invalid 'needs' array containing non-string item
    bad_needs_item = """
jobs:
  deploy_vercel:
    runs-on: ubuntu-latest
    needs: [test-apps-web, 42]
    steps:
      - run: echo deploy
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_needs_item)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)

    # Invalid 'defaults' type (string instead of object)
    bad_defaults = """
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    defaults: apps/web
    steps:
      - run: npm test
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_defaults)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)

    # Invalid 'strategy' type (list instead of object)
    bad_strategy = """
jobs:
  test-apps-web:
    runs-on: ubuntu-latest
    strategy:
      - ubuntu-latest
    steps:
      - run: npm test
"""
    is_valid, errors = validator.validate(".github/workflows/ci.yml", bad_strategy)
    assert not is_valid
    assert any("GitHub Workflow Schema Error" in e for e in errors)
