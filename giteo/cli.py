"""Giteo CLI — all user interaction goes through here."""

import argparse
import json
import os
import shutil
import sys

from . import __version__
from .core import (
    GitError,
    find_project_root,
    git_add,
    git_branch,
    git_checkout,
    git_commit,
    git_current_branch,
    git_diff,
    git_init,
    git_list_branches,
    git_list_conflicted_files,
    git_log,
    git_merge,
    git_merge_abort,
    git_merge_base,
    git_pull,
    git_push,
    git_revert,
    git_show_file,
    git_status,
    is_git_repo,
)
from .json_writer import read_all_domain_files, write_timeline
from .validator import format_issues, validate_project


def _require_project() -> str:
    """Find the giteo project root or exit with error."""
    root = find_project_root()
    if root is None:
        print("Error: Not a giteo project. Run 'giteo init' first.")
        sys.exit(1)
    return root


def cmd_init(args):
    """Initialize a new giteo project."""
    project_dir = args.path or os.getcwd()

    if os.path.isdir(os.path.join(project_dir, ".giteo")):
        print(f"Error: '{project_dir}' is already a giteo project.")
        sys.exit(1)

    git_init(project_dir)

    # Write empty domain files for initial commit
    from .models import Timeline
    write_timeline(project_dir, Timeline())

    git_add(project_dir, [".giteo/", "timeline/", "assets/", ".gitignore"])
    git_commit(project_dir, "giteo: initial snapshot")
    print(f"  Initialized giteo project in {project_dir}")
    print("  Created: .giteo/, timeline/, assets/")
    print("  Initial snapshot committed.")


def cmd_add(args):
    """Serialize current timeline state and stage files."""
    project_dir = _require_project()

    # If Resolve is available, serialize. Otherwise just stage existing files.
    # The serializer is called from Resolve plugin scripts, not from CLI directly.
    # CLI 'add' just stages the JSON files that were already written.
    git_add(project_dir, ["timeline/", "assets/"])
    print("  Staged timeline and asset files.")


def cmd_commit(args):
    """Stage and commit current state."""
    project_dir = _require_project()

    git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])

    message = args.message or "giteo: save version"
    try:
        commit_hash = git_commit(project_dir, message)
        print(f"  Committed: {message}")
        if commit_hash:
            print(f"  Hash: {commit_hash}")
    except GitError as e:
        if "nothing to commit" in str(e):
            print("  Nothing to commit — timeline unchanged.")
        else:
            raise


def cmd_branch(args):
    """Create and switch to a new branch."""
    project_dir = _require_project()

    if args.list:
        branches = git_list_branches(project_dir)
        current = git_current_branch(project_dir)
        for b in branches:
            prefix = "* " if b == current else "  "
            print(f"{prefix}{b}")
        return

    if not args.name:
        # Show current branch
        current = git_current_branch(project_dir)
        print(f"  Current branch: {current}")
        return

    git_branch(project_dir, args.name)
    print(f"  Created and switched to branch '{args.name}'")


def cmd_checkout(args):
    """Switch to a branch or commit."""
    project_dir = _require_project()
    git_checkout(project_dir, args.ref)
    print(f"  Switched to '{args.ref}'")


