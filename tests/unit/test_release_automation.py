from pathlib import Path


import re
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_ci_workflows_cover_rc_and_main_branches() -> None:
    executable_workflow_text = read_text(".github/workflows/executable.yml")
    release_workflow_text = (
        read_text(".github/workflows/release-main.yml")
        + read_text(".github/workflows/release-rc-pr.yml")
        + read_text(".github/workflows/release-rc-push.yml")
    )

    assert "main" in executable_workflow_text
    assert "rc*" in executable_workflow_text
    assert "rc/**" in executable_workflow_text

    assert "main" in release_workflow_text
    assert "rc*" in release_workflow_text
    assert "rc/**" in release_workflow_text
    assert "[skip ci]" in release_workflow_text


def test_rc_workflow_builds_executables_for_rc_branch() -> None:
    workflow_text = read_text(".github/workflows/executable.yml")

    assert "main" in workflow_text
    assert "rc*" in workflow_text
    assert "rc/**" in workflow_text
    assert "pull_request:" in workflow_text
    assert "Upload artifact" in workflow_text
    assert "Create Release" not in workflow_text


def test_main_release_workflow_uses_commitizen_to_cut_release() -> None:
    workflow_text = read_text(".github/workflows/release-rc-pr.yml")
    main_workflow_text = read_text(".github/workflows/release-main.yml")

    assert "main" in main_workflow_text
    assert "rc*" in workflow_text
    assert "rc/**" in workflow_text
    assert (
        r'cz bump --yes --changelog --prerelease rc --bump-message "chore(release): rc-\$new_version"'
        in workflow_text
    )
    assert "git commit --amend --no-edit --no-verify" in workflow_text
    assert 'git tag -a "v${RELEASE_VERSION}"' in workflow_text
    assert 'git push origin "v${RELEASE_VERSION}"' in workflow_text
    assert 'git tag -a "v${RELEASE_VERSION}"' in main_workflow_text
    assert 'git push origin "v${RELEASE_VERSION}"' in main_workflow_text


def test_legacy_make_release_target_is_deprecated() -> None:
    makefile_text = read_text("Makefile")

    assert "Release automation now runs in GitHub Actions" in makefile_text
    assert "git push origin main" not in makefile_text


def test_no_actual_urls_in_tests() -> None:
    """Scan all python files in tests/ and verify that no actual/live external URLs are used."""
    tests_dir = PROJECT_ROOT / "tests"
    allowed_hosts = {
        "localhost",
        "127.0.0.1",
        "192.168.1.10",
        "example.invalid",
        "cdn.example.invalid",
        "jellyfin.local",
        "jellyfin",
        "jelly",
        "jf",
        "test",
        "test-jf",
        "fallback",
        "download.url",
    }

    url_pattern = re.compile(r"https?://[a-zA-Z0-9.-]+")

    for path in tests_dir.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        matches = url_pattern.findall(content)
        for url in matches:
            parsed = urlparse(url)
            host = parsed.netloc.split(":")[0]
            if not host:
                continue
            assert host in allowed_hosts, (
                f"Actual/unauthorized URL hostname found in "
                f"{path.relative_to(PROJECT_ROOT)}: {host} (from '{url}'). "
                f"Please use mock/test domains like 'example.invalid'."
            )


def test_extract_changelog_section_logic() -> None:
    def extract_notes(changelog_content: str, tag_name: str) -> list[str]:
        raw_sections = re.split(r"^(##\s+)", changelog_content, flags=re.MULTILINE)

        sections = []
        for i in range(1, len(raw_sections), 2):
            sections.append(raw_sections[i] + raw_sections[i + 1])

        notes = []
        for section in sections:
            header_line = section.split("\n")[0]
            header_match = re.match(r"^##\s+([^\s]+)", header_line)
            if header_match:
                sec_tag = header_match.group(1)
                sec_version_match = re.search(
                    r"^(?:v|rc-)?([0-9]+\.[0-9]+\.[0-9]+)", sec_tag
                )
                if sec_version_match:
                    if sec_tag.lstrip("v") == tag_name.lstrip("v"):
                        notes.append(section)
                        break

        if not notes and sections:
            notes.append(sections[0])
        return notes

    mock_changelog = """## v0.38.1 (2026-06-30)

- Fix issue with macOS runner hangs.
- Prevent duplicate QApplication instance.

## v0.38.1rc0 (2026-06-30)

- Fix issue with macOS runner hangs.
- Prevent duplicate QApplication instance.

## v0.38.0 (2026-06-29)

- Initial stable release.
"""

    notes_stable = extract_notes(mock_changelog, "v0.38.1")
    assert len(notes_stable) == 1
    assert "v0.38.1 (2026-06-30)" in notes_stable[0]
    assert "v0.38.1rc0" not in notes_stable[0]

    notes_rc = extract_notes(mock_changelog, "v0.38.1rc0")
    assert len(notes_rc) == 1
    assert "v0.38.1rc0" in notes_rc[0]
    assert "## v0.38.1 (2026-06-30)" not in notes_rc[0]
