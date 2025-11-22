#!/bin/bash
action=${1:-all}
dir=samples
for file in ${dir}/*
do
    echo $file >&2
    python -m bspl $action $file
done
