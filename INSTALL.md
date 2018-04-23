# ---  INSTALL for RAY SESSION  ---

To install Ray Session, simply run as usual: <br/>
`$ make` <br/>
`$ [sudo] make install`

You can run Ray Session without install, by using instead: <br/>
`$ make` <br/>
`$ ./src/raysession`

Packagers can make use of the 'PREFIX' and 'DESTDIR' variable during install, like this: <br/>
`$ make install PREFIX=/usr DESTDIR=./test-dir`


To uninstall Ray Session, run: <br/>
`$ [sudo] make uninstall`
<br/>

===== BUILD DEPENDENCIES =====
--------------------------------
The required build dependencies are: <i>(devel packages of these)</i>

 - PyQt5
 - Qt4 linguist tools (executable : lrelease-qt4)

On Debian and Ubuntu, use these commands to install all build dependencies: <br/>
`$ sudo apt-get install python3-pyqt5 pyqt5-dev-tools qt4-linguist-tools`

To run it, you'll additionally need:

 - python3-liblo
