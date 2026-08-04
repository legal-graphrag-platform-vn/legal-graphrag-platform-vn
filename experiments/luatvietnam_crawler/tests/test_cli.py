from typer.testing import CliRunner

from experiments.luatvietnam_crawler.__main__ import (
    DEFAULT_MAX_REQUEST_DELAY,
    DEFAULT_MIN_REQUEST_DELAY,
    app,
)


def test_cli_keeps_crawl_as_explicit_subcommand() -> None:
    result = CliRunner().invoke(app, ["crawl", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0
    assert "--url" in result.stdout
    assert "--max-documents" in result.stdout
    assert "--request-budget" in result.stdout
    assert "--daily-request-budget" in result.stdout
    assert "--block-cooldown-hours" in result.stdout
    assert "--headless" in result.stdout


def test_cli_exposes_list_only_discovery_command() -> None:
    result = CliRunner().invoke(app, ["list", "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0
    assert "without opening their detail pages" in result.stdout
    assert "--max-pages" in result.stdout
    assert "--max-documents" in result.stdout
    assert "--output" in result.stdout


def test_cli_exposes_resumable_job_commands() -> None:
    runner = CliRunner()

    prepare = runner.invoke(app, ["prepare-jobs", "--help"], env={"COLUMNS": "200"})
    next_job = runner.invoke(app, ["job-next", "--help"], env={"COLUMNS": "200"})
    update = runner.invoke(app, ["job-update", "--help"], env={"COLUMNS": "200"})
    crawl = runner.invoke(app, ["crawl-jobs", "--help"], env={"COLUMNS": "200"})
    migrate = runner.invoke(
        app, ["migrate-job-states", "--help"], env={"COLUMNS": "200"}
    )
    requeue = runner.invoke(
        app, ["requeue-stale-content", "--help"], env={"COLUMNS": "200"}
    )

    assert prepare.exit_code == 0
    assert "--discovery" in prepare.stdout
    assert "--output-root" in prepare.stdout
    assert next_job.exit_code == 0
    assert "--claim" in next_job.stdout
    assert update.exit_code == 0
    assert "--status" in update.stdout
    assert crawl.exit_code == 0
    assert "--max-jobs" in crawl.stdout
    assert "--metadata-only-output" in crawl.stdout
    assert "--quiet" in crawl.stdout
    assert migrate.exit_code == 0
    assert "--bundle" in migrate.stdout
    assert requeue.exit_code == 0
    assert "--apply" in requeue.stdout


def test_cli_uses_moderately_faster_request_pacing_defaults() -> None:
    assert DEFAULT_MIN_REQUEST_DELAY == 7.0
    assert DEFAULT_MAX_REQUEST_DELAY == 12.0
