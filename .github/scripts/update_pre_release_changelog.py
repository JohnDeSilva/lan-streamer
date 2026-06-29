import sys
import subprocess
from datetime import datetime
import re


def get_commits(latest_tag):
    try:
        # Get commit subjects since latest_tag
        result = subprocess.run(
            ["git", "log", f"{latest_tag}..HEAD", "--pretty=format:%s"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().split("\n")
    except Exception as e:
        print(f"Error getting commits: {e}")
        sys.exit(1)


def parse_commits(commits):
    categories = {"Feat": [], "Fix": [], "Refactor": [], "Perf": []}

    # Match pattern: type(scope): message or type: message
    pattern = re.compile(
        r"^(feat|fix|refactor|perf)(?:\([^)]+\))?!?: (.+)$", re.IGNORECASE
    )

    for commit in commits:
        commit = commit.strip()
        if not commit:
            continue
        match = pattern.match(commit)
        if match:
            ctype = match.group(1).lower()
            msg = match.group(2).strip()
            # Capitalize first letter of message
            msg = msg[0].upper() + msg[1:] if msg else msg

            # Reconstruct the line (with scope if present)
            scope_match = re.match(r"^[a-zA-Z0-9_-]+(?:\([^)]+\))?!?:", commit)
            prefix = ""
            if scope_match:
                prefix = scope_match.group(0).split(":")[0].strip()
                # e.g. "feat(ui)" -> "**ui**: "
                if "(" in prefix:
                    scope = prefix.split("(")[1].split(")")[0]
                    line = f"**{scope}**: {msg}"
                else:
                    line = msg
            else:
                line = msg

            if ctype == "feat":
                categories["Feat"].append(line)
            elif ctype == "fix":
                categories["Fix"].append(line)
            elif ctype == "refactor":
                categories["Refactor"].append(line)
            elif ctype == "perf":
                categories["Perf"].append(line)

    return categories


def main():
    if len(sys.argv) < 3:
        print("Usage: python update_pre_release_changelog.py <latest_tag> <next_tag>")
        sys.exit(1)

    latest_tag = sys.argv[1]
    next_tag = sys.argv[2]
    today = datetime.now().strftime("%Y-%m-%d")

    commits = get_commits(latest_tag)
    categories = parse_commits(commits)

    # Check if there are any conventional commits to document
    has_content = any(len(items) > 0 for items in categories.values())
    if not has_content:
        print(
            "No conventional commits found since last tag. Skipping changelog generation."
        )
        # But we still want a header if they pushed commits (or just list them as other)
        categories["Other"] = []
        for commit in commits:
            commit = commit.strip()
            if commit and not any(
                commit.lower().startswith(x)
                for x in [
                    "feat",
                    "fix",
                    "refactor",
                    "perf",
                    "chore",
                    "docs",
                    "style",
                    "test",
                    "ci",
                ]
            ):
                categories["Other"].append(commit)

    # Build markdown
    markdown_lines = [f"## {next_tag} ({today})\n"]

    for cat_name, items in categories.items():
        if items:
            markdown_lines.append(f"\n### {cat_name}\n\n")
            for item in items:
                markdown_lines.append(f"- {item}\n")

    markdown_lines.append("\n")
    new_section = "".join(markdown_lines)

    # Read existing changelog
    try:
        with open("CHANGELOG.md", "r", encoding="utf-8") as f:
            existing_content = f.read()
    except FileNotFoundError:
        existing_content = ""

    # Prepend new section
    with open("CHANGELOG.md", "w", encoding="utf-8") as f:
        f.write(new_section + existing_content)

    print(f"Changelog successfully updated for pre-release {next_tag}.")


if __name__ == "__main__":
    main()
