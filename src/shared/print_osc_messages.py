#!/usr/bin/python3

import sys

file = open(sys.argv[1], 'r')
contents = file.read()
all_lines = contents.split('\n')
output = ""

for line in all_lines:
    while line.startswith('    '):
        line = line.replace('    ', '')
    if line.startswith('@ray_method('):
        raym, par, qmessargs = line.partition('(')
        qmess, qargs = qmessargs.split(',')
        output += "%s %s\n" % (qmess[1:-1], qargs[2:-2])

print(output)