def cmd_merge(args):
    """Merge a branch into current branch."""
    from .core import git_is_clean
    project_dir = _require_project()
    branch = args.branch
    current = git_current_branch(project_dir)

    # Auto-commit any outstanding changes before merge
    if not git_is_clean(project_dir):
        print(f"  Auto-saving uncommitted changes before merge...")
        git_add(project_dir, ["timeline/", "assets/", ".giteo/", ".gitignore"])
        try:
            git_commit(project_dir, f"giteo: auto-save before merging '{branch}'")
        except GitError as e:
            if "nothing to commit" not in str(e):
                raise

    print(f"  Merging '{branch}' into '{current}'...")

    # Capture pre-merge state for AI merge if needed
    pre_merge_files = read_all_domain_files(project_dir)

    success, output = git_merge(project_dir, branch)

    if success:
        # Git merge succeeded — run post-merge validation
        print("  Git merge succeeded.")
        issues = validate_project(project_dir)

        # Get merge base and branch files for overlap detection
        merge_base_ref = git_merge_base(project_dir, current, branch)
        base_files = _load_files_at_ref(project_dir, merge_base_ref) if merge_base_ref else {}
        theirs_files = _load_files_at_ref(project_dir, branch)

        # Check if both branches modified the same domain files
        overlapping_domains = _detect_overlapping_domains(
            base_files, pre_merge_files, theirs_files
        )

        errors = [i for i in issues if i.severity == "error"]
        needs_ai_review = (
            not args.no_ai and (errors or overlapping_domains)
        )

        if not issues and not overlapping_domains:
            print("  Post-merge validation passed.")
            return

        if issues:
            print(f"\n  Post-merge validation found issues:")
            print(format_issues(issues))

        if overlapping_domains and not issues:
            print(f"\n  Both branches modified: {', '.join(overlapping_domains)}")
            print("  Running AI review to check for semantic conflicts...")

        if needs_ai_review:
            from .ai_merge import merge_with_ai
            resolved = merge_with_ai(
                project_dir, branch,
                base_files, pre_merge_files, theirs_files,
                issues, [],
            )
            if resolved:
                git_add(project_dir, ["timeline/", "assets/"])
                git_commit(project_dir, f"giteo: AI-resolved merge of '{branch}'")
                print("  Merge complete with AI resolution.")
            else:
                if errors:
                    print("  Merge completed with unresolved issues. Review manually.")
                else:
                    print("  AI review declined. Merge completed.")
        else:
            if errors:
                print("  Merge completed with issues. Review manually.")
    else:
        # Git merge failed — conflicts
        print("  Git merge has conflicts.")
        conflicted = git_list_conflicted_files(project_dir)

        if conflicted:
            print(f"  Conflicted files: {', '.join(conflicted)}")

        if args.no_ai:
            print("  Resolve conflicts manually, then run 'giteo commit'.")
            return

        # Try AI resolution
        print("\n  Attempting AI-assisted conflict resolution...")
        merge_base_ref = git_merge_base(project_dir, current, branch)
        base_files = _load_files_at_ref(project_dir, merge_base_ref) if merge_base_ref else {}
        theirs_files = _load_files_at_ref(project_dir, branch)

        # Abort the failed merge to get clean state for AI
        git_merge_abort(project_dir)

        from .ai_merge import merge_with_ai
        resolved = merge_with_ai(
            project_dir, branch,
            base_files, pre_merge_files, theirs_files,
            [], conflicted,
        )
        if resolved:
            git_add(project_dir, ["timeline/", "assets/"])
            git_commit(project_dir, f"giteo: AI-resolved merge of '{branch}'")
            print("  Merge complete with AI resolution.")
        else:
            print("  AI merge failed. Resolve conflicts manually.")
            # Re-attempt the merge so user can resolve
            git_merge(project_dir, branch)


def _load_files_at_ref(project_dir: str, ref: str) -> dict:
    """Load all domain files at a specific git ref."""
    domain_paths = {
        "cuts": "timeline/cuts.json",
        "color": "timeline/color.json",
        "audio": "timeline/audio.json",
        "effects": "timeline/effects.json",
        "markers": "timeline/markers.json",
        "metadata": "timeline/metadata.json",
        "manifest": "assets/manifest.json",
    }
    files = {}
    for domain, path in domain_paths.items():
        content = git_show_file(project_dir, ref, path)
        if content:
            try:
                files[domain] = json.loads(content)
            except json.JSONDecodeError:
                files[domain] = {}
        else:
            files[domain] = {}
    return files


def _detect_overlapping_domains(
    base_files: dict,
    ours_files: dict,
    theirs_files: dict,
) -> list:
    """Detect which domain files were modified by both branches.

    Returns list of domain names that both branches modified relative to the base.
    This indicates potential semantic conflicts that git may not catch.
    """
    overlapping = []

    for domain in base_files.keys():
        base_content = base_files.get(domain, {})
        ours_content = ours_files.get(domain, {})
        theirs_content = theirs_files.get(domain, {})

        # Check if both branches modified this domain
        ours_changed = base_content != ours_content
        theirs_changed = base_content != theirs_content

        if ours_changed and theirs_changed:
            overlapping.append(domain)

    return overlapping


