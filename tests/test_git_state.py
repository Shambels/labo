import subprocess

from rag_calorvia.git_state import git_state


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(tmp_path):
    """A throwaway repository with one commit: tests never depend on the state of the real one."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("a")
    git(tmp_path, "add", "a.txt")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_clean_repo(tmp_path):
    repo = make_repo(tmp_path)
    commit, dirty = git_state(repo)
    assert len(commit) == 40 and not dirty


def test_modified_file_is_dirty(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "a.txt").write_text("changed")
    assert git_state(repo)[1]


def test_untracked_file_is_dirty(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "new.py").write_text("")
    assert git_state(repo)[1]
