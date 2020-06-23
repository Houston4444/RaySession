
#include "nuitka/prelude.h"

// Sentinel PyObject to be used for all our call iterator endings. It will
// become a PyCObject pointing to NULL. It's address is unique, and that's
// enough for us to use it as sentinel value.
PyObject *_sentinel_value = NULL;

PyObject *const_int_0;
PyObject *const_str_dot;
PyObject *const_int_neg_1;
PyObject *const_int_pos_1;
PyObject *const_int_pos_2;
PyObject *const_str_empty;
PyObject *const_dict_empty;
PyObject *const_bytes_empty;
PyObject *const_int_pos_101;
PyObject *const_str_plain_s;
PyObject *const_tuple_empty;
PyObject *const_str_plain_os;
PyObject *const_str_plain_rb;
PyObject *const_str_plain_end;
PyObject *const_str_plain_int;
PyObject *const_str_plain_len;
PyObject *const_str_plain_pop;
PyObject *const_str_plain_str;
PyObject *const_str_plain_sum;
PyObject *const_str_plain_sys;
PyObject *const_str_plain_None;
PyObject *const_str_plain_args;
PyObject *const_str_plain_exit;
PyObject *const_str_plain_file;
PyObject *const_str_plain_iter;
PyObject *const_str_plain_name;
PyObject *const_str_plain_open;
PyObject *const_str_plain_path;
PyObject *const_str_plain_port;
PyObject *const_str_plain_read;
PyObject *const_str_plain_repr;
PyObject *const_str_plain_send;
PyObject *const_str_plain_site;
PyObject *const_str_plain_type;
PyObject *const_str_plain_False;
PyObject *const_str_plain_bytes;
PyObject *const_str_plain_close;
PyObject *const_str_plain_level;
PyObject *const_str_plain_print;
PyObject *const_str_plain_range;
PyObject *const_str_plain_throw;
PyObject *const_str_plain_tuple;
PyObject *const_str_plain_types;
PyObject *const_str_plain_write;
PyObject *const_str_plain_detach;
PyObject *const_str_plain_format;
PyObject *const_str_plain_locals;
PyObject *const_str_plain_stderr;
PyObject *const_str_plain_stdout;
PyObject *const_str_plain_string;
PyObject *const_str_plain___all__;
PyObject *const_str_plain___cmp__;
PyObject *const_str_plain___doc__;
PyObject *const_str_plain_compile;
PyObject *const_str_plain_globals;
PyObject *const_str_plain_inspect;
PyObject *const_str_plain_message;
PyObject *const_tuple_int_0_tuple;
PyObject *const_str_plain___dict__;
PyObject *const_str_plain___exit__;
PyObject *const_str_plain___file__;
PyObject *const_str_plain___iter__;
PyObject *const_str_plain___main__;
PyObject *const_str_plain___name__;
PyObject *const_str_plain___path__;
PyObject *const_str_plain___spec__;
PyObject *const_str_plain_fromlist;
PyObject *const_str_angle_metaclass;
PyObject *const_str_plain_OscServer;
PyObject *const_str_plain___class__;
PyObject *const_str_plain___debug__;
PyObject *const_str_plain___enter__;
PyObject *const_str_plain_bytearray;
PyObject *const_str_plain_metaclass;
PyObject *const_str_plain___cached__;
PyObject *const_str_plain___import__;
PyObject *const_str_plain___loader__;
PyObject *const_str_plain___module__;
PyObject *const_str_plain_finalError;
PyObject *const_str_plain_osc_server;
PyObject *const_str_plain_startswith;
PyObject *const_str_plain___getitem__;
PyObject *const_str_plain___package__;
PyObject *const_str_plain___prepare__;
PyObject *const_str_plain_classmethod;
PyObject *const_str_plain_daemon_port;
PyObject *const_str_plain_stopDaemons;
PyObject *const_str_plain___builtins__;
PyObject *const_str_plain___internal__;
PyObject *const_str_plain___qualname__;
PyObject *const_str_plain_staticmethod;
PyObject *const_str_plain_waitForStart;
PyObject *const_str_plain___metaclass__;
PyObject *const_str_plain__initializing;
PyObject *const_str_plain_getDaemonPort;
PyObject *const_tuple_int_pos_101_tuple;
PyObject *const_slice_int_pos_1_none_none;
PyObject *const_str_plain_sendOrderMessage;
PyObject *const_str_plain_setDaemonAddress;
PyObject *const_str_plain_setOrderPathArgs;
PyObject *const_str_plain_waitForStartOnly;
PyObject *const_tuple_str_plain_string_tuple;
PyObject *const_str_plain_disannounceToDaemon;
PyObject *const_tuple_str_plain___class___tuple;
PyObject *const_str_plain_isWaitingStartForALong;
PyObject *const_str_plain_submodule_search_locations;
PyObject *const_str_digest_25731c733fd74e8333aa29126ce85686;
PyObject *const_str_digest_45e4dde2057b0bf276d6a84f4c917d27;
PyObject *const_str_digest_72035249113faa63f8939ea70bf6ef12;
PyObject *const_str_digest_75fd71b1edada749c2ef7ac810062295;
PyObject *const_str_digest_adc474dd61fbd736d69c1bac5d9712e0;
PyObject *const_str_digest_aed02aab7465cf50b55884286d8beb4b;
PyObject *const_str_digest_b85383ba44b80132e8fbbd8bc602d23c;
PyObject *const_tuple_anon_function_anon_builtin_function_or_method_tuple;