def cmd_diff(args):
    """Show human-readable diff of timeline changes."""
    project_dir = _require_project()

    ref = args.ref or "HEAD"

    try:
        from .differ import diff_from_project
        output = diff_from_project(project_dir, ref)
        if output.strip():
            print(output)
        else:
            print("  No changes.")
    except GitError:
        # No commits yet or other git issue — show raw git diff
        raw = git_diff(project_dir)
        if raw:
            print(raw)
        else:
            print("  No changes.")


def cmd_log(args):
    """Show version history."""
    project_dir = _require_project()
    count = args.count or 20
    output = git_log(project_dir, max_count=count)
    if output:
        print(output)
    else:
        print("  No commits yet.")


def cmd_status(args):
    """Show current project status."""
    project_dir = _require_project()
    current = git_current_branch(project_dir)
    print(f"  Branch: {current}")

    status = git_status(project_dir)
    if status:
        print(status)
    else:
        print("  Working tree clean.")


def cmd_revert(args):
    """Revert the last commit."""
    project_dir = _require_project()
    try:
        git_revert(project_dir)
        print("  Reverted last commit.")
    except GitError as e:
        print(f"  Error: {e}")


def cmd_push(args):
    """Push to remote."""
    project_dir = _require_project()
    remote = args.remote or "origin"
    branch = args.branch
    try:
        output = git_push(project_dir, remote, branch)
        print(f"  Pushed to {remote}")
        if output.strip():
            print(output)
    except GitError as e:
        print(f"  Error: {e}")


def cmd_pull(args):
    """Pull from remote."""
    project_dir = _require_project()
    remote = args.remote or "origin"
    branch = args.branch
    try:
        output = git_pull(project_dir, remote, branch)
        print(f"  Pulled from {remote}")
        if output.strip():
            print(output)
    except GitError as e:
        print(f"  Error: {e}")


def cmd_validate(args):
    """Run post-merge validation on current state."""
    project_dir = _require_project()
    issues = validate_project(project_dir)
    if issues:
        print(format_issues(issues))
        sys.exit(1)
    else:
        print("  Validation passed — no issues found.")


if sys.platform == "win32":
    RESOLVE_SCRIPTS_DIR = os.path.join(
        os.environ.get("APPDATA", ""),
        "Blackmagic Design",
        "DaVinci Resolve",
        "Fusion",
        "Scripts",
        "Edit",
    )
else:
    RESOLVE_SCRIPTS_DIR = os.path.expanduser(
        "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"
    )

RESOLVE_SCRIPT_NAMES = [
    "giteo_panel.py",
]


_RESOLVE_MENU_NAMES = {
    "giteo_panel.py": "Giteo.py",
}


def _resolve_menu_name(script_name: str) -> str:
    return _RESOLVE_MENU_NAMES.get(script_name, script_name)


def cmd_install_resolve(args):
    """Install Resolve plugin scripts via symlink."""
    # Find the resolve_plugin directory relative to this package
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(package_dir, "resolve_plugin")

    if not os.path.isdir(plugin_dir):
        print(f"  Error: resolve_plugin/ directory not found at {plugin_dir}")
        sys.exit(1)

    os.makedirs(RESOLVE_SCRIPTS_DIR, exist_ok=True)

    for script_name in RESOLVE_SCRIPT_NAMES:
        source = os.path.join(plugin_dir, script_name)
        if not os.path.exists(source):
            print(f"  Warning: {script_name} not found, skipping.")
            continue

        menu_name = _resolve_menu_name(script_name)
        dest = os.path.join(RESOLVE_SCRIPTS_DIR, menu_name)

        # Remove existing link/file
        if os.path.islink(dest) or os.path.exists(dest):
            os.remove(dest)

        if sys.platform == "win32":
            shutil.copy2(source, dest)
        else:
            os.symlink(source, dest)
        print(f"  Linked: {menu_name} → {source}")

    # Save the repo root path so Resolve scripts can find the giteo package
    # even if __file__ or symlink resolution fails in Resolve's Python
    giteo_user_dir = os.path.expanduser("~/.giteo")
    os.makedirs(giteo_user_dir, exist_ok=True)
    with open(os.path.join(giteo_user_dir, "package_path"), "w") as f:
        f.write(package_dir)
    print(f"  Saved package path: {package_dir}")

    print(f"\n  Installed {len(RESOLVE_SCRIPT_NAMES)} script(s) to Resolve.")
    print("  Restart Resolve, then run Workspace > Scripts > Giteo for the unified panel.")


