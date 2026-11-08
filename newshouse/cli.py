"""newshouse command line."""
import argparse
import json
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select

from newshouse.breaking import run_breaking
from newshouse.build import build_edition
from newshouse.config import get_settings
from newshouse.db import default_engine, ensure_columns, get_engine, init_db, session_scope
from newshouse.edition_config import load_edition_config
from newshouse.embed import Embedder
from newshouse.health import check_sources
from newshouse.feedback import ACTIONS, record_feedback
from newshouse.ingest import DEFAULT_KINDS, ingest
from newshouse.llm.backend import get_backend
from newshouse.models import AlsoHappened, Card, Edition
from newshouse.profile import load_profile
from newshouse.render_static import render_edition
from newshouse.sources import load_sources, sync_sources
from newshouse.tick import tick
from newshouse.validate import load_banned


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="newshouse")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="create tables")
    sub.add_parser("inbox-init", help="create the feedback inbox table in Neon")
    sub.add_parser("sync-feedback", help="record new inbox rows as feedback")
    sub.add_parser("sync-sources", help="load sources.yaml into the database")
    ing = sub.add_parser("ingest", help="fetch all enabled sources")
    ing.add_argument("--kinds", nargs="+", default=sorted(DEFAULT_KINDS))
    fb = sub.add_parser("feedback", help="record a reaction to a card or cluster")
    fb.add_argument("target", nargs="?", help="card id (omit when using --cluster)")
    fb.add_argument("action", nargs="?")
    fb.add_argument("--cluster", help="cluster id instead of a card id")
    fb.add_argument("--payload", help="JSON object stored with the reaction")
    bd = sub.add_parser("build", help="build today's edition")
    bd.add_argument("--date", type=date.fromisoformat, help="edition date YYYY-MM-DD")
    bd.add_argument("--force", action="store_true", help="rebuild an already built edition")
    rd = sub.add_parser("render", help="render an edition to static HTML + JSON")
    rd.add_argument("--date", type=date.fromisoformat, help="edition date YYYY-MM-DD (default: today)")
    rd.add_argument("--out", type=Path, default=Path("out"), help="output directory")
    rd.add_argument("--validate", action="store_true",
                    help="run the edition validator (report only) and store its warnings")
    sub.add_parser("breaking", help="run the breaking lane once")
    sub.add_parser("health", help="re-fetch every feed and report dead sources")
    tk = sub.add_parser("tick", help="the scheduled entry point (ingest, build or breaking)")
    tk.add_argument("--out", type=Path, default=Path("out"), help="output directory")
    ls = sub.add_parser("lesson", help="the lessons ledger (path: LESSONS_PATH)")
    lsub = ls.add_subparsers(dest="lesson_cmd", required=True)
    la = lsub.add_parser("add", help="add a lesson")
    src = la.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-feedback", metavar="FEEDBACK_ID",
                     help="stub from a 'Should have been in' tap")
    src.add_argument("--text", help="the miss, in your words")
    lsub.add_parser("list", help="print open lessons, one per line")
    pb = sub.add_parser("publish", help="push the rendered pages and site bundle to the site branch")
    pb.add_argument("--out", type=Path, default=Path("out"), help="rendered pages directory")
    sv = sub.add_parser("serve", help="serve out/ and accept POST /feedback")
    sv.add_argument("--out", type=Path, default=Path("out"), help="directory to serve")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--host", default="0.0.0.0")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd not in ("init-db", "publish"):  # init-db runs it itself; publish reads no models
        # an older database lacks the newer columns (create_all never adds them); every
        # other command reads the models, so upgrade it once here, before any query
        ensure_columns(default_engine())
    if args.cmd == "init-db":
        init_db(get_engine())
        print("ok")
    elif args.cmd in ("inbox-init", "sync-feedback"):
        from newshouse.inbox import init_inbox, inbox_engine, sync_feedback
        settings = get_settings()
        if not settings.neon_database_url:
            print("NEON_DATABASE_URL is not set (put it in ~/.config/news-house/neon.env)",
                  file=sys.stderr)
            return 2
        eng = inbox_engine(settings.neon_database_url)
        try:
            if args.cmd == "inbox-init":
                init_inbox(eng)
                print("ok")
            else:
                with session_scope() as s:
                    print(json.dumps(sync_feedback(s, eng, profile_id=settings.profile_id,
                                                   now=datetime.now(timezone.utc))))
        finally:
            eng.dispose()
    elif args.cmd == "sync-sources":
        specs = load_sources(get_settings().sources_path)
        with session_scope() as s:
            n = sync_sources(s, specs)
        print(f"synced {n} sources")
    elif args.cmd == "ingest":
        with httpx.Client() as client, session_scope() as s:
            stats = ingest(s, now=datetime.now(timezone.utc), client=client, kinds=set(args.kinds))
        print(json.dumps(stats.model_dump(), indent=2))
    elif args.cmd == "feedback":
        if args.cluster:  # `feedback --cluster <id> <action>`: the action lands in `target`
            action, card_id = args.action or args.target, None
        else:
            action, card_id = args.action, args.target
        if action not in ACTIONS or (not args.cluster and not card_id):
            build_parser().error("usage: feedback <card_id> <action> | feedback --cluster <id> <action>")
        payload = None
        if args.payload is not None:
            try:
                payload = json.loads(args.payload)
            except ValueError:
                build_parser().error("--payload must be valid JSON")
            if not isinstance(payload, dict):
                build_parser().error("--payload must be a JSON object")
        with session_scope() as s:
            fb = record_feedback(s, profile_id=get_settings().profile_id, action=action,
                                 card_id=card_id, cluster_id=args.cluster,
                                 at=datetime.now(timezone.utc), payload=payload)
            print(fb.id)
    elif args.cmd == "build":
        settings = get_settings()
        with httpx.Client() as client, session_scope() as s:
            ed = build_edition(s, get_backend(settings), settings=settings,
                               now=datetime.now(timezone.utc), client=client,
                               embedder=Embedder(), force=args.force, date=args.date)
            n_cards = s.scalar(select(func.count()).select_from(Card).where(Card.edition_id == ed.id))
            n_also = s.scalar(select(func.count()).select_from(AlsoHappened)
                              .where(AlsoHappened.edition_id == ed.id))
            print(json.dumps({"edition": ed.id, "date": ed.date.isoformat(),
                              "cards": n_cards, "also": n_also}))
    elif args.cmd == "render":
        settings = get_settings()
        day = args.date or datetime.now(ZoneInfo(settings.tz)).date()
        with session_scope() as s:
            ed = s.scalar(select(Edition).where(Edition.profile_id == settings.profile_id,
                                                Edition.date == day))
            if ed is None:
                build_parser().error(f"no edition for {day.isoformat()}")
            if args.validate:
                path = render_edition(s, ed, args.out, validate=True,
                                      cfg=load_edition_config(settings.edition_config_path),
                                      profile_text=load_profile(s, settings).text,
                                      banned=load_banned())
            else:
                path = render_edition(s, ed, args.out)
            newest = s.scalar(select(Edition.date).where(Edition.profile_id == settings.profile_id,
                                                         Edition.built_at.is_not(None))
                              .order_by(Edition.date.desc()).limit(1))
            if newest == ed.date:
                shutil.copyfile(path, Path(args.out) / "latest.html")
            print(path)
    elif args.cmd == "breaking":
        settings = get_settings()
        with httpx.Client() as client, session_scope() as s:
            cards = run_breaking(s, get_backend(settings), settings=settings,
                                 now=datetime.now(timezone.utc), client=client)
            print(json.dumps({"breaking": [c.id for c in cards]}))
    elif args.cmd == "health":
        with httpx.Client() as client, session_scope() as s:
            report = check_sources(s, client=client, now=datetime.now(timezone.utc))
        print(json.dumps(report, indent=2))
    elif args.cmd == "tick":
        settings = get_settings()
        with httpx.Client() as client, session_scope() as s:
            result = tick(s, get_backend(settings), settings=settings,
                          now=datetime.now(timezone.utc), client=client,
                          embedder=Embedder(), out_dir=args.out)
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "lesson":
        from newshouse.lessons import add_text, load_lessons, stub_from_feedback
        settings = get_settings()
        path = settings.lessons_path
        if args.lesson_cmd == "list":
            for l in load_lessons(path):
                if l.status == "open":
                    print(f"{l.id}\t{l.date}\t{l.miss}")
            return 0
        today = datetime.now(ZoneInfo(settings.tz)).date()
        if args.text is not None:
            print(add_text(path, args.text, today=today).id)
            return 0
        with session_scope() as s:
            lesson = stub_from_feedback(s, path, args.from_feedback, today=today)
        if lesson is None:
            print(f"no stub: {args.from_feedback} is not a should_have tap on a cluster, "
                  "or it already has a lesson", file=sys.stderr)
            return 1
        print(lesson.id)
    elif args.cmd == "publish":
        from newshouse import publish as pub
        settings = get_settings()
        if not settings.publish_remote:
            print("PUBLISH_REMOTE is not set (put it in ~/.config/news-house/publish.env)",
                  file=sys.stderr)
            return 2
        result = pub.publish(args.out, repo=pub.REPO_ROOT, remote=settings.publish_remote,
                             branch=settings.publish_branch, worktree=settings.publish_worktree,
                             now=datetime.now(timezone.utc),
                             author_name=settings.publish_author_name,
                             author_email=settings.publish_author_email)
        print(json.dumps(result))
        return 1 if result["status"] == "error" else 0
    elif args.cmd == "serve":
        import logging
        from newshouse.serve import serve
        logging.basicConfig(level=logging.INFO)
        serve(args.out, host=args.host, port=args.port)
    return 0
