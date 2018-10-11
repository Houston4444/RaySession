#!/usr/bin/python3

import subprocess



ally = subprocess.check_output(['wmctrl', '-l', '-p']).decode()
all_lines = ally.split('\n')

for line in all_lines:
    line_sep = line.split(' ')
    non_empt = []
    for el in line_sep:
        if el:
            non_empt.append(el)
            
    if len(non_empt) >= 3 and non_empt[2].isdigit():
        pid = non_empt[2]
        print(pid)
