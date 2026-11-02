"""Read one real report and prove a denied report never reaches the handler."""
import argparse
from pathlib import Path

from langchain_core.tools import tool
from tenuo.exceptions import ConstraintViolation
from tenuo.langchain import TenuoTool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=".tenuo")
    parser.add_argument("--warrant", default=".tenuo/report.warrant")
    options = parser.parse_args()
    calls = []
    reports = Path(__file__).parent / "reports"

    @tool
    def read_report(report: str) -> str:
        """Read a named service report."""
        calls.append(report)
        return (reports / (report + ".md")).read_text().strip()

    protected = TenuoTool.local(read_report, path=options.home, warrant=options.warrant)
    print("ALLOW:", protected.invoke({"report": "weekly"}))
    try:
        protected.invoke({"report": "private"})
    except ConstraintViolation as exc:
        print("DENY: private report:", exc)
    else:
        raise RuntimeError("private report unexpectedly allowed")
    if calls != ["weekly"]:
        raise RuntimeError("a denied call reached the report handler")
    print("Handler calls: 1 (weekly only)")


if __name__ == "__main__":
    main()
