"""reproduce.sh / run.sh contracts: no silent-success paths, every computation is a logged step, inputs first."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.repro import artifacts as A  # noqa: E402

REPRO = (ROOT / "reproduce.sh").read_text()
RUN = (ROOT / "run.sh").read_text()


def section(name):
    """The body of one top-level `case` item of run.sh (up to the next item at the same indent)."""
    parts = re.split(r"^  ([a-z|\-]+)\)$", RUN, flags=re.M)
    for i in range(1, len(parts) - 1, 2):
        if name in parts[i].split("|"):
            return parts[i + 1]
    raise AssertionError(f"run.sh has no command {name}")


def code_lines(text):
    out = []
    for line in text.replace("\\\n", " ").splitlines():
        s = line.split(" #", 1)[0].strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def order(cmd_fragment):
    ids = [s["id"] for s in A.steps(REPRO) if cmd_fragment in s["cmd"]]
    assert ids, f"no reproduce.sh step runs {cmd_fragment}"
    return [s["id"] for s in A.steps(REPRO)].index(ids[0])


def test_strict_shell_and_no_escape_hatches():
    assert "set -euo pipefail" in REPRO
    for bad in ("|| true", "FORCE", "--no-checks-fail", "--allow-stale-pdf"):
        assert bad not in REPRO, bad
    assert "FORCE" not in RUN


def test_every_python_call_is_a_logged_step():
    allowed = ("step() {", "$PY scripts/repro/run_manifest.py", "$PY -c \"import duckdb, cv2\"")
    for line in code_lines(REPRO):
        if re.search(r"\$PY(?![A-Za-z_])", line) and not line.startswith("step ") and not any(a in line for a in allowed):
            if line.startswith("trap "):
                continue
            raise AssertionError(f"python call outside a logged step: {line}")


def test_snapshot_mode_is_offline_and_refuses_refetch():
    assert "COURTSIDE_OFFLINE=1" in REPRO and "scripts/repro/offline" in REPRO
    assert re.search(r'FRESH:-0}" = 1 \]; then.*?exit 2', REPRO, re.S), "FRESH=1 must be refused in reproduce.sh"
    assert "fresh_holdout.py --all" not in REPRO
    assert "holdout_inputs.py run-fixed" in REPRO
    assert "holdout_inputs.py new-fetch" in section("fresh-fetch")


def test_inputs_verified_first_and_caches_built_before_consumers():
    ids = [s["id"] for s in A.steps(REPRO)]
    assert ids[:3] == ["s00_universe", "s00_inputs", "s00_archived"]
    assert order("run_all.py --oos") < order("scripts/reproduce_inputs.py")
    for consumer in ("v2_wallet_cap.py --is", "v2_wallet_cap.py --oos", "psr_mintrl.py", "cv_cost_turnover.py"):
        assert order("scripts/reproduce_inputs.py") < order(consumer), consumer
    assert order("build_paper.py") > order("cv_cost_turnover.py")
    assert ids[-1] == "s11_artifacts"


def test_step_ids_unique_and_outputs_declared_for_paper_sources():
    st = A.steps(REPRO)
    assert len({s["id"] for s in st}) == len(st)
    outs = {o for s in st for o in s["outs"]}
    for f in ("results/summary.json", "results/v2/causal.json", "results/rigor/psr.json",
              "results/tier0/cost_turnover.json", "results/fresh_holdout/results.json", "results/paper/numbers.json",
              "docs/NOTE.pdf"):
        assert f in outs, f


def test_skipped_parts_fail_the_run():
    assert "snowflake.recheck.status=ran" in REPRO and "vultr.tests.returncode=0" in REPRO
    impact = [s for s in A.steps(REPRO) if "impact_model.py" in s["cmd"]][0]
    assert impact["skip_unless"], "impact_model needs data/live: it must be an explicit, recorded skip"


def test_run_sh_has_no_hidden_failures():
    assert "wait $R1 $R2" not in RUN
    redteam = section("redteam")
    assert "&& echo" not in redteam
    assert "manifest.py verify" in section("data")
    cv = section("cv")
    assert "check_model.py" in cv and "ALLOW_NO_CALL_MODEL" in cv


def test_setup_installs_reproduction_dependencies_and_compiler():
    setup = section("setup")
    assert "requirements-repro.txt" in setup and "requirements.lock" in setup and "ensure_tectonic" in setup
    reqs = (ROOT / "requirements-repro.txt").read_text()
    for pkg in ("duckdb==", "opencv-python-headless==", "paramiko==", "tabulate=="):
        assert pkg in reqs and pkg in (ROOT / "requirements.lock").read_text(), pkg
    core = [l.split("==")[0].lower() for l in (ROOT / "requirements.txt").read_text().splitlines()
            if "==" in l and not l.startswith("#")]
    lock = (ROOT / "requirements.lock").read_text().lower()
    for pkg in core:
        assert f"{pkg}==" in lock, pkg
