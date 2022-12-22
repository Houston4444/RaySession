# ---  INSTALL for RAYSESSION  ---

Before installing, please uninstall any existing RaySession installation: <br/>
`$ [sudo] make uninstall`

To install RaySession, simply run as usual: <br/>
`$ make` <br/>
`$ [sudo] make install`

depending of the distribution you'll need to use LRELEASE variable to install.
If you don't have 'lrelease' executable but 'lrelease-qt5' use:
`$ make LRELEASE=lrelease-qt5` <br/>
`$ [sudo] make install`

You can run RaySession without install, by using instead: <br/>
`$ make` <br/>
`$ ./src/bin/raysession`

Packagers can make use of the 'PREFIX' and 'DESTDIR' variable during install, like this: <br/>
`$ make install PREFIX=/usr DESTDIR=./test-dir`



To uninstall RaySession, run: <br/>
`$ [sudo] make uninstall`
<br/>

===== BUILD DEPENDENCIES =====
--------------------------------
The required build dependencies are: <i>(devel packages of these)</i>

 - PyQt5
 - Qt5 dev tools 
 - qtchooser

On Debian and Ubuntu, use these commands to install all build dependencies: <br/>
`$ sudo apt-get install python3-pyqt5 pyqt5-dev-tools qtchooser qttools5-dev-tools`

===== RUNTIME DEPENDENCIES =====

To run it, you'll additionally need:

 - python3-liblo

IMPORTANT : since python 3.11, because pyliblo has been totally abandonned by Dominic Sacre, you need to use the following fork: https://github.com/gesellkammer/pyliblo3, simply install it with `python3 -m pip install pyliblo3`.
