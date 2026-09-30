"""Command-line entry point: `caseflow process ...`.

Exit codes:
  0   every document succeeded (expected email skips and unsupported-file skips count as success)
  1   run completed but at least one document failed or was only partially processed
  2   fatal: invalid configuration/startup failure, or the run aborted (e.g. invalid API key)
  130 interrupted by the user (Ctrl+C); completed outputs and the manifest are kept
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, Settings, load_settings
from .llm_client import build_provider
from .logging_config import configure_logging
from .output_writer import make_run_id
from .workflow import ABORTED, FAILED, INTERRUPTED, PARTIAL, SKIPPED, SUCCESS, RunResult, run_batch

EXIT_OK, EXIT_PARTIAL, EXIT_FATAL, EXIT_INTERRUPTED = 0, 1, 2, 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caseflow", description="CaseFlow AI - customer complaint & case processing")
    parser.add_argument("--version", action="version", version=f"caseflow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="process all documents in a folder")
    p.add_argument("--input", type=Path, default=Path("data"), help="input folder (default: data)")
    p.add_argument("--output", type=Path, default=Path("output"), help="output root (default: output)")
    p.add_argument("--provider", choices=["mock", "openai"], default="mock",
                   help="mock = offline demo fixtures; openai = real API calls (default: mock)")
    p.add_argument("--recursive", action="store_true", help="also scan sub-folders")
    p.add_argument("--log-dir", type=Path, default=Path("logs"))
    p.add_argument("--batch-concurrency", type=int, help="override BATCH_CONCURRENCY")
    p.add_argument("--llm-concurrency", type=int, help="override LLM_CONCURRENCY")
    p.add_argument("--company-name", help="override COMPANY_NAME")
    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    d = sub.add_parser("dashboard", help="(re)build the HTML dashboard for a run")
    d.add_argument("run_dir", nargs="?", type=Path, help="run folder (default: latest run in --output)")
    d.add_argument("--output", type=Path, default=Path("output"))
    return parser


def _print_summary(result: RunResult) -> None:
    c = result.counts()
    line = "=" * 64
    print(line)
    if result.provider_mode == "mock":
        print("MOCK MODE - results are canned demo fixtures, NOT real AI output.")
    print(f"Run {result.run_id}: {result.status}   provider={result.provider_mode}")
    print(f"  successful:           {c[SUCCESS]}")
    print(f"  partially successful: {c[PARTIAL]}")
    print(f"  failed:               {c[FAILED]}")
    print(f"  skipped (unsupported):{c[SKIPPED]:>2}")
    if c[INTERRUPTED] or c[ABORTED]:
        print(f"  interrupted/aborted:  {c[INTERRUPTED] + c[ABORTED]}")
    print(f"  elapsed:              {result.elapsed_seconds:.2f}s  (peak concurrent LLM calls: {result.llm_peak_concurrency})")
    if result.fatal_error:
        print(f"  FATAL: {result.fatal_error} - remaining documents were not processed")
    print(f"Final report: {result.report_path}")
    print(f"Manifest:     {result.manifest_path}")
    print(f"Dashboard:    {result.run_dir / 'dashboard.html'}")
    print(line)


def exit_code_for(result: RunResult) -> int:
    if result.status == "aborted":
        return EXIT_FATAL
    if result.status == "interrupted":
        return EXIT_INTERRUPTED
    c = result.counts()
    return EXIT_PARTIAL if (c[FAILED] or c[PARTIAL]) else EXIT_OK


async def _run(settings: Settings, run_id: str) -> RunResult:
    provider = build_provider(settings)
    try:
        return await run_batch(settings, provider, run_id=run_id)
    finally:
        await provider.aclose()


def _dashboard(args: argparse.Namespace) -> int:
    from .dashboard import write_dashboard

    run_dir = args.run_dir
    if run_dir is None:
        latest = args.output / "LATEST_RUN.txt"
        if not latest.exists():
            print(f"No runs found in {args.output}", file=sys.stderr)
            return EXIT_FATAL
        run_dir = args.output / latest.read_text(encoding="utf-8").strip()
    if not (run_dir / "run_manifest.json").exists():
        print(f"Not a run folder: {run_dir}", file=sys.stderr)
        return EXIT_FATAL
    print(f"Dashboard: {write_dashboard(run_dir)}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dashboard":
        return _dashboard(args)
    try:
        settings = load_settings({
            "provider": args.provider,
            "input_dir": args.input,
            "output_dir": args.output,
            "log_dir": args.log_dir,
            "recursive": args.recursive or None,
            "batch_concurrency": args.batch_concurrency,
            "llm_concurrency": args.llm_concurrency,
            "company_name": args.company_name,
            "log_level": args.log_level,
        })
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_FATAL

    run_id = make_run_id()
    configure_logging(settings.log_level, settings.log_dir / f"{run_id}.log")
    if settings.is_mock:
        print("MOCK MODE - no API calls; bundled fixture responses are used for the demo documents.", flush=True)
    else:
        print(f"REAL MODE - document text will be sent to the OpenAI API (model {settings.openai_model}).", flush=True)

    try:
        result = asyncio.run(_run(settings, run_id))
    except KeyboardInterrupt:
        print(f"\nInterrupted. Completed outputs and the manifest were saved in {settings.output_dir / run_id}",
              file=sys.stderr)
        return EXIT_INTERRUPTED
    except (OSError, ConfigError) as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        return EXIT_FATAL

    _print_summary(result)
    return exit_code_for(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
