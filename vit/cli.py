"""Vit CLI — all user interaction goes through here."""

import argparse
import json
import os
import shutil
import sys
from typing import Optional

from . import __version__
from .core import (
    GitError,
    find_project_root,
    git_add,
    git_branch,
    git_checkout,
    git_clone,
    git_commit,
    git_config_get,
    git_config_set,
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
    git_push_set_upstream,
    git_remote_add,
    git_remote_list,
    git_remote_remove,
    git_revert,
    git_show_file,
    git_status,
    is_git_repo,
)
from .json_writer import read_all_domain_files, write_timeline
from .validator import format_issues, validate_project


def _require_project() -> str:
    """Find the vit project root or exit with error."""
    root = find_project_root()
    if root is None:
        print("Error: Not a vit project. Run 'vit init' first.")
        sys.exit(1)
    return root


def cmd_init(args):
    """Initialize a new vit project."""
    project_dir = args.path or os.getcwd()

    if os.path.isdir(os.path.join(project_dir, ".vit")):
        print(f"Error: '{project_dir}' is already a vit project.")
        sys.exit(1)

    git_init(project_dir)

    # Write empty domain files for initial commit
    from .models import Timeline
    write_timeline(project_dir, Timeline())

    git_add(project_dir, [".vit/", "timeline/", "assets/", ".gitignore"])
    git_commit(project_dir, "vit: initial snapshot")
    print(f"  Initialized vit project in {project_dir}")
    print("  Created: .vit/, timeline/, assets/")
    print("  Initial snapshot committed.")


def cmd_add(args):
    """Serialize current timeline state and stage files."""
    project_dir = _require_project()

    # If Resolve is available, serialize. Otherwise just stage existing files.
    # The serializer is called from Resolve plugin scripts, not from CLI directly.
    # CLI 'add' just stages the JSON files that were already written.
    git_add(project_dir, ["timeline/", "assets/"])
    print("  Staged timeline and asset files.")


def _ensure_git_identity(project_dir: str) -> None:
    """Prompt for git user.name/email if not set, so commits are attributed correctly."""
    name = git_config_get(project_dir, "user.name")
    email = git_config_get(project_dir, "user.email")
    if not name or not email:
        print("  Git identity not set. This ensures commits show who made each change.")
        if not name:
            name = input("  Your name: ").strip()
            if name:
                git_config_set(project_dir, "user.name", name)
        if not email:
            email = input("  Your email: ").strip()
            if email:
                git_config_set(project_dir, "user.email", email)


def cmd_commit(args):
    """Stage and commit current state."""
    project_dir = _require_project()

    _ensure_git_identity(project_dir)
    git_add(project_dir, ["timeline/", "assets/", ".vit/", ".gitignore"])

    message = args.message
    if not message:
        # Try AI-suggested commit message
        try:
            from .differ import diff_from_project
            diff_text = diff_from_project(project_dir)
            if diff_text.strip():
                from .ai_merge import suggest_commit_message
                suggestion = suggest_commit_message(diff_text)
                if suggestion:
                    print(f'  AI suggested: "{suggestion}"')
                    response = input("  Use this message? [Y/n/edit]: ").strip().lower()
                    if response in ("", "y", "yes"):
                        message = suggestion
                    elif response in ("n", "no"):
                        message = None  # will fall through to default
                    else:
                        # User typed a custom message
                        message = response
        except Exception:
            pass  # Fall through to default
        if not message:
            message = "vit: save version"

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
        git_add(project_dir, ["timeline/", "assets/", ".vit/", ".gitignore"])
        try:
            git_commit(project_dir, f"vit: auto-save before merging '{branch}'")
        except GitError as e:
            if "nothing to commit" not in str(e):
                raise

    # Pre-merge AI analysis
    if not args.no_ai:
        try:
            from .differ import get_branch_diff_by_category
            from .ai_merge import analyze_branch_comparison
            changes_ours, changes_theirs = get_branch_diff_by_category(
                project_dir, current, branch
            )
            has_changes = any(changes_ours.values()) or any(changes_theirs.values())
            if has_changes:
                print(f"  Analyzing merge of '{branch}' into '{current}'...")
                analysis = analyze_branch_comparison(
                    current, branch, changes_ours, changes_theirs
                )
                rec = analysis.get("recommendation", "manual_review")
                explanation = analysis.get("explanation", "")
                conflicts = analysis.get("conflicts", [])
                if conflicts:
                    print(f"  ⚠ Potential conflicts: {', '.join(conflicts)}")
                if explanation:
                    print(f"  Analysis: {explanation}")
                if rec == "manual_review":
                    response = input("  Proceed with merge? [Y/n]: ").strip().lower()
                    if response in ("n", "no"):
                        print("  Merge cancelled.")
                        return
        except Exception:
            pass  # Skip analysis on any failure

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
                git_commit(project_dir, f"vit: AI-resolved merge of '{branch}'")
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
            print("  Resolve conflicts manually, then run 'vit commit'.")
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
            git_commit(project_dir, f"vit: AI-resolved merge of '{branch}'")
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
        if args.summary:
            try:
                from .ai_merge import summarize_log
                summary = summarize_log(output)
                if summary:
                    print(f"\n  AI Summary: {summary}")
                else:
                    print("\n  AI summary unavailable (check GEMINI_API_KEY).")
            except Exception:
                print("\n  AI summary unavailable.")
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


