class Heurix < Formula
  include Language::Python::Virtualenv

  desc "Deterministic Codebase Scanner & Automated YAML Synthesizer"
  homepage "https://github.com/Naveen-Boddepalli/heurix"
  url "https://files.pythonhosted.org/packages/source/h/heurix/heurix-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "MIT"
  head "https://github.com/Naveen-Boddepalli/heurix.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Heurix (hx)", shell_output("#{bin}/hx --help")
  end
end
