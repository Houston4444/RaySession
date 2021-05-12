#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Helper functions for extra jacklib functionality
# Copyright (C) 2012-2013 Filipe Coelho <falktx@falktx.com>
#               2016-2021 Christopher Arndt <chrisæchrisarndt.de>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the COPYING file

# -------------------------------------------------------------------------------------------------
# Try Import jacklib

from __future__ import absolute_import, print_function, unicode_literals

from . import api as jacklib


# -------------------------------------------------------------------------------------------------
# Get JACK error status as string

def get_jack_status_error_string(cStatus):
    status = cStatus.value

    if status == 0x0:
        return ""

    errorString = []

    if status == jacklib.JackFailure:
        # Only include this generic message if no other error status is set
        errorString.append("Overall operation failed")
    if status & jacklib.JackInvalidOption:
        errorString.append("The operation contained an invalid or unsupported option")
    if status & jacklib.JackNameNotUnique:
        errorString.append("The desired client name was not unique")
    if status & jacklib.JackServerStarted:
        errorString.append("The JACK server was started as a result of this operation")
    if status & jacklib.JackServerFailed:
        errorString.append("Unable to connect to the JACK server")
    if status & jacklib.JackServerError:
        errorString.append("Communication error with the JACK server")
    if status & jacklib.JackNoSuchClient:
        errorString.append("Requested client does not exist")
    if status & jacklib.JackLoadFailure:
        errorString.append("Unable to load internal client")
    if status & jacklib.JackInitFailure:
        errorString.append("Unable to initialize client")
    if status & jacklib.JackShmFailure:
        errorString.append("Unable to access shared memory")
    if status & jacklib.JackVersionError:
        errorString.append("Client's protocol version does not match")
    if status & jacklib.JackBackendError:
        errorString.append("Backend Error")
    if status & jacklib.JackClientZombie:
        errorString.append("Client is being shutdown against its will")

    return ";\n".join(errorString) + "."


# -------------------------------------------------------------------------------------------------
# Convert C char** -> Python list

def c_char_p_p_to_list(c_char_p_p, encoding=jacklib.ENCODING, errors='ignore'):
    i = 0
    retList = []

    if not c_char_p_p:
        return retList

    while True:
        new_char_p = c_char_p_p[i]
        if not new_char_p:
            break

        retList.append(new_char_p.decode(encoding=encoding, errors=errors))
        i += 1

    jacklib.free(c_char_p_p)
    return retList


# -------------------------------------------------------------------------------------------------
# Convert C void* -> string

def voidptr2str(void_p):
    char_p = jacklib.cast(void_p, jacklib.c_char_p)
    string = str(char_p.value, encoding="utf-8")
    return string


# -------------------------------------------------------------------------------------------------
# Convert C void* -> jack_default_audio_sample_t*

def translate_audio_port_buffer(void_p):
    return jacklib.cast(void_p, jacklib.POINTER(jacklib.jack_default_audio_sample_t))


# -------------------------------------------------------------------------------------------------
# Convert a JACK midi buffer into a python variable-size list

def translate_midi_event_buffer(void_p, size):
    if not void_p:
        return ()
    elif size == 1:
        return (void_p[0],)
    elif size == 2:
        return (void_p[0], void_p[1])
    elif size == 3:
        return (void_p[0], void_p[1], void_p[2])
    elif size == 4:
        return (void_p[0], void_p[1], void_p[2], void_p[3])
    else:
        return ()