def cmd_config(args):
    """Configure AI/LLM settings for the project."""
    from .ai_merge import load_llm_config
    
    project_dir = _require_project()
    env_path = os.path.join(project_dir, ".env")
    
    if args.list:
        # Show current config
        config = load_llm_config()
        print("  AI Configuration:")
        print("  " + "-" * 40)
        if config.provider == "openai":
            print(f"  Provider: OpenAI-compatible API")
            print(f"  URL: {config.base_url or '(not set)'}")
            print(f"  Model: {config.model or '(default: qwen2.5-coder:14b)'}")
        else:
            print(f"  Provider: Gemini")
            gemini_key = _load_api_key_from_env(project_dir)
            if gemini_key:
                masked = gemini_key[:8] + "..." + gemini_key[-4:] if len(gemini_key) > 12 else "***"
                print(f"  GEMINI_API_KEY: {masked}")
            else:
                print(f"  GEMINI_API_KEY: (not set)")
        
        # Show .env file location
        if os.path.exists(env_path):
            print(f"  Config file: {env_path}")
        else:
            print(f"  Config file: {env_path} (will be created when setting values)")
        return
    
    # Read existing .env content
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    env_vars[key] = value.strip().strip('"').strip("'")
    
    updated = False
    
    if args.gemini_key:
        env_vars["GEMINI_API_KEY"] = args.gemini_key
        print("  Set GEMINI_API_KEY")
        updated = True
        # If setting Gemini key, remove local LLM URL to avoid conflict
        if "VIT_LLM_URL" in env_vars:
            del env_vars["VIT_LLM_URL"]
            print("  Cleared VIT_LLM_URL (using Gemini)")
    
    if args.llm_url:
        env_vars["VIT_LLM_URL"] = args.llm_url
        print(f"  Set VIT_LLM_URL to {args.llm_url}")
        print(f"  (Using OpenAI-compatible API)")
        updated = True
    
    if args.llm_model:
        env_vars["VIT_LLM_MODEL"] = args.llm_model
        print(f"  Set VIT_LLM_MODEL to {args.llm_model}")
        updated = True
    
    if args.clear_gemini:
        if "GEMINI_API_KEY" in env_vars:
            del env_vars["GEMINI_API_KEY"]
            print("  Cleared GEMINI_API_KEY")
            updated = True
    
    if args.clear_llm:
        if "VIT_LLM_URL" in env_vars:
            del env_vars["VIT_LLM_URL"]
            print("  Cleared VIT_LLM_URL")
            updated = True
        if "VIT_LLM_MODEL" in env_vars:
            del env_vars["VIT_LLM_MODEL"]
            print("  Cleared VIT_LLM_MODEL")
            updated = True
    
    if updated:
        # Write back to .env
        with open(env_path, "w") as f:
            f.write("# Vit AI Configuration\n")
            f.write("# Set either GEMINI_API_KEY or VIT_LLM_URL (local LLM takes priority)\n\n")
            for key, value in sorted(env_vars.items()):
                # Quote value if it contains spaces
                if " " in value:
                    f.write(f'{key}="{value}"\n')
                else:
                    f.write(f"{key}={value}\n")
        print(f"\n  Configuration saved to {env_path}")
    else:
        print("  No changes made. Use --help to see available options.")


