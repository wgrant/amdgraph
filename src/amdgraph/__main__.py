"""Layer 6 -- entry point.

Kept thin, and kept free of any package import that pulls in numpy or Qt until
after the dependency check: the whole value of the check is that a missing
package produces one line of advice rather than a traceback.

    python3 -m amdgraph          (or just ./amdgraph)
"""

import argparse
import sys


def _check_deps():
    try:
        import numpy                                        # noqa: F401
    except ImportError:
        sys.exit("amdgraph needs numpy:  apt install python3-numpy")
    try:
        import PyQt6.QtWidgets                              # noqa: F401
    except ImportError:
        sys.exit("amdgraph needs PyQt6:  apt install python3-pyqt6")


def main():
    from . import HELP

    ap = argparse.ArgumentParser(
        description="Live strip charts for AMD Ryzen laptops.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP)
    ap.add_argument("-i", "--interval", type=float, default=1.0,
                    help="seconds between samples (default 1.0)")
    ap.add_argument("--open", metavar="FILE",
                    help="open a recorded session instead of sampling")
    ap.add_argument("--replay", metavar="FILE",
                    help="drive a live Sampler from a filesystem recording "
                         "made by tools/amdgraph-record, instead of the "
                         "real machine")
    ap.add_argument("--socket", metavar="PATH",
                    help="connect to amdgraphd instead of sampling locally")
    args = ap.parse_args()

    _check_deps()
    from PyQt6.QtWidgets import QApplication
    from .window import Main

    source = service = None
    if args.replay:
        from .sampler import Sampler
        from .sysfs import ReplayFS
        source = Sampler(fs=ReplayFS.load(args.replay))
    if args.socket:
        from .remote import RemoteHistoryService
        service = RemoteHistoryService(args.socket)

    app = QApplication(sys.argv)
    app.setApplicationName("amdgraph")
    w = Main(max(0.1, args.interval), args.open, source=source, service=service)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
