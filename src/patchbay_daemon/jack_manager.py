from dataclasses import dataclass
from enum import IntEnum
import os
import signal
import sys
from typing import Optional
import warnings
import threading
import time
from pathlib import Path
import logging
import json
from queue import Queue

import jack
from patshared.base_enums import PrettyDiff

from proc_name import set_proc_name
from patshared import JackMetadatas, JackMetadata, PrettyNames

from osc_server import PatchbayDaemonServer

from alsa_lib_check import ALSA_LIB_OK
if ALSA_LIB_OK:
    from alsa_manager import AlsaManager