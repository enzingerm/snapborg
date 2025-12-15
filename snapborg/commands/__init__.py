import signal, sys

def shutdown(signum, _frame):
    sys.exit(128 + signum)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

def main():
    from .snapborg import run_snapborg
    from ..exceptions import SnapborgBaseException
    try:
        run_snapborg()
    except SnapborgBaseException as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Snapborg failed unexpectedly: {e}!", file=sys.stderr)
        sys.exit(2)