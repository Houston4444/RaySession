#!/usr/bin/python3

import sys

def diff(contents1, contents2):
    contents_params_1 = {}
    for line in contents1.split('\n'):
        if ':' in line:
            param, colon, value = line.partition(':')
            contents_params_1[param] = value
    
    contents_params_2 = {}
    for line in contents2.split('\n'):
        if ':' in line:
            param, colon, value = line.partition(':')
            contents_params_2[param] = value
    
    output_str = ''
    already_seen = []
    
    for param in contents_params_1:
        if param in contents_params_2:
            if contents_params_1[param] != contents_params_2[param]:
                output_str += "%s\n" % param
        already_seen.append(param)
    
    for param in contents_params_2:
        if param in already_seen:
            continue
        
        if param in contents_params_1:
            if contents_params_1[param] != contents_params_2[param]:
                output_str += "%s\n" % param
        else:
            output_str += "%s\n" % param
    
    return output_str

if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.stderr.write("Not Enough arguments\n.")
        sys.exit(1)
    
    output_str = diff(sys.argv[1], sys.argv[2])
    sys.stdout.write(output_str)
