import os
import sys

SRC = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, os.path.abspath(SRC))
FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), 'rb') as f:
        return f.read()