def cmd_uninstall_resolve(args):
    """Remove Resolve plugin symlinks."""
    # Include legacy script names so old installs get cleaned up
    _ALL_GITEO_NAMES = [
        "Giteo.py",
        "Giteo - Panel.py",
        "Giteo - Save Version.py",
        "Giteo - New Branch.py",
        "Giteo - Merge Branch.py",
        "Giteo - Switch Branch.py",
        "Giteo - Status.py",
        "Giteo - Push.py",
        "Giteo - Pull & Restore.py",
    ]
    removed = 0
    for menu_name in _ALL_GITEO_NAMES:
        dest = os.path.join(RESOLVE_SCRIPTS_DIR, menu_name)
        if os.path.islink(dest) or os.path.exists(dest):
            os.remove(dest)
            print(f"  Removed: {menu_name}")
            removed += 1

    if removed:
        print(f"\n  Uninstalled {removed} scripts from Resolve.")
    else:
        print("  No giteo scripts found in Resolve.")


def main():
    parser = argparse.ArgumentParser(
        prog="giteo",
        description="Git for Video Editing — version control timeline metadata",
    )
    parser.add_argument("--version", action="version", version=f"giteo {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new giteo project")
    p_init.add_argument("path", nargs="?", help="Project directory (default: current)")
    p_init.set_defaults(func=cmd_init)

    # add
    p_add = subparsers.add_parser("add", help="Stage timeline files")
    p_add.set_defaults(func=cmd_add)

    # commit
    p_commit = subparsers.add_parser("commit", help="Save a version")
    p_commit.add_argument("-m", "--message", help="Commit message")
    p_commit.set_defaults(func=cmd_commit)

    # branch
    p_branch = subparsers.add_parser("branch", help="Create or list branches")
    p_branch.add_argument("name", nargs="?", help="Branch name to create")
    p_branch.add_argument("-l", "--list", action="store_true", help="List branches")
    p_branch.set_defaults(func=cmd_branch)

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="Switch branch or version")
    p_checkout.add_argument("ref", help="Branch name or commit hash")
    p_checkout.set_defaults(func=cmd_checkout)

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge a branch")
    p_merge.add_argument("branch", help="Branch to merge")
    p_merge.add_argument("--no-ai", action="store_true", help="Skip AI merge resolution")
    p_merge.set_defaults(func=cmd_merge)

    # diff
    p_diff = subparsers.add_parser("diff", help="Show timeline changes")
    p_diff.add_argument("ref", nargs="?", help="Compare against ref (default: HEAD)")
    p_diff.set_defaults(func=cmd_diff)

    # log
    p_log = subparsers.add_parser("log", help="Show version history")
    p_log.add_argument("-n", "--count", type=int, help="Max entries (default: 20)")
    p_log.set_defaults(func=cmd_log)

    # status
    p_status = subparsers.add_parser("status", help="Show project status")
    p_status.set_defaults(func=cmd_status)

    # revert
    p_revert = subparsers.add_parser("revert", help="Revert last version")
    p_revert.set_defaults(func=cmd_revert)

    # push
    p_push = subparsers.add_parser("push", help="Push to remote")
    p_push.add_argument("--remote", default="origin", help="Remote name")
    p_push.add_argument("--branch", help="Branch to push")
    p_push.set_defaults(func=cmd_push)

    # pull
    p_pull = subparsers.add_parser("pull", help="Pull from remote")
    p_pull.add_argument("--remote", default="origin", help="Remote name")
    p_pull.add_argument("--branch", help="Branch to pull")
    p_pull.set_defaults(func=cmd_pull)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate timeline consistency")
    p_validate.set_defaults(func=cmd_validate)

    # install-resolve
    p_install = subparsers.add_parser("install-resolve", help="Install scripts into DaVinci Resolve")
    p_install.set_defaults(func=cmd_install_resolve)

    # uninstall-resolve
    p_uninstall = subparsers.add_parser("uninstall-resolve", help="Remove scripts from DaVinci Resolve")
    p_uninstall.set_defaults(func=cmd_uninstall_resolve)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except GitError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
