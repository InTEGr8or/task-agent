from pathlib import Path
import pytest
from taskagent import templates
from taskagent.templates import DotfileDef, Template


class TestLoadTemplate:
    def test_load_minimal_meta(self):
        t = templates.load_template("minimal")
        assert t.name == "minimal"
        assert t.description
        assert len(t.dotfiles) >= 2

        paths = {df.path for df in t.dotfiles}
        assert ".gitconfig" in paths
        assert ".ssh/id_ed25519" in paths

    def test_load_gh_meta(self):
        t = templates.load_template("gh")
        assert t.name == "gh"
        paths = {df.path for df in t.dotfiles}
        assert ".gitconfig" in paths
        assert ".ssh/id_ed25519" in paths

    def test_uat_aws_includes_aws_config(self):
        t = templates.load_template("uat-aws")
        paths = {df.path for df in t.dotfiles}
        assert ".aws/config" in paths

    def test_load_uat_aws_meta(self):
        t = templates.load_template("uat-aws")
        assert t.name == "uat-aws"
        paths = {df.path for df in t.dotfiles}
        assert ".gitconfig" in paths
        assert ".ssh/id_ed25519" in paths
        assert ".aws/config" in paths

    def test_load_nonexistent_raises(self):
        with pytest.raises(RuntimeError, match="not found"):
            templates.load_template("nonexistent")

    def test_load_no_meta_raises(self, tmp_path: Path, monkeypatch):
        empty_dir = tmp_path / ".ta" / "agents" / "empty"
        empty_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(RuntimeError, match="no meta.toml"):
            templates.load_template("empty")

    def test_get_template_dir(self):
        d = templates.get_template_dir("minimal")
        assert d.is_dir()
        assert (d / "meta.toml").exists()

    def test_get_template_dir_nonexistent(self):
        with pytest.raises(RuntimeError, match="not found"):
            templates.get_template_dir("nonexistent")


class TestDotfileDef:
    def test_inline_content(self):
        df = DotfileDef(path=".gitconfig", source="inline", content="[user]\n")
        assert df.content == "[user]\n"

    def test_file_source(self):
        df = DotfileDef(path=".gitconfig", source="file", source_path=Path("/tmp/test"))
        assert df.source_path == Path("/tmp/test")

    def test_generate_source(self):
        df = DotfileDef(path=".ssh/id_ed25519", source="generate")
        assert df.source == "generate"


class TestHasDotfile:
    def test_has_dotfile_true(self):
        t = Template(
            name="test",
            dotfiles=[
                DotfileDef(path=".gitconfig", source="inline"),
                DotfileDef(path=".ssh/id_ed25519", source="generate"),
            ],
        )
        assert templates.has_dotfile(t, ".gitconfig")
        assert templates.has_dotfile(t, ".ssh/id_ed25519")

    def test_has_dotfile_false(self):
        t = Template(name="test")
        assert not templates.has_dotfile(t, ".gitconfig")
