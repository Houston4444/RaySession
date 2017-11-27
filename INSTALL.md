# ---  INSTALL for RAY SESSION  ---

To install Ray Session, simply run as usual: <br/>
`$ make` <br/>
`$ [sudo] make install`

You can run Ray Session without installing them, by using instead: <br/>
`$ make` <br/>
`$ python3 src/raysession`

Packagers can make use of the 'PREFIX' and 'DESTDIR' variable during install, like this: <br/>
`$ make install PREFIX=/usr DESTDIR=./test-dir`

<br/>

===== BUILD DEPENDENCIES =====
--------------------------------
The required build dependencies are: <i>(devel packages of these)</i>

 - PyQt5 (Py3 version)

On Debian and Ubuntu, use these commands to install all build dependencies: <br/>
`$ sudo apt-get install python3-pyqt5 pyqt5-dev-tools`

To run it, you'll additionally need:

 - python3-liblo
 - non-session-manager (source at : http://non.tuxfamily.org/wiki/Non%20Session%20Manager , present in kxstudio repositories)
