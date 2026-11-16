class Heurix < Formula
  include Language::Python::Virtualenv

  desc "Deterministic Codebase Scanner & Automated YAML Synthesizer"
  homepage "https://github.com/Naveen-Boddepalli/heurix"
  url "https://files.pythonhosted.org/packages/source/h/heurix/heurix-0.2.2.tar.gz"
  sha256 "9d7bdd350e94aaf64613d739ca3ecec980f250053d7ccde8376c96c712942efb"
  # TODO: add `resource` stanzas for the Python dependencies (typer, rich,
  # pydantic, ruamel.yaml, jsonschema, jinja2, ...). Homebrew installs Python
  # packages without their dependencies, so hx cannot import them until then.
  license "MIT"
  head "https://github.com/Naveen-Boddepalli/heurix.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Heurix (hx)", shell_output("#{bin}/hx --version")
    assert_match "Deterministic Codebase Scanner", shell_output("#{bin}/hx --help")

    (testpath/"pyproject.toml").write <<~EOS
      [project]
      name = "homebrew-smoke"
      version = "0.1.0"
    EOS
    assert_match '"python"', shell_output("#{bin}/hx scan --path #{testpath}")
  end
end
