try:
    from pyalsa.alsaseq import SEQ_LIB_VERSION_STR
    ALSA_VERSION_LIST = [int(num) for num in SEQ_LIB_VERSION_STR.split('.')]
    assert ALSA_VERSION_LIST >= [1, 2, 4]
    ALSA_LIB_OK = True
except:
    ALSA_LIB_OK = False