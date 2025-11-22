#!/usr/bin/env python3

import tatsu
import os


grammar_path = os.path.join(os.path.dirname(__file__), "langshaw.gr")


def build_parser():
    with open(grammar_path, "r", encoding="utf8") as grammar:
        # warning: dynamically compiled grammar is different from precompiled code
        model = tatsu.compile(grammar.read(), name="Langshaw")
    return model


def save_parser(model):
    parser_path = os.path.join(os.path.dirname(__file__), "langshaw_parser.py")
    with open(grammar_path, "r", encoding="utf8") as grammar:
        langshaw_parser = tatsu.to_python_sourcecode(
            grammar.read(), "Langshaw", "langshaw_parser.py"
        )
        with open(parser_path, "w", encoding="utf8") as parser_file:
            parser_file.write(langshaw_parser)
