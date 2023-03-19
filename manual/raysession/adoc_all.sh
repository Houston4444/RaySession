#!/bin/bash

cd `dirname "$0"`

for dir in de en fr;do
    cd "$dir"
    echo "htmlize $dir"
    asciidoctor -d book manual.adoc
    cd ..
done