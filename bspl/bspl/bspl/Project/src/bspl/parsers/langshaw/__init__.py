from ...protocol import *
import re
import tatsu
import sys
from .build import build_parser, save_parser

debug = True

model = build_parser()


def parse(definition):
    return model.parse(definition, rule_name="document")


def load(definition, path=None):
    try:
        return parse(definition)
    except:  # catch *all* exceptions
        if not debug:  # suppress traceback by default
            e = sys.exc_info()[1]
            if path:
                print("Error in: ", path, file=sys.stderr)
            print(e, file=sys.stderr)
            sys.exit(1)
        else:
            raise


def load_file(path):
    """
    Load a Langshaw file
    Args:
      path: The file to load, containing a single Langshaw specification
    """
    with open(path, "r", encoding="utf8") as file:
        raw = file.read()
        spec = load(raw, path)
        return spec