static void _createGlobalConstants( void )
{
    NUITKA_MAY_BE_UNUSED PyObject *exception_type, *exception_value;
    NUITKA_MAY_BE_UNUSED PyTracebackObject *exception_tb;

#ifdef _MSC_VER
    // Prevent unused warnings in case of simple programs, the attribute
    // NUITKA_MAY_BE_UNUSED doesn't work for MSVC.
    (void *)exception_type; (void *)exception_value; (void *)exception_tb;
#endif

    const_int_0 = PyLong_FromUnsignedLong( 0ul );
    const_str_dot = UNSTREAM_STRING_ASCII( &constant_bin[ 150 ], 1, 0 );
    const_int_neg_1 = PyLong_FromLong( -1l );
    const_int_pos_1 = PyLong_FromUnsignedLong( 1ul );
    const_int_pos_2 = PyLong_FromUnsignedLong( 2ul );
    const_str_empty = UNSTREAM_STRING_ASCII( &constant_bin[ 0 ], 0, 0 );
    const_dict_empty = _PyDict_NewPresized( 0 );
    assert( PyDict_Size( const_dict_empty ) == 0 );
    const_bytes_empty = UNSTREAM_BYTES( &constant_bin[ 0 ], 0 );
    const_int_pos_101 = PyLong_FromUnsignedLong( 101ul );
    const_str_plain_s = UNSTREAM_STRING_ASCII( &constant_bin[ 1 ], 1, 1 );
    const_tuple_empty = PyTuple_New( 0 );
    const_str_plain_os = UNSTREAM_STRING_ASCII( &constant_bin[ 158 ], 2, 1 );
    const_str_plain_rb = UNSTREAM_STRING_ASCII( &constant_bin[ 3994 ], 2, 1 );
    const_str_plain_end = UNSTREAM_STRING_ASCII( &constant_bin[ 758 ], 3, 1 );
    const_str_plain_int = UNSTREAM_STRING_ASCII( &constant_bin[ 856 ], 3, 1 );
    const_str_plain_len = UNSTREAM_STRING_ASCII( &constant_bin[ 3996 ], 3, 1 );
    const_str_plain_pop = UNSTREAM_STRING_ASCII( &constant_bin[ 3999 ], 3, 1 );
    const_str_plain_str = UNSTREAM_STRING_ASCII( &constant_bin[ 4002 ], 3, 1 );
    const_str_plain_sum = UNSTREAM_STRING_ASCII( &constant_bin[ 4005 ], 3, 1 );
    const_str_plain_sys = UNSTREAM_STRING_ASCII( &constant_bin[ 4008 ], 3, 1 );
    const_str_plain_None = UNSTREAM_STRING_ASCII( &constant_bin[ 4011 ], 4, 1 );
    const_str_plain_args = UNSTREAM_STRING_ASCII( &constant_bin[ 2035 ], 4, 1 );
    const_str_plain_exit = UNSTREAM_STRING_ASCII( &constant_bin[ 1674 ], 4, 1 );
    const_str_plain_file = UNSTREAM_STRING_ASCII( &constant_bin[ 58 ], 4, 1 );
    const_str_plain_iter = UNSTREAM_STRING_ASCII( &constant_bin[ 4015 ], 4, 1 );
    const_str_plain_name = UNSTREAM_STRING_ASCII( &constant_bin[ 1045 ], 4, 1 );
    const_str_plain_open = UNSTREAM_STRING_ASCII( &constant_bin[ 313 ], 4, 1 );
    const_str_plain_path = UNSTREAM_STRING_ASCII( &constant_bin[ 67 ], 4, 1 );
    const_str_plain_port = UNSTREAM_STRING_ASCII( &constant_bin[ 220 ], 4, 1 );
    const_str_plain_read = UNSTREAM_STRING_ASCII( &constant_bin[ 728 ], 4, 1 );
    const_str_plain_repr = UNSTREAM_STRING_ASCII( &constant_bin[ 4019 ], 4, 1 );
    const_str_plain_send = UNSTREAM_STRING_ASCII( &constant_bin[ 2964 ], 4, 1 );
    const_str_plain_site = UNSTREAM_STRING_ASCII( &constant_bin[ 4023 ], 4, 1 );
    const_str_plain_type = UNSTREAM_STRING_ASCII( &constant_bin[ 682 ], 4, 1 );
    const_str_plain_False = UNSTREAM_STRING_ASCII( &constant_bin[ 4027 ], 5, 1 );
    const_str_plain_bytes = UNSTREAM_STRING_ASCII( &constant_bin[ 4032 ], 5, 1 );
    const_str_plain_close = UNSTREAM_STRING_ASCII( &constant_bin[ 2099 ], 5, 1 );
    const_str_plain_level = UNSTREAM_STRING_ASCII( &constant_bin[ 4037 ], 5, 1 );
    const_str_plain_print = UNSTREAM_STRING_ASCII( &constant_bin[ 854 ], 5, 1 );
    const_str_plain_range = UNSTREAM_STRING_ASCII( &constant_bin[ 4042 ], 5, 1 );
    const_str_plain_throw = UNSTREAM_STRING_ASCII( &constant_bin[ 4047 ], 5, 1 );
    const_str_plain_tuple = UNSTREAM_STRING_ASCII( &constant_bin[ 4052 ], 5, 1 );
    const_str_plain_types = UNSTREAM_STRING_ASCII( &constant_bin[ 3283 ], 5, 1 );
    const_str_plain_write = UNSTREAM_STRING_ASCII( &constant_bin[ 4057 ], 5, 1 );
    const_str_plain_detach = UNSTREAM_STRING_ASCII( &constant_bin[ 2016 ], 6, 1 );
    const_str_plain_format = UNSTREAM_STRING_ASCII( &constant_bin[ 4062 ], 6, 1 );
    const_str_plain_locals = UNSTREAM_STRING_ASCII( &constant_bin[ 4068 ], 6, 1 );
    const_str_plain_stderr = UNSTREAM_STRING_ASCII( &constant_bin[ 4074 ], 6, 1 );
    const_str_plain_stdout = UNSTREAM_STRING_ASCII( &constant_bin[ 4080 ], 6, 1 );
    const_str_plain_string = UNSTREAM_STRING_ASCII( &constant_bin[ 4086 ], 6, 1 );
    const_str_plain___all__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4092 ], 7, 1 );
    const_str_plain___cmp__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4099 ], 7, 1 );
    const_str_plain___doc__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4106 ], 7, 1 );
    const_str_plain_compile = UNSTREAM_STRING_ASCII( &constant_bin[ 4113 ], 7, 1 );
    const_str_plain_globals = UNSTREAM_STRING_ASCII( &constant_bin[ 4120 ], 7, 1 );
    const_str_plain_inspect = UNSTREAM_STRING_ASCII( &constant_bin[ 4127 ], 7, 1 );
    const_str_plain_message = UNSTREAM_STRING_ASCII( &constant_bin[ 85 ], 7, 1 );
    const_tuple_int_0_tuple = PyTuple_New( 1 );
    PyTuple_SET_ITEM( const_tuple_int_0_tuple, 0, const_int_0 ); Py_INCREF( const_int_0 );
    const_str_plain___dict__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4134 ], 8, 1 );
    const_str_plain___exit__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4142 ], 8, 1 );
    const_str_plain___file__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4150 ], 8, 1 );
    const_str_plain___iter__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4158 ], 8, 1 );
    const_str_plain___main__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4166 ], 8, 1 );
    const_str_plain___name__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4174 ], 8, 1 );
    const_str_plain___path__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4182 ], 8, 1 );
    const_str_plain___spec__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4190 ], 8, 1 );
    const_str_plain_fromlist = UNSTREAM_STRING_ASCII( &constant_bin[ 4198 ], 8, 1 );
    const_str_angle_metaclass = UNSTREAM_STRING_ASCII( &constant_bin[ 4206 ], 11, 0 );
    const_str_plain_OscServer = UNSTREAM_STRING_ASCII( &constant_bin[ 2501 ], 9, 1 );
    const_str_plain___class__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4217 ], 9, 1 );
    const_str_plain___debug__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4226 ], 9, 1 );
    const_str_plain___enter__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4235 ], 9, 1 );
    const_str_plain_bytearray = UNSTREAM_STRING_ASCII( &constant_bin[ 4244 ], 9, 1 );
    const_str_plain_metaclass = UNSTREAM_STRING_ASCII( &constant_bin[ 4207 ], 9, 1 );
    const_str_plain___cached__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4253 ], 10, 1 );
    const_str_plain___import__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4263 ], 10, 1 );
    const_str_plain___loader__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4273 ], 10, 1 );
    const_str_plain___module__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4283 ], 10, 1 );
    const_str_plain_finalError = UNSTREAM_STRING_ASCII( &constant_bin[ 3586 ], 10, 1 );
    const_str_plain_osc_server = UNSTREAM_STRING_ASCII( &constant_bin[ 2668 ], 10, 1 );
    const_str_plain_startswith = UNSTREAM_STRING_ASCII( &constant_bin[ 4293 ], 10, 1 );
    const_str_plain___getitem__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4303 ], 11, 1 );
    const_str_plain___package__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4314 ], 11, 1 );
    const_str_plain___prepare__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4325 ], 11, 1 );
    const_str_plain_classmethod = UNSTREAM_STRING_ASCII( &constant_bin[ 4336 ], 11, 1 );
    const_str_plain_daemon_port = UNSTREAM_STRING_ASCII( &constant_bin[ 760 ], 11, 1 );
    const_str_plain_stopDaemons = UNSTREAM_STRING_ASCII( &constant_bin[ 2649 ], 11, 1 );
    const_str_plain___builtins__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4347 ], 12, 1 );
    const_str_plain___internal__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4359 ], 12, 1 );
    const_str_plain___qualname__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4371 ], 12, 1 );
    const_str_plain_staticmethod = UNSTREAM_STRING_ASCII( &constant_bin[ 4383 ], 12, 1 );
    const_str_plain_waitForStart = UNSTREAM_STRING_ASCII( &constant_bin[ 2583 ], 12, 1 );
    const_str_plain___metaclass__ = UNSTREAM_STRING_ASCII( &constant_bin[ 4395 ], 13, 1 );
    const_str_plain__initializing = UNSTREAM_STRING_ASCII( &constant_bin[ 4408 ], 13, 1 );
    const_str_plain_getDaemonPort = UNSTREAM_STRING_ASCII( &constant_bin[ 2511 ], 13, 1 );
    const_tuple_int_pos_101_tuple = PyTuple_New( 1 );
    PyTuple_SET_ITEM( const_tuple_int_pos_101_tuple, 0, const_int_pos_101 ); Py_INCREF( const_int_pos_101 );
    const_slice_int_pos_1_none_none = PySlice_New( const_int_pos_1, Py_None, Py_None );
    const_str_plain_sendOrderMessage = UNSTREAM_STRING_ASCII( &constant_bin[ 2964 ], 16, 1 );
    const_str_plain_setDaemonAddress = UNSTREAM_STRING_ASCII( &constant_bin[ 2609 ], 16, 1 );
    const_str_plain_setOrderPathArgs = UNSTREAM_STRING_ASCII( &constant_bin[ 2741 ], 16, 1 );
    const_str_plain_waitForStartOnly = UNSTREAM_STRING_ASCII( &constant_bin[ 2583 ], 16, 1 );
    const_tuple_str_plain_string_tuple = PyTuple_New( 1 );
    PyTuple_SET_ITEM( const_tuple_str_plain_string_tuple, 0, const_str_plain_string ); Py_INCREF( const_str_plain_string );
    const_str_plain_disannounceToDaemon = UNSTREAM_STRING_ASCII( &constant_bin[ 3087 ], 19, 1 );
    const_tuple_str_plain___class___tuple = PyTuple_New( 1 );
    PyTuple_SET_ITEM( const_tuple_str_plain___class___tuple, 0, const_str_plain___class__ ); Py_INCREF( const_str_plain___class__ );
    const_str_plain_isWaitingStartForALong = UNSTREAM_STRING_ASCII( &constant_bin[ 3833 ], 22, 1 );
    const_str_plain_submodule_search_locations = UNSTREAM_STRING_ASCII( &constant_bin[ 4421 ], 26, 1 );
    const_str_digest_25731c733fd74e8333aa29126ce85686 = UNSTREAM_STRING_ASCII( &constant_bin[ 4447 ], 2, 0 );
    const_str_digest_45e4dde2057b0bf276d6a84f4c917d27 = UNSTREAM_STRING_ASCII( &constant_bin[ 4449 ], 7, 0 );
    const_str_digest_72035249113faa63f8939ea70bf6ef12 = UNSTREAM_STRING_ASCII( &constant_bin[ 4456 ], 16, 0 );
    const_str_digest_75fd71b1edada749c2ef7ac810062295 = UNSTREAM_STRING_ASCII( &constant_bin[ 4472 ], 46, 0 );
    const_str_digest_adc474dd61fbd736d69c1bac5d9712e0 = UNSTREAM_STRING_ASCII( &constant_bin[ 4518 ], 47, 0 );
    const_str_digest_aed02aab7465cf50b55884286d8beb4b = UNSTREAM_STRING_ASCII( &constant_bin[ 169 ], 3, 0 );
    const_str_digest_b85383ba44b80132e8fbbd8bc602d23c = UNSTREAM_STRING_ASCII( &constant_bin[ 4565 ], 16, 0 );
    const_tuple_anon_function_anon_builtin_function_or_method_tuple = PyTuple_New( 2 );
    PyTuple_SET_ITEM( const_tuple_anon_function_anon_builtin_function_or_method_tuple, 0, (PyObject *)&PyFunction_Type ); Py_INCREF( (PyObject *)&PyFunction_Type );
    PyTuple_SET_ITEM( const_tuple_anon_function_anon_builtin_function_or_method_tuple, 1, (PyObject *)&PyCFunction_Type ); Py_INCREF( (PyObject *)&PyCFunction_Type );

#if _NUITKA_EXE
    /* Set the "sys.executable" path to the original CPython executable. */
    PySys_SetObject(
        (char *)"executable",
        const_str_digest_72035249113faa63f8939ea70bf6ef12
    );
#endif
}

// In debug mode we can check that the constants were not tampered with in any
// given moment. We typically do it at program exit, but we can add extra calls
// for sanity.
#ifndef __NUITKA_NO_ASSERT__
void checkGlobalConstants( void )
{

}
#endif

void createGlobalConstants( void )
{
    if ( _sentinel_value == NULL )
    {
#if PYTHON_VERSION < 300
        _sentinel_value = PyCObject_FromVoidPtr( NULL, NULL );
#else
        // The NULL value is not allowed for a capsule, so use something else.
        _sentinel_value = PyCapsule_New( (void *)27, "sentinel", NULL );
#endif
        assert( _sentinel_value );

        _createGlobalConstants();
    }
}
