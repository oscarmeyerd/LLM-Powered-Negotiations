import os
import tatsu

grammar_path = os.path.join(os.path.dirname(__file__), "precedence.gr")


def build_parser():
    with open(grammar_path, "r", encoding="utf8") as grammar:
        # warning: dynamically compiled grammar is different from precompiled code
        model = tatsu.compile(grammar.read(), name="Precedence")
    return model


model = build_parser()


def parse(definition, **kwargs):
    return model.parse(definition, rule_name="start", **kwargs)
