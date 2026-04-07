#!/usr/bin/env python3

import time
da = dict[str, float]()

da['start'] = time.time()

import os
da['os'] = time.time()

import sys
da['sys'] = time.time()

import json
da['json'] = time.time()

import xml.etree.ElementTree as ET
da['ET'] = time.time()

import argparse
da['argparse'] = time.time()

from ctypes import cdll, byref, create_string_buffer
da['ctypes'] = time.time()

import logging
da['logging'] = time.time()

_logger = logging.getLogger(__name__)

da['_logger'] = time.time()

def set_proc_name(new_name: str):
    # use the app name instead of 'python' in processes list. 
    # solution was found here: 
    # https://stackoverflow.com/questions/564695/is-there-a-way-to-change-effective-process-name-in-python
    try:
        libc = cdll.LoadLibrary('libc.so.6')
        buff = create_string_buffer(len(new_name)+1)
        buff.value = new_name.encode()
        libc.prctl(15, byref(buff), 0, 0, 0)

    except BaseException as e:
        _logger.info(
            f'impossible to set process name to {new_name}, '
            'it should not be strong.')
        _logger.info(str(e))

da['write func'] = time.time()
set_proc_name('chichipat')
da['set_proc_name'] = time.time()

for key, value in da.items():
    print(value, key)