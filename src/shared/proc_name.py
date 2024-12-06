from ctypes import cdll, byref, create_string_buffer
import logging

_logger = logging.getLogger(__name__)


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