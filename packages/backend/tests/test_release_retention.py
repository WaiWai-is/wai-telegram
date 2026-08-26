import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[3]


def test_prune_releases_keeps_active_rollback_and_newest_release(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "releases"
    release_root.mkdir()
    active = release_root / "release-active"
    stale = release_root / "release-stale"
    newest = release_root / "release-newest"
    for release in (active, stale, newest):
        release.mkdir()

    os.utime(active, (100, 100))
    os.utime(stale, (200, 200))
    os.utime(newest, (300, 300))
    current_link = tmp_path / "current"
    current_link.symlink_to(active)
    unrelated = release_root / "failed-build"
    unrelated.mkdir()

    env = os.environ.copy()
    env.update(
        {
            "WAI_TELEGRAM_RELEASE_ROOT": str(release_root),
            "WAI_TELEGRAM_CURRENT_LINK": str(current_link),
        }
    )
    subprocess.run(
        ["bash", str(REPOSITORY_ROOT / "scripts/prune-releases.sh")],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert active.is_dir()
    assert newest.is_dir()
    assert not stale.exists()
    assert unrelated.is_dir()


def test_production_deploy_prunes_releases_after_activation() -> None:
    workflow = REPOSITORY_ROOT.joinpath(".github/workflows/deploy.yml").read_text()

    assert "/opt/wai-telegram/scripts/prune-releases.sh" in workflow
