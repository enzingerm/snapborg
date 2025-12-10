"""
snapborg module entry point
"""

import signal, sys

def shutdown(_signum, _frame):
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

if __name__ == "__main__":
    from .commands import snapborg
    snapborg.main() 
