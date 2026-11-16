"""Which code produced an experiment: the commit, and whether the working tree had uncommitted changes."""
import subprocess


def git_state(cwd=None):
    """(commit hash, dirty) of the repository containing `cwd` (default: the current directory).

    dirty is True when `git status --porcelain` lists anything: modified, staged or untracked files.
    A run with dirty=True can't be reproduced from its commit alone, so it doesn't go in the report.
    """
    def git(*args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout

    return git("rev-parse", "HEAD").strip(), git("status", "--porcelain") != ""
