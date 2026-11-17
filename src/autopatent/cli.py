import argparse
import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from autopatent.config import Settings
from autopatent.reports import export_report
from autopatent.workflow import STAGES, ResearchApp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autopatent", description="关键词驱动的科研与专利工作流（当前 M1）")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--data-dir", type=Path, help="覆盖 AUTOPATENT_DATA_DIR")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="创建项目并执行研究")
    run.add_argument("--keywords", required=True)
    run.add_argument("--until", choices=STAGES, default="ideation")
    status = commands.add_parser("status", help="查看项目状态和最近一次运行")
    status.add_argument("project_id")
    resume = commands.add_parser("resume", help="从保存位置继续")
    resume.add_argument("project_id")
    resume.add_argument("--until", choices=STAGES, default="ideation")
    export = commands.add_parser("export", help="重新导出研究报告")
    export.add_argument("project_id")
    export.add_argument("--format", choices=["markdown"], default="markdown")
    args = parser.parse_args(argv)
    app = None
    try:
        settings = Settings.load(args.env_file)
        if args.data_dir is not None:
            settings.data_dir = args.data_dir
        app = ResearchApp(settings, progress=lambda message: print(message, flush=True))
        if args.command == "run":
            keywords = [item.strip() for item in re.split(r"[、,，;；\n]+", args.keywords) if item.strip()]
            app.run(keywords, args.until)
        elif args.command == "resume":
            app.resume(args.project_id, args.until)
        elif args.command == "status":
            print(json.dumps(app.status(args.project_id), ensure_ascii=False, indent=2))
        elif args.command == "export":
            with app.execution_lock():
                print(export_report(app.store, args.project_id))
        return 0
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors(include_input=False))
        print(f"输入或配置不正确：{details}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断，可用 autopatent resume <project_id> 继续。", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if app is not None:
            app.close()
