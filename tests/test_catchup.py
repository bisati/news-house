"""scripts/catchup.sh: start a tick the 2-hour timer missed while the Mac slept."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "catchup.sh"
H = 3600
MORNING = 1_000_000  # today's 06:00 as epoch seconds


def due(now: int, last: int, morning: int = MORNING) -> bool:
    r = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; due {now} {last} {morning}'])
    return r.returncode == 0


def test_due_after_two_hours():
    assert due(MORNING + 5 * H, MORNING + 3 * H)
    assert not due(MORNING + 5 * H, MORNING + 4 * H)


def test_due_once_after_the_build_hour():
    # last tick at 03:15, Mac wakes at 06:40: owed even though under 2 hours
    assert due(MORNING + 40 * 60, MORNING - 165 * 60)
    # a tick already started after 06:00: not owed again until 2 hours pass
    assert not due(MORNING + 60 * 60, MORNING + 5 * 60)
    # before 06:00 and under 2 hours: not owed
    assert not due(MORNING - 10 * 60, MORNING - 60 * 60)


def test_build_hour_matches_the_pipeline():
    from newshouse.tick import BUILD_HOUR
    assert f"BUILD_HOUR={BUILD_HOUR:02d}" in SCRIPT.read_text()


def test_tick_stamps_and_stays_awake():
    sh = (ROOT / "scripts" / "tick.sh").read_text()
    assert "date +%s > out/.last-tick" in sh
    assert "exec /usr/bin/caffeinate -i newshouse tick --out out" in sh


def test_installers_know_the_catchup_agent():
    assert "CATCHUP_LABEL=com.bisati.news-house.catchup" in (ROOT / "scripts" / "install_launchd.sh").read_text()
    assert "com.bisati.news-house.catchup" in (ROOT / "scripts" / "uninstall_launchd.sh").read_text()
    plist = (ROOT / "launchd" / "com.bisati.news-house.catchup.plist.template").read_text()
    assert "<integer>600</integer>" in plist and "@REPO@/scripts/catchup.sh" in plist
