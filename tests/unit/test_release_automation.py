from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_rc_workflow_builds_executables_for_rc_branch() -> None:
    workflow_text = read_text(".github/workflows/executable.yml")

    assert 'branches: [ "rc" ]' in workflow_text
    assert "pull_request:" in workflow_text
    assert "Upload artifact" in workflow_text
    assert "Create Release" not in workflow_text


def test_main_release_workflow_uses_commitizen_to_cut_release() -> None:
    workflow_text = read_text(".github/workflows/release.yml")

    assert 'branches: [ "main" ]' in workflow_text
    assert "cz bump --yes --changelog --files-only" in workflow_text
    assert (
        'git commit -m "chore(release): v${RELEASE_VERSION} [skip ci]"' in workflow_text
    )
    assert 'git tag -a "v${RELEASE_VERSION}"' in workflow_text
    assert "git push origin HEAD:main" in workflow_text
    assert 'git push origin "v${RELEASE_VERSION}"' in workflow_text


def test_legacy_make_release_target_is_deprecated() -> None:
    makefile_text = read_text("Makefile")

    assert "Release automation now runs in GitHub Actions" in makefile_text
    assert "git push origin main" not in makefile_text


def test_ci_workflows_cover_rc_and_main_branches() -> None:
    test_workflow_text = read_text(".github/workflows/test.yml")
    lint_workflow_text = read_text(".github/workflows/lint.yml")

    assert 'branches: [ "main", "rc" ]' in test_workflow_text
    assert 'branches: [ "main", "rc" ]' in lint_workflow_text
    assert "[skip ci]" in test_workflow_text
    assert "[skip ci]" in lint_workflow_text