def _load_api_key_from_env(project_dir: str) -> Optional[str]:
    """Load GEMINI_API_KEY from environment or .env file."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    
    env_path = os.path.join(project_dir, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


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
    "vit_panel.py",
]


_RESOLVE_MENU_NAMES = {
    "vit_panel.py": "Vit.py",
}


def _resolve_menu_name(script_name: str) -> str:
    return _RESOLVE_MENU_NAMES.get(script_name, script_name)


def cmd_install_resolve(args):
    """Install Resolve plugin scripts via symlink."""
    # Find the resolve_plugin directory — check multiple locations
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin_dir = os.path.join(package_dir, "resolve_plugin")

    if not os.path.isdir(plugin_dir):
        # Fallback: check ~/.vit/vit-src/ (curl installer location)
        # Also update package_dir so package_path gets the correct value
        vit_src = os.path.join(os.path.expanduser("~"), ".vit", "vit-src")
        if os.path.isdir(os.path.join(vit_src, "resolve_plugin")):
            package_dir = vit_src
            plugin_dir = os.path.join(package_dir, "resolve_plugin")

    if not os.path.isdir(plugin_dir):
        print(f"  Error: resolve_plugin/ directory not found.")
        print(f"  Checked: {os.path.join(package_dir, 'resolve_plugin')}")
        print(f"  Checked: {plugin_dir}")
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

    # Save the repo root path so Resolve scripts can find the vit package
    # even if __file__ or symlink resolution fails in Resolve's Python
    vit_user_dir = os.path.expanduser("~/.vit")
    os.makedirs(vit_user_dir, exist_ok=True)
    with open(os.path.join(vit_user_dir, "package_path"), "w") as f:
        f.write(package_dir)
    print(f"  Saved package path: {package_dir}")

    print(f"\n  Installed {len(RESOLVE_SCRIPT_NAMES)} script(s) to Resolve.")
    print("  Restart Resolve, then run Workspace > Scripts > Vit for the unified panel.")


def cmd_clone(args):
    """Clone a remote vit repo to a local directory."""
    url = args.url
    dest = args.directory or os.path.basename(url.rstrip("/").rstrip(".git"))
    if os.path.exists(dest):
        print(f"  Error: '{dest}' already exists.")
        sys.exit(1)
    print(f"  Cloning {url} into '{dest}'...")
    try:
        git_clone(url, dest)
    except GitError as e:
        print(f"  Error: {e}")
        sys.exit(1)
    print(f"  Cloned into '{dest}'")
    print(f"  Note: Media files are not included. Open the project in Resolve and relink any offline clips.")
    print(f"  Run 'vit checkout main' inside '{dest}' to restore the latest timeline.")


def cmd_remote(args):
    """Manage remote repositories."""
    project_dir = _require_project()

    if args.remote_cmd == "add":
        git_remote_add(project_dir, args.name, args.url)
        print(f"  Added remote '{args.name}' → {args.url}")

    elif args.remote_cmd == "list" or args.remote_cmd is None:
        remotes = git_remote_list(project_dir)
        if remotes:
            for r in remotes:
                print(f"  {r['name']}\t{r['url']}")
        else:
            print("  No remotes configured. Run 'vit collab setup' to add one.")

    elif args.remote_cmd == "remove":
        git_remote_remove(project_dir, args.name)
        print(f"  Removed remote '{args.name}'")


def cmd_collab_setup(args):
    """Interactive wizard to set up collaboration with a remote repository."""
    project_dir = _require_project()

    print("  Vit Collaboration Setup")
    print("  ─────────────────────────────────────")

    # Check existing remotes
    remotes = git_remote_list(project_dir)
    if remotes:
        print(f"  Existing remotes:")
        for r in remotes:
            print(f"    {r['name']}  {r['url']}")
        print()

    url = input("  Remote URL (e.g. https://github.com/you/film.git): ").strip()
    if not url:
        print("  Cancelled.")
        return

    remote_name = "origin"
    if remotes:
        remote_name = input("  Remote name [origin]: ").strip() or "origin"

    # Set identity if needed
    _ensure_git_identity(project_dir)

    # Add remote if not already present
    existing_names = {r["name"] for r in remotes}
    if remote_name not in existing_names:
        git_remote_add(project_dir, remote_name, url)
        print(f"  Added remote '{remote_name}'")

    # Push
    current_branch = git_current_branch(project_dir)
    print(f"  Pushing '{current_branch}' to {remote_name}...")
    try:
        output = git_push_set_upstream(project_dir, remote_name, current_branch)
        if output.strip():
            print(output)
    except GitError as e:
        print(f"  Push failed: {e}")
        print("  You may need to authenticate or create the remote repo first.")
        return

    print()
    print("  Setup complete!")
    print(f"  Share this command with collaborators:")
    print(f"    vit clone {url}")
    print()
    print("  Each collaborator should:")
    print("    1. Run: vit clone <url>")
    print("    2. Open the project folder in DaVinci Resolve")
    print("    3. Relink any offline media files")
    print("    4. Create their own branch: vit branch <name>")


def cmd_uninstall_resolve(args):
    """Remove Resolve plugin symlinks."""
    # Include legacy script names so old installs get cleaned up
    _ALL_VIT_NAMES = [
        "Vit.py",
        "Vit - Panel.py",
        "Vit - Save Version.py",
        "Vit - New Branch.py",
        "Vit - Merge Branch.py",
        "Vit - Switch Branch.py",
        "Vit - Status.py",
        "Vit - Push.py",
        "Vit - Pull & Restore.py",
    ]
    removed = 0
    for menu_name in _ALL_VIT_NAMES:
        dest = os.path.join(RESOLVE_SCRIPTS_DIR, menu_name)
        if os.path.islink(dest) or os.path.exists(dest):
            os.remove(dest)
            print(f"  Removed: {menu_name}")
            removed += 1

    if removed:
        print(f"\n  Uninstalled {removed} scripts from Resolve.")
    else:
        print("  No vit scripts found in Resolve.")


def main():
    parser = argparse.ArgumentParser(
        prog="vit",
        description="Git for Video Editing — version control timeline metadata",
    )
    parser.add_argument("--version", action="version", version=f"vit {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new vit project")
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
    p_log.add_argument("--summary", action="store_true", help="Show AI summary of recent commits")
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

    # config
    p_config = subparsers.add_parser("config", help="Configure AI/LLM settings")
    p_config.add_argument("-l", "--list", action="store_true", help="Show current configuration")
    p_config.add_argument("--gemini-key", help="Set Gemini API key")
    p_config.add_argument("--llm-url", help="Set OpenAI-compatible API URL (e.g., http://localhost:11434/v1, https://api.openai.com/v1)")
    p_config.add_argument("--llm-model", help="Set model name for OpenAI-compatible API (default: qwen2.5-coder:14b)")
    p_config.add_argument("--clear-gemini", action="store_true", help="Remove Gemini API key")
    p_config.add_argument("--clear-llm", action="store_true", help="Remove OpenAI-compatible API settings")
    p_config.set_defaults(func=cmd_config)

    # clone
    p_clone = subparsers.add_parser("clone", help="Clone a remote vit project")
    p_clone.add_argument("url", help="Remote URL to clone")
    p_clone.add_argument("directory", nargs="?", help="Target directory (default: repo name)")
    p_clone.set_defaults(func=cmd_clone)

    # remote
    p_remote = subparsers.add_parser("remote", help="Manage remote repositories")
    remote_sub = p_remote.add_subparsers(dest="remote_cmd")
    p_remote.set_defaults(func=cmd_remote, remote_cmd=None)

    p_remote_add = remote_sub.add_parser("add", help="Add a remote")
    p_remote_add.add_argument("name", help="Remote name (e.g. origin)")
    p_remote_add.add_argument("url", help="Remote URL")

    p_remote_list = remote_sub.add_parser("list", help="List remotes")

    p_remote_rm = remote_sub.add_parser("remove", help="Remove a remote")
    p_remote_rm.add_argument("name", help="Remote name to remove")

    # collab
    p_collab = subparsers.add_parser("collab", help="Collaboration setup")
    collab_sub = p_collab.add_subparsers(dest="collab_cmd")
    p_collab_setup = collab_sub.add_parser("setup", help="Guided remote setup wizard")
    p_collab_setup.set_defaults(func=cmd_collab_setup)
    p_collab.set_defaults(func=lambda a: p_collab.print_help())

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
